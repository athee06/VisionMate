# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Checks that ask whether you are a person. They shut blind people out when the audio way is missing or broken.
VisionMate only makes a check readable and workable: it names the kind of check and the ways through it that need
no sight, and numbers the squares of a picture puzzle. The user answers it. No NVDA modules here, so it can be
tested on its own."""
import re

import addonHandler
from PIL import Image, ImageChops

addonHandler.initTranslation()

_KINDS = [
	("grid", re.compile(r"select all (images|squares)|click (on )?(all|each) (image|square)|"
		r"(images|squares) (with|containing)|if there are none,? click skip", re.I)),
	("hold", re.compile(r"press (and|&) hold|hold (the )?button", re.I)),
	("slider", re.compile(r"slide (to|the)|drag the (slider|piece)|move the slider", re.I)),
	("text", re.compile(r"type the (characters|text|letters|word)|enter the (characters|text) (you see|shown)", re.I)),
	("audio", re.compile(r"press play (and|to) (listen|hear)|enter what you hear|audio challenge", re.I)),
	("box", re.compile(r"i'?m not a robot|verify (that )?you are (a )?human|i am human|"
		r"confirm you are (a )?human|are you a robot", re.I)),
]
_AUDIO_WORDS = re.compile(r"\b(audio|listen|headphones?|sound)\b", re.I)


def kind(text):
	"""The kind of check in a window's text: "grid", "hold", "slider", "text", "audio", "box", or None."""
	for name, pattern in _KINDS:
		if pattern.search(text or ""):
			return name
	return None


def advice(kindName, text=""):
	"""One or two sentences: what kind of check this is, and the ways through it that need no sight."""
	audio = bool(_AUDIO_WORDS.search(text or ""))
	messages = {
		# Translators: Said about a check that asks whether you are a person.
		"box": _("Human check: a box to tick. Use Click on the box; often that is all it asks."),
		"grid": _("Human check: a picture puzzle. Each square is numbered and described; press Space on the squares "
			"that match, then the Verify button."),
		"hold": _("Human check: press and hold. Use the overlay's actions, Hold the button, on it."),
		"slider": _("Human check: a slider to drag. Use the overlay's actions, Drag, on the slider."),
		"text": _("Human check: characters to type from a picture. The characters are read by OCR and may be wrong."),
		"audio": _("Human check: an audio challenge. Play it and type what you hear."),
	}
	message = messages.get(kindName, "")
	if audio and kindName not in ("audio", None):
		# Translators: Added when a check also offers a way that needs no sight.
		message += " " + _("It also has an audio way, which needs no sight: look for the audio or headphones button.")
	return message


# Picture squares: grainy cells (photos) separated by flat gaps.
_CELL = 3
_FLAT = 10
TILE_MIN_SIDE = 50
TILE_SIZE_MATCH = 0.18
GRID_SIZES = (3, 4)


def _grainy(image):
	rgb = image.convert("RGB")
	w, h = rgb.size
	gw, gh = w // _CELL, h // _CELL
	rgb = rgb.crop((0, 0, gw * _CELL, gh * _CELL))
	means = rgb.reduce(_CELL)
	spread = ImageChops.difference(rgb, means.resize(rgb.size, Image.NEAREST)).convert("L").reduce(_CELL)
	return [v > _FLAT for v in spread.tobytes()], gw, gh


def _boxes(on, gw, gh):
	seen = [False] * len(on)
	boxes = []
	for start, v in enumerate(on):
		if not v or seen[start]:
			continue
		stack, seen[start] = [start], True
		x0 = x1 = start % gw
		y0 = y1 = start // gw
		count = 0
		while stack:
			i = stack.pop()
			count += 1
			x, y = i % gw, i // gw
			x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
			for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
				nx, ny = x + dx, y + dy
				if 0 <= nx < gw and 0 <= ny < gh:
					j = ny * gw + nx
					if on[j] and not seen[j]:
						seen[j] = True
						stack.append(j)
		boxes.append(((x0 * _CELL, y0 * _CELL, (x1 + 1) * _CELL, (y1 + 1) * _CELL), count * _CELL * _CELL))
	return boxes


def _square(box):
	w, h = box[2] - box[0], box[3] - box[1]
	return w >= TILE_MIN_SIDE and h >= TILE_MIN_SIDE and 0.7 <= w / h <= 1.43


def _asGrid(tiles):
	"""tiles sorted into rows and columns when they form a full 3 by 3 or 4 by 4 grid, else None."""
	for n in sorted(GRID_SIZES, reverse=True):
		if len(tiles) < n * n:
			continue
		tiles = sorted(tiles, key=lambda b: (b[1], b[0]))
		rows, row = [], []
		for b in tiles:
			if row and abs(b[1] - row[0][1]) > (row[0][3] - row[0][1]) / 2:
				rows.append(row)
				row = []
			row.append(b)
		rows.append(row)
		rows = [sorted(r, key=lambda b: b[0]) for r in rows if len(r) == n]
		if len(rows) >= n:
			return [b for r in rows[:n] for b in r]
	return None


def _splitBySeparators(image, box):
	"""A grid drawn as one picture with thin light lines between the squares: the squares, or None."""
	crop = image.convert("L").crop(box)
	w, h = crop.size
	data = crop.load()

	def light(values):
		return sum(1 for v in values if v >= 235) / max(len(values), 1) >= 0.9

	cols = [x for x in range(2, w - 2) if light([data[x, y] for y in range(0, h, 2)])]
	rows = [y for y in range(2, h - 2) if light([data[x, y] for x in range(0, w, 2)])]

	def cuts(lines, size):
		groups = []
		for v in lines:
			if groups and v - groups[-1][-1] <= 2:
				groups[-1].append(v)
			else:
				groups.append([v])
		return [0] + [sum(g) // len(g) for g in groups] + [size]

	xs, ys = cuts(cols, w), cuts(rows, h)
	for n in GRID_SIZES:
		if len(xs) == n + 1 and len(ys) == n + 1:
			widths = [xs[i + 1] - xs[i] for i in range(n)]
			if max(widths) - min(widths) <= TILE_SIZE_MATCH * max(widths):
				return [(box[0] + xs[c], box[1] + ys[r], box[0] + xs[c + 1], box[1] + ys[r + 1])
					for r in range(n) for c in range(n)]
	return None


def findGrid(image):
	"""The squares of a picture puzzle, numbered left to right and top to bottom, as boxes in image pixels, or None."""
	on, gw, gh = _grainy(image)
	if gw < 4 or gh < 4:
		return None
	found = [b for b, _n in _boxes(on, gw, gh) if _square(b)]
	if not found:
		return None
	# Squares of the same size are one grid.
	found.sort(key=lambda b: -(b[2] - b[0]))
	for first in found:
		side = first[2] - first[0]
		same = [b for b in found if abs((b[2] - b[0]) - side) <= TILE_SIZE_MATCH * side]
		grid = _asGrid(same)
		if grid:
			return grid
	# One big square picture may be split by thin lines.
	for box in found[:3]:
		grid = _splitBySeparators(image, box)
		if grid:
			return grid
	return None
