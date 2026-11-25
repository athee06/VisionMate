# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Questions about a picture, split into their parts, each with the one rule of its kind right after it, where a
small model heeds it most. "What is in this photo, and is there any text in it?" is two questions.
No NVDA modules here, so it can be tested on its own."""
import re

# Words that start a new question after "and", a comma or "also".
_STARTERS = (
	r"what|whats|what's|which|who|whose|where|wheres|where's|when|why|how|is|are|was|were|does|do|did|can|could|"
	r"read|describe|tell|count|name|list|say|show|explain"
)
_SPLIT = re.compile(
	r"\?\s*|;\s*|,?\s+(?:and|also|plus)\s+(?:also\s+)?(?=(?:" + _STARTERS + r")\b)|,\s+(?=(?:" + _STARTERS + r")\b)",
	re.IGNORECASE,
)
MAX_PARTS = 4

# Kinds of question, tested in this order, and the rule for each.
_KINDS = [
	("text", re.compile(r"\b(text|written|writing|says?|read|words?|letters?|caption|label|sign|error code|number on|"
		r"scribbled|spell)\b", re.I)),
	("count", re.compile(r"\b(how many|count|number of|tally)\b", re.I)),
	("colour", re.compile(r"\b(colou?rs?|shade|hue)\b", re.I)),
	("chart", re.compile(r"\b(chart|graph|plot|diagram|axis|axes|trend)\b", re.I)),
	("people", re.compile(r"\b(people|person|persons|man|woman|men|women|child|children|kids?|boy|girl|face|"
		r"someone|anybody|anyone|wearing)\b", re.I)),
	("where", re.compile(r"^\s*(where|which side|what side)\b", re.I)),
	("yesno", re.compile(r"^\s*(is|are|was|were|does|do|did|can|could|has|have)\b", re.I)),
]
RULES = {
	"text": " Read the text exactly as it is written, word for word. If it is too small or blurry, say so.",
	"count": " Give the number first, then what was counted.",
	"colour": " Name the colours in plain words, like navy blue or light grey.",
	"chart": " Say the chart's title, its axes and the overall trend, then the most important values.",
	"people": " Describe the people without saying who they are, and do not guess ages or feelings as facts.",
	"where": " Say where it is in plain words, like at the top left or below the title.",
	"yesno": " Answer yes or no first, then where or what you see.",
	"general": "",
}


def kind(question):
	for name, pattern in _KINDS:
		if pattern.search(question):
			return name
	return "general"


def split(question):
	"""The separate questions in what the user asked, in order, each ending with a question mark."""
	parts = [p.strip(" ,.") for p in _SPLIT.split(question or "")]
	parts = [p for p in parts if len(p.split()) >= 2 or (p and len(parts) == 1)]
	if not parts:
		return [question.strip()] if question and question.strip() else []
	if len(parts) > MAX_PARTS:
		parts = parts[:MAX_PARTS - 1] + [" ".join(parts[MAX_PARTS - 1:])]
	return [p[:1].upper() + p[1:] + ("" if p.endswith(("?", "!")) else "?") for p in parts]


def withRule(question):
	"""The question with the rule for its kind after it."""
	return question + RULES[kind(question)]
