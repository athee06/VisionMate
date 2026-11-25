# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Automatic descriptions of unlabeled images in browse mode."""
import addonHandler

from .common import *  # noqa: F401,F403

addonHandler.initTranslation()


class AutoImagesMixin:
	def _remember(self, key, text):
		self._autoCache[key] = text
		self._autoCache.move_to_end(key)
		while len(self._autoCache) > AUTO_CACHE_SIZE:
			self._autoCache.popitem(last=False)

	def _speakTextInfo(self, info, *args, **kwargs):
		result = self._origSpeakTextInfo(info, *args, **kwargs)
		if conf()["autoDescribe"] and self._hasData:
			reason = kwargs.get("reason", args[3] if len(args) > 3 else None)
			if reason in (OutputReason.CARET, OutputReason.FOCUS, OutputReason.QUICKNAV):
				try:
					self._autoDescribeIn(info)
				except Exception:
					# Never let this break NVDA's own reading.
					log.debugWarning("VisionMate: automatic description check failed", exc_info=True)
		return result

	def _autoDescribeIn(self, info):
		self._autoGeneration += 1
		if scriptHandler.isScriptWaiting():
			return  # the user is moving on; do not slow them down
		document = getattr(info, "obj", None)
		context = self._documentContext(info, document)
		found = autodescribe.findUnlabeledGraphic(info)
		if found is not None:
			locate, place = found
			# Give browse mode a moment to scroll the image into view before taking its picture.
			wx.CallLater(150, self._autoCapture, locate, self._autoGeneration, document, place, context)
		if conf()["readAhead"] and getattr(document, "getNVDAObjectFromIdentifier", None) is not None:
			wx.CallLater(READ_AHEAD_DELAY_MS, self._readAhead, info, self._autoGeneration, context)

	@staticmethod
	def _documentContext(info, document):
		return [
			("app", _safe(lambda: document.rootNVDAObject.appModule.appName) or _safe(lambda: document.appModule.appName)),
			("page title", _safe(lambda: document.rootNVDAObject.name)),
			("text next to the image", _safe(lambda: info.text)),
		]

	def _readAhead(self, info, generation, context):
		"""Describe images a little further down the page in the background, so they are instant when reached."""
		if generation != self._autoGeneration or self._busy or scriptHandler.isScriptWaiting():
			return
		try:
			ahead = info.copy()
			ahead.collapse(end=True)
			ahead.move(textInfos.UNIT_LINE, READ_AHEAD_LINES, endPoint="end")
			found = autodescribe.findUnlabeledGraphics(ahead, limit=READ_AHEAD_IMAGES * 3)
		except Exception:
			log.debugWarning("VisionMate: read ahead failed", exc_info=True)
			return
		window = _safe(lambda: api.getForegroundObject().location)
		queued = 0
		for locate, _place in found:
			loc = _safe(locate)
			if not autodescribe.bigEnough(loc) or not window or not self._inside(loc, window):
				continue
			image = self._grabOrReport(_bbox(loc), quiet=True)
			if image is None or autodescribe.isBlank(image):
				continue
			key = hashlib.sha1(image.tobytes()).hexdigest()
			if key in self._autoCache:
				continue
			self._queueBackground(self._readAheadJob(image, key, context), ("auto", key))
			queued += 1
			if queued >= READ_AHEAD_IMAGES:
				break

	def _readAheadJob(self, image, key, context):
		prompt = _contextPrompt(context[:2]) + AUTO_PROMPT + HONESTY + _languageInstruction()

		def run(cancel):
			text = self._backgroundDescribe(image, prompt, 80, conf()["quickSize"], cancel)
			if text is None:
				return False
			if text:
				wx.CallAfter(self._remember, key, text)
			return True
		return run

	@staticmethod
	def _inside(loc, outer):
		return (loc.left >= outer.left and loc.top >= outer.top
			and loc.left + loc.width <= outer.left + outer.width and loc.top + loc.height <= outer.top + outer.height)

	def _autoCapture(self, locate, generation, document=None, place=None, context=()):
		if generation != self._autoGeneration or scriptHandler.isScriptWaiting():
			return
		loc = _safe(locate)
		if not autodescribe.bigEnough(loc):
			return
		image = self._grabOrReport(_bbox(loc), quiet=True)
		if image is None or autodescribe.isBlank(image):
			return
		key = hashlib.sha1(image.tobytes()).hexdigest()
		if self._repeats.seen(document, key, place):
			return
		cached = self._autoCache.get(key)
		if cached:
			self._autoCache.move_to_end(key)
			# Translators: Spoken before an automatic description of an image without a label.
			ui.message(_("Image: ") + _clean(cached))
			return
		self._describe(image, AUTO, cacheKey=key, context=context)

	def setAutoDescribe(self, on):
		conf()["autoDescribe"] = on
		if not on:
			self._autoGeneration += 1
