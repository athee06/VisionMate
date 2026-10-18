# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - the overlay's layout, found from shapes and colours without AI: the window's areas, like a sidebar
# or a dialog, and which items are buttons, edit fields, checkboxes, radio buttons, links and headings.
# The vision data was tested for this and could not tell these apart, so it only names icons.

import collections
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# The window is looked at in cells, so it stays fast without extra libraries. Bigger windows use bigger cells.
MIN_CELL = 4
MAX_CELLS = 60000
EDGE_THRESHOLD = 40
# Neighbouring cells this close in colour (per colour channel) have the same background.
COLOR_TOLERANCE = 10
# An area is at least this share of the window and this big.
AREA_MIN_SHARE = 0.04
AREA_MIN_WIDTH = 120
AREA_MIN_HEIGHT = 28
# A floating area at least this share of the window is a dialog; smaller ones are panels.
DIALOG_MIN_SHARE = 0.08
# A bar along the top or bottom is at most this share of the window's height; a side panel this share of its width.
BAR_MAX_SHARE = 0.2
PANEL_MAX_SHARE = 0.4
# Areas are read in this order: what floats on top first, as it usually needs an answer.
AREA_ORDER = ("dialog", "panel", "top", "left", "main", "right", "bottom")
# Boxes, like buttons and edit fields: their height in pixels, and how rectangular they must be.
BOX_MIN_HEIGHT = 14
BOX_MAX_HEIGHT = 90
BOX_MIN_FILL = 0.7
BOX_MAX_WIDTH_SHARE = 0.6
# A box this different in colour from the area around it is filled, like a button; edit fields are not.
FILLED_DIFFERENCE = 40
# An edit field is at least this many times as wide as it is tall.
FIELD_MIN_ASPECT = 3
# Text this many times taller than most text is a heading, if it is short.
HEADING_FACTOR = 1.4
HEADING_MAX_WORDS = 8
# Columns side by side, with an empty gap at least this wide between them, each spanning this share of the area's
# height, are read one after the other.
COLUMN_MIN_GAP = 24
COLUMN_MIN_SPAN = 0.4
COLUMN_MIN_ITEMS = 3
# How different from the background a pixel must be to be a line, like an underline or a checkbox border.
INK_DIFFERENCE = 60
UNDERLINE_MIN_SHARE = 0.9
# A word starting like this is text, not a checkbox read as a letter.
_REAL_WORD_START = re.compile(r"[A-Za-z]{2}")
# Checkboxes and radio buttons: their size in pixels.
CHECK_MIN_SIDE = 10
CHECK_MAX_SIDE = 28


def _distance(a, b):
	return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def _outsideColor(image, box, pad=3):
	"""The background colour around a box: the most common of the four points just outside its corners."""
	w, h = image.size
	left, top, right, bottom = box
	points = [(left - pad, top - pad), (right + pad, top - pad), (left - pad, bottom + pad), (right + pad, bottom + pad)]
	colors = [image.getpixel((min(max(x, 0), w - 1), min(max(y, 0), h - 1))) for x, y in points]
	return collections.Counter(colors).most_common(1)[0][0]


def _mostCommonColor(image, box):
	crop = image.crop(box)
	colors = crop.getcolors(crop.width * crop.height)
	return max(colors)[1] if colors else (255, 255, 255)


class _Region:
	__slots__ = ("index", "cells", "box", "color", "kind", "name", "parent", "items")

	def __init__(self, index, color):
		self.index = index
		self.cells = 0
		self.box = None
		self.color = color
		self.kind = None  # "area", "box" or None
		self.name = None
		self.parent = None
		self.items = []


