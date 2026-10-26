# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - fast, fully offline image description for NVDA.
# Images never leave the computer: a vision model runs locally through a bundled engine.

import collections
import contextlib
import hashlib
import json
import logging
import os
import re
import threading
import time

import addonHandler
import api
import config
import controlTypes
import globalPluginHandler
import globalVars
import gui
import languageHandler
import queueHandler
import scriptHandler
import speech
import textInfos
import ui
import wx
from controlTypes import OutputReason
from logHandler import log
from scriptHandler import script
from speech import extensions as speechExtensions

from . import autodescribe, curtain, datapack, dialogs, explorer, followup, hardware, imaging, labels, localmedia, ocr, sounds, viewers, winzapp
from .engine import Engine, EngineError, imageMessages, prepareImage

addonHandler.initTranslation()

CONF_SECTION = "visionMate"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.abspath(os.path.join(PLUGIN_DIR, "..", ".."))
ENGINE_DIR = os.path.join(ADDON_DIR, "engine")
# Kept outside the add-on folder so the data survives add-on updates.
DATA_DIR = os.path.join(globalVars.appArgs.configPath, "visionMate")
PACK_DIR = os.path.join(DATA_DIR, "data")
IDLE_CHECK_SECONDS = 30
# Freeing memory: when Windows has less than this left, VisionMate gives its memory back after a short pause.
LOW_MEMORY_GB = 1.5
LOW_MEMORY_IDLE_SECONDS = 60
# Without "Get ready when NVDA starts", the memory is given back after this long unused.
NO_PRELOAD_IDLE_SECONDS = 10 * 60
# After freeing for low memory, VisionMate gets ready again once this much is free.
RELOAD_MEMORY_GB = 6

QUICK_PROMPT = (
	"Describe this image for a blind person in 2-3 short sentences. "
	"Say what it is, the main subjects, and read any important text."
)
DETAIL_PROMPT = (
	"Describe this image in detail for a blind person. Start with what kind of image it is, "
	"then describe the layout, people, objects, colours and actions. "
	"Read all visible text exactly as written."
)
AUTO_PROMPT = (
	"Describe this image in one short sentence for a blind person. "
	"If it contains important text, read it."
)
# Added to every prompt: say what cannot be seen instead of guessing.
HONESTY = (
	" If text is too small or blurry to read, say so instead of guessing it. "
	"Do not guess who a person is or how old they are."
)
# What NVDA knows about where the image is. Each part is cut to this length.
CONTEXT_PART_CHARS = 100
ICON_PROMPT = (
	"This is an icon on a button. In 1 to 3 words, what does the button probably do? Answer with the words only."
)
# In the overlay the icon is shown as "<name> icon", so ask what it is rather than what it does.
OVERLAY_ICON_PROMPT = (
	"What is this icon? Answer with 1 to 3 words only, like Settings, Search, Firefox, Folder or Play."
)
# Several icons at once, in one numbered picture (imaging.iconSheet).
ICON_SHEET_PROMPT = (
	"This picture shows {count} numbered icons. For each number, say what the icon is in 1 to 3 words, "
	"like Settings, Search, Back or Play. Answer one per line as: number: name"
)
ICON_SHEET_LINE = re.compile(r"^\s*(\d+)\s*[:.)-]\s*(.+)$", re.MULTILINE)
SHEET_SIZE = 512
# Follow-up questions must be about the image; see followup.py. Refused questions get no reply.
NOT_IMAGE = followup.NOT_IMAGE
# Questions and answers kept in a conversation, so it fits in the engine's memory.
FOLLOWUP_HISTORY = 3
# Screen pictures with less text than this are photos. They are sent a little smaller, which is faster.
PHOTO_MAX_OCR_CHARS = 20
PHOTO_SIZE_FACTOR = 0.875
# A detailed description this soon after a quick one is a second press, and reuses its picture.
REUSE_PICTURE_SECONDS = 2
ICON_SIZE = 64
# Larger buttons are not icon-only buttons.
ICON_MAX_SIDE = 200
ICON_MIN_SIDE = 8
READ_AHEAD_LINES = 40
READ_AHEAD_IMAGES = 3
READ_AHEAD_DELAY_MS = 1000
# Background work waits until the user has not asked for anything for this long. The engine cannot stop
# halfway through reading a picture, so a request made meanwhile would wait 1 to 2 seconds for it.
BACKGROUND_IDLE_SECONDS = 3
# After a click in the overlay, wait this long for the window to react before reading it again.
OVERLAY_REOPEN_MS = 700
OVERLAY_FOLLOW_SECONDS = 3
# Modes of a description.
QUICK, DETAILED, AUTO, ICON = "quick", "detailed", "auto", "icon"
_ICON_ROLE_NAMES = (
	"BUTTON", "TOGGLEBUTTON", "MENUBUTTON", "DROPDOWNBUTTON", "SPLITBUTTON", "MENUITEM", "LINK", "TAB", "ICON",
)
ICON_ROLES = {getattr(controlTypes.Role, n) for n in _ICON_ROLE_NAMES if hasattr(controlTypes.Role, n)}
AUTO_CACHE_SIZE = 300
# Elements that can be a chat message holding a photo. Only the photo in them is described.
_PHOTO_HOLDER_NAMES = ("LISTITEM", "GROUPING", "SECTION", "PARAGRAPH", "CELL", "TREEVIEWITEM")
PHOTO_HOLDER_ROLES = {getattr(controlTypes.Role, n) for n in _PHOTO_HOLDER_NAMES if hasattr(controlTypes.Role, n)}
# Some chat apps show a photo as a button that opens it, like Telegram's "Open file".
PHOTO_BUTTON_ROLES = {getattr(controlTypes.Role, n) for n in ("BUTTON", "LINK") if hasattr(controlTypes.Role, n)}
# How far into a message to look for its picture element.
PHOTO_SEARCH_DEPTH = 4
PHOTO_SEARCH_OBJECTS = 60
# WinZapp photos: if the photo is not there after this long, say that it is being fetched.
CHAT_PHOTO_WAIT_MS = 2000
# Focus events of the hidden viewer, and of WinZapp getting the focus back, are ignored until this long after.
CHAT_PHOTO_QUIET_SECONDS = 1.0
CHAT_PHOTO_CONTEXT = [("app", "WinZapp"), ("shown", "a photo someone sent in a WhatsApp chat")]
# Automatic descriptions wait until the user stays on a message this long, so moving through a chat stays quick.
AUTO_FOCUS_DELAY_MS = 500
# A viewer may show its title a moment before the photo is ready.
VIEWER_DELAY_MS = 300

confspec = {
	"autoDescribe": "boolean(default=False)",
	"useGpu": "boolean(default=True)",
	"preload": "boolean(default=True)",
	"answerInNvdaLanguage": "boolean(default=True)",
	"progressBeeps": "boolean(default=True)",
	"useOcr": "boolean(default=True)",
	"iconLabeler": "boolean(default=False)",
	"readAhead": "boolean(default=True)",
	"overlayLive": "boolean(default=True)",
	"quickSize": "integer(default=512, min=224, max=2048)",
	"detailSize": "integer(default=768, min=224, max=2048)",
}
config.conf.spec[CONF_SECTION] = confspec


def conf():
	return config.conf[CONF_SECTION]


def _languageInstruction():
	if not conf()["answerInNvdaLanguage"]:
		return ""
	lang = languageHandler.getLanguage().split("_")[0]
	if lang == "en":
		return ""
	name = languageHandler.getLanguageDescription(lang) or lang
	return f" Answer in {name}."


