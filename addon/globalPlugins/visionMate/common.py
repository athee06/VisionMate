# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - fast, fully offline image description for NVDA.
# Images never leave the computer: a vision model runs locally through a bundled engine.

"""Settings, constants and small helpers shared by the plugin and its parts."""
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

from . import autodescribe, colours, curtain, datapack, dialogs, explorer, findonscreen, followup, hardware, imaging, labels, localmedia, ocr, questions, sounds, viewers, winzapp
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
# After the graphics card fails this many requests in a row, descriptions use the processor instead.
GPU_FAILURES_BEFORE_CPU = 2
# Freeing memory: when Windows has less than this left, VisionMate gives its memory back after a short pause.
LOW_MEMORY_GB = 1.5
LOW_MEMORY_IDLE_SECONDS = 60
# Without "Get ready when NVDA starts", the memory is given back after this long unused.
NO_PRELOAD_IDLE_SECONDS = 10 * 60
# PCs with this much memory or less (Windows reports a 16 GB PC as a little under 16) free it even with "Get ready"
# after this long unused.
SMALL_MEMORY_GB = 16.5
SMALL_MEMORY_IDLE_SECONDS = 30 * 60
# After freeing for low memory, VisionMate gets ready again once this much is free.
RELOAD_MEMORY_GB = 6
# Without "Get ready", the engine still loads this long after NVDA starts, on PCs with at least this much memory.
EARLY_LOAD_DELAY_MS = 15000
EARLY_LOAD_TOTAL_GB = 16

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
# Squares of a picture puzzle (a check that asks whether you are a person), named a few at a time.
TILE_PROMPT = "This is one square of a picture puzzle. In 1 to 4 words, what does it show? Answer with the words only."
TILE_SHEET_PROMPT = (
	"This picture shows {count} numbered squares of a picture puzzle. For each number, say what the square shows in "
	"1 to 4 words, like bus, traffic light, part of a bicycle or nothing clear. Answer one per line as: number: words"
)
TILE_SIZE = 128
ICON_SHEET_LINE = re.compile(r"^\s*(\d+)\s*[:.)-]\s*(.+)$", re.MULTILINE)
SHEET_SIZE = 512
# Icons named together in one background picture. The engine can't stop while it reads a picture, so a key press
# waits for the one being read: a sheet of 4 adds about 0.4 s to the user's next description, a sheet of 16 about 1.3 s.
BACKGROUND_SHEET_ICONS = 4
# Follow-up questions must be about the image; see followup.py. Refused questions get no reply.
NOT_IMAGE = followup.NOT_IMAGE
# Questions and answers kept in a conversation, so it fits in the engine's memory.
FOLLOWUP_HISTORY = 3
# Screen pictures with less text than this are photos. They are sent a little smaller, which is faster.
PHOTO_MAX_OCR_CHARS = 20
PHOTO_SIZE_FACTOR = 0.875
# A detailed description this soon after a quick one is a second press, and reuses its picture.
REUSE_PICTURE_SECONDS = 2
# "Still working" is said when a description has not started after this long (the default of the setting), then
# again this often.
STILL_WORKING_SECONDS = 5
STILL_WORKING_REPEAT_SECONDS = 10
# A quick description this soon after the last one reuses its picture when the screen barely changed.
REUSE_SIMILAR_SECONDS = 30
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
# Find on screen: the longest wait for the window to be read, and the pauses before and after the click.
FIND_WAIT_SECONDS = 8
FIND_ACT_DELAY_MS = 400
FIND_CLICK_SETTLE_MS = 300
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
	# 6.0: seconds of waiting before "Still working" (0 = never), help offers, the game controller, VisionMate's voice.
	"statusSeconds": "integer(default=5, min=0, max=60)",
	"helpOffer": "boolean(default=True)",
	"helpMuted": "string(default='')",
	"controller": "string(default='announce')",
	"voicePitch": "integer(default=0, min=-50, max=50)",
	"voiceRate": "integer(default=0, min=-50, max=50)",
	"voiceVolume": "integer(default=0, min=-50, max=50)",
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
		log.debug(f"VisionMate: {getattr(fn, '__name__', 'call')} failed")
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
	queueHandler.queueFunction(queueHandler.eventQueue, _say, text)


def _voice():
	"""VisionMate's own voice: (pitch, rate, volume) changes from NVDA's voice, each -50 to 50."""
	c = conf()
	try:
		return c["voicePitch"], c["voiceRate"], c["voiceVolume"]
	except KeyError:
		return 0, 0, 0


def _say(text):
	"""Say a description or answer, in VisionMate's own voice when one is set. Braille shows it as usual."""
	pitch, rate, volume = _voice()
	if not (pitch or rate or volume):
		ui.message(text)
		return
	try:
		from speech.commands import PitchCommand, RateCommand, VolumeCommand
		speech.speak([PitchCommand(offset=pitch), RateCommand(offset=rate), VolumeCommand(offset=volume), text])
	except Exception:
		log.debugWarning("VisionMate: could not speak with its own voice", exc_info=True)
		ui.message(text)
		return
	try:
		import braille
		braille.handler.message(text)
	except Exception:
		log.debug("VisionMate: no braille message")


def _sound(name):
	queueHandler.queueFunction(queueHandler.eventQueue, sounds.play, name)


def _cleanLeftovers(folders):
	"""Remove half-written .tmp files that VisionMate left in its own folders when NVDA stopped mid-write.
	The partial download (.part) is kept so the download can resume."""
	for folder in folders:
		try:
			names = os.listdir(folder)
		except OSError:
			continue
		for name in names:
			if name.endswith(".tmp"):
				try:
					os.remove(os.path.join(folder, name))
					log.debugWarning(f"VisionMate: removed leftover {name}")
				except OSError:
					log.debugWarning(f"VisionMate: could not remove leftover {name}", exc_info=True)


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



def _clean_paragraphs(text):
	return "\n".join(_clean(line) for line in text.splitlines() if _clean(line))


# Everything here, including names starting with _, is shared with the plugin's other modules.
__all__ = [n for n in dir() if not n.startswith("__")]
