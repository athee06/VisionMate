# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Finds what the user asks for, like "the Save button", among the overlay's items for a window, and says roughly
where it is. No NVDA modules here, so it can be tested on its own."""
import difflib
import re

import addonHandler

addonHandler.initTranslation()

# How close a fuzzy match must be (0 to 1). OCR often gets a letter or two wrong.
FUZZY_MIN = 0.72
MAX_RESULTS = 5

# Kind words the user may add, and the overlay role each one means.
_KINDS = {
	"button": "button", "buttons": "button", "icon": "icon", "field": "field", "box": "field", "edit": "field",
	"textbox": "field", "link": "link", "heading": "heading", "title": "heading", "checkbox": "checkbox",
	"check": "checkbox", "radio": "radio", "option": "radio", "tab": None, "menu": None, "item": None,
}
_FILLER = re.compile(
	r"^\W*(where\s+is|where's|wheres|find|show\s+me|look\s+for|search\s+for|go\s+to|click|is\s+there)?\s*"
	r"(an?|the|my)?\s*",
	re.IGNORECASE,
)


def _words(text):
	return re.findall(r"\w+", (text or "").lower())


def cleanQuery(query):
	"""Split "where is the Save button?" into ("save", "button"): the name to look for, and the kind if given."""
	words = _words(_FILLER.sub("", query.strip(), count=1))
	kind = None
	while words and words[-1] in _KINDS:
		kind = kind or _KINDS[words[-1]]
		words.pop()
	if words and words[0] in _KINDS and len(words) > 1:  # "button Save"
		kind = kind or _KINDS[words[0]]
		words.pop(0)
	return " ".join(words), kind


def _role(item):
	return item.get("role") or ("icon" if item.get("kind") == "icon" else None)


def score(name, kind, item):
	"""How well an item matches, from 0 (not at all) to about 3. Exact words beat close spellings."""
	plain = " ".join(_words(item.get("plain") or item.get("name") or item.get("text")))
	if not plain or not name:
		return 0
	if plain == name:
		s = 3.0
	elif plain.startswith(name + " ") or (" " + name + " ") in (" " + plain + " "):
		s = 2.0 + len(name) / max(len(plain), 1) * 0.5
	elif all(w in plain.split() for w in name.split()):
		s = 1.8
	else:
		ratio = difflib.SequenceMatcher(None, name, plain).ratio()
		# A long line that holds a close spelling of the name, like "Sav as" in "File Sav as PDF".
		best = max([ratio] + [difflib.SequenceMatcher(None, name, " ".join(part)).ratio()
			for part in _windows(plain.split(), len(name.split()))])
		if best < FUZZY_MIN:
			return 0
		s = 1.0 + best * 0.5
	if kind is not None:
		role = _role(item)
		if role == kind or (kind == "button" and role == "icon"):
			s += 0.5
		elif role is not None:
			s -= 0.3
	return s


def _windows(words, size):
	size = max(size, 1)
	return [words[i:i + size] for i in range(0, max(len(words) - size + 1, 1))]


def find(query, items):
	"""The best matching items for the query, best first, as a list of items."""
	name, kind = cleanQuery(query)
	if not name and kind:
		ranked = [(1.0, i, it) for i, it in enumerate(items) if _role(it) == kind]
	else:
		ranked = [(score(name, kind, it), i, it) for i, it in enumerate(items)]
	ranked = [r for r in ranked if r[0] > 0]
	ranked.sort(key=lambda r: (-r[0], r[1]))
	if ranked and ranked[0][0] >= 3.0:
		# An exact match: only show others that are exact too, like two Save buttons.
		ranked = [r for r in ranked if r[0] >= 3.0]
	return [it for _s, _i, it in ranked[:MAX_RESULTS]]


def place(box, size):
	"""Roughly where a box is in a picture of this size, like "at the bottom right"."""
	left, top, right, bottom = box
	width, height = size
	x = (left + right) / 2 / max(width, 1)
	y = (top + bottom) / 2 / max(height, 1)
	row = 0 if y < 1 / 3 else (2 if y > 2 / 3 else 1)
	col = 0 if x < 1 / 3 else (2 if x > 2 / 3 else 1)
	names = [
		# Translators: Where something is in the window.
		[_("at the top left"), _("at the top"), _("at the top right")],
		# Translators: Where something is in the window.
		[_("on the left"), _("in the middle"), _("on the right")],
		# Translators: Where something is in the window.
		[_("at the bottom left"), _("at the bottom"), _("at the bottom right")],
	]
	return names[row][col]


# The item a sighted person's eye goes to first, in this order: what looks selected, a default button by its words,
# an empty edit field, then the biggest button.
_USEFUL_WORDS = [
	"continue", "next", "ok", "play", "start", "resume", "yes", "accept", "allow", "sign in", "log in", "login",
	"submit", "send", "verify", "save", "install", "finish", "done", "confirm", "agree", "apply", "open", "search",
	"close",
]


def mostUseful(items, selected=None):
	"""The index of the most useful item, and why, like (3, "default"), or (None, None) when there are no items.
	Reasons: "selected", "default", "field", "biggest", "first"."""
	if not items:
		return None, None
	if selected is not None and 0 <= selected < len(items):
		return selected, "selected"
	best = None
	for i, item in enumerate(items):
		plain = " ".join(_words(item.get("plain") or item.get("name") or ""))
		if not plain or _role(item) not in ("button", "icon", None, "link"):
			continue
		for rank, word in enumerate(_USEFUL_WORDS):
			if plain == word or (_role(item) == "button" and plain.startswith(word + " ")):
				if best is None or rank < best[0]:
					best = (rank, i)
				break
	if best is not None:
		return best[1], "default"
	for i, item in enumerate(items):
		if _role(item) == "field" and not (item.get("plain") or "").strip():
			return i, "field"
	buttons = [(  # biggest first
		(it["box"][2] - it["box"][0]) * (it["box"][3] - it["box"][1]), -i, i)
		for i, it in enumerate(items) if _role(it) == "button"]
	if buttons:
		return max(buttons)[2], "biggest"
	return 0, "first"


def appeared(before, after):
	"""Texts in after that were not in before, like a tooltip that came up: a list in after's order."""
	seen = {" ".join(_words(t)) for t in before}
	result = []
	for text in after:
		key = " ".join(_words(text))
		if not key or key in seen:
			continue
		if any(difflib.SequenceMatcher(None, key, old).ratio() >= 0.85 for old in seen if abs(len(old) - len(key)) < 6):
			continue
		seen.add(key)
		result.append(text)
	return result
