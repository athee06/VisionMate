# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - the accessible overlay: makes a window that NVDA cannot read into a document of items.
# Text comes from Windows OCR, icons are found by shape and named by the vision data.
# It runs inside NVDA's content recognition, like NVDA+R: arrows or Tab move through the items, Enter clicks the
# item in the real window, Escape closes. The real window keeps the focus, so clicks reach it.

import bisect
import hashlib
import re
import threading
import time

import addonHandler
from contentRecog import ContentRecognizer, LinesWordsResult, recogUi
from logHandler import log
from PIL import ImageStat

from . import colours, findonscreen, formcheck, humancheck, imaging, labels, layout, ocr, sounds, structure

addonHandler.initTranslation()

LIVE_INTERVAL_MS = 1000
# With the screen curtain on, each window is drawn on its own, which is slower, so refresh less often.
CURTAIN_INTERVAL_MS = 3000
# Words further apart than this many line heights are separate items, like buttons on one row.
ITEM_GAP = 1.2
# How much brighter or darker than the others an item's background must be to count as selected.
HIGHLIGHT_MIN_DIFF = 35
# A look this close to the learned look of the selected item is the selected item.
LEARNED_LOOK_MATCH = 30
TEXT_LOOK_WEIGHT = 0.5
# Items are shrunk to about this many pixels before their colours are read.
LOOK_MAX_PIXELS = 1600
# Where the selected item's look is kept, in the names store for the app.
HIGHLIGHT_KEY = "look:selected"
# Width of one character, compared to its height, above which OCR text is really icons.
ICON_CHAR_WIDTH = 0.85
# A word of three or more letters with a vowel is real text, not icons read as letters.
_REAL_WORD = re.compile(r"(?i)(?=[a-z]*[aeiouy])[a-z]{3,}")
# Lines of one label, like "VLC media" over "player", are closer than this many line heights.
STACK_GAP = 0.6
# The second line of a name under an icon starts within this many line heights of the first.
WRAP_GAP = 1.2
# A label belongs to an icon when it starts within this many icon sizes below or beside it.
LABEL_DISTANCE = 1.0
# How long to wait after a click before moving the mouse back.
CLICK_SETTLE_MS = 300
# Live updates normally come every second; after this long without one, start them again.
STALL_SECONDS = 2.5


def _box(items):
	return (min(i["box"][0] for i in items), min(i["box"][1] for i in items),
		max(i["box"][2] for i in items), max(i["box"][3] for i in items))


def _joinWords(words):
	"""Join OCR words with spaces, except where OCR split one word at a dot with almost no gap, like
	"Report." "docx" for Report.docx."""
	text = ""
	prev = None
	for w in words:
		if prev is not None:
			gap = w["x"] - (prev["x"] + prev["width"])
			if not (prev["text"].endswith(".") and w["text"][:1].isalnum() and w["text"][:1].islower()
					and gap <= 0.2 * max(prev["height"], w["height"])):
				text += " "
		text += w["text"]
		prev = w
	return text


def splitItems(lines):
	"""Turn OCR lines into items: a line splits where there is a wide gap between words."""
	items = []
	for line in lines or ():
		current = []
		for word in line:
			if current:
				prev = current[-1]
				gap = word["x"] - (prev["x"] + prev["width"])
				if gap > max(ITEM_GAP * max(prev["height"], word["height"]), 18):
					items.append(current)
					current = []
			current.append(word)
		if current:
			items.append(current)
	result = []
	for words in items:
		left = min(w["x"] for w in words)
		top = min(w["y"] for w in words)
		right = max(w["x"] + w["width"] for w in words)
		bottom = max(w["y"] + w["height"] for w in words)
		first = words[0]
		result.append({"kind": "text", "text": _joinWords(words), "box": (left, top, right, bottom),
			"lineHeight": bottom - top, "firstWord": (first["text"], (first["x"], first["y"],
			first["x"] + first["width"], first["y"] + first["height"]))})
	return result


def _looksLikeIcons(item):
	"""OCR sometimes reads icons as letters, like a row of icons as "0000". Real letters are about half as wide
	as they are tall; letters read from icons are as wide as the icons, with the gaps between them."""
	left, top, right, bottom = item["box"]
	chars = len(item["text"].replace(" ", ""))
	if any(_REAL_WORD.fullmatch(word) for word in item["text"].split()):
		return False  # a real word, like widely spaced capitals on a button
	return chars > 0 and bottom > top and (right - left) / chars >= ICON_CHAR_WIDTH * (bottom - top)


def _isIconBit(item):
	"""OCR's reading of a small icon or thumbnail, like "@", "Q" or "0l": a few letters that are no word."""
	text = item["text"].strip()
	chars = re.sub(r"\W", "", text)
	if any(_REAL_WORD.fullmatch(word) for word in re.findall(r"[A-Za-z]+", text)):
		return False
	if chars.isdigit() and len(chars) >= 2:
		return False  # a number, like a count or a time
	return len(chars) <= 3


