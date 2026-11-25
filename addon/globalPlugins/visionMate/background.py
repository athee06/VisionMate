# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Background work: naming icons for the overlay and describing images ahead of the reader."""
import addonHandler

from .common import *  # noqa: F401,F403

addonHandler.initTranslation()


class BackgroundMixin:
	def _queueBackground(self, job, key):
		if key in self._backgroundKeys or not self._dataReady():
			return
		self._backgroundKeys.add(key)
		self._background.append((job, key))
		self._backgroundWake.set()

	def _backgroundLoop(self):
		while not self._stopped.is_set():
			self._backgroundWake.wait()
			self._backgroundWake.clear()
			while self._background and not self._stopped.is_set():
				# Give way to anything the user asked for, and to what they may ask next.
				while self._userActive() and not self._stopped.is_set():
					time.sleep(0.2)
				try:
					job, key = self._background.popleft()
				except IndexError:
					break  # the overlay closed and dropped its work meanwhile
				self._backgroundCancel = cancel = threading.Event()
				self._backgroundKey = key
				try:
					with self._inUse():
						done = job(cancel)
				except Exception:
					log.debugWarning("VisionMate: background work failed", exc_info=True)
					done = True
				self._backgroundKey = None
				if done or self._stopped.is_set() or key not in self._backgroundKeys:
					self._backgroundKeys.discard(key)
				else:
					self._background.appendleft((job, key))  # interrupted: try again later
			self.labels.save()

	def _userActive(self):
		return self._busy or time.monotonic() - self._lastRequest < BACKGROUND_IDLE_SECONDS

	def _backgroundDescribe(self, image, prompt, maxTokens, size, cancel):
		self._ensureEngine()
		return self._engine.describe(prepareImage(image, size), prompt, maxTokens, cancel=cancel)

	def nameIcons(self, app, icons, onNamed, tiles=False):
		"""Name icons for the overlay in the background, a few at a time from one picture.
		onNamed() is called after new names arrive. tiles: the squares of a picture puzzle, which are named by what
		they show."""
		icons = [(k, crop) for k, crop in icons if (app, k) not in self._iconsQueued]
		for start in range(0, len(icons), BACKGROUND_SHEET_ICONS):
			batch = icons[start:start + BACKGROUND_SHEET_ICONS]
			self._iconsQueued.update((app, k) for k, _crop in batch)
			self._queueBackground(self._iconJob(app, batch, onNamed, tiles), ("icon", app, tuple(k for k, _crop in batch)))

	def _iconJob(self, app, batch, onNamed, tiles=False):
		def run(cancel):
			try:
				done = nameBatch(cancel)
			except Exception:
				done = True
				raise
			finally:
				if done is not False:
					self._iconsQueued.difference_update((app, k) for k, _crop in batch)
			return done

		def nameBatch(cancel):
			context = _contextPrompt([("app", app)])
			single, sheet = (TILE_PROMPT, TILE_SHEET_PROMPT) if tiles else (OVERLAY_ICON_PROMPT, ICON_SHEET_PROMPT)
			if len(batch) == 1:
				text = self._backgroundDescribe(
					batch[0][1], context + single + _languageInstruction(), 10, TILE_SIZE if tiles else ICON_SIZE, cancel)
				names = {1: text} if text is not None else None
			else:
				prompt = context + sheet.format(count=len(batch)) + _languageInstruction()
				text = self._backgroundDescribe(
					imaging.iconSheet([crop for _k, crop in batch]), prompt, (12 if tiles else 8) * len(batch) + 8, SHEET_SIZE, cancel)
				names = _sheetNames(text, len(batch)) if text is not None else None
			if names is None:
				return False  # interrupted; tried again later
			named = False
			for number, (iconKey, _crop) in enumerate(batch, 1):
				name = _iconName(names.get(number, ""))
				if name:
					self.labels.setGuess(app, iconKey, name)
					named = True
			if named:
				onNamed()
				wx.CallAfter(self._refreshOverlaySoon)
			return True
		return run

	def _refreshOverlaySoon(self):
		if self._overlayRefreshPending:
			return
		self._overlayRefreshPending = True
		wx.CallLater(800, self._refreshOverlay)

	def _refreshOverlay(self):
		"""Show new icon names in an overlay that does not update by itself."""
		self._overlayRefreshPending = False
		from . import overlay
		obj = api.getFocusObject()
		recognizer = getattr(obj, "recognizer", None)
		if not isinstance(recognizer, overlay.OverlayRecognizer) or recognizer.allowAutoRefresh:
			return
		try:
			obj._recognize(obj._onResult)
		except Exception:
			log.debugWarning("VisionMate: could not refresh the overlay", exc_info=True)

	@staticmethod
	def _progressBeeps(cancel, stop, beeps=True):
		"""Until stop is set: a short sound every second if beeps, and "Still working" after a long wait (and again
		every STILL_WORKING_REPEAT_SECONDS), so a slow start, like loading after an idle time, never sounds like a hang.
		The wait is the setting "statusSeconds"; 0 means never."""
		start = time.monotonic()
		try:
			first = conf()["statusSeconds"]
		except KeyError:
			first = STILL_WORKING_SECONDS
		nextSay = first if first > 0 else float("inf")
		while not stop.wait(1.0):
			if cancel.is_set():
				return
			if time.monotonic() - start >= nextSay:
				nextSay += STILL_WORKING_REPEAT_SECONDS
				# Translators: Said when a description is taking a long time to start.
				_speak(_("Still working"))
			elif beeps:
				_sound("working")

	@staticmethod
	def _pressMode():
		return DETAILED if scriptHandler.getLastScriptRepeatCount() > 0 else QUICK