def _contextPrompt(parts):
	"""Turn what NVDA knows, like [("app", "chrome")], into a prompt prefix that helps the model understand the image."""
	cleaned = []
	for label, value in parts:
		value = " ".join(str(value or "").split())
		if value:
			if len(value) > CONTEXT_PART_CHARS:
				value = value[:CONTEXT_PART_CHARS].rsplit(" ", 1)[0] + "..."
			cleaned.append(f"{label}: {value}")
	if not cleaned:
		return ""
	return (
		"Context from the screen reader, only to help you understand the image. Do not read it out: "
		+ "; ".join(cleaned) + ".\n"
	)


def _safe(fn):
	try:
		return fn()
	except Exception:  # objects can die or raise COM errors at any time
		return None


def _windowContext():
	fg = _safe(api.getForegroundObject)
	return [
		("app", _safe(lambda: fg.appModule.appName)),
		("window title", _safe(lambda: fg.name)),
	]


def _isPhotoElement(obj, children):
	"""A picture element, or a button or link with nothing written in it, like Telegram's photo, which opens the photo
	when pressed. A file attachment is a button too, but has its name and size in it."""
	if obj.role == controlTypes.Role.GRAPHIC:
		return True
	return obj.role in PHOTO_BUTTON_ROLES and not any(_safe(lambda c=c: (c.name or "").strip()) for c in children)


def _iconName(text):
	"""Clean a guessed icon name: one short line, no quotes or full stop."""
	text = _clean(text.splitlines()[0] if text else "").strip(" .:;\"'")
	if text.lower().endswith(" icon"):
		text = text[:-5]
	words = text.split()[:4]
	text = " ".join(words)
	return text[:1].upper() + text[1:] if text else ""


def _sheetNames(text, count):
	"""{number: name} from an answer like "1: Back" on each line. The first answer for a number counts."""
	names = {}
	for m in ICON_SHEET_LINE.finditer(text or ""):
		number = int(m.group(1))
		if 1 <= number <= count and number not in names:
			names[number] = m.group(2)
	return names


def _bbox(loc):
	return (loc.left, loc.top, loc.left + loc.width, loc.top + loc.height)


_Box = collections.namedtuple("_Box", "left top width height")


def _windowBox(fg):
	"""Where the foreground window is on screen. Some windows, like the desktop, full-screen apps and games, do not
	tell NVDA; then Windows is asked for the window's rectangle, and if that fails too, the whole screen is used.
	The result is kept inside the screen, so a window partly off screen still works."""
	import ctypes
	from ctypes import wintypes
	user32 = ctypes.windll.user32
	# The whole screen, over all monitors.
	sx, sy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
	sw, sh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
	box = None
	loc = _safe(lambda: fg.location)
	if loc and loc.width > 0 and loc.height > 0:
		box = (loc.left, loc.top, loc.left + loc.width, loc.top + loc.height)
	else:
		handle = _safe(lambda: fg.windowHandle) or user32.GetForegroundWindow()
		rect = wintypes.RECT()
		if handle and user32.GetWindowRect(handle, ctypes.byref(rect)) and rect.right > rect.left and rect.bottom > rect.top:
			box = (rect.left, rect.top, rect.right, rect.bottom)
	if box is not None:
		left, top = max(box[0], sx), max(box[1], sy)
		right, bottom = min(box[2], sx + sw), min(box[3], sy + sh)
		if right - left >= 16 and bottom - top >= 16:
			return _Box(left, top, right - left, bottom - top)
	return _Box(sx, sy, sw, sh)


def _speak(text):
	queueHandler.queueFunction(queueHandler.eventQueue, ui.message, text)


def _sound(name):
	queueHandler.queueFunction(queueHandler.eventQueue, sounds.play, name)


def _bundledDataInfo():
	"""Download details of the vision data this add-on version was built with (written by build.py)."""
	try:
		with open(os.path.join(PLUGIN_DIR, "datainfo.json"), encoding="utf-8") as f:
			return json.load(f)
	except (OSError, ValueError):
		return None


_MARKDOWN = re.compile(r"\*\*|__|^#+\s*|`", re.MULTILINE)


def _clean(text):
	return " ".join(_MARKDOWN.sub("", text).split()).strip(" -")


class SentenceSpeaker:
	"""Speaks streamed text one sentence at a time, so speech starts before the model finishes."""

	_END = re.compile(r"(\S*)[.!?。！？](?=\s)|\n")
	# Shorter pieces are joined with the next one, so list labels like "Phone number:" are not spoken alone.
	_MIN_CHARS = 30
	# A long first sentence is started at a comma once it is this long, so speech begins sooner.
	_FIRST_CLAUSE_CHARS = 60
	_CLAUSE = re.compile(r",(?=\s)")

	def __init__(self, cancel, prefix=""):
		self._cancel = cancel
		self._buf = ""
		self._prefix = prefix
		self.spokeAnything = False

	def feed(self, delta):
		self._buf += delta
		pos = 0
		while True:
			m = self._END.search(self._buf, pos)
			if not m:
				self._sayFirstClause()
				return
			pos = m.end()
			word = m.group(1) or ""
			# "R." "Nr." "Tel." are abbreviations or initials, not sentence ends.
			if 0 < len(word) <= 3 and word[0].isupper():
				continue
			if len(self._buf[:pos].strip()) < self._MIN_CHARS:
				continue
			self._say(self._buf[:pos])
			self._buf = self._buf[pos:]
			pos = 0

	def _sayFirstClause(self):
		if self.spokeAnything or len(self._buf) < self._FIRST_CLAUSE_CHARS:
			return
		commas = [m.end() for m in self._CLAUSE.finditer(self._buf) if m.end() >= self._MIN_CHARS]
		if commas:
			self._say(self._buf[:commas[-1]])
			self._buf = self._buf[commas[-1]:]

	def flush(self):
		self._say(self._buf)
		self._buf = ""

	def _say(self, text):
		text = _clean(text)
		if text and not self._cancel.is_set():
			if not self.spokeAnything:
				text = self._prefix + text
			self.spokeAnything = True
			_speak(text)


