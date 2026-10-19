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

from . import imaging, labels, layout, ocr, sounds

addonHandler.initTranslation()

LIVE_INTERVAL_MS = 1000
# With the screen curtain on, each window is drawn on its own, which is slower, so refresh less often.
CURTAIN_INTERVAL_MS = 3000
# Words further apart than this many line heights are separate items, like buttons on one row.
ITEM_GAP = 1.2
# How much brighter or darker than the others an item's background must be to count as selected.
HIGHLIGHT_MIN_DIFF = 35
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
		result.append({"kind": "text", "text": " ".join(w["text"] for w in words), "box": (left, top, right, bottom),
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


def _background(image, box):
	left, top, right, bottom = box
	pad = 4
	w, h = image.size
	crop = image.crop((max(0, left - pad), max(0, top - pad), min(w, right + pad), min(h, bottom + pad)))
	return ImageStat.Stat(crop.convert("L")).median[0]


def findHighlighted(image, items):
	"""Index of the text item that stands out from the others, like a selected menu entry, or None."""
	texts = [i for i, item in enumerate(items) if item["kind"] == "text"]
	if len(texts) < 3:
		return None
	values = {i: _background(image, items[i]["box"]) for i in texts}
	ordered = sorted(values.values())
	median = ordered[len(ordered) // 2]
	diffs = sorted(((abs(v - median), i) for i, v in values.items()), reverse=True)
	best, index = diffs[0]
	if best < HIGHLIGHT_MIN_DIFF or diffs[1][0] > best * 0.6:
		return None
	return index


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
		self.items = [item for _line, members in groups for item in members]
		self.headerCount = len(headers)
		# For each line: its item, or None for header and area lines.
		self.lineItems = [None] * len(headers)
		self.areaLines = []
		texts = list(headers)
		for line, members in groups:
			if line is not None:
				self.areaLines.append(len(texts))
				self.lineItems.append(None)
				texts.append(line)
			for item in members:
				self.lineItems.append(item)
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
			if ("area" in roles and i in self.areaLines) or (item is not None and item.get("role") in roles):
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
	"""What the overlay says for an item: its text and what kind of item it is."""
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
	return _("{area}, {count} items").format(area=name, count=count)


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

	def _makeResult(self, image, lines, imageInfo):
		store = self._plugin.labels
		texts = mergeStacked([item for item in splitItems(lines) if not _looksLikeIcons(item)])
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
			name, _byUser = store.get(self.app, iconKey)
			if not name:
				unnamed.append((iconKey, crop))
			icons.append({"kind": "icon", "key": iconKey, "box": box, "name": name})
		try:
			groups = layout.arrange(image, texts + icons)
		except Exception:
			log.error("VisionMate: could not find the window's layout", exc_info=True)
			groups = [(None, orderItems(texts + icons))]
		for _area, members in groups:
			for item in members:
				item["plain"] = item.get("text", "")
				item["text"] = itemText(item)
		items = [item for _area, members in groups for item in members]
		if unnamed:
			self._plugin.nameIcons(self.app, unnamed, self.namesChanged)
		# Translators: First line of the overlay. {title} is the window title, {count} the number of items.
		headers = [_("{title}, {count} items").format(title=self.title or self.app, count=len(items))]
		index = findHighlighted(image, items)
		if index is not None:
			# Translators: A line of the overlay when one item looks selected. {item} is its text.
			headers.append(_("Selected: {item}").format(item=items[index]["plain"] or items[index]["text"]))
		lines = [(areaLine(area, len(members)) if area is not None else None, members) for area, members in groups]
		return OverlayResult(items, imageInfo, headers, lines)


def _opensWithDoubleClick(x, y):
	"""Desktop shortcuts and files in a list open with a double click, the way Enter opens them.
	Everything else, including anything NVDA cannot see, gets a single click."""
	try:
		import api
		import controlTypes
		obj = api.getDesktopObject().objectFromPoint(x, y)
		return obj is not None and obj.role == controlTypes.Role.LISTITEM
	except Exception:
		return False


class OverlayDocument(recogUi.RefreshableRecogResultNVDAObject):
	"""The overlay as NVDA shows it. Besides NVDA's arrow keys: Tab and Shift+Tab move by item, H, B, E, X, K and D
	move to the next heading, button, edit field, checkbox, link and area (with Shift, the previous one),
	Enter activates (a double click on list items like desktop shortcuts, otherwise a click), Space clicks,
	Shift+Enter double-clicks, the Applications key right-clicks. The overlay stays open after a
	click or when the real window changes, until Escape."""

	# Translators: Name of the overlay document.
	name = _("VisionMate overlay")

	def __init__(self, plugin=None, restoreText=None, **kwargs):
		self._plugin = plugin
		self._restoreText = restoreText
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
			pass

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
				pass
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
				pass

	def _onFirstResult(self, result):
		super()._onFirstResult(result)
		if self._restoreText and isinstance(result, OverlayResult):
			import queueHandler
			queueHandler.queueFunction(queueHandler.eventQueue, self._restore, result, self._restoreText)

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
	}
