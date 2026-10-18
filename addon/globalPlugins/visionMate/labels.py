# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - remembers names for icons and buttons, per app.
# Names the user gives always win over names the vision data guessed.

import hashlib
import json
import os
import threading

from logHandler import log

# Guessed names kept per app. Older ones are dropped first.
MAX_GUESSES_PER_APP = 2000


def imageKey(image):
	"""Identifies a picture of an icon by its pixels."""
	return hashlib.sha1(image.convert("RGB").tobytes() + repr(image.size).encode()).hexdigest()[:20]


class LabelStore:
	"""Saved in a small file, so names survive restarts and add-on updates."""

	def __init__(self, path):
		self._path = path
		self._lock = threading.Lock()
		self._data = {}
		self._dirty = False
		try:
			with open(path, encoding="utf-8") as f:
				data = json.load(f)
			if isinstance(data, dict):
				self._data = data
		except FileNotFoundError:
			pass
		except (OSError, ValueError):
			log.warning("VisionMate: could not read saved names", exc_info=True)

	def _app(self, app):
		return self._data.setdefault(app or "?", {"user": {}, "guess": {}})

	def get(self, app, key):
		"""Returns (name, byUser), or (None, False)."""
		with self._lock:
			entry = self._data.get(app or "?")
			if not entry:
				return None, False
			if key in entry["user"]:
				return entry["user"][key], True
			return entry["guess"].get(key), False

	def setUser(self, app, key, name):
		with self._lock:
			entry = self._app(app)
			if name:
				entry["user"][key] = name
			else:
				entry["user"].pop(key, None)
			self._dirty = True
		self.save()

	def setGuess(self, app, key, name):
		with self._lock:
			guesses = self._app(app)["guess"]
			guesses.pop(key, None)
			guesses[key] = name
			while len(guesses) > MAX_GUESSES_PER_APP:
				guesses.pop(next(iter(guesses)))
			self._dirty = True

	def save(self):
		with self._lock:
			if not self._dirty:
				return
			data = json.dumps(self._data, ensure_ascii=False)
			self._dirty = False
		tmp = self._path + ".tmp"
		try:
			with open(tmp, "w", encoding="utf-8") as f:
				f.write(data)
			os.replace(tmp, self._path)
		except OSError:
			log.warning("VisionMate: could not save names", exc_info=True)
