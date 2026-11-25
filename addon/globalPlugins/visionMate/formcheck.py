# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Fields and text a form marks in red, measured from the pixels without AI: a field outlined in red, and an error
message written in red. Only what is on the screen is seen. No NVDA modules here, so it can be tested on its own."""
from PIL import Image

# A pixel is red when red is strong and clearly above green and blue.
RED_MIN = 150
RED_OVER = 70
# Text is red when this share of its dark-enough pixels is red.
TEXT_RED_SHARE = 0.3
# An outline is at least this big, and red covers at most this share of its box (a filled red block is not a field).
OUTLINE_MIN_WIDTH = 40
OUTLINE_MIN_HEIGHT = 14
OUTLINE_MAX_FILL = 0.45
# An outline must be red along most of its top and bottom edges.
OUTLINE_EDGE_SHARE = 0.6


def _isRed(p):
	r, g, b = p[0], p[1], p[2]
	return r >= RED_MIN and r - g >= RED_OVER and r - b >= RED_OVER


def redMask(image):
	"""A 1-bit picture: white where the pixel is red."""
	rgb = image.convert("RGB")
	r, g, b = rgb.split()
	# r >= RED_MIN, r - g >= RED_OVER, r - b >= RED_OVER, in PIL arithmetic.
	from PIL import ImageChops
	strong = r.point(lambda v: 255 if v >= RED_MIN else 0)
	overG = ImageChops.subtract(r, g).point(lambda v: 255 if v >= RED_OVER else 0)
	overB = ImageChops.subtract(r, b).point(lambda v: 255 if v >= RED_OVER else 0)
	return ImageChops.multiply(ImageChops.multiply(strong, overG), overB).convert("1")


def _redShare(mask, box):
	crop = mask.crop(box)
	n = crop.width * crop.height
	return crop.histogram()[255] / n if n else 0.0


def isRedText(image, mask, box):
	"""True when the text in box is written in red."""
	from PIL import ImageChops
	redCrop = mask.crop(box)
	if not redCrop.getbbox():
		return False
	crop = image.convert("RGB").crop(box)
	back = max(crop.getcolors(crop.width * crop.height) or [(0, (255, 255, 255))])[1]
	diff = ImageChops.difference(crop, Image.new("RGB", crop.size, back))
	r, g, b = diff.split()
	inkMask = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v >= 60 else 0).convert("1")
	ink = inkMask.histogram()[255]
	red = ImageChops.logical_and(inkMask, redCrop).histogram()[255]
	return ink >= 6 and red / ink >= TEXT_RED_SHARE


def _components(mask, cell=2):
	"""Boxes of connected red parts, on a grid of small cells so it stays fast."""
	w, h = mask.size
	gw, gh = max(1, w // cell), max(1, h // cell)
	small = mask.convert("L").resize((gw, gh), Image.BOX)
	data = small.tobytes()
	on = [v > 40 for v in data]
	seen = [False] * len(on)
	boxes = []
	for start, v in enumerate(on):
		if not v or seen[start]:
			continue
		stack, seen[start] = [start], True
		x0 = x1 = start % gw
		y0 = y1 = start // gw
		while stack:
			i = stack.pop()
			x, y = i % gw, i // gw
			x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
			for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
				nx, ny = x + dx, y + dy
				if 0 <= nx < gw and 0 <= ny < gh:
					j = ny * gw + nx
					if on[j] and not seen[j]:
						seen[j] = True
						stack.append(j)
		boxes.append((x0 * cell, y0 * cell, (x1 + 1) * cell, (y1 + 1) * cell))
	return boxes


def _edgeShare(mask, box, y):
	left, _top, right, _bottom = box
	row = [mask.getpixel((x, min(max(y, 0), mask.height - 1))) for x in range(left, right)]
	return sum(1 for v in row if v) / max(len(row), 1)


def redOutlines(mask):
	"""Boxes of rectangles drawn in red, like a field marked as wrong."""
	found = []
	bbox = mask.getbbox()
	if not bbox:
		return found
	ox, oy = bbox[0], bbox[1]
	for local in _components(mask.crop(bbox)):
		box = (local[0] + ox, local[1] + oy, local[2] + ox, local[3] + oy)
		left, top, right, bottom = box
		if right - left < OUTLINE_MIN_WIDTH or bottom - top < OUTLINE_MIN_HEIGHT:
			continue
		if _redShare(mask, box) > OUTLINE_MAX_FILL:
			continue
		topShare = max(_edgeShare(mask, box, y) for y in range(top, min(top + 3, bottom)))
		bottomShare = max(_edgeShare(mask, box, y) for y in range(max(bottom - 3, top), bottom))
		if topShare >= OUTLINE_EDGE_SHARE and bottomShare >= OUTLINE_EDGE_SHARE:
			found.append(box)
	return found


def _overlaps(a, b):
	return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def mark(image, items):
	"""Set item["red"] on overlay items that are outlined in red or written in red. Returns how many were marked,
	and the outline boxes that hold no item (an empty field marked in red)."""
	mask = redMask(image)
	if not mask.getbbox():
		return 0, []
	outlines = redOutlines(mask)
	count = 0
	used = set()
	for item in items:
		box = item["box"]
		red = False
		for i, outline in enumerate(outlines):
			if _overlaps(box, outline):
				red = True
				used.add(i)
		if not red and item.get("kind") == "text" and isRedText(image, mask, box):
			red = True
		if red:
			item["red"] = True
			count += 1
	return count, [o for i, o in enumerate(outlines) if i not in used]
