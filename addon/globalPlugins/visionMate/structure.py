# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Tables and scroll bars for the overlay: items that line up in rows and columns, and whether there is more to
see above or below. Works on the overlay's items ("box", "kind", "text") and the window picture only."""
import collections

# Items are on one row when their middles are this many line heights apart or less.
ROW_TOLERANCE = 0.6
# Cells are in one column when their left edges are this close (pixels, or line heights if that is more).
COLUMN_TOLERANCE = 10
COLUMN_TOLERANCE_LINES = 0.6
# A table has at least this many rows, and this many columns used by most rows.
TABLE_MIN_ROWS = 3
TABLE_MIN_COLUMNS = 2
TABLE_COLUMN_SHARE = 0.6
# Rows of one table are at most this many line heights apart.
TABLE_MAX_ROW_GAP = 3.0
# Most cells of a table are plain text; rows of labels with edit fields or buttons are a form, not a table.
TABLE_TEXT_SHARE = 0.75
# At most this share of a table's items may be out of line with its columns.
TABLE_LOOSE_SHARE = 0.1
# At most this share of cells may run on into the cell below, like wrapped sentences.
TABLE_WRAPPED_SHARE = 0.15

# A scroll bar: a strip this wide at the right edge, a track of one colour with a thumb of another.
SCROLL_STRIP = 28
SCROLL_MIN_WIDTH = 4
SCROLL_MAX_WIDTH = 22
SCROLL_MIN_HEIGHT = 150
SCROLL_MIN_CONTRAST = 14
SCROLL_TRACK_SHARE = 0.85
SCROLL_THUMB_MIN = 0.04
SCROLL_THUMB_MAX = 0.92
SCROLL_THUMB_ASPECT = 3
# Space at the ends of the track for arrow buttons, and how far the thumb must be from an end to mean "more".
SCROLL_END_ROOM = 0.03
SCROLL_ARROW = 12


def _mid(box):
	return (box[1] + box[3]) / 2


def _height(item):
	return item.get("lineHeight") or (item["box"][3] - item["box"][1])


def _rows(items):
	"""Items grouped into rows, top to bottom; each row left to right."""
	rows = []
	for item in sorted(items, key=lambda it: _mid(it["box"])):
		h = _height(item)
		if rows and abs(_mid(item["box"]) - rows[-1]["mid"]) <= ROW_TOLERANCE * max(h, rows[-1]["h"]):
			rows[-1]["items"].append(item)
		else:
			rows.append({"mid": _mid(item["box"]), "h": h, "items": [item]})
	for row in rows:
		row["items"].sort(key=lambda it: it["box"][0])
	return rows


def _columns(rows, h):
	"""Left edges shared by the rows, as column positions, left to right."""
	tolerance = max(COLUMN_TOLERANCE, COLUMN_TOLERANCE_LINES * h)
	lefts = sorted(it["box"][0] for row in rows for it in row["items"])
	clusters = []
	for x in lefts:
		if clusters and x - clusters[-1][-1] <= tolerance:
			clusters[-1].append(x)
		else:
			clusters.append([x])
	need = TABLE_COLUMN_SHARE * len(rows)
	return [sum(c) / len(c) for c in clusters if len(c) >= need], tolerance


def _column(x, columns, tolerance):
	best = min(range(len(columns)), key=lambda i: abs(columns[i] - x))
	return best if abs(columns[best] - x) <= tolerance else None


