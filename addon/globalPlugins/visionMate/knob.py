# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Knobs, dials and sliders that are only drawn: the number shown next to one, read from OCR, and the steps that
move it to the number the user asked for. No NVDA modules here, so it can be tested on its own."""
import re

_NUMBER = re.compile(r"(?<![\w.])([-+−]?\d+(?:[.,]\d+)?)\s*(%|percent|db|hz|khz|ms|s|°)?(?![\w])", re.IGNORECASE)
# How far around the control to look for its number, in control sizes.
NEAR = 1.5
# The most steps tried for one change, and how many steps without a change mean this way does not work.
MAX_STEPS = 80
STUCK_STEPS = 3
# Ways to move a control, tried in this order.
METHODS = ("wheel", "dragUp", "dragRight", "dragCircle")


def parse(text):
	"""(number, unit) from text like "35%", "-6.0 dB" or "Mix 120", or None. The unit is lower case or ""."""
	m = _NUMBER.search((text or "").replace("−", "-"))
	if not m:
		return None
	value = float(m.group(1).replace(",", ".").replace("−", "-"))
	unit = (m.group(2) or "").lower()
	if unit == "percent":
		unit = "%"
	return value, unit


def numberNear(box, items):
	"""The number written closest to a control, from text items with "box" and "text": (value, unit, item), or None."""
	left, top, right, bottom = box
	w, h = max(right - left, 1), max(bottom - top, 1)
	cx, cy = (left + right) / 2, (top + bottom) / 2
	best = None
	for item in items:
		parsed = parse(item.get("plain") or item.get("text"))
		if parsed is None:
			continue
		il, it, ir, ib = item["box"]
		ix, iy = (il + ir) / 2, (it + ib) / 2
		if abs(ix - cx) > w * (0.5 + NEAR) or abs(iy - cy) > h * (0.5 + NEAR):
			continue
		d = ((ix - cx) / w) ** 2 + ((iy - cy) / h) ** 2
		if best is None or d < best[0]:
			best = (d, parsed, item)
	if best is None:
		return None
	return best[1][0], best[1][1], best[2]


class Stepper:
	"""Decides each step toward a target number. Call next(value) with the number read after each step; it returns
	+1 or -1 for the next step, "done", "stuck" (this way moves nothing; try the next) or "limit"."""

	def __init__(self, start, target):
		self.start = start
		self.target = target
		self.values = [start]
		self.steps = 0
		self._unchanged = 0
		self._direction = 1 if target > start else -1
		# Some controls go down when moved "up": learned from the first change.
		self._flip = 1

	@property
	def direction(self):
		return self._direction * self._flip

	def first(self):
		if self.start == self.target:
			return "done"
		return self.direction

	def next(self, value):
		self.steps += 1
		last = self.values[-1]
		self.values.append(value)
		if value is None or value == last:
			self._unchanged += 1
			if self._unchanged >= STUCK_STEPS:
				return "stuck"
			return self.direction if self.steps < MAX_STEPS else "limit"
		self._unchanged = 0
		moved = 1 if value > last else -1
		wanted = 1 if self.target > last else -1
		if self.steps == 1 and moved != wanted and self._flip == 1 and abs(value - self.start) > 0:
			# The control moved the other way: reverse what "up" means for it.
			self._flip = -1
		if value == self.target:
			return "done"
		if (last - self.target) * (value - self.target) < 0:
			# Went past the target: stop on whichever side is closer, one step back if needed.
			if abs(value - self.target) > abs(last - self.target):
				self._direction = -self._direction
				return "back"
			return "done"
		if self.steps >= MAX_STEPS:
			return "limit"
		self._direction = 1 if self.target > value else -1
		return self.direction
