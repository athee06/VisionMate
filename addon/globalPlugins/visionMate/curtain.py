# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - lifts NVDA's screen curtain for a moment, so the screen can be captured.
# With the curtain on, every screenshot is black.

import time

from logHandler import log

# After the curtain is lifted, the screen needs a moment to show its contents again.
SETTLE_SECONDS = 0.05
MAX_WAIT_SECONDS = 0.5


class CurtainError(Exception):
	"""The screen curtain could not be turned back on."""


class _Curtain2026:
	"""NVDA 2026 and later: the screenCurtain module."""

	def __init__(self, curtain):
		self._curtain = curtain

	@property
	def enabled(self):
		return self._curtain.enabled

	def lift(self):
		self._curtain.disable(persist=False)

	def restore(self):
		self._curtain.enable(persist=False)

	def quietly(self):
		return self._curtain.settings


class _CurtainProvider:
	"""Older NVDA: the screen curtain is a vision enhancement provider."""

	def __init__(self, info):
		import vision
		self._handler = vision.handler
		self._info = info

	@property
	def enabled(self):
		return self._handler.getProviderInstance(self._info) is not None

	def lift(self):
		self._handler.terminateProvider(self._info, saveSettings=False)

	def restore(self):
		self._handler.initializeProvider(self._info, temporary=True)

	def quietly(self):
		return self._info.providerClass.getSettings()


def _find():
	try:
		import screenCurtain
		curtain = getattr(screenCurtain, "screenCurtain", None)
		return _Curtain2026(curtain) if curtain is not None else None
	except ImportError:
		pass
	try:
		import vision
		info = vision.handler.getProviderInfo("screenCurtain") if vision.handler else None
		return _CurtainProvider(info) if info is not None else None
	except ImportError:
		return None
	except Exception:
		log.debugWarning("VisionMate: could not find the screen curtain", exc_info=True)
		return None


def isOn():
	curtain = _find()
	try:
		return curtain is not None and curtain.enabled
	except Exception:
		return False


def _getSounds(settings):
	try:
		return settings["playToggleSounds"]
	except (TypeError, KeyError):
		return getattr(settings, "playToggleSounds", None)


def _setSounds(settings, value):
	try:
		settings["playToggleSounds"] = value
	except TypeError:
		settings.playToggleSounds = value


def isBlack(image):
	small = image.convert("L").resize((64, 64))
	return small.getextrema()[1] < 16


def captureUnderCurtain(grab):
	"""Lift the screen curtain, call grab() until it returns a picture that is not black, and put the curtain back.
	Raises CurtainError if the curtain cannot be turned back on. Must run on NVDA's main thread."""
	curtain = _find()
	if curtain is None or not curtain.enabled:
		return grab()
	# The curtain's on and off sounds would play on every description, so keep them quiet meanwhile.
	settings, sounds = None, None
	try:
		settings = curtain.quietly()
		sounds = _getSounds(settings)
		if sounds:
			_setSounds(settings, False)
	except Exception:
		log.debugWarning("VisionMate: could not silence the screen curtain", exc_info=True)
		settings = None
	try:
		curtain.lift()
		try:
			deadline = time.monotonic() + MAX_WAIT_SECONDS
			while True:
				time.sleep(SETTLE_SECONDS)
				image = grab()
				if not isBlack(image) or time.monotonic() > deadline:
					return image
		finally:
			try:
				curtain.restore()
			except Exception as e:
				log.error("VisionMate: could not turn the screen curtain back on", exc_info=True)
				raise CurtainError(str(e))
			if not curtain.enabled:
				raise CurtainError("the screen curtain is still off")
	finally:
		if settings is not None and sounds:
			_setSounds(settings, sounds)