def _curtainBlockedMessage():
	# Translators: Reported when the screen curtain is on and VisionMate cannot see through it.
	return _("The screen curtain is on and VisionMate cannot see this. Please turn the screen curtain off "
		"with NVDA+Control+Escape and try again.")


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = _("VisionMate")

	def __init__(self):
		super().__init__()
		os.makedirs(DATA_DIR, exist_ok=True)
		# The engine log can name internals, so it is only written when NVDA logs at debug level.
		engineLog = os.path.join(DATA_DIR, "engine.log") if log.isEnabledFor(logging.DEBUG) else None
		self._engine = Engine(ENGINE_DIR, engineLog)
		self._cancel = threading.Event()
		self._speakingCancel = None
		self._gpuFailed = False
		self._dataDialog = None
		self._hasData = datapack.installedVersion(PACK_DIR) > 0
		self._autoCache = collections.OrderedDict()
		self._autoGeneration = 0
		self._repeats = autodescribe.RepeatTracker()
		# Freeing memory when idle: how many descriptions are running, and when the last one ended.
		self._useLock = threading.Lock()
		self._busy = 0
		self._lastUse = time.monotonic()
		self._stopped = threading.Event()
		# True after the memory was given back because Windows ran low.
		self._freedForMemory = False
		self.labels = labels.LabelStore(os.path.join(DATA_DIR, "labels.json"))
		self._focusGeneration = 0
		# Background work: naming icons for the overlay and describing images ahead of the reader.
		self._background = collections.deque()
		self._backgroundWake = threading.Event()
		self._backgroundCancel = threading.Event()
		self._backgroundKeys = set()
		self._backgroundKey = None
		# (app, icon key) of icons waiting to be named, so a live overlay does not ask twice.
		self._iconsQueued = set()
		self._lastRequest = 0
		# (time, picture, screen) of the last quick description, for a second press.
		self._lastQuick = None
		self._overlayRefreshPending = False
		# While the overlay is open for a window, it opens again after clicks and focus changes in that window.
		self._overlayWindow = None
		self._overlayItem = None
		# Until this time, the overlay follows a click into whatever window comes to the front.
		self._overlayFollowUntil = 0
		self._overlayDoc = None
		# WinZapp photos: descriptions kept by message, the photo being fetched, and the last photo for a second press.
		self.chatPhotos = winzapp.DescriptionStore(os.path.join(DATA_DIR, "winzapp.json"))
		self._chatFetch = None
		self._chatPhoto = None
		# While a photo is fetched, the viewer WinZapp opens and WinZapp getting the focus back are not announced.
		self._quietUntil = 0
		self._quietFocus = None
		self._quietTop = None
		# The viewer photo last described automatically, so moving inside the viewer does not repeat it.
		self._viewerShown = None
		# Full-size photo searches; only the newest one is described.
		self._originalRequest = 0
		from .settings import VisionMatePanel
		self._panelClass = VisionMatePanel
		VisionMatePanel.plugin = self
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(VisionMatePanel)
		speechExtensions.pre_speechCanceled.register(self._onSpeechCanceled)
		# NVDA has no event for "browse mode reached an image", so watch what it reads.
		self._origSpeakTextInfo = speech.speakTextInfo
		speech.speakTextInfo = self._speakTextInfo
		if self._dataReady():
			if conf()["preload"]:
				self._startEngineInBackground()
			# Add-on updates come from the Add-on Store; one that needs newer vision data offers it here.
			bundled = _bundledDataInfo()
			if bundled and bundled.get("version", 0) > datapack.installedVersion(PACK_DIR):
				wx.CallLater(3000, self.showDataDialog, bundled, True)
		else:
			wx.CallLater(3000, self.showDataDialog)
		threading.Thread(target=self._unloadWhenIdle, name="visionMate-idle", daemon=True).start()
		threading.Thread(target=self._backgroundLoop, name="visionMate-background", daemon=True).start()

	def terminate(self):
		self._stopped.set()
		self._cancel.set()
		self._backgroundCancel.set()
		self._backgroundWake.set()
		self.labels.save()
		if speech.speakTextInfo == self._speakTextInfo:
			speech.speakTextInfo = self._origSpeakTextInfo
		speechExtensions.pre_speechCanceled.unregister(self._onSpeechCanceled)
		self._engine.stop()
		try:
			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(self._panelClass)
		except ValueError:
			pass
		super().terminate()

	# --- Engine ---

	def _dataReady(self):
		# Cached: this is checked every time NVDA reads a line while automatic descriptions are on.
		return self._hasData

	def _ensureEngine(self):
		core, vision = datapack.enginePaths(PACK_DIR)
		useGpu = conf()["useGpu"] and not self._gpuFailed
		try:
			self._engine.ensure(core, vision, useGpu)
		except EngineError:
			if not useGpu:
				raise
			log.warning("VisionMate: GPU start failed, falling back to CPU", exc_info=True)
			self._gpuFailed = True
			self._engine.ensure(core, vision, False)

	def _startEngineInBackground(self):
		def run():
			try:
				self._ensureEngine()
			except EngineError:
				log.error("VisionMate: could not start the engine", exc_info=True)

		threading.Thread(target=run, name="visionMate-preload", daemon=True).start()

	def _unloadWhenIdle(self):
		"""Gives the memory back when Windows runs low, or after a while unused if the user did not ask
		VisionMate to stay ready. Gets ready again once memory is free, if it should stay ready."""
		while not self._stopped.wait(IDLE_CHECK_SECONDS):
			try:
				free = hardware.freeMemoryGb()
			except Exception:
				free = None
			with self._useLock:
				if self._busy:
					continue
				idle = time.monotonic() - self._lastUse
				if not self._engine.running:
					if (self._freedForMemory and conf()["preload"] and free is not None and free >= RELOAD_MEMORY_GB
							and self._dataReady()):
						self._freedForMemory = False
						log.debug("VisionMate: memory is free again, getting ready")
						self._startEngineInBackground()
					continue
				if free is not None and free < LOW_MEMORY_GB and idle >= LOW_MEMORY_IDLE_SECONDS:
					log.debug(f"VisionMate: freeing memory, only {free:.1f} GB left")
					self._freedForMemory = True
					self._engine.stop()
				elif not conf()["preload"] and idle >= NO_PRELOAD_IDLE_SECONDS:
					log.debug("VisionMate: freeing memory after 10 idle minutes")
					self._engine.stop()

	def onSettingsSaved(self):
		self._gpuFailed = False
		if not self._dataReady():
			return
		if conf()["preload"]:
			self._startEngineInBackground()
		else:
			self._engine.stop()

	def _onDataInstalled(self):
		self._hasData = datapack.installedVersion(PACK_DIR) > 0
		self._autoCache.clear()
		self._engine.stop()  # the data may have been replaced by a newer version
		if conf()["preload"]:
			self._startEngineInBackground()

	# --- Vision data window ---

	def showDataDialog(self, info=None, isUpdate=False):
		if self._dataDialog:
			self._dataDialog.Raise()
			return
		info = info or _bundledDataInfo()
		if not info:
			# Translators: Reported when the add-on was built without download details.
			ui.message(_("VisionMate cannot find its vision data download. Please reinstall the add-on."))
			return
		self._dataDialog = dialogs.DataDialog(gui.mainFrame, info, PACK_DIR, self._onDataInstalled, isUpdate)
		dialogs.show(self._dataDialog)

	# --- Describing ---

	def _onSpeechCanceled(self):
		# Control (or anything else that silences NVDA) also stops a spoken description.
		if self._speakingCancel is not None:
			self._speakingCancel.set()

	def _describe(self, image, mode, cacheKey=None, context=(), screen=False, onDone=None):
		"""Describe a picture in the background. screen means it shows part of the screen, so OCR helps.
		onDone(text) is called with the result of an icon description, and onDone(text, mode) with any other."""
		self._cancel.set()
		# Background work gives way at once.
		self._backgroundCancel.set()
		if not self._dataReady():
			if mode not in (AUTO, ICON):
				self.showDataDialog()
			return
		cancel = self._cancel = threading.Event()
		now = self._lastRequest = time.monotonic()
		# Pressing twice: use the first press's picture, so the engine's work on it is reused even if the screen
		# changed a little, like a blinking cursor.
		if mode == QUICK:
			self._lastQuick = (now, image, screen)
		elif mode == DETAILED and self._lastQuick and now - self._lastQuick[0] < REUSE_PICTURE_SECONDS:
			image, screen = self._lastQuick[1], self._lastQuick[2]
		if mode != QUICK:
			self._lastQuick = None
		if mode not in (AUTO, ICON):
			sounds.play("detailed" if mode == DETAILED else "quick")
		threading.Thread(
			target=self._worker, args=(image, mode, cancel, cacheKey, context, screen, onDone),
			name="visionMate-describe", daemon=True,
		).start()

	@contextlib.contextmanager
	def _inUse(self):
		"""Marks the engine as in use, so it is not unloaded meanwhile."""
		with self._useLock:
			self._busy += 1
		try:
			yield
		finally:
			with self._useLock:
				self._busy -= 1
				self._lastUse = time.monotonic()

	def _worker(self, image, mode, cancel, cacheKey=None, context=(), screen=False, onDone=None):
		try:
			with self._inUse():
				self._describeNow(image, mode, cancel, cacheKey, context, screen, onDone)
		finally:
			self._lastRequest = time.monotonic()

	def _describeNow(self, image, mode, cancel, cacheKey, context, screen=False, onDone=None):
		c = conf()
		detailed = mode == DETAILED
		quiet = mode in (AUTO, ICON)
		# Detailed uses the same picture as quick, so pressing twice reuses the engine's work on it and starts at once.
		# OCR gives the exact screen text, so only screens without OCR need a bigger picture for small text.
		size = c["detailSize"] if detailed and screen and not c["useOcr"] else c["quickSize"]
		textPart = ""
		if mode in (QUICK, DETAILED):
			image = imaging.smartCrop(image)
			if screen and c["useOcr"]:
				lines = ocr.recognize(image)
				if cancel.is_set():
					return
				textPart = ocr.promptPart(lines)
				if len(ocr.linesText(lines).strip()) < PHOTO_MAX_OCR_CHARS:
					size = int(size * PHOTO_SIZE_FACTOR)
		if mode == ICON:
			size = ICON_SIZE
			prompt = _contextPrompt(context) + ICON_PROMPT + _languageInstruction()
		else:
			prompt = (
				_contextPrompt(context) + textPart
				+ {QUICK: QUICK_PROMPT, DETAILED: DETAIL_PROMPT, AUTO: AUTO_PROMPT}[mode]
				+ HONESTY + _languageInstruction()
			)
		maxTokens = {QUICK: 200, DETAILED: 600, AUTO: 80, ICON: 8}[mode]
		# Beep until speech starts, or until the detailed description window opens.
		# Automatic descriptions stay quiet so reading is not cluttered.
		stopBeeps = threading.Event()
		if c["progressBeeps"] and not quiet:
			threading.Thread(target=self._progressBeeps, args=(cancel, stopBeeps), daemon=True).start()
		# Translators: Spoken before an automatic description of an image without a label.
		speaker = None if detailed or mode == ICON else SentenceSpeaker(cancel, prefix=_("Image: ") if mode == AUTO else "")
		conversation = {"start": None, "history": []}
		window = dialogs.StreamingResult(
			onOpened=stopBeeps.set, onAsk=lambda question, dialog: self._askFollowUp(conversation, question, dialog),
		) if detailed else None

		def onText(delta):
			if speaker is not None:
				stopBeeps.set()
				speaker.feed(delta)
			elif window is not None:
				window.feed(delta)

		if speaker is not None:
			self._speakingCancel = cancel
		try:
			jpeg = prepareImage(image, size)
			for attempt in range(2):
				try:
					self._ensureEngine()
					text = self._engine.describe(jpeg, prompt, maxTokens, onText, cancel)
					break
				except EngineError:
					# The GPU can fail mid-request (e.g. driver reset). Retry once on the processor.
					if attempt or (speaker and speaker.spokeAnything) or not self._engine.usingGpu:
						raise
					log.warning("VisionMate: GPU request failed, retrying on CPU", exc_info=True)
					self._gpuFailed = True
		except EngineError as e:
			log.error("VisionMate: description failed", exc_info=True)
			if not cancel.is_set() and not quiet:
				_sound("error")
				# Translators: Reported when an image could not be described. {error} is the reason.
				_speak(_("Could not describe the image: {error}").format(error=e))
			return
		finally:
			stopBeeps.set()
			if self._speakingCancel is cancel:
				self._speakingCancel = None
		if text is None or cancel.is_set():
			return
		if cacheKey and text:
			self._remember(cacheKey, text)
		if mode == ICON:
			if text and onDone is not None:
				onDone(text)
		elif not text:
			if not quiet:
				# Translators: Reported when no description was produced.
				_speak(_("No description was produced."))
		elif detailed:
			conversation["start"] = imageMessages(jpeg, prompt) + [{"role": "assistant", "content": text}]
			window.finish(_clean_paragraphs(text))
		else:
			speaker.flush()
		if onDone is not None and text and mode != ICON:
			onDone(text, mode)

	# --- Follow-up questions in the detailed window ---

	def _askFollowUp(self, conversation, question, dialog):
		sounds.play("send")
		if followup.clearlyOffTopic(question):
			self._declineQuestion(question, dialog)
			return
		if conversation["start"] is None:
			wx.CallAfter(dialog.addAnswer, question, None)
			# Translators: Reported when a question is asked before the description has finished.
			ui.message(_("Please wait until the description is finished."))
			return
		self._cancel.set()
		self._backgroundCancel.set()
		cancel = self._cancel = threading.Event()
		threading.Thread(
			target=self._answer, args=(conversation, question, dialog, cancel), name="visionMate-describe", daemon=True,
		).start()

	@staticmethod
	def _declineQuestion(question, dialog):
		"""Say plainly that only questions about the image are answered, so silence is never mistaken for a hang."""
		# Translators: Reply to a question that is not about the described image.
		reply = _("I can only answer questions about this image.")
		_sound("receive")
		_speak(reply)
		wx.CallAfter(dialog.addAnswer, question, reply)

	def _answer(self, conversation, question, dialog, cancel):
		messages = list(conversation["start"])
		for q, a in conversation["history"]:
			messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
		speaker = SentenceSpeaker(cancel)
		refused = threading.Event()
		state = {"held": "", "open": False}

		def onText(delta):
			if state["open"]:
				speaker.feed(delta)
				return
			# Hold the start back until it is clear the answer is not the refusal word.
			state["held"] += delta
			start = state["held"].strip().upper()
			if start.startswith(NOT_IMAGE):
				refused.set()
				cancel.set()
				return
			if not start or NOT_IMAGE.startswith(start):
				return
			state["open"] = True
			_sound("receive")
			speaker.feed(state["held"])

		answer = None
		declined = False
		self._speakingCancel = cancel
		try:
			with self._inUse():
				self._ensureEngine()
				check = self._engine.chat(
					messages + [{"role": "user", "content": followup.CHECK.format(question=question)}], 2, cancel=cancel,
				)
				if check is not None and not check.strip().lower().startswith("yes"):
					declined = True
				elif check is not None and not cancel.is_set():
					answer = self._engine.chat(
						messages + [{"role": "user", "content": question + followup.ANSWER}], 150, onText, cancel,
					)
		except EngineError as e:
			log.error("VisionMate: follow-up question failed", exc_info=True)
			if not cancel.is_set():
				# Translators: Reported when a question about the image could not be answered. {error} is the reason.
				_speak(_("Could not answer the question: {error}").format(error=e))
		finally:
			if self._speakingCancel is cancel:
				self._speakingCancel = None
		if declined or refused.is_set() or (answer and answer.strip().upper().startswith(NOT_IMAGE)):
			self._declineQuestion(question, dialog)
			return
		if not answer:
			answer = None
		else:
			if not state["open"]:
				_sound("receive")
				speaker.feed(state["held"])
			speaker.flush()
			answer = _clean(answer)
			conversation["history"] = (conversation["history"] + [(question, answer)])[-FOLLOWUP_HISTORY:]
		wx.CallAfter(dialog.addAnswer, question, answer)

	# --- Background work ---

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

	def nameIcons(self, app, icons, onNamed):
		"""Name icons for the overlay in the background, up to 16 at a time from one picture.
		onNamed() is called after new names arrive."""
		icons = [(k, crop) for k, crop in icons if (app, k) not in self._iconsQueued]
		for start in range(0, len(icons), imaging.SHEET_MAX_ICONS):
			batch = icons[start:start + imaging.SHEET_MAX_ICONS]
			self._iconsQueued.update((app, k) for k, _crop in batch)
			self._queueBackground(self._iconJob(app, batch, onNamed), ("icon", app, tuple(k for k, _crop in batch)))

	def _iconJob(self, app, batch, onNamed):
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
			if len(batch) == 1:
				text = self._backgroundDescribe(
					batch[0][1], context + OVERLAY_ICON_PROMPT + _languageInstruction(), 8, ICON_SIZE, cancel)
				names = {1: text} if text is not None else None
			else:
				prompt = context + ICON_SHEET_PROMPT.format(count=len(batch)) + _languageInstruction()
				text = self._backgroundDescribe(
					imaging.iconSheet([crop for _k, crop in batch]), prompt, 8 * len(batch) + 8, SHEET_SIZE, cancel)
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
	def _progressBeeps(cancel, stop):
		while not stop.wait(1.0):
			if cancel.is_set():
				return
			_sound("working")

	@staticmethod
	def _pressMode():
		return DETAILED if scriptHandler.getLastScriptRepeatCount() > 0 else QUICK

	# --- Automatic descriptions of unlabeled images ---

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

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_("Turns automatic descriptions of images without a label on or off."),
		gesture="kb:NVDA+alt+g",
	)
	def script_toggleAutoDescribe(self, gesture):
		on = not conf()["autoDescribe"]
		self.setAutoDescribe(on)
		if on and not self._dataReady():
			self.showDataDialog()
		ui.message(
			# Translators: Reported when automatic image descriptions are turned on.
			_("Automatic image descriptions on") if on
			# Translators: Reported when automatic image descriptions are turned off.
			else _("Automatic image descriptions off")
		)

	# --- Naming buttons from their icons, and images that get focus outside browse mode ---

	def event_gainFocus(self, obj, nextHandler):
		if self._overlayDoc is not None and self._holdOverlay(obj):
			return  # NVDA stays in the overlay, which updates in place
		if self._isQuiet(obj):
			return
		nextHandler()
		self._focusGeneration += 1
		try:
			localmedia.warmUp(obj.appModule.appName)
		except Exception:
			pass  # objects can die at any time
		try:
			self._sayChatPhoto(obj)
		except Exception:
			log.debugWarning("VisionMate: WinZapp photo check failed", exc_info=True)
		if not self._hasData:
			return
		try:
			self._checkFocus(obj, self._focusGeneration)
		except Exception:
			# Never let this break NVDA's own focus handling.
			log.debugWarning("VisionMate: focus check failed", exc_info=True)

	def event_foreground(self, obj, nextHandler):
		if self._isQuiet(obj):
			return
		nextHandler()

	def _isQuiet(self, obj):
		"""True for focus changes caused by fetching a WinZapp photo: the viewer it opens, which is hidden at once, and
		WinZapp getting the focus back on the same message."""
		if time.monotonic() > self._quietUntil:
			return False
		try:
			app = (obj.appModule.appName or "").lower()
			if app in winzapp.VIEWER_APPS:
				return True
			if winzapp.isWinZapp(app):
				# The window coming back to the front, or the message the user is still on.
				return obj.windowHandle == self._quietTop or (self._quietFocus is not None and obj == self._quietFocus)
		except Exception:
			log.debugWarning("VisionMate: quiet check failed", exc_info=True)
		return False

	# --- Photos in WinZapp ---

	def _chatPhotoTarget(self, obj):
		"""(WinZapp window, Open image button, message key) when obj is a selected photo message in WinZapp, else None."""
		appModule = _safe(lambda: obj.appModule)
		if appModule is None or not winzapp.isWinZapp(appModule.appName) or obj.role != controlTypes.Role.LISTITEM:
			return None
		if controlTypes.State.SELECTED not in obj.states:
			return None  # the button belongs to the selected message
		top = api.getForegroundObject().windowHandle
		appDir = os.path.dirname(_safe(lambda: appModule.appPath) or "")
		button = winzapp.openImageButton(top, winzapp.openImageNames(appDir))
		if not button:
			return None
		return top, button, winzapp.messageKey(winzapp.chatName(obj.windowHandle), obj.name)

	def _sayChatPhoto(self, obj):
		"""On a WinZapp photo message that was described before, say what the photo shows."""
		appName = _safe(lambda: obj.appModule.appName)
		if not winzapp.isWinZapp(appName) or obj.role != controlTypes.Role.LISTITEM:
			return
		text = self.chatPhotos.get(winzapp.messageKey(winzapp.chatName(obj.windowHandle), obj.name))
		if text:
			# Translators: Spoken after a WinZapp photo message, before what its photo shows.
			ui.message(_("Image: ") + text)

	def _describeChatPhoto(self, obj):
		"""NVDA+Alt+A on a photo message in WinZapp. Returns False if obj is not one."""
		target = self._chatPhotoTarget(obj)
		if target is None:
			return False
		key = target[2]
		mode = self._pressMode()
		fetch = self._chatFetch
		if fetch is not None and fetch["key"] == key and fetch["image"] is None and not fetch["cancel"].is_set():
			fetch["mode"] = mode  # a second press while the photo is still coming
			return True
		if mode == QUICK:
			saved = self.chatPhotos.get(key)
			if saved:
				ui.message(saved)
				return True
		elif self._chatPhoto is not None and self._chatPhoto[0] == key:
			self._describeChatPhotoNow(key, self._chatPhoto[1], mode)
			return True
		if not self._dataReady():
			self.showDataDialog()
			return True
		self._startChatFetch(target, mode)
		return True

	def _startChatFetch(self, target, mode):
		"""Get the photo of a WinZapp message in the background, then describe it."""
		top, button, key = target
		if self._chatFetch is not None:
			self._chatFetch["cancel"].set()
		focus = api.getFocusObject()
		fetch = self._chatFetch = {"key": key, "mode": mode, "image": None, "cancel": threading.Event(), "focus": focus}
		self._quietFocus = focus
		self._quietTop = top
		self._quietUntil = time.monotonic() + winzapp.FETCH_SECONDS + winzapp.VIEWER_SECONDS

		def onPhoto(image):
			fetch["image"] = image if image is not None else False
			wx.CallAfter(self._chatPhotoReady, fetch)

		def run():
			try:
				winzapp.fetchPhoto(top, button, fetch["cancel"], onPhoto)
			except Exception:
				log.error("VisionMate: could not get the photo from WinZapp", exc_info=True)
				if fetch["image"] is None:
					onPhoto(None)
			finally:
				if self._chatFetch is fetch:
					self._quietUntil = time.monotonic() + CHAT_PHOTO_QUIET_SECONDS

		def stillComing():
			if fetch["image"] is None and not fetch["cancel"].is_set() and self._chatFetch is fetch:
				# Translators: Spoken when a WinZapp photo takes a while, usually because it is being downloaded.
				ui.message(_("Getting the photo"))

		threading.Thread(target=run, name="visionMate-winzapp", daemon=True).start()
		if mode != AUTO:
			wx.CallLater(CHAT_PHOTO_WAIT_MS, stillComing)

	def _chatPhotoReady(self, fetch):
		if fetch["cancel"].is_set() or self._chatFetch is not fetch:
			return
		if fetch["image"] is False:
			if fetch["mode"] != AUTO:
				_sound("error")
				# Translators: Reported when WinZapp did not give VisionMate the photo of a message.
				ui.message(_("Could not get the photo from WinZapp."))
			return
		key, image = fetch["key"], fetch["image"]
		self._chatPhoto = (key, image)
		if fetch["mode"] == AUTO and api.getFocusObject() != fetch["focus"]:
			# The user moved on: describe it quietly, so it is ready when they come back.
			self._queueBackground(self._chatPhotoJob(key, image), ("chat", key))
			return
		self._describeChatPhotoNow(key, image, fetch["mode"])

	def _chatPhotoJob(self, key, image):
		prompt = _contextPrompt(CHAT_PHOTO_CONTEXT) + AUTO_PROMPT + HONESTY + _languageInstruction()

		def run(cancel):
			text = self._backgroundDescribe(image, prompt, 80, conf()["quickSize"], cancel)
			if text is None:
				return False
			if text and not self.chatPhotos.get(key):
				self.chatPhotos.set(key, " ".join(_clean(text).split()))
			return True
		return run

	def _describeChatPhotoNow(self, key, image, mode):
		def onDone(text, doneMode):
			# The short description is the one said on the message; a detailed one is kept only if there is none.
			if doneMode == QUICK or not self.chatPhotos.get(key):
				self.chatPhotos.set(key, " ".join(_clean(text).split()))

		self._describe(image, mode, context=CHAT_PHOTO_CONTEXT, onDone=onDone)

	def _checkFocus(self, obj, generation):
		c = conf()
		if c["autoDescribe"] and self._autoPhoto(obj, generation):
			return
		if not (c["iconLabeler"] or c["autoDescribe"]) or not autodescribe.isUnlabeled(obj.name):
			return
		role = obj.role
		if c["iconLabeler"] and role in ICON_ROLES and not (obj.description or "").strip():
			wx.CallLater(100, self._labelFocusedButton, obj, generation)
		elif c["autoDescribe"] and role == controlTypes.Role.GRAPHIC:
			ti = obj.treeInterceptor
			if ti is None or ti.passThrough:  # browse mode is handled while reading
				wx.CallLater(150, self._autoCapture, lambda: obj.location, self._autoGeneration, None, None,
					_windowContext())

	# --- Automatic descriptions of photos: in messages of any app, and in image viewers ---

	def _autoPhoto(self, obj, generation):
		"""Describe a photo where the focus landed, once the user stays there for a moment. Returns True if obj is a
		photo message or the focus is in an image viewer, so nothing else needs checking."""
		if self._viewerName(api.getForegroundObject()):
			wx.CallLater(VIEWER_DELAY_MS, self._autoViewer)
			return True
		if obj.role not in PHOTO_HOLDER_ROLES:
			return False
		if explorer.isExplorer(_safe(lambda: obj.appModule.appName)):
			# Image files in File Explorer and on the desktop are described from the file, not the thumbnail.
			wx.CallLater(AUTO_FOCUS_DELAY_MS, self._autoExplorerFile, obj, generation)
			return True
		target = self._chatPhotoTarget(obj)
		if target is not None:
			if not self.chatPhotos.get(target[2]):  # a described one was already said with the message
				wx.CallLater(AUTO_FOCUS_DELAY_MS, self._autoChatPhoto, obj, target, generation)
			return True
		loc = obj.location
		if winzapp.isWinZapp(_safe(lambda: obj.appModule.appName)) or not loc or loc.height < imaging.PHOTO_MIN_SIDE:
			return False
		wx.CallLater(AUTO_FOCUS_DELAY_MS, self._autoMessagePhoto, obj, generation)
		return False

	def _stillThere(self, generation):
		return generation == self._focusGeneration and not scriptHandler.isScriptWaiting()

	def _autoChatPhoto(self, obj, target, generation):
		if self._stillThere(generation) and self._dataReady():
			self._startChatFetch(target, AUTO)

	def _autoMessagePhoto(self, obj, generation):
		"""A message in a chat app that shows its photo on screen, like WhatsApp or Telegram."""
		if not self._stillThere(generation) or not self._dataReady():
			return
		loc = _safe(lambda: obj.location)
		if not loc or loc.width <= 0 or loc.height <= 0:
			return
		bbox = _bbox(loc)
		image = self._grabOrReport(bbox, quiet=True)
		if image is None:
			return
		photo = _safe(lambda: self._photoIn(obj, bbox, image))
		if not photo:
			return
		image = image.crop(photo)
		if autodescribe.isBlank(image):
			return
		key = hashlib.sha1(image.tobytes()).hexdigest()
		cached = self._autoCache.get(key)
		if cached:
			self._autoCache.move_to_end(key)
			ui.message(_("Image: ") + _clean(cached))
			return
		self._describeMessagePhoto(image, AUTO, _safe(lambda: obj.appModule.appName), cacheKey=key, generation=generation)

	def _describeMessagePhoto(self, preview, mode, appName, cacheKey=None, generation=None):
		"""Describe a photo cut from a chat message. If the app keeps the full-size photo as a file, like Unigram, that
		is found in the background and described instead, so small text can be read. With a focus generation, it is
		dropped if the user moved on meanwhile."""
		context = _windowContext() + [("shown", "a photo someone sent in a chat")]
		if not localmedia.folders(appName):
			self._describe(preview, mode, cacheKey=cacheKey, context=context, screen=True)
			return
		self._originalRequest += 1
		request = self._originalRequest

		def describe(image):
			# Only the newest request: a second press replaces the first.
			if request != self._originalRequest or (generation is not None and not self._stillThere(generation)):
				return
			self._describe(image, mode, cacheKey=cacheKey, context=context, screen=True)

		def find():
			path = localmedia.findOriginal(preview, appName)
			image = viewers.openImage(path) if path else None
			wx.CallAfter(describe, image if image is not None else preview)

		threading.Thread(target=find, name="visionMate-original", daemon=True).start()

	@staticmethod
	def _viewerName(fg):
		"""The image file name in the title of the window in front, like "beach.jpg - Photos", or None."""
		return viewers.imageName(_safe(lambda: fg.name))

	def _describeViewerImage(self):
		"""In an image viewer, describe the image file it shows at full quality. Returns False if not in one."""
		if not self._viewerName(api.getForegroundObject()):
			return False
		found = viewers.imageInWindow(_safe(lambda: api.getForegroundObject().name))
		# If the file was not found, the screen is described instead.
		return bool(found) and self._describeFile(found[0], self._pressMode())

	@staticmethod
	def _fileKey(path):
		try:
			return f"file:{path}:{os.path.getmtime(path)}"
		except OSError:
			return None

	def _describeFile(self, path, mode):
		"""Describe an image file. Returns False if it cannot be read, like a format VisionMate does not know."""
		key = self._fileKey(path)
		if mode == AUTO:
			cached = self._autoCache.get(key)
			if cached:
				self._autoCache.move_to_end(key)
				ui.message(_("Image: ") + _clean(cached))
				return True
		image = viewers.openImage(path)
		if image is None:
			return False
		self._describe(image, mode, cacheKey=key, context=[("file name", os.path.basename(path))])
		return True

	def _explorerImage(self, obj):
		"""The image file an item in File Explorer or on the desktop stands for, or None."""
		if not explorer.isExplorer(_safe(lambda: obj.appModule.appName)) or obj.role != controlTypes.Role.LISTITEM:
			return None
		fg = api.getForegroundObject()
		onDesktop = _safe(lambda: fg.windowClassName) in ("Progman", "WorkerW")
		return explorer.imageFile(_safe(lambda: fg.windowHandle), obj.name, onDesktop)

	def _autoExplorerFile(self, obj, generation):
		if not self._stillThere(generation) or not self._dataReady():
			return
		path = _safe(lambda: self._explorerImage(obj))
		if path:
			self._describeFile(path, AUTO)

	def _autoViewer(self):
		"""An image viewer is in front: describe its photo once."""
		if not conf()["autoDescribe"] or not self._dataReady() or time.monotonic() < self._quietUntil:
			return
		found = viewers.imageInWindow(_safe(lambda: api.getForegroundObject().name))
		if not found:
			return
		path = found[0]
		key = self._fileKey(path)
		if key is None or key == self._viewerShown:
			return  # the focus moved inside the viewer; this photo was already said
		self._viewerShown = key
		self._describeFile(path, AUTO)

	def event_nameChange(self, obj, nextHandler):
		nextHandler()
		# A viewer shows the next photo by changing its title.
		try:
			if conf()["autoDescribe"] and obj == api.getForegroundObject() and self._viewerName(obj):
				wx.CallLater(VIEWER_DELAY_MS, self._autoViewer)
		except Exception:
			log.debugWarning("VisionMate: viewer title check failed", exc_info=True)

	def _buttonImage(self, obj):
		"""A picture of a small button, or None."""
		loc = obj.location
		if not loc or not (ICON_MIN_SIDE <= loc.width <= ICON_MAX_SIDE and ICON_MIN_SIDE <= loc.height <= ICON_MAX_SIDE):
			return None
		return self._grabOrReport(_bbox(loc), quiet=True)

	def _labelFocusedButton(self, obj, generation):
		if generation != self._focusGeneration or scriptHandler.isScriptWaiting():
			return
		image = self._buttonImage(obj)
		if image is None:
			return
		app = _safe(lambda: obj.appModule.appName)
		key = labels.imageKey(image)
		name, byUser = self.labels.get(app, key)
		if name:
			# Translators: Spoken when a button without a name is focused. {name} is a guess from its icon.
			ui.message(name if byUser else _("Probably {name}").format(name=name))
			return

		def onDone(text):
			name = _iconName(text)
			if name:
				self.labels.setGuess(app, key, name)
				if generation == self._focusGeneration:
					_speak(_("Probably {name}").format(name=name))

		self._describe(image, ICON, context=[("app", app)], onDone=onDone)

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_("Turns naming of buttons that have no name, from their icon, on or off."),
		gesture="kb:NVDA+alt+b",
	)
	def script_toggleIconLabeler(self, gesture):
		on = not conf()["iconLabeler"]
		conf()["iconLabeler"] = on
		if on and not self._dataReady():
			self.showDataDialog()
		ui.message(
			# Translators: Reported when button naming is turned on.
			_("Button names on") if on
			# Translators: Reported when button naming is turned off.
			else _("Button names off")
		)

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_("Gives your own name to the current button, or to the current item in the overlay."),
		gesture="kb:NVDA+alt+n",
	)
	def script_nameItem(self, gesture):
		focus = api.getFocusObject()
		recognizer = getattr(focus, "recognizer", None)
		try:
			from . import overlay
		except ImportError:
			overlay = None
		if overlay is not None and isinstance(recognizer, overlay.OverlayRecognizer):
			result = recognizer.lastResult
			try:
				offset = focus.makeTextInfo(textInfos.POSITION_CARET)._startOffset
			except Exception:
				offset = None
			item = result.itemAt(offset) if result is not None and offset is not None else None
			if item is None:
				# Translators: Reported when there is no overlay item to name at the cursor.
				ui.message(_("No item here to name."))
				return
			app = recognizer.app

			def onName(name):
				self.labels.setUser(app, item["key"], name)
				recognizer.namesChanged()
				# The naming window took the focus away from the overlay, so open it again on the same item.
				self._overlayItem = name or item["text"]
				wx.CallLater(400, self.openOverlay, True)

			self._askName(item["text"], onName)
			return
		image = self._buttonImage(focus)
		if image is None:
			# Translators: Reported when the focus is not a small button that can be named.
			ui.message(_("Only buttons and items in the overlay can be named."))
			return
		app = _safe(lambda: focus.appModule.appName)
		key = labels.imageKey(image)
		current, _byUser = self.labels.get(app, key)
		self._askName(current or focus.name or "", lambda name: self.labels.setUser(app, key, name))

	def _askName(self, current, onName):
		def show():
			# Translators: Title and prompt of the window for naming a button or overlay item.
			dlg = wx.TextEntryDialog(gui.mainFrame, _("Name (leave empty to remove your name):"), _("VisionMate name"),
				value=current)
			gui.mainFrame.prePopup()
			try:
				ok = dlg.ShowModal() == wx.ID_OK
				name = dlg.GetValue().strip()
			finally:
				dlg.Destroy()
				gui.mainFrame.postPopup()
			if ok:
				onName(name)
				# Translators: Reported after a name was saved or removed.
				ui.message(_("Name saved") if name else _("Name removed"))

		wx.CallAfter(show)

	# --- The overlay for inaccessible windows ---

	def captureForOverlay(self, box):
		try:
			return self._grab(box)
		except curtain.CurtainBlocked:
			raise RuntimeError(_curtainBlockedMessage())

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_(
			"Opens the overlay: the current window as a list of its texts and icons. "
			"Enter clicks an item in the real window, Escape closes."
		),
		gesture="kb:NVDA+alt+o",
	)
	def script_overlay(self, gesture):
		self.openOverlay()

	def openOverlay(self, restore=False):
		try:
			from contentRecog import RecogImageInfo, recogUi
			from . import overlay
		except ImportError:
			log.debugWarning("VisionMate: content recognition is not available", exc_info=True)
			return
		focus = api.getFocusObject()
		if isinstance(focus, overlay.OverlayDocument):
			if not restore:
				# Pressing NVDA+Alt+O again closes the overlay.
				focus.script_exit(None)
			return
		fg = api.getForegroundObject()
		loc = _windowBox(fg)
		app = _safe(lambda: fg.appModule.appName) or "?"
		recognizer = overlay.OverlayRecognizer(self, app, live=conf()["overlayLive"], underCurtain=curtain.isOn(),
			title=_safe(lambda: fg.name) or "")
		try:
			imageInfo = RecogImageInfo.createFromRecognizer(loc.left, loc.top, loc.width, loc.height, recognizer)
		except ValueError:
			ui.message(_("This window has no location on screen."))
			return
		# The same steps as NVDA's own recognizeNavigatorObject, but with the overlay's own document.
		if getattr(recogUi, "_activeRecog", None):
			recogUi._activeRecog.cancel()
		recogUi._activeRecog = recognizer
		if not restore:
			sounds.play("overlayOpen")
			# Translators: Reported while the overlay is being prepared.
			ui.message(_("Overlay"))
		try:
			# NVDA creates its objects from keyword arguments only.
			document = overlay.OverlayDocument(
				plugin=self, restoreText=self._overlayItem if restore else None, recognizer=recognizer,
				imageInfo=imageInfo,
			)
			document.start()
		except Exception:
			log.error("VisionMate: could not open the overlay", exc_info=True)
			self.overlayClosed()
			sounds.play("error")
			# Translators: Reported when the overlay could not be opened.
			ui.message(_("Could not open the overlay."))
			return
		self._overlayWindow = _safe(lambda: fg.windowHandle)
		self._overlayDoc = document

	def overlayClicked(self, itemText):
		"""An item was clicked. A click can open another window, so for a moment the overlay follows the window
		in front. Without live updates, show the result of the click once the window has reacted."""
		self._overlayItem = itemText
		self._overlayFollowUntil = time.monotonic() + OVERLAY_FOLLOW_SECONDS
		doc = self._overlayDoc
		if doc is not None and not doc.recognizer.allowAutoRefresh:
			wx.CallLater(OVERLAY_REOPEN_MS, self._refreshOverlayNow, doc)

	def _overlayLeft(self):
		"""True if the user has moved to another window, not just clicked something that opened one."""
		fg = api.getForegroundObject()
		return (_safe(lambda: fg.windowHandle) != self._overlayWindow
			and time.monotonic() > self._overlayFollowUntil)

	def overlayClosed(self):
		# Icons not named yet are not needed now; naming them would only hold up the next description.
		icons = [item for item in list(self._background) if item[1][0] == "icon"]
		for item in icons:
			try:
				self._background.remove(item)
			except ValueError:
				pass
			self._backgroundKeys.discard(item[1])
		key = self._backgroundKey
		if key is not None and key[0] == "icon":
			self._backgroundKeys.discard(key)
			self._backgroundCancel.set()
		self._iconsQueued.clear()
		self._overlayWindow = None
		self._overlayItem = None
		self._overlayFollowUntil = 0
		self._overlayDoc = None

	def _holdOverlay(self, obj):
		"""The real window took the focus, for example after a click. Keep NVDA in the overlay, silently, and
		update it in place: the same window refreshes, a new window replaces the contents.
		Returns False if the overlay should close, because the user moved to another program."""
		from . import overlay
		doc = self._overlayDoc
		if isinstance(obj, overlay.OverlayDocument):
			return False
		if self._overlayLeft():
			self.overlayClosed()
			return False
		fg = api.getForegroundObject()
		# Escape goes back to the real control that has the focus now. Set first: NVDA builds the focus
		# ancestors from it.
		doc.parent = obj
		try:
			api.setFocusObject(doc)
		except Exception:
			log.debugWarning("VisionMate: could not keep the overlay", exc_info=True)
			self.overlayClosed()
			return False
		handle = _safe(lambda: fg.windowHandle)
		if handle != self._overlayWindow:
			self._retargetOverlay(doc, fg)
			self._overlayWindow = handle
		doc.recognizer.namesChanged()  # read the window again even if it looks the same
		doc.keepAlive()
		return True

	def _retargetOverlay(self, doc, fg):
		"""Point the overlay at a new window."""
		from contentRecog import RecogImageInfo
		loc = _windowBox(fg)
		recognizer = doc.recognizer
		recognizer.app = _safe(lambda: fg.appModule.appName) or "?"
		recognizer.title = _safe(lambda: fg.name) or ""
		try:
			doc.imageInfo = RecogImageInfo.createFromRecognizer(loc.left, loc.top, loc.width, loc.height, recognizer)
		except ValueError:
			return
		doc.newWindow()

	def _refreshOverlayNow(self, doc):
		if doc is self._overlayDoc and api.getFocusObject() is doc:
			doc.refreshNow()

	# --- Image sources ---

	@staticmethod
	def _grab(bbox=None):
		return curtain.capture(bbox)

	def _grabOrReport(self, bbox=None, quiet=False):
		"""Take a picture of the screen. Returns None, and unless quiet tells the user, if that is not possible."""
		try:
			return self._grab(bbox)
		except curtain.CurtainBlocked:
			if not quiet:
				ui.message(_curtainBlockedMessage())
			return None
		except Exception:
			log.error("VisionMate: could not capture the screen", exc_info=True)
			if quiet:
				return None
			# Translators: Reported when the screen could not be captured.
			ui.message(_("Could not take a picture of the screen."))
		return None

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_("Describes the current element. Press twice for a detailed description in a window."),
		gesture="kb:NVDA+alt+a",
	)
	def script_describeElement(self, gesture):
		obj = api.getNavigatorObject()
		# WinZapp never shows photos on screen; its photo messages are described from the photo itself.
		try:
			if obj and self._describeChatPhoto(obj):
				return
		except Exception:
			log.error("VisionMate: WinZapp photo failed", exc_info=True)
		# In an image viewer, the photo itself is described, unless a button is chosen.
		if obj and _safe(lambda: obj.role not in ICON_ROLES) and self._describeViewerImage():
			return
		# An image file in File Explorer or on the desktop: the file itself, without opening it.
		path = obj and _safe(lambda: self._explorerImage(obj))
		if path and self._describeFile(path, self._pressMode()):
			return
		loc = obj.location if obj else None
		if not loc or loc.width <= 0 or loc.height <= 0:
			# Translators: Reported when the current element has no position on screen.
			ui.message(_("This element has no location on screen."))
			return
		bbox = _bbox(loc)
		context = _windowContext() + [
			("element type", _safe(lambda: obj.role.displayString)),
			("element name", _safe(lambda: obj.name)),
		]
		image = self._grabOrReport(bbox)
		if image is None:
			return
		# A message with a photo, like in WhatsApp or Telegram: describe the photo, not the name and time around it.
		photo = _safe(lambda: self._photoIn(obj, bbox, image))
		if photo:
			self._describeMessagePhoto(image.crop(photo), self._pressMode(), _safe(lambda: obj.appModule.appName))
			return
		self._describe(image, self._pressMode(), context=context, screen=True)

	@staticmethod
	def _photoIn(obj, bbox, image):
		"""Where the photo is in a picture of a message, in image pixels, or None. The app's own picture element is
		used if it has one; otherwise the photo is found in the pixels."""
		if obj.role not in PHOTO_HOLDER_ROLES:
			return None
		best, seen, todo = None, 0, [(obj, 0)]
		while todo and seen < PHOTO_SEARCH_OBJECTS:
			current, depth = todo.pop(0)
			seen += 1
			children = current.children or ()
			if current is not obj and _isPhotoElement(current, children):
				loc = current.location
				if loc and min(loc.width, loc.height) >= imaging.PHOTO_MIN_SIDE:
					if best is None or loc.width * loc.height > best.width * best.height:
						best = loc
			if depth < PHOTO_SEARCH_DEPTH:
				todo.extend((child, depth + 1) for child in children)
		if best is not None:
			left, top = max(best.left, bbox[0]) - bbox[0], max(best.top, bbox[1]) - bbox[1]
			right = min(best.left + best.width, bbox[2]) - bbox[0]
			bottom = min(best.top + best.height, bbox[3]) - bbox[1]
			if right - left >= imaging.PHOTO_MIN_SIDE and bottom - top >= imaging.PHOTO_MIN_SIDE:
				return (left, top, right, bottom)
		return imaging.findPhoto(image)

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_("Describes the current window. Press twice for a detailed description in a window."),
		gesture="kb:NVDA+alt+w",
	)
	def script_describeWindow(self, gesture):
		if self._describeViewerImage():
			return
		image = self._grabOrReport(_bbox(_windowBox(api.getForegroundObject())))
		if image is not None:
			self._describe(image, self._pressMode(), context=_windowContext(), screen=True)

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_("Describes the whole screen. Press twice for a detailed description in a window."),
		gesture="kb:NVDA+alt+f",
	)
	def script_describeScreen(self, gesture):
		image = self._grabOrReport()
		if image is not None:
			self._describe(image, self._pressMode(), context=_windowContext(), screen=True)

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_(
			"Describes the image or image file on the clipboard. Press twice for a detailed description in a window."
		),
		gesture="kb:NVDA+alt+d",
	)
	def script_describeClipboard(self, gesture):
		from PIL import Image, ImageGrab
		try:
			content = ImageGrab.grabclipboard()
		except Exception:
			log.debugWarning("VisionMate: could not read clipboard", exc_info=True)
			content = None
		context = []
		if isinstance(content, list):
			for path in content:
				try:
					img = Image.open(path)
					img.load()
					content = img
					context = [("file name", os.path.basename(path))]
					break
				except Exception:
					continue
			else:
				content = None
		if content is None:
			# Translators: Reported when there is no image on the clipboard.
			ui.message(_("No image or image file on the clipboard."))
			return
		self._describe(content, self._pressMode(), context=context)


def _clean_paragraphs(text):
	return "\n".join(_clean(line) for line in text.splitlines() if _clean(line))


if globalVars.appArgs.secure:
	# Do not run on secure screens such as the Windows sign-in screen.
	GlobalPlugin = globalPluginHandler.GlobalPlugin  # noqa: F811