class Layout:
	"""Background regions of a window picture. Text and icons are painted over first, so only backgrounds,
	borders and lines are left."""

	def __init__(self, image, itemBoxes):
		self.image = image.convert("RGB")
		w, h = self.image.size
		self.size = (w, h)
		cell = MIN_CELL
		while (w // cell) * (h // cell) > MAX_CELLS:
			cell += 1
		self.cell = cell
		self.gw, self.gh = max(1, w // cell), max(1, h // cell)
		plain = self.image.copy()
		draw = ImageDraw.Draw(plain)
		for box in itemBoxes:
			left, top, right, bottom = box
			draw.rectangle((left - 2, top - 2, right + 2, bottom + 2), fill=_outsideColor(self.image, box))
		self._label(plain)

	def _label(self, plain):
		cell, gw, gh = self.cell, self.gw, self.gh
		area = (0, 0, gw * cell, gh * cell)
		colors = list(plain.crop(area).reduce(cell).getdata())
		edges = plain.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > EDGE_THRESHOLD else 0)
		ImageDraw.Draw(edges).rectangle((0, 0, edges.width - 1, edges.height - 1), outline=0)
		ink = edges.crop(area).reduce(cell).tobytes()
		labels = [-1] * (gw * gh)
		regions = []
		for start in range(gw * gh):
			if labels[start] != -1 or ink[start]:
				continue
			region = _Region(len(regions), colors[start])
			regions.append(region)
			labels[start] = region.index
			stack = [start]
			x0 = x1 = start % gw
			y0 = y1 = start // gw
			n = 0
			while stack:
				i = stack.pop()
				n += 1
				x, y = i % gw, i // gw
				if x < x0:
					x0 = x
				elif x > x1:
					x1 = x
				if y < y0:
					y0 = y
				elif y > y1:
					y1 = y
				c = colors[i]
				for j in (i - 1 if x > 0 else -1, i + 1 if x < gw - 1 else -1, i - gw, i + gw):
					if 0 <= j < gw * gh and labels[j] == -1 and not ink[j] and _distance(colors[j], c) <= COLOR_TOLERANCE:
						labels[j] = region.index
						stack.append(j)
			region.cells = n
			region.box = (x0 * cell, y0 * cell, (x1 + 1) * cell, (y1 + 1) * cell)
		self._labels = labels
		self.regions = regions
		total = gw * gh
		w, h = self.size
		for r in regions:
			left, top, right, bottom = r.box
			rw, rh = right - left, bottom - top
			bw, bh = (rw // cell) or 1, (rh // cell) or 1
			if r.cells / total >= AREA_MIN_SHARE and rw >= AREA_MIN_WIDTH and rh >= AREA_MIN_HEIGHT:
				r.kind = "area"
			elif (BOX_MIN_HEIGHT <= rh <= BOX_MAX_HEIGHT and rw >= 0.8 * rh and rw <= BOX_MAX_WIDTH_SHARE * w
					and r.cells / (bw * bh) >= BOX_MIN_FILL):
				r.kind = "box"
		areas = [r for r in regions if r.kind == "area"]
		self.main = max(areas, key=lambda r: r.cells) if areas else None
		for r in regions:
			if r.kind is not None and r is not self.main:
				r.parent = self._enclosing(r)

	def regionAt(self, x, y):
		gx, gy = int(x) // self.cell, int(y) // self.cell
		if not (0 <= gx < self.gw and 0 <= gy < self.gh):
			return None
		index = self._labels[gy * self.gw + gx]
		return self.regions[index] if index >= 0 else None

	def _enclosing(self, region):
		"""The area around a region: what is just outside its left, top, right or bottom edge."""
		left, top, right, bottom = region.box
		cx, cy = (left + right) // 2, (top + bottom) // 2
		reach = 2 * self.cell
		for x, y in ((left - reach, cy), (cx, top - reach), (right + reach, cy), (cx, bottom + reach)):
			for step in range(4):
				outer = self.regionAt(x - step * self.cell if x < left else x + step * self.cell if x > right else x,
					y - step * self.cell if y < top else y + step * self.cell if y > bottom else y)
				if outer is not None and outer is not region and outer.cells > region.cells:
					return self._areaOf(outer)
		return self.main

	def _areaOf(self, region):
		seen = set()
		while region is not None and region.kind != "area" and region.index not in seen:
			seen.add(region.index)
			region = region.parent or (self._enclosing(region) if region.kind is None else None)
		return region or self.main

	def regionOf(self, box):
		"""The background region an item sits on. Text was painted over with its background, so the middle of the
		item is on it; if that spot is a small leftover, the spot just left of the item is used."""
		left, top, right, bottom = box
		cx, cy = (left + right) // 2, (top + bottom) // 2
		region = self.regionAt(cx, cy)
		itemCells = max(1, ((right - left) // self.cell) * ((bottom - top) // self.cell))
		if region is None or (region.kind is None and region.cells < itemCells):
			for x, y in ((left - 2 * self.cell, cy), (cx, top - 2 * self.cell), (right + 2 * self.cell, cy)):
				other = self.regionAt(x, y)
				if other is not None:
					return other
		return region

	def areaName(self, region):
		"""Where an area is in the window: dialog, panel, top bar, bottom bar, left panel, right panel or main area."""
		w, h = self.size
		left, top, right, bottom = region.box
		margin = 2 * self.cell
		atLeft, atTop = left <= margin, top <= margin
		atRight, atBottom = right >= w - margin, bottom >= h - margin
		if not (atLeft or atTop or atRight or atBottom):
			share = (right - left) * (bottom - top) / (w * h)
			return "dialog" if share >= DIALOG_MIN_SHARE else "panel"
		if region is self.main:
			return "main"
		if atTop and not atBottom and bottom - top <= BAR_MAX_SHARE * h:
			return "top"
		if atBottom and not atTop and bottom - top <= BAR_MAX_SHARE * h:
			return "bottom"
		if atLeft and not atRight and right - left <= PANEL_MAX_SHARE * w:
			return "left"
		if atRight and not atLeft and right - left <= PANEL_MAX_SHARE * w:
			return "right"
		return "main"


def isUnderlined(image, box):
	"""True if a line runs under the text, as under a link."""
	left, top, right, bottom = box
	w, h = image.size
	if right - left < 12:
		return False
	bg = _mostCommonColor(image, box)
	for y in range(top + (bottom - top) * 3 // 5, min(h, bottom + 4)):
		row = [image.getpixel((x, y)) for x in range(left, min(w, right))]
		if row and sum(1 for c in row if _distance(c, bg) > INK_DIFFERENCE) >= UNDERLINE_MIN_SHARE * len(row):
			return True
	return False


def checkKind(image, box):
	"""("checkbox" or "radio", checked) if a small shape is a checkbox or radio button, otherwise None.
	A checkbox has a border on all four sides; a radio button is round, so its corners are empty.
	Checked ones have a mark or fill in the middle."""
	image = image.convert("RGB")
	bg = _outsideColor(image, box, pad=4)
	# Shapes are found on a grid, so first trim the box to the shape itself.
	left, top, right, bottom = box
	diff = ImageChops.difference(image.crop(box), Image.new("RGB", (right - left, bottom - top), bg)).convert("L")
	inkBox = diff.point(lambda v: 255 if v > INK_DIFFERENCE else 0).getbbox()
	if not inkBox:
		return None
	box = (left + inkBox[0], top + inkBox[1], left + inkBox[2], top + inkBox[3])
	left, top, right, bottom = box
	bw, bh = right - left, bottom - top
	if not (CHECK_MIN_SIDE <= bw <= CHECK_MAX_SIDE and CHECK_MIN_SIDE <= bh <= CHECK_MAX_SIDE) or not 0.8 <= bw / bh <= 1.25:
		return None
	crop = image.crop(box)
	w, h = crop.size

	def inked(x, y):
		return _distance(crop.getpixel((x, y)), bg) > INK_DIFFERENCE

	def sideShare(points):
		points = list(points)
		return sum(1 for p in points if any(inked(*q) for q in p)) / len(points)

	# Each side is checked one pixel deep or two, because shapes are found on a grid.
	sides = [
		sideShare([(x, 0), (x, 1)] for x in range(w)), sideShare([(x, h - 1), (x, h - 2)] for x in range(w)),
		sideShare([(0, y), (1, y)] for y in range(h)), sideShare([(w - 1, y), (w - 2, y)] for y in range(h)),
	]
	corners = [inked(x, y) for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
	middles = [inked(w // 2, 0) or inked(w // 2, 1), inked(w // 2, h - 1) or inked(w // 2, h - 2),
		inked(0, h // 2) or inked(1, h // 2), inked(w - 1, h // 2) or inked(w - 2, h // 2)]
	inner = [(x, y) for x in range(w * 3 // 10, w * 7 // 10 + 1) for y in range(h * 3 // 10, h * 7 // 10 + 1)]
	checked = sum(1 for p in inner if inked(*p)) >= 0.25 * len(inner)
	# Between the border and the middle there is a plain gap, or the whole box is one solid fill. Icons, like a
	# globe or a picture, have lines or detail there instead.
	d = max(2, min(w, h) // 5)
	gap = [(x, d) for x in range(w // 3, w - w // 3)] + [(x, h - 1 - d) for x in range(w // 3, w - w // 3)]
	gap += [(d, y) for y in range(h // 3, h - h // 3)] + [(w - 1 - d, y) for y in range(h // 3, h - h // 3)]
	gapInk = sum(1 for p in gap if inked(*p)) / len(gap)
	if gapInk > 0.25:
		colors = [crop.getpixel(p) for p in gap]
		if gapInk < 0.95 or max(_distance(c, colors[0]) for c in colors) > 30:
			return None
		checked = True  # a filled box, like a blue checkbox with a white tick
	if min(sides) >= 0.8 and sum(corners) >= 3:
		return "checkbox", checked
	if all(middles) and not any(corners):
		return "radio", checked
	return None


def isBoxedIcon(image, box):
	"""True if an icon sits on its own filled square or rounded box, as icon buttons in toolbars do."""
	left, top, right, bottom = box
	w, h = right - left, bottom - top
	inset = max(3, min(w, h) // 6)
	if w < 2 * inset + 4 or h < 2 * inset + 4:
		return False
	image = image.convert("RGB")
	inner = [image.getpixel(p) for p in ((left + inset, top + inset), (right - 1 - inset, top + inset),
		(left + inset, bottom - 1 - inset), (right - 1 - inset, bottom - 1 - inset))]
	if max(_distance(c, inner[0]) for c in inner) > COLOR_TOLERANCE:
		return False
	return _distance(inner[0], _outsideColor(image, box, pad=4)) > 25


def textRightOf(box, texts):
	"""The text item that starts just right of a small shape, on the same line, or None."""
	left, top, right, bottom = box
	size = max(right - left, bottom - top)
	cy = (top + bottom) / 2
	best = None
	for item in texts:
		tl, tt, tr, tb = item["box"]
		if 0 <= tl - right <= 1.5 * size and tt - size / 2 <= cy <= tb + size / 2:
			if best is None or tl < best["box"][0]:
				best = item
	return best


def _textBox(item):
	"""Where an item's own text is, without an icon joined to it."""
	return item.get("textBox") or item["box"]


def _lineHeight(item):
	"""The height of one line of an item's text, even if its name has two lines."""
	return item.get("lineHeight") or item["box"][3] - item["box"][1]


def _inColumn(item, texts):
	"""True if plain text items line up with this one, like the other rows of a list or menu."""
	left, top, right, bottom = item["box"]
	h = bottom - top
	for other in texts:
		ol, ot, orr, ob = other["box"]
		if other is not item and abs(ol - left) <= max(6, 0.3 * h) and 0.7 <= (ob - ot) / max(h, 1) <= 1.4 and abs(ot - top) <= 4 * h:
			return True
	return False


def _labelForField(field, texts):
	"""The text naming an edit field: right before it on the same line, or right above it."""
	left, top, right, bottom = field
	h = bottom - top
	cy = (top + bottom) / 2
	best, bestGap = None, None
	for item in texts:
		tl, tt, tr, tb = item["box"]
		if tt - h / 2 <= cy <= tb + h / 2 and 0 <= left - tr <= 3 * h:
			gap = left - tr
		elif 0 <= top - tb <= h and abs(tl - left) <= 2 * h:
			gap = top - tb
		else:
			continue
		if bestGap is None or gap < bestGap:
			best, bestGap = item, gap
	return best


def _readingOrder(items):
	"""Top to bottom and left to right, but columns side by side, like a sidebar beside the content, are read one
	after the other."""
	from .overlay import orderItems
	if len(items) < 2 * COLUMN_MIN_ITEMS:
		return orderItems(items)
	top = min(it["box"][1] for it in items)
	height = max(it["box"][3] for it in items) - top
	edges = sorted({it["box"][0] for it in items} | {it["box"][2] for it in items})
	best = None
	for x in edges:
		left = [it for it in items if it["box"][2] <= x]
		right = [it for it in items if it["box"][0] >= x + COLUMN_MIN_GAP]
		if len(left) + len(right) != len(items) or len(left) < COLUMN_MIN_ITEMS or len(right) < COLUMN_MIN_ITEMS:
			continue
		spans = [(max(i["box"][3] for i in side) - min(i["box"][1] for i in side)) / max(1, height) for side in (left, right)]
		if min(spans) >= COLUMN_MIN_SPAN:
			gap = min(it["box"][0] for it in right) - x
			if best is None or gap > best[0]:
				best = (gap, left, right)
	if best is None:
		return orderItems(items)
	return _readingOrder(best[1]) + _readingOrder(best[2])


def arrange(image, items):
	"""Find kinds and areas for the overlay's items, which have "text", "box" and "kind" ("text" or "icon").
	Sets item["role"] to "button", "field", "heading", "link", "checkbox" or "radio" when it is one, adds edit
	fields that have no text in them, and returns a list of (area, items) in reading order. area is None when the
	window has only one area, otherwise {"kind": "dialog"/"panel"/"top"/"bottom"/"left"/"right"/"main", "title": ...}.
	Within an area, items are in reading order."""
	layout = Layout(image, [_textBox(it) for it in items])
	image = layout.image
	heights = sorted(_lineHeight(it) for it in items if it["kind"] == "text")
	usual = heights[len(heights) // 2] if heights else 0
	inBox = collections.defaultdict(list)
	for item in items:
		region = layout.regionOf(_textBox(item))
		item["_region"] = region
		if region is not None and region.kind == "box":
			inBox[region.index].append(item)
	texts = [it for it in items if it["kind"] == "text"]
	# A checkbox or radio button that OCR read as a character, like "O" or "@", before its name.
	for item in texts:
		first = item.get("firstWord")
		if "role" in item or not first or len(item["text"].split()) < 2:
			continue
		word, wordBox = first
		if len(word) > 2 or _REAL_WORD_START.match(word):
			continue
		l, t, r, b = wordBox
		size = max(r - l, b - t)
		cx, cy = (l + r) // 2, (t + b) // 2
		check = checkKind(image, (cx - size // 2 - 3, cy - size // 2 - 3, cx + size // 2 + 4, cy + size // 2 + 4))
		if check:
			item["role"], item["checked"] = check
			item["fullText"] = item["text"]
			item["text"] = item["text"].split(None, 1)[1]
	# Radio buttons come in groups, lined up. A lone round shape is more likely an icon, like a globe.
	radios = [it for it in texts if it.get("role") == "radio"]
	for item in radios:
		l, t = item["box"][0], item["box"][1]
		if not any(o is not item and (abs(o["box"][0] - l) <= 6 or abs(o["box"][1] - t) <= 6) for o in radios):
			del item["role"], item["checked"]
			if "fullText" in item:
				item["text"] = item["fullText"]
	for item in texts:
		item.pop("fullText", None)
	plainTexts = [it for it in texts if it["_region"] is None or it["_region"].kind != "box"]
	for item in items:
		if item["kind"] == "icon" and isBoxedIcon(layout.image, item["box"]):
			item["role"] = "button"
	for index, members in inBox.items():
		box = layout.regions[index]
		if len(members) != 1:
			continue
		item = members[0]
		if item["kind"] == "text" and _inColumn(item, plainTexts):
			continue  # the highlighted row of a list or menu, not a button
		bl, bt, br, bb = box.box
		il, it_, ir, ib = item["box"]
		bw, bh = br - bl, bb - bt
		centred = abs((il + ir) / 2 - (bl + br) / 2) <= 0.2 * bw
		parent = box.parent or layout.main
		filled = parent is not None and _distance(box.color, parent.color) > FILLED_DIFFERENCE and min(box.color) < 230
		if item["kind"] == "text" and bw >= FIELD_MIN_ASPECT * bh and not centred and ir - il <= 0.6 * bw and not filled:
			item["role"] = "field"  # the text is a hint inside an edit field, like "Search"
			item["box"] = box.box
		else:
			item["role"] = "button"
	# Edit fields with nothing in them.
	added = []
	for region in layout.regions:
		if region.kind != "box" or region.index in inBox:
			continue
		left, top, right, bottom = region.box
		if right - left < FIELD_MIN_ASPECT * (bottom - top) or bottom - top < 18:
			continue
		label = _labelForField(region.box, [t for t in texts if "role" not in t])
		field = {"kind": "text", "role": "field", "box": region.box, "text": label["text"] if label else "",
			"key": label.get("key", "") + "|field" if label else "field:%d,%d" % (left, top), "_region": region}
		if label is not None:
			items.remove(label)
			texts.remove(label)
		added.append(field)
	items.extend(added)
	for item in texts:
		if "role" in item:
			continue
		region = item.get("_region")
		if item["text"].rstrip().endswith(("...", "…")) and region is not None and (
				region.kind == "box" or (region.kind == "area" and layout.areaName(region) == "panel")):
			item["role"] = "field"  # a hint like "Ask a question..." in a text box
			continue
		short = len(item["text"].split()) <= HEADING_MAX_WORDS and not item["text"].rstrip().endswith((".", ",", ":"))
		if usual and short and _lineHeight(item) >= HEADING_FACTOR * usual:
			item["role"] = "heading"
		elif isUnderlined(image, _textBox(item)):
			item["role"] = "link"
	# Group by area.
	groups = collections.OrderedDict()
	for item in items:
		region = item.pop("_region", None)
		area = layout._areaOf(region) if region is not None else layout.main
		groups.setdefault(area.index if area is not None else -1, []).append(item)
	if len(groups) <= 1:
		return [(None, _readingOrder(items))]
	result = []
	for index, members in groups.items():
		region = layout.regions[index] if index >= 0 else None
		kind = layout.areaName(region) if region is not None else "main"
		members = _readingOrder(members)
		heading = next((it["text"] for it in members if it.get("role") == "heading"), "")
		result.append(({"kind": kind, "title": heading, "box": region.box if region else (0, 0) + layout.size}, members))
	result.sort(key=lambda g: (AREA_ORDER.index(g[0]["kind"]), g[0]["box"][1] // 40, g[0]["box"][0]))
	return result