def findTables(items):
	"""Find tables among one area's items. Returns (items in reading order with tables row by row, tables).
	Each cell item gets item["cell"] = (table number, row, column), from 0; each table is
	{"rows": n, "columns": m, "first": the first cell}. Items that are not in a table keep their order."""
	if len(items) < TABLE_MIN_ROWS * TABLE_MIN_COLUMNS:
		return items, []
	rows = _rows(items)
	h = sorted(_height(it) for it in items)[len(items) // 2]
	# Runs of rows with several items each, close together.
	runs, run = [], []
	for row in rows:
		if len(row["items"]) >= TABLE_MIN_COLUMNS and (not run or row["mid"] - run[-1]["mid"] <= TABLE_MAX_ROW_GAP * h):
			run.append(row)
			continue
		if len(run) >= TABLE_MIN_ROWS:
			runs.append(run)
		run = [row] if len(row["items"]) >= TABLE_MIN_COLUMNS else []
	if len(run) >= TABLE_MIN_ROWS:
		runs.append(run)
	tables = []
	placed = {}
	for run in runs:
		columns, tolerance = _columns(run, h)
		if len(columns) < TABLE_MIN_COLUMNS:
			continue
		# Nearly every item in the run must sit in a column, or this is not a table but lines of loose items.
		# An icon or a word OCR misread can be a little out of line; it goes in the nearest column.
		cells = [(r, it, _column(it["box"][0], columns, tolerance)) for r, row in enumerate(run) for it in row["items"]]
		loose = [cell for cell in cells if cell[2] is None]
		if len(loose) > TABLE_LOOSE_SHARE * len(cells):
			continue
		cells = [(r, it, c if c is not None else _column(it["box"][0], columns, 3 * tolerance)) for r, it, c in cells]
		if any(c is None for _r, _it, c in cells):
			continue
		plain = sum(1 for _r, it, _c in cells if it.get("kind") == "text" and it.get("role") in (None, "link"))
		if plain < TABLE_TEXT_SHARE * len(cells):
			continue
		if _wrapped(cells) > TABLE_WRAPPED_SHARE * len(cells):
			continue  # paragraphs side by side, like cards in a grid, not a table
		number = len(tables)
		for r, it, c in cells:
			it["cell"] = (number, r, c)
		ordered = [it for _r, it, _c in cells]
		tables.append({"rows": len(run), "columns": len(columns), "first": ordered[0]})
		for it in ordered:
			placed[id(it)] = (number, ordered)
	if not tables:
		return items, []
	# The table's cells come together, row by row, where its first cell was in the reading order.
	result, done = [], set()
	for it in items:
		key = placed.get(id(it))
		if key is None:
			result.append(it)
		elif key[0] not in done:
			done.add(key[0])
			result.extend(key[1])
	return result, tables


def _wrapped(cells):
	"""How many cells go on in the cell below, like a sentence wrapped onto the next line: the text below starts
	with a small letter."""
	byPlace = {(r, c): it for r, it, c in cells}
	count = 0
	for (r, c), it in byPlace.items():
		below = byPlace.get((r + 1, c))
		text = (below or {}).get("plain") or (below or {}).get("text") or ""
		if below is not None and text[:1].islower() and not (it.get("plain") or it.get("text") or "").rstrip().endswith((".", ":")):
			count += 1
	return count


def moveInTable(items, item, rowStep, columnStep):
	"""The cell next to item in its table: rowStep and columnStep are -1, 0 or 1. None at the edge."""
	cell = item.get("cell") if item else None
	if cell is None:
		return None
	number, row, column = cell
	target = (number, row + rowStep, column + columnStep)
	for other in items:
		if other.get("cell") == target:
			return other
	# An empty cell: keep going the same way.
	if rowStep or columnStep:
		rows = [o["cell"][1] for o in items if o.get("cell") and o["cell"][0] == number]
		columns = [o["cell"][2] for o in items if o.get("cell") and o["cell"][0] == number]
		r, c = row + rowStep, column + columnStep
		while min(rows) <= r <= max(rows) and min(columns) <= c <= max(columns):
			for other in items:
				if other.get("cell") == (number, r, c):
					return other
			r, c = r + rowStep, c + columnStep
	return None


def scrollState(image, box=None):
	"""Look for a vertical scroll bar at the right edge of box (or the whole picture). Returns (more above,
	more below), or None if there is no scroll bar."""
	gray = image.convert("L")
	left, top, right, bottom = box or (0, 0) + image.size
	height = bottom - top
	if height < SCROLL_MIN_HEIGHT or right - left < 3 * SCROLL_STRIP:
		return None

	def columnAt(x):
		return list(gray.crop((x, top, x + 1, bottom)).getdata())

	xs = list(range(right - 1, max(left, right - SCROLL_STRIP) - 1, -1))
	runs = [_thumb(columnAt(x)) for x in xs]

	def similar(a, b):
		return a is not None and b is not None and abs(a[0] - b[0]) <= 3 and abs(a[1] - b[1]) <= 3

	# The thumb must be the same in several columns side by side, as wide as a scroll bar, and stop there: a band
	# of colour across a whole panel, like a heading, or a button, goes on to the left.
	room = SCROLL_END_ROOM * height + 2
	best = None
	i = 0
	while i < len(runs):
		if runs[i] is None:
			i += 1
			continue
		j = i
		while j + 1 < len(runs) and similar(runs[j + 1], runs[i]):
			j += 1
		width = j - i + 1
		beyond = xs[j] - 2
		thumb = _realThumb(runs[i], columnAt(beyond) if beyond >= left else None, height, room)
		stops = beyond < left or not _continues(columnAt, thumb, range(beyond, max(left, beyond - 6) - 1, -2))
		# A thumb is long and thin; a square, like a Send button, is not one.
		long = thumb[1] - thumb[0] >= SCROLL_THUMB_ASPECT * width
		if SCROLL_MIN_WIDTH <= width <= SCROLL_MAX_WIDTH and stops and long and (best is None or width > best[0]):
			best = (width, thumb)
		i = j + 1
	if best is None:
		return None
	start, end, _value, trackTop, trackBottom = best[1]
	# Without arrow buttons found, leave room for them at each end of the track.
	endRoom = room + (0 if trackTop or trackBottom < height else SCROLL_ARROW)
	start, end, height = start - trackTop, end - trackTop, trackBottom - trackTop
	return start > endRoom, end < height - endRoom


def _realThumb(run, besideColumn, height, room):
	"""(start, end, colour, track top, track bottom) of the thumb. A long thumb may have been taken for the track:
	the track is the colour closer to the window's background just left of the bar."""
	start, end, thumbValue, trackValue, trackTop, trackBottom = run
	if besideColumn is not None:
		endRoom = room + SCROLL_ARROW
		background = sorted(besideColumn)[len(besideColumn) // 2]
		atTop, atBottom = start <= trackTop + endRoom, end >= trackBottom - endRoom
		if abs(trackValue - background) > abs(thumbValue - background) and atTop != atBottom:
			start, end = (end, trackBottom) if atTop else (trackTop, start)
			return start, end, trackValue, trackTop, trackBottom
	return start, end, thumbValue, trackTop, trackBottom


def _continues(columnAt, run, xs):
	"""True if the thumb's colour carries on in any of these columns, so it is a band or a button, not a thumb.
	The middle of the colour is used, so text on a button does not hide it."""
	start, end, thumbValue = run[0], run[1], run[2]
	cut = (end - start) // 5
	for x in xs:
		values = sorted(columnAt(x)[start + cut:end - cut])
		if values and abs(values[len(values) // 2] - thumbValue) < SCROLL_MIN_CONTRAST:
			return True
	return False


def _thumb(column):
	"""(start, end, thumb colour, track colour) of the one stretch of a different colour in a column that is
	otherwise one colour, or None."""
	n = len(column)
	counts = collections.Counter(v // 4 for v in column)
	track = counts.most_common(1)[0][0]
	inTrack = [abs(v // 4 - track) <= 1 for v in column]
	# The thumb: the longest stretch clearly different from the track. Short ones may be arrow buttons.
	stretches, start = [], None
	for i, v in enumerate(column + [track * 4]):
		far = abs(v - track * 4) >= SCROLL_MIN_CONTRAST
		if far and start is None:
			start = i
		elif not far and start is not None:
			stretches.append((start, i))
			start = None
	if not stretches:
		return None
	best = max(stretches, key=lambda r: r[1] - r[0])
	length = best[1] - best[0]
	if not (SCROLL_THUMB_MIN * n <= length <= SCROLL_THUMB_MAX * n):
		return None
	# Apart from the thumb (and a little edge on it), the column is track.
	outside = sum(1 for i, t in enumerate(inTrack) if not t and not (best[0] - 2 <= i < best[1] + 2))
	if outside > (1 - SCROLL_TRACK_SHARE) * (n - length):
		return None
	# A thumb is one colour, apart from soft edges; text or a picture is not.
	cut = length // 10
	thumbValues = sorted(column[best[0] + cut:best[1] - cut])
	if not thumbValues or thumbValues[-1] - thumbValues[0] > SCROLL_MIN_CONTRAST:
		return None
	# The track ends at the arrow buttons, if there are any: the nearest short stretches above and below.
	above = [r for r in stretches if r[1] <= best[0] and r[1] - r[0] <= SCROLL_ARROW]
	below = [r for r in stretches if r[0] >= best[1] and r[1] - r[0] <= SCROLL_ARROW]
	trackTop = above[-1][1] if above else 0
	trackBottom = below[0][0] if below else n
	return best[0], best[1], thumbValues[len(thumbValues) // 2], track * 4 + 2, trackTop, trackBottom
