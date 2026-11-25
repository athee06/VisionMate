# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Memories: things the user asked VisionMate to remember, like "I am colour blind, always name colours", kept as
the user's own words in a file on this computer and given with every description and answer.
And the user's own instructions: every instruction given to the vision data can be read, rewritten and restored.
No NVDA modules here, so it can be tested on its own."""
import json
import os
import re
import threading

MAX_MEMORIES = 20
MAX_CHARS = 200
# The most memory text added to one prompt.
MAX_PROMPT_CHARS = 700

# "remember that ..." or "remember I ...": not "remember what the sign said?", which is a question about the picture.
_REMEMBER = re.compile(r"^\s*(please\s+)?(remember|note|keep in mind)(\s+that\s+|\s*:\s*|\s+(?=(i|i'm|my|me|we|our)\b))"
	r"(?P<fact>.+?)\s*$", re.I)
_FORGET_ALL = re.compile(r"^\s*(please\s+)?forget\s+(everything|all( of it| memories)?)\s*[.!]?\s*$", re.I)
_FORGET = re.compile(r"^\s*(please\s+)?forget\s+(that\s+|about\s+)?(?P<what>.+?)\s*[.!]?\s*$", re.I)
_RECALL = re.compile(r"^\s*what\s+(do\s+you|did\s+i\s+ask\s+you\s+to)\s+remember\b", re.I)


def _atomicWrite(path, data):
	tmp = path + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent=1)
	os.replace(tmp, path)


class Memories:
	def __init__(self, path):
		self.path = path
		self._lock = threading.Lock()
		try:
			with open(path, encoding="utf-8") as f:
				self.items = [str(m)[:MAX_CHARS] for m in json.load(f)][:MAX_MEMORIES]
		except (OSError, ValueError, TypeError):
			self.items = []

	def save(self):
		with self._lock:
			_atomicWrite(self.path, self.items)

	def add(self, fact):
		fact = " ".join(fact.split()).strip(" .")[:MAX_CHARS]
		if not fact:
			return None
		fact = fact[:1].upper() + fact[1:] + "."
		key = fact.lower()
		self.items = [m for m in self.items if m.lower() != key]
		self.items.append(fact)
		self.items = self.items[-MAX_MEMORIES:]
		self.save()
		return fact

	def remove(self, index):
		if 0 <= index < len(self.items):
			del self.items[index]
			self.save()

	def forget(self, words):
		"""Remove the memories that hold all these words. Returns what was removed."""
		wanted = set(re.findall(r"\w+", words.lower())) - {"the", "a", "an", "my", "i", "that"}
		removed = [m for m in self.items if wanted and wanted <= set(re.findall(r"\w+", m.lower()))]
		if removed:
			self.items = [m for m in self.items if m not in removed]
			self.save()
		return removed

	def clear(self):
		self.items = []
		self.save()

	def promptPart(self):
		if not self.items:
			return ""
		text, used = "", 0
		for m in reversed(self.items):  # the newest first, if they do not all fit
			if used + len(m) > MAX_PROMPT_CHARS:
				break
			text = m + " " + text
			used += len(m) + 1
		return "What the user asked you to remember about them: " + text.strip() + "\n"


def command(text):
	"""What a typed question asks of the memories: ("remember", fact), ("forget", words), ("forgetAll", None),
	("recall", None), or None for an ordinary question."""
	if _RECALL.match(text):
		return "recall", None
	if _FORGET_ALL.match(text):
		return "forgetAll", None
	m = _REMEMBER.match(text)
	if m and len(m.group("fact").split()) >= 2:
		return "remember", m.group("fact")
	m = _FORGET.match(text)
	if m:
		return "forget", m.group("what")
	return None


class Instructions:
	"""Overrides of the built-in instructions, by name, and the user's own instruction for every answer."""
	OWN = "own"

	def __init__(self, path):
		self.path = path
		try:
			with open(path, encoding="utf-8") as f:
				data = json.load(f)
			self.overrides = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
		except (OSError, ValueError):
			self.overrides = {}

	def get(self, name, default):
		value = self.overrides.get(name, "").strip()
		return value or default

	def own(self):
		value = self.overrides.get(self.OWN, "").strip()
		return (" The user's own instruction: " + value) if value else ""

	def set(self, name, value, default=None):
		value = (value or "").strip()
		if not value or value == (default or "").strip():
			self.overrides.pop(name, None)
		else:
			self.overrides[name] = value
		_atomicWrite(self.path, self.overrides)

	def restore(self, name=None):
		if name is None:
			self.overrides = {}
		else:
			self.overrides.pop(name, None)
		_atomicWrite(self.path, self.overrides)
