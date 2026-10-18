# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - image helpers that need no AI: trimming empty borders, and finding icons on a screen.

import collections

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# Only trim when it removes at least this share of the picture.
MIN_CROP_SAVING = 0.15
CROP_PADDING = 8
# How different from the border colour a pixel must be to count as content.
CONTENT_THRESHOLD = 20

# Icon finding works on cells of this many pixels, so it stays fast without extra libraries.
CELL = 4
EDGE_THRESHOLD = 48
ICON_MIN_SIDE = 10
ICON_MAX_SIDE = 96
ICON_MAX_ASPECT = 2.5
# Icons sit on plain backgrounds. Shapes inside photos or busy textures are not icons.
MAX_RING_INK = 0.15
MAX_ICONS = 40
# Icons are named together from one picture: each sits in a numbered cell. Naming 16 this way takes about
# half as long as one by one.
SHEET_CELL = 96
SHEET_NUMBER_WIDTH = 40
SHEET_COLUMNS = 4
SHEET_MAX_ICONS = 16


def smartCrop(image):
	"""Trim plain borders, so the vision data spends its effort on the content."""
	rgb = image.convert("RGB")
	w, h = rgb.size
	if w < 64 or h < 64:
		return rgb
	corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
	bg, count = collections.Counter(corners).most_common(1)[0]
	if count < 3:
		return rgb
	diff = ImageChops.difference(rgb, Image.new("RGB", (w, h), bg)).convert("L")
	box = diff.point(lambda v: 255 if v > CONTENT_THRESHOLD else 0).getbbox()
	if not box:
		return rgb
	left, top = max(0, box[0] - CROP_PADDING), max(0, box[1] - CROP_PADDING)
	right, bottom = min(w, box[2] + CROP_PADDING), min(h, box[3] + CROP_PADDING)
	if (right - left) * (bottom - top) > (1 - MIN_CROP_SAVING) * w * h:
		return rgb
	return rgb.crop((left, top, right, bottom))


def _inkCells(image, textBoxes):
	"""A grid of cells that contain sharp edges, with text areas blanked out."""
	edges = image.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > EDGE_THRESHOLD else 0)
	# The outermost pixels always look like edges after filtering.
	draw = ImageDraw.Draw(edges)
	w, h = edges.size
	draw.rectangle((0, 0, w - 1, h - 1), outline=0)
	for x, y, bw, bh in textBoxes:
		draw.rectangle((x - 3, y - 3, x + bw + 3, y + bh + 3), fill=0)
	small = edges.reduce(CELL)
	return small.tobytes(), small.size[0], small.size[1]


def _components(cells, gw, gh):
	"""Bounding boxes, in cells, of groups of touching ink cells."""
	seen = bytearray(len(cells))
	boxes = []
	for start in range(len(cells)):
		if not cells[start] or seen[start]:
			continue
		seen[start] = 1
		stack = [start]
		x0 = x1 = start % gw
		y0 = y1 = start // gw
		n = 0
		while stack:
			i = stack.pop()
			n += 1
			x, y = i % gw, i // gw
			x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
			if n > 2000:
				break  # a huge shape like a photo; not an icon
			for dy in (-1, 0, 1):
				ny = y + dy
				if ny < 0 or ny >= gh:
					continue
				for dx in (-1, 0, 1):
					nx = x + dx
					if 0 <= nx < gw:
						j = ny * gw + nx
						if cells[j] and not seen[j]:
							seen[j] = 1
							stack.append(j)
		boxes.append((x0, y0, x1 + 1, y1 + 1, n))
	return boxes


def _ringInk(cells, gw, gh, box):
	"""Share of ink cells in a ring around a box."""
	x0, y0, x1, y1 = box
	bw, bh = x1 - x0, y1 - y0
	rx0, ry0 = max(0, x0 - bw // 2 - 1), max(0, y0 - bh // 2 - 1)
	rx1, ry1 = min(gw, x1 + bw // 2 + 1), min(gh, y1 + bh // 2 + 1)
	ink = total = 0
	for y in range(ry0, ry1):
		row = y * gw
		for x in range(rx0, rx1):
			if x0 <= x < x1 and y0 <= y < y1:
				continue
			total += 1
			if cells[row + x]:
				ink += 1
	return ink / total if total else 1


def findIcons(image, textBoxes=()):
	"""Find icon-like shapes that are not text. Returns boxes (left, top, right, bottom) in image pixels,
	top to bottom and left to right."""
	cells, gw, gh = _inkCells(image, textBoxes)
	icons = []
	for x0, y0, x1, y1, n in _components(cells, gw, gh):
		w, h = (x1 - x0) * CELL, (y1 - y0) * CELL
		if n < 3 or not (ICON_MIN_SIDE <= w <= ICON_MAX_SIDE and ICON_MIN_SIDE <= h <= ICON_MAX_SIDE):
			continue
		if max(w, h) > ICON_MAX_ASPECT * min(w, h):
			continue
		if _ringInk(cells, gw, gh, (x0, y0, x1, y1)) > MAX_RING_INK:
			continue
		icons.append((x0 * CELL, y0 * CELL, x1 * CELL, y1 * CELL))
	# A shape inside a button that was also found is part of the same icon.
	icons = [b for b in icons if not any(o != b and _contains(o, b) for o in icons)]
	icons.sort(key=lambda b: (b[1] // 16, b[0]))
	return icons[:MAX_ICONS]


def _contains(outer, inner):
	return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def iconCrop(image, box):
	"""The icon with a little space around it, for naming."""
	left, top, right, bottom = box
	pad = max(4, (right - left) // 4)
	w, h = image.size
	return image.crop((max(0, left - pad), max(0, top - pad), min(w, right + pad), min(h, bottom + pad)))


def iconSheet(crops):
	"""One picture with each icon in a cell, numbered from 1 in red on its left."""
	rows = (len(crops) + SHEET_COLUMNS - 1) // SHEET_COLUMNS
	width = SHEET_CELL + SHEET_NUMBER_WIDTH
	sheet = Image.new("RGB", (SHEET_COLUMNS * width, rows * SHEET_CELL), "white")
	draw = ImageDraw.Draw(sheet)
	try:
		font = ImageFont.truetype("segoeuib.ttf", 18)
	except OSError:
		font = ImageFont.load_default()
	for i, crop in enumerate(crops):
		x, y = (i % SHEET_COLUMNS) * width, (i // SHEET_COLUMNS) * SHEET_CELL
		crop = crop.convert("RGB")
		crop.thumbnail((SHEET_CELL - 12, SHEET_CELL - 12))
		sheet.paste(crop, (x + SHEET_NUMBER_WIDTH + (SHEET_CELL - crop.width) // 2, y + (SHEET_CELL - crop.height) // 2))
		draw.text((x + 6, y + SHEET_CELL // 2 - 12), str(i + 1), font=font, fill="red")
	return sheet
