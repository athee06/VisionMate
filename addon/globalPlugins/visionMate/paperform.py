# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Scanned forms that are only a picture: the blank line or box that belongs to a printed label, like the line after
"Full Name", found in the pixels without AI. To its right first, then under it, then above it.
No NVDA modules here, so it can be tested on its own."""

# A pixel this much darker than the paper is ink.
INK_DIFFERENCE = 80
# A line to write on is at least this long; a dotted line may have gaps this wide.
LINE_MIN_LENGTH = 50
LINE_MAX_GAP = 5
# Dots and dashes cover at least this share of a dotted line.
LINE_MIN_COVER = 0.35
# How far from the label to look, in label heights.
RIGHT_REACH = 40
BELOW_REACH = 3.0
# Where to click, above the line, in label heights.
CLICK_ABOVE = 0.5


def _grey(image):
	return image.convert("L")


def _paper(grey):
	hist = grey.histogram()
	return max(range(128, 256), key=lambda v: hist[v])


def _runs(grey, y, x0, x1, paper, blocked):
	"""Stretches of ink along row y from x0 to x1, allowing small gaps: [(start, end, inked pixels)]."""
	runs = []
	start = last = None
	inked = 0
	w, h = grey.size
	if not 0 <= y < h:
		return runs
	for x in range(max(0, x0), min(w, x1)):
		ink = paper - grey.getpixel((x, y)) >= INK_DIFFERENCE and not blocked(x, y)
		if ink:
			if start is None or x - last > LINE_MAX_GAP:
				if start is not None:
					runs.append((start, last + 1, inked))
				start, inked = x, 0
			last = x
			inked += 1
	if start is not None:
		runs.append((start, last + 1, inked))
	return runs


def _lineIn(grey, x0, x1, y0, y1, paper, blocked):
	"""The first writing line found from top to bottom in a band: (left, y, right), or None."""
	for y in range(max(0, y0), min(grey.height, y1)):
		for start, end, inked in _runs(grey, y, x0, x1, paper, blocked):
			if end - start >= LINE_MIN_LENGTH and inked / (end - start) >= LINE_MIN_COVER:
				return (start, y, end)
	return None


def findBlank(image, label, textBoxes=()):
	"""Where to write for the printed label at box label (left, top, right, bottom): a point (x, y) in image pixels
	just above the line or inside the box that belongs to it, and where it is ("right", "below" or "above"), or None."""
	grey = _grey(image)
	paper = _paper(grey)
	left, top, right, bottom = label
	h = max(bottom - top, 8)

	def blocked(x, y):
		# Ink inside other text is letters, not a line.
		return any(b[0] <= x < b[2] and b[1] <= y < b[3] for b in textBoxes if b != tuple(label))

	def point(found):
		x0, y, x1 = found
		x = x0 + min(20, (x1 - x0) // 4)
		# A box: another line of about the same length below the first is its bottom edge; write between them.
		below = _lineIn(grey, x0, x1, y + 6, y + int(BELOW_REACH * h), paper, blocked)
		if below and abs((below[2] - below[0]) - (x1 - x0)) <= 0.2 * (x1 - x0) and abs(below[0] - x0) <= 6:
			return (x, (y + below[1]) // 2)
		return (x, max(0, y - int(CLICK_ABOVE * h)))

	wide = left + max(int(RIGHT_REACH * h), right - left + 4 * h)
	# To the right, on the label's own row: the line is near the label's bottom, or a box starts at its top.
	found = _lineIn(grey, right + 2, right + int(RIGHT_REACH * h), top - h, bottom + h // 2, paper, blocked)
	if found:
		x0, y, x1 = found
		over = [r for r in _runs(grey, y, left, right, paper, blocked) if r[1] - r[0] >= (right - left) * 0.8]
		if y < top and over:
			# A line above the label that also runs over it, like a signature line: it is the label's line above.
			return point((min(over[0][0], x0), y, x1)), "above"
		return point(found), "right"
	# Under the label, about as wide as the label or wider.
	found = _lineIn(grey, left - h, wide, bottom + 2, bottom + int(BELOW_REACH * h), paper, blocked)
	if found:
		return point(found), "below"
	# Above the label, like a signature line with its label printed under it.
	found = _lineIn(grey, left - h, wide, max(0, top - int(BELOW_REACH * h)), top - 2, paper, blocked)
	if found:
		return point(found), "above"
	return None