def mergeIconBits(items):
	"""An icon or thumbnail just left of its label, read by OCR as a few stray letters, is part of that label, so the
	element is one item and not two. The label's box grows to cover it, so a click still hits the element."""
	result = list(items)
	for bit in [it for it in items if _isIconBit(it)]:
		left, top, right, bottom = bit["box"]
		h = max(bottom - top, 1)
		best = None
		for other in result:
			if other is bit or _isIconBit(other):
				continue
			ol, ot, orr, ob = other["box"]
			overlap = min(bottom, ob) - max(top, ot)
			gap = ol - right
			if overlap >= 0.4 * min(h, ob - ot) and -2 <= gap <= max(2.5 * h, 40):
				if best is None or gap < best[0]:
					best = (gap, other)
		if best is not None:
			label = best[1]
			label["box"] = _box([label, bit])
			result.remove(bit)
	return result


def mergeStacked(items):
	"""Join a label that wraps onto a second line, like desktop icon names, into one item."""
	items = sorted(items, key=lambda it: it["box"][1])
	merged = []
	for item in items:
		left, top, right, bottom = item["box"]
		h = bottom - top
		for prev in reversed(merged):
			pl, pt, pr, pb = prev["box"]
			ph = pb - pt
			gap = top - pb
			# Only centred lines: left-aligned rows of a list must stay separate items.
			sameColumn = abs((left + right) / 2 - (pl + pr) / 2) < 0.25 * max(right - left, pr - pl) and abs(left - pl) >= 6
			if sameColumn and -2 <= gap <= STACK_GAP * min(h, ph) and 0.7 <= h / max(ph, 1) <= 1.4:
				prev["text"] = prev["text"] + " " + item["text"]
				prev["box"] = _box([prev, item])
				prev["lineHeight"] = max(prev.get("lineHeight", ph), item.get("lineHeight", h))
				break
		else:
			merged.append(dict(item))
	return merged


def labelFor(icon, texts):
	"""The text item right below or right beside an icon, which names it, or None.
	A name below an icon may wrap onto a second line, like desktop shortcuts; that line is joined to it
	and removed from texts."""
	left, top, right, bottom = icon
	w, h = right - left, bottom - top
	reach = LABEL_DISTANCE * max(w, h)
	cx, cy = (left + right) / 2, (top + bottom) / 2
	for item in texts:
		tl, tt, tr, tb = item["box"]
		below = top < tt and tt - bottom <= reach and tl - w / 2 <= cx <= tr + w / 2
		beside = left < tl and tl - right <= reach and tt - h / 2 <= cy <= tb + h / 2
		if below:
			_joinWrappedLine(item, texts, left - w / 2, right + w / 2)
		if below or beside:
			return item
	return None


def _joinWrappedLine(label, texts, minX, maxX):
	tl, tt, tr, tb = label["box"]
	for other in texts:
		ol, ot, orr, ob = other["box"]
		if other is label or not (0 <= ot - tb <= WRAP_GAP * (tb - tt)):
			continue
		if minX <= (ol + orr) / 2 <= maxX:
			label["text"] += " " + other["text"]
			label["box"] = _box([label, other])
			texts.remove(other)
			return


def _distance(a, b):
	return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def look(image, box):
	"""How an item looks: the colour around its text and the colour of its text, as (r, g, b, r, g, b)."""
	left, top, right, bottom = box
	pad = 4
	w, h = image.size
	crop = image.crop((max(0, left - pad), max(0, top - pad), min(w, right + pad), min(h, bottom + pad))).convert("RGB")
	if crop.width * crop.height > LOOK_MAX_PIXELS:
		scale = (LOOK_MAX_PIXELS / (crop.width * crop.height)) ** 0.5
		crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))))
	back = tuple(int(v) for v in ImageStat.Stat(crop).median)
	pixels = list(crop.getdata())
	# The text is the pixels most unlike the background.
	pixels.sort(key=lambda p: _distance(p, back), reverse=True)
	ink = pixels[:max(1, len(pixels) // 12)]
	text = tuple(sorted(p[c] for p in ink)[len(ink) // 2] for c in range(3))
	return back + text


def lookDistance(a, b):
	"""How different two looks are: the bigger of the background and text colour differences. Text colour is read
	from thin, smoothed letters, so it counts half."""
	return max(_distance(a[:3], b[:3]), TEXT_LOOK_WEIGHT * _distance(a[3:], b[3:]))


def findHighlighted(image, items, learned=None, looks=None):
	"""(index, look) of the text item that stands out from the others, like a selected menu entry, or (None, None).
	learned is how the selected item looked before in this app; it settles cases where several items stand out.
	looks maps item index to look, if already known."""
	texts = [i for i, item in enumerate(items) if item["kind"] == "text"]
	if len(texts) < 3:
		return None, None
	looks = looks or {i: look(image, items[i]["box"]) for i in texts}
	usual = tuple(sorted(v[c] for v in looks.values())[len(looks) // 2] for c in range(6))
	diffs = sorted(((lookDistance(v, usual), i) for i, v in looks.items()), reverse=True)
	if learned is not None:
		like = [i for d, i in diffs if d >= HIGHLIGHT_MIN_DIFF and lookDistance(looks[i], learned) <= LEARNED_LOOK_MATCH]
		if len(like) == 1:
			return like[0], looks[like[0]]
	best, index = diffs[0]
	if best < HIGHLIGHT_MIN_DIFF or diffs[1][0] > best * 0.6:
		return None, None
	return index, looks[index]


def selectionMoved(before, after):
	"""Learn the selected look from a change between two pictures of the same window. before and after map item
	text to look. If the only items that changed are one that now looks the way another one looked, and that one,
	the selection moved: returns the new selected look, or None."""
	changed = [t for t in after if t in before and lookDistance(after[t], before[t]) >= HIGHLIGHT_MIN_DIFF]
	if len(changed) != 2:
		return None
	a, b = changed
	if not (lookDistance(after[a], before[b]) <= LEARNED_LOOK_MATCH and lookDistance(after[b], before[a]) <= LEARNED_LOOK_MATCH):
		return None  # not one look passed from one item to the other
	# The two swapped looks: the selected one is the one unlike the items that did not change.
	others = [after[t] for t in after if t not in changed]
	if not others:
		return None
	usual = tuple(sorted(v[c] for v in others)[len(others) // 2] for c in range(6))
	new = max((a, b), key=lambda t: lookDistance(after[t], usual))
	return after[new] if lookDistance(after[new], usual) >= HIGHLIGHT_MIN_DIFF else None


def orderItems(items):
	"""Top to bottom, then left to right, like reading the screen."""
	if not items:
		return []
	heights = sorted(item["box"][3] - item["box"][1] for item in items)
	band = max(6, heights[len(heights) // 2] * 0.6)
	rows = []
	for item in sorted(items, key=lambda it: (it["box"][1] + it["box"][3]) / 2):
		center = (item["box"][1] + item["box"][3]) / 2
		if rows and abs(rows[-1][0] - center) <= band:
			rows[-1][1].append(item)
		else:
			rows.append([center, [item]])
	return [item for _c, row in rows for item in sorted(row, key=lambda it: it["box"][0])]


class OverlayResult(LinesWordsResult):
	"""One line per item, after some header lines, with a line before each area when the window has several.
	Remembers which line is which item."""

	def __init__(self, items, imageInfo, headers=(), groups=None):
		"""items in order, or groups: a list of (area line or None, items)."""
		if groups is None:
			groups = [(None, items)]
		self.items = [item for _line, members in groups for item in members if item.get("kind") != "label"]
		self.headerCount = len(headers)
		# For each line: its item, or None for header and area lines.
		self.lineItems = [None] * len(headers)
		self.areaLines = []
		self.tableLines = []
		texts = list(headers)
		for line, members in groups:
			if line is not None:
				self.areaLines.append(len(texts))
				self.lineItems.append(None)
				texts.append(line)
			for item in members:
				# Label lines, like the line before a table, are not items to click.
				if item.get("kind") == "label" and item.get("role") == "table":
					self.tableLines.append(len(texts))
				self.lineItems.append(None if item.get("kind") == "label" else item)
				texts.append(item["text"])
		if not texts:
			# Translators: Shown in the overlay when nothing was found in the window.
			texts.append(_("Nothing found in this window."))
			self.lineItems.append(None)
		data = []
		for text, item in zip(texts, self.lineItems):
			if item is None:
				data.append([{"x": 0, "y": 0, "width": 1, "height": 1, "text": text}])
			else:
				left, top, right, bottom = item["box"]
				data.append([{"x": left, "y": top, "width": right - left, "height": bottom - top, "text": text}])
		# Where each line starts in the text: every line is one word and a line break.
		# Kept here because NVDA's own "lines" list holds where lines end.
		self.lineStarts = []
		offset = 0
		for line in data:
			self.lineStarts.append(offset)
			offset += len(line[0]["text"]) + 1
		super().__init__(data, imageInfo)

	def lineAt(self, offset):
		return bisect.bisect_right(self.lineStarts, offset) - 1

	def itemAt(self, offset):
		line = self.lineAt(offset)
		return self.lineItems[line] if 0 <= line < len(self.lineItems) else None

	def findLine(self, offset, roles, forward=True):
		"""Where the next (or previous) line after offset starts whose item has one of these roles, or None.
		The role "area" finds area lines."""
		line = self.lineAt(offset)
		lines = range(line + 1, len(self.lineItems)) if forward else range(line - 1, -1, -1)
		for i in lines:
			item = self.lineItems[i]
			if (("area" in roles and i in self.areaLines) or ("table" in roles and i in self.tableLines)
					or ("red" in roles and item is not None and item.get("red"))
					or (item is not None and item.get("role") in roles)):
				return self.lineStarts[i]
		return None

	def lineOf(self, item):
		"""Where the line of this item starts, or None."""
		for i, other in enumerate(self.lineItems):
			if other is item:
				return self.lineStarts[i]
		return None

	def offsetOf(self, text):
		"""Where the first item with this text starts, or None."""
		for i, item in enumerate(self.lineItems):
			if item is not None and item["text"] == text:
				return self.lineStarts[i]
		return None

	def screenPoint(self, item):
		"""The middle of an item on the screen, for clicking."""
		left, top, right, bottom = item["box"]
		info = self.imageInfo
		return (info.convertXToScreen((left + right) // 2), info.convertYToScreen((top + bottom) // 2))


def iconLabel(name):
	# Translators: An icon in the overlay. {name} is what the icon probably is.
	return _("{name} icon").format(name=name)


def itemText(item):
	"""What the overlay says for an item: its text and what kind of item it is, and whether it is marked in red."""
	text = _itemText(item)
	if item.get("red"):
		# Translators: Added to an overlay item that the form marks in red, like a wrong or missing field.
		text = _("{item}, marked in red").format(item=text)
	return text


def _itemText(item):
	if item.get("tile"):
		name = item.get("name")
		# Translators: A square of a picture puzzle in the overlay. {number} counts from 1, {name} what it shows.
		return (_("Square {number}: {name}").format(number=item["tile"], name=name) if name
			# Translators: A square of a picture puzzle in the overlay that is still being described.
			else _("Square {number}, describing").format(number=item["tile"]))
	role = item.get("role")
	if item["kind"] == "icon":
		name = item.get("name")
		if role == "button":
			# Translators: A button with only an icon in the overlay. {name} is what the icon probably is.
			return _("{name} button").format(name=name) if name else _("button, naming")
		# Translators: An icon in the overlay that has not been named yet.
		return iconLabel(name) if name else _("icon, naming")
	text = item["text"]
	if role == "button":
		# Translators: A button in the overlay. {text} is its text.
		return _("{text} button").format(text=text)
	if role == "field":
		# Translators: An edit field in the overlay. {text} is its name or the hint in it.
		return _("{text} edit field").format(text=text) if text else _("edit field")
	if role == "heading":
		# Translators: A heading in the overlay. {text} is its text.
		return _("{text} heading").format(text=text)
	if role == "link":
		# Translators: A link in the overlay. {text} is its text.
		return _("{text} link").format(text=text)
	if role in ("checkbox", "radio"):
		# Translators: The state of a checkbox or radio button in the overlay.
		state = _("checked") if item.get("checked") else _("not checked")
		if role == "checkbox":
			# Translators: A checkbox in the overlay. {text} is its name, {state} checked or not checked.
			return _("{text} checkbox, {state}").format(text=text, state=state)
		# Translators: A radio button in the overlay. {text} is its name, {state} checked or not checked.
		return _("{text} radio button, {state}").format(text=text, state=state)
	return text


def areaLine(area, count):
	"""The line before an area's items, like "Dialog: Sign in, 5 items"."""
	names = {
		# Translators: Areas of a window in the overlay.
		"dialog": _("Dialog"), "panel": _("Panel"), "top": _("Top bar"), "bottom": _("Bottom bar"),
		"left": _("Left panel"), "right": _("Right panel"), "main": _("Main area"),
	}
	name = names.get(area["kind"], names["main"])
	if area.get("title"):
		# Translators: An area with its heading, like "Dialog: Sign in".
		name = _("{area}: {title}").format(area=name, title=area["title"])
	# Translators: The line before an area's items in the overlay. {area} is its name, {count} how many items.
	line = _("{area}, {count} items").format(area=name, count=count)
	more = scrollText(area.get("scroll"))
	return f"{line}, {more}" if more else line


class OverlayRecognizer(ContentRecognizer):
	"""Recognizes a window for the overlay. The plugin provides capturing and icon naming."""

	def __init__(self, plugin, app, live, underCurtain, title=""):
		self._plugin = plugin
		self.app = app
		self.title = title
		self.lastStarted = 0
		self._live = live
		self._underCurtain = underCurtain
		self._cancelled = False
		self._lastKey = None
		self._lastResult = None
		self._dirty = threading.Event()
		self.lastResult = None
		# How each text item looked in the last picture, to learn the selected look when the selection moves.
		self._lastLooks = None

	def _get_allowAutoRefresh(self):
		return self._live

	def _get_autoRefreshInterval(self):
		return CURTAIN_INTERVAL_MS if self._underCurtain else LIVE_INTERVAL_MS

	def _get_autoSayAllOnResult(self):
		return False

	def getResizeFactor(self, width, height):
		return 1

	def namesChanged(self):
		"""Rebuild on the next refresh, even if the window looks the same."""
		self._dirty.set()

	def cancel(self):
		self._cancelled = True

	def recognize(self, pixels, imageInfo, onResult):
		# NVDA's own picture is black under the screen curtain, so take our own.
		self._cancelled = False
		self.lastStarted = time.monotonic()
		box = (imageInfo.screenLeft, imageInfo.screenTop,
			imageInfo.screenLeft + imageInfo.screenWidth, imageInfo.screenTop + imageInfo.screenHeight)
		try:
			image = self._plugin.captureForOverlay(box)
		except Exception as e:
			onResult(e)
			return
		key = hashlib.sha1(image.tobytes()).digest()
		if key == self._lastKey and self._lastResult is not None and not self._dirty.is_set():
			onResult(self._lastResult)
			return
		self._dirty.clear()

		def onLines(lines):
			if self._cancelled:
				return
			threading.Thread(
				target=self._build, args=(image, key, lines, imageInfo, onResult), name="visionMate-overlay", daemon=True,
			).start()

		ocr.recognizeAsync(image, onLines)

	def _build(self, image, key, lines, imageInfo, onResult):
		try:
			result = self._makeResult(image, lines, imageInfo)
		except Exception as e:
			log.error("VisionMate: overlay failed", exc_info=True)
			onResult(e)
			return
		if self._cancelled:
			return
		self._lastKey, self._lastResult = key, result
		self.lastResult = result
		onResult(result)

	def _selected(self, image, items):
		"""Index of the selected item, or None. The look of a selected item is learned per app: from a clear case,
		or from the selection moving between two pictures, so later pictures with several items that stand out
		still find it."""
		store = self._plugin.labels
		learned = _learnedLook(store, self.app)
		byIndex = {i: look(image, it["box"]) for i, it in enumerate(items) if it["kind"] == "text"}
		index, selectedLook = findHighlighted(image, items, learned, byIndex)
		looks = {items[i]["plain"] or items[i]["text"]: v for i, v in byIndex.items()}
		if index is None and self._lastLooks is not None:
			moved = selectionMoved(self._lastLooks, looks)
			if moved is not None:
				selectedLook = moved
				index = next((i for i, v in byIndex.items() if lookDistance(v, moved) <= LEARNED_LOOK_MATCH), None)
		self._lastLooks = looks
		if index is not None and selectedLook is not None and (learned is None
				or lookDistance(learned, selectedLook) > LEARNED_LOOK_MATCH / 2):
			store.setGuess(self.app, HIGHLIGHT_KEY, ",".join(str(v) for v in selectedLook))
		return index

	def _makeResult(self, image, lines, imageInfo):
		store = self._plugin.labels
		texts = mergeStacked(mergeIconBits([item for item in splitItems(lines) if not _looksLikeIcons(item)]))
		for item in texts:
			item["key"] = "t:" + item["text"]
			name, byUser = store.get(self.app, item["key"])
			if byUser and name:
				item["text"] = name
		for item in texts:
			item["textBox"] = item["box"]  # before icons beside it are joined to it
		textBoxes = [(b[0], b[1], b[2] - b[0], b[3] - b[1]) for b in (it["box"] for it in texts)]
		icons, unnamed = [], []
		for box in imaging.findIcons(image, textBoxes):
			check = layout.checkKind(image, box)
			label = layout.textRightOf(box, texts) if check else None
			if label is not None and "role" not in label:
				# A checkbox or radio button with its name beside it: one item, clicked on the box.
				label["role"], label["checked"] = check
				label["box"] = _box([label, {"box": box}])
				continue
			label = labelFor(box, texts)
			if label is not None:
				# An icon with its name next to it, like a desktop shortcut: one item, clicked in the middle.
				label["box"] = _box([label, {"box": box}])
				continue
			crop = imaging.iconCrop(image, box)
			iconKey = labels.imageKey(crop)
			name, byUser = store.get(self.app, iconKey)
			if not byUser:
				# A plain one-colour square, like a colour choice on a shopping page, is named by its measured colour.
				swatch = colours.swatch(image.crop(box))
				if swatch is not None:
					# Translators: A colour choice in the overlay, named by its measured colour, like "navy blue colour".
					name = _("{colour} colour").format(colour=colours.say(swatch))
			if not name:
				unnamed.append((iconKey, crop))
			icons.append({"kind": "icon", "key": iconKey, "box": box, "name": name})
		check = humancheck.kind(" ".join(t["text"] for t in texts))
		tiles = []
		if check == "grid":
			tiles = self._tiles(image, store)
			if tiles:
				def inside(it):
					return any(_inBox(it["box"], t["box"]) for t in tiles)
				texts = [t for t in texts if not inside(t)]
				icons = [i for i in icons if not inside(i)]
				unnamed = [(k, c) for k, c in unnamed if any(i["key"] == k for i in icons)]
		try:
			redCount, emptyRed = formcheck.mark(image, texts + icons)
		except Exception:
			log.error("VisionMate: could not look for red marks", exc_info=True)
			redCount, emptyRed = 0, []
		for box in emptyRed:
			# A field outlined in red with nothing written in it.
			texts.append({"kind": "text", "role": "field", "text": "", "box": box, "red": True})
			redCount += 1
		try:
			groups = layout.arrange(image, texts + icons + tiles)
		except Exception:
			log.error("VisionMate: could not find the window's layout", exc_info=True)
			groups = [(None, orderItems(texts + icons + tiles))]
		for _area, members in groups:
			for item in members:
				item["plain"] = item.get("text", "")
				item["text"] = itemText(item)
		groups = [(area, _withTables(members)) for area, members in groups]
		for area, _members in groups:
			if area is not None:
				area["scroll"] = structure.scrollState(image, area["box"])
		items = [item for _area, members in groups for item in members if item["kind"] != "label"]
		if unnamed:
			self._plugin.nameIcons(self.app, unnamed, self.namesChanged)
		# Translators: First line of the overlay. {title} is the window title, {count} the number of items.
		headers = [_("{title}, {count} items").format(title=self.title or self.app, count=len(items))]
		if check is not None:
			headers.append(humancheck.advice(check, " ".join(t.get("plain", "") for t in texts)))
		if redCount:
			# Translators: A line of the overlay when the form marks items in red. R moves to them.
			headers.append(_("{count} marked in red. R moves to them.").format(count=redCount))
		index = self._selected(image, items)
		if index is not None:
			# Translators: A line of the overlay when one item looks selected. {item} is its text.
			headers.append(_("Selected: {item}").format(item=items[index]["plain"] or items[index]["text"]))
		if len(groups) == 1 and groups[0][0] is None:
			more = scrollText(structure.scrollState(image))
			if more:
				headers.append(more)
		lines = [(areaLine(area, sum(1 for it in members if it["kind"] != "label")) if area is not None else None, members)
			for area, members in groups]
		result = OverlayResult(items, imageInfo, headers, lines)
		result.selectedIndex = index
		return result

	def _tiles(self, image, store):
		"""The squares of a picture puzzle as overlay items, numbered left to right and top to bottom, named by what
		they show in the background."""
		boxes = humancheck.findGrid(image)
		if not boxes:
			return []
		tiles, unnamed = [], []
		for number, box in enumerate(boxes, 1):
			crop = image.crop(box)
			key = labels.imageKey(crop)
			name, _byUser = store.get(self.app, key)
			if not name:
				unnamed.append((key, crop))
			tiles.append({"kind": "icon", "role": "button", "key": key, "box": box, "name": name, "tile": number})
		if unnamed:
			self._plugin.nameIcons(self.app, unnamed, self.namesChanged, tiles=True)
		return tiles


def _inBox(inner, outer):
	cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
	return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _withTables(members):
	"""Members with tables read row by row, each after a line like "Table, 4 rows, 3 columns"."""
	ordered, tables = structure.findTables(members)
	if not tables:
		return members
	result = []
	for item in ordered:
		cell = item.get("cell")
		if cell is not None and tables[cell[0]]["first"] is item:
			t = tables[cell[0]]
			# Translators: The line before a table in the overlay. {rows} and {columns} are numbers.
			result.append({"kind": "label", "role": "table", "text": _("Table, {rows} rows, {columns} columns").format(
				rows=t["rows"], columns=t["columns"]), "plain": "", "box": item["box"]})
		result.append(item)
	return result


def scrollText(state):
	"""Words for a scroll bar's state: "more below", "more above", "more above and below", or ""."""
	if not state:
		return ""
	above, below = state
	if above and below:
		# Translators: Said for an area of the overlay that can scroll both ways.
		return _("more above and below")
	if below:
		# Translators: Said for an area of the overlay that has more below what is shown.
		return _("more below")
	if above:
		# Translators: Said for an area of the overlay that has more above what is shown.
		return _("more above")
	return ""


def _learnedLook(store, app):
	saved, _byUser = store.get(app, HIGHLIGHT_KEY)
	try:
		return tuple(int(v) for v in saved.split(",")) if saved else None
	except ValueError:
		return None


def _opensWithDoubleClick(x, y):
	"""Desktop shortcuts and files in a list open with a double click, the way Enter opens them.
	Everything else, including anything NVDA cannot see, gets a single click."""
	try:
		import api
		import controlTypes
		obj = api.getDesktopObject().objectFromPoint(x, y)
		return obj is not None and obj.role == controlTypes.Role.LISTITEM
	except Exception:
		log.debug("VisionMate: could not check the object under a point")
		return False


class OverlayDocument(recogUi.RefreshableRecogResultNVDAObject):
	"""The overlay as NVDA shows it. Besides NVDA's arrow keys: Tab and Shift+Tab move by item, H, B, E, X, K and D
	move to the next heading, button, edit field, checkbox, link and area (with Shift, the previous one),
	Enter activates (a double click on list items like desktop shortcuts, otherwise a click), Space clicks,
	Shift+Enter double-clicks, the Applications key right-clicks. The overlay stays open after a
	click or when the real window changes, until Escape."""

	# Translators: Name of the overlay document.
	name = _("VisionMate overlay")

	def __init__(self, plugin=None, restoreText=None, startBest=False, **kwargs):
		self._plugin = plugin
		self._restoreText = restoreText
		self._startBest = startBest
		self._newWindow = False
		super().__init__(**kwargs)

	def newWindow(self):
		"""The overlay now shows another window. When it is read, say only its first line, not every new line."""
		self._newWindow = True

	def refreshNow(self):
		self._recognize(self._onResult)

	def keepAlive(self):
		"""After NVDA's focus came back, make sure live updates still run."""
		import core
		recognizer = self.recognizer
		if not recognizer.allowAutoRefresh:
			return
		try:
			self.startMonitoring()
		except Exception:
			log.debugWarning("VisionMate: could not start live updates", exc_info=True)

		def check():
			# If a refresh was missed while the focus was away, the refresh loop has stopped: start it again.
			if self._plugin._overlayDoc is self and time.monotonic() - recognizer.lastStarted > STALL_SECONDS:
				self.refreshNow()

		core.callLater(int(STALL_SECONDS * 1000), check)

	def _onResult(self, result):
		if self._newWindow and isinstance(result, OverlayResult):
			self._newWindow = False
			try:
				self.stopMonitoring()  # do not read out the whole new window
			except Exception:
				log.debugWarning("VisionMate: could not pause live updates", exc_info=True)
			super()._onResult(result)
			import queueHandler
			queueHandler.queueFunction(queueHandler.eventQueue, self._showNewWindow, result)
			return
		super()._onResult(result)

	def _showNewWindow(self, result):
		"""Go to the top of the new window's items and say its first line: its name and how many items."""
		import speech
		import textInfos
		from controlTypes import OutputReason
		info = result.makeTextInfo(self, textInfos.POSITION_FIRST)
		self._selection = info
		speech.cancelSpeech()
		line = info.copy()
		line.expand(textInfos.UNIT_LINE)
		speech.speakTextInfo(line, unit=textInfos.UNIT_LINE, reason=OutputReason.CARET)
		if self.recognizer.allowAutoRefresh:
			try:
				self.startMonitoring()
			except Exception:
				log.debugWarning("VisionMate: could not restart live updates", exc_info=True)

	def _onFirstResult(self, result):
		super()._onFirstResult(result)
		if self._restoreText and isinstance(result, OverlayResult):
			import queueHandler
			queueHandler.queueFunction(queueHandler.eventQueue, self._restore, result, self._restoreText)
		elif self._startBest and isinstance(result, OverlayResult):
			import queueHandler
			queueHandler.queueFunction(queueHandler.eventQueue, self._goToBest, result)

	def _goToBest(self, result):
		"""Put the cursor where a sighted person's eye goes first, and say why."""
		import ui
		index, why = findonscreen.mostUseful(result.items, getattr(result, "selectedIndex", None))
		if index is None:
			# Translators: Reported when the overlay has nothing to go to.
			ui.message(_("Nothing found in this window."))
			return
		offset = result.lineOf(result.items[index])
		if offset is None:
			return
		self._goTo(result, offset)
		reasons = {
			# Translators: Why the overlay put the cursor on an item.
			"selected": _("it looks selected"), "default": _("it is the usual next step"),
			"field": _("it is an empty field to type in"), "biggest": _("it is the biggest button"),
			"first": _("it is the first item"),
		}
		# Translators: Said after the overlay moved to its most useful item. {why} is a reason.
		ui.message(_("Most useful here, because {why}. A for actions.").format(why=reasons[why]))

	def script_mostUseful(self, gesture):
		result = getattr(self.recognizer, "lastResult", None)
		if isinstance(result, OverlayResult):
			self._goToBest(result)

	def script_actions(self, gesture):
		result, item = self._currentItem()
		if item is None:
			import ui
			# Translators: Reported in the overlay when the cursor is not on an item.
			ui.message(_("No item here."))
			return
		left, top, right, bottom = item["box"]
		info = result.imageInfo
		box = (info.convertXToScreen(left), info.convertYToScreen(top), info.convertXToScreen(right),
			info.convertYToScreen(bottom))
		text = item["text"]
		isText = item.get("kind") == "text" and bool((item.get("plain") or "").strip())
		self._plugin.itemActions(result.screenPoint(item), box, item.get("plain") or text, isText,
			afterClick=lambda: self._plugin.overlayClicked(text))

	def script_nextRed(self, gesture):
		# Translators: Reported in the overlay when there is no next item marked in red.
		self._jump(("red",), True, _("No next item marked in red"))

	def script_previousRed(self, gesture):
		# Translators: Reported in the overlay when there is no previous item marked in red.
		self._jump(("red",), False, _("No previous item marked in red"))

	def _restore(self, result, text):
		"""Put the cursor back on the item that was clicked, after the overlay opened again."""
		offset = result.offsetOf(text)
		if offset is None:
			return
		import speech
		import textInfos
		from controlTypes import OutputReason
		from textInfos.offsets import Offsets
		info = result.makeTextInfo(self, Offsets(offset, offset))
		self._selection = info
		speech.cancelSpeech()
		line = info.copy()
		line.expand(textInfos.UNIT_LINE)
		speech.speakTextInfo(line, unit=textInfos.UNIT_LINE, reason=OutputReason.CARET)

	def _currentItem(self):
		result = getattr(self.recognizer, "lastResult", None)
		try:
			offset = self._selection._startOffset
		except AttributeError:
			return None, None
		return result, (result.itemAt(offset) if result is not None else None)

	def _click(self, kind):
		result, item = self._currentItem()
		if item is None:
			return
		import mouseHandler
		import winUser
		import core
		x, y = result.screenPoint(item)
		if kind == "activate":
			kind = "double" if _opensWithDoubleClick(x, y) else "single"
		log.debug(f"VisionMate: overlay {kind} click on {item['text']!r} at {(x, y)}")
		sounds.play("click")
		old = winUser.getCursorPos()
		winUser.setCursorPos(x, y)
		if kind == "right":
			mouseHandler.doSecondaryClick()
		else:
			mouseHandler.doPrimaryClick()
			if kind == "double":
				mouseHandler.doPrimaryClick()
		# Windows handles the click a moment later, so put the mouse back only after that.
		core.callLater(CLICK_SETTLE_MS, winUser.setCursorPos, *old)
		self._plugin.overlayClicked(item["text"])

	def script_activatePosition(self, gesture):
		self._click("activate")

	def script_select(self, gesture):
		self._click("single")

	def script_doubleClick(self, gesture):
		self._click("double")

	def script_rightClick(self, gesture):
		self._click("right")

	def script_nextItem(self, gesture):
		self.script_moveByLine_forward(gesture)

	def script_previousItem(self, gesture):
		self.script_moveByLine_back(gesture)

	def _jump(self, roles, forward, notFound):
		"""Move to the next or previous item of these roles and read it, like quick navigation in browse mode."""
		result = getattr(self.recognizer, "lastResult", None)
		try:
			offset = self._selection._startOffset
		except AttributeError:
			return
		if not isinstance(result, OverlayResult):
			return
		target = result.findLine(offset, roles, forward)
		if target is None:
			import ui
			ui.message(notFound)
			return
		import speech
		import textInfos
		from controlTypes import OutputReason
		from textInfos.offsets import Offsets
		info = result.makeTextInfo(self, Offsets(target, target))
		self._selection = info
		speech.cancelSpeech()
		line = info.copy()
		line.expand(textInfos.UNIT_LINE)
		speech.speakTextInfo(line, unit=textInfos.UNIT_LINE, reason=OutputReason.CARET)

	def script_nextHeading(self, gesture):
		# Translators: Reported in the overlay when there is no next heading.
		self._jump(("heading",), True, _("No next heading"))

	def script_previousHeading(self, gesture):
		# Translators: Reported in the overlay when there is no previous heading.
		self._jump(("heading",), False, _("No previous heading"))

	def script_nextButton(self, gesture):
		# Translators: Reported in the overlay when there is no next button.
		self._jump(("button",), True, _("No next button"))

	def script_previousButton(self, gesture):
		# Translators: Reported in the overlay when there is no previous button.
		self._jump(("button",), False, _("No previous button"))

	def script_nextField(self, gesture):
		# Translators: Reported in the overlay when there is no next edit field.
		self._jump(("field",), True, _("No next edit field"))

	def script_previousField(self, gesture):
		# Translators: Reported in the overlay when there is no previous edit field.
		self._jump(("field",), False, _("No previous edit field"))

	def script_nextCheckbox(self, gesture):
		# Translators: Reported in the overlay when there is no next checkbox or radio button.
		self._jump(("checkbox", "radio"), True, _("No next checkbox"))

	def script_previousCheckbox(self, gesture):
		# Translators: Reported in the overlay when there is no previous checkbox or radio button.
		self._jump(("checkbox", "radio"), False, _("No previous checkbox"))

	def script_nextLink(self, gesture):
		# Translators: Reported in the overlay when there is no next link.
		self._jump(("link",), True, _("No next link"))

	def script_previousLink(self, gesture):
		# Translators: Reported in the overlay when there is no previous link.
		self._jump(("link",), False, _("No previous link"))

	def script_nextArea(self, gesture):
		# Translators: Reported in the overlay when there is no next area.
		self._jump(("area",), True, _("No next area"))

	def script_previousArea(self, gesture):
		# Translators: Reported in the overlay when there is no previous area.
		self._jump(("area",), False, _("No previous area"))

	def script_nextTable(self, gesture):
		# Translators: Reported in the overlay when there is no next table.
		self._jump(("table",), True, _("No next table"))

	def script_previousTable(self, gesture):
		# Translators: Reported in the overlay when there is no previous table.
		self._jump(("table",), False, _("No previous table"))

	def _moveInTable(self, rowStep, columnStep):
		"""Move to the next cell down, up, right or left in a table, like table navigation in browse mode."""
		import ui
		result, item = self._currentItem()
		if result is None or item is None or item.get("cell") is None:
			# Translators: Reported in the overlay when table navigation is used outside a table.
			ui.message(_("Not in a table"))
			return
		target = structure.moveInTable(result.items, item, rowStep, columnStep)
		if target is None:
			# Translators: Reported in the overlay at the edge of a table.
			ui.message(_("Edge of table"))
			return
		self._goTo(result, result.lineOf(target))
		_number, row, column = target["cell"]
		# Translators: Where a table cell is, said before its text. {row} and {column} count from 1.
		ui.message(_("Row {row}, column {column}").format(row=row + 1, column=column + 1))

	def _goTo(self, result, offset, speak=True):
		import speech
		import textInfos
		from controlTypes import OutputReason
		from textInfos.offsets import Offsets
		info = result.makeTextInfo(self, Offsets(offset, offset))
		self._selection = info
		speech.cancelSpeech()
		if speak:
			line = info.copy()
			line.expand(textInfos.UNIT_LINE)
			speech.speakTextInfo(line, unit=textInfos.UNIT_LINE, reason=OutputReason.CARET)

	def script_tableDown(self, gesture):
		self._moveInTable(1, 0)

	def script_tableUp(self, gesture):
		self._moveInTable(-1, 0)

	def script_tableRight(self, gesture):
		self._moveInTable(0, 1)

	def script_tableLeft(self, gesture):
		self._moveInTable(0, -1)

	def script_exit(self, gesture):
		sounds.play("overlayClose")
		self._plugin.overlayClosed()
		super().script_exit(gesture)

	__gestures = {
		"kb:space": "select",
		"kb:tab": "nextItem",
		"kb:shift+tab": "previousItem",
		"kb:shift+enter": "doubleClick",
		"kb:applications": "rightClick",
		"kb:shift+f10": "rightClick",
		# Quick navigation, with the same letters as browse mode.
		"kb:h": "nextHeading", "kb:shift+h": "previousHeading",
		"kb:b": "nextButton", "kb:shift+b": "previousButton",
		"kb:e": "nextField", "kb:shift+e": "previousField",
		"kb:x": "nextCheckbox", "kb:shift+x": "previousCheckbox",
		"kb:k": "nextLink", "kb:shift+k": "previousLink",
		"kb:d": "nextArea", "kb:shift+d": "previousArea",
		"kb:t": "nextTable", "kb:shift+t": "previousTable",
		"kb:r": "nextRed", "kb:shift+r": "previousRed",
		"kb:a": "actions", "kb:u": "mostUseful",
		# Table navigation, with the same keys as browse mode.
		"kb:control+alt+downArrow": "tableDown", "kb:control+alt+upArrow": "tableUp",
		"kb:control+alt+rightArrow": "tableRight", "kb:control+alt+leftArrow": "tableLeft",
	}
