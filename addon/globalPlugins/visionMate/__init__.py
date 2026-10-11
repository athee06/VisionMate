# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - fast, fully offline image description for NVDA.
# Images never leave the computer: a vision model runs locally through a bundled engine.

import collections
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time

import addonHandler
import api
import config
import globalPluginHandler
import globalVars
import gui
import languageHandler
import queueHandler
import scriptHandler
import speech
import tones
import ui
import wx
from controlTypes import OutputReason
from logHandler import log
from scriptHandler import script
from speech import extensions as speechExtensions

from . import autodescribe, datapack, dialogs, net, release
from .engine import Engine, EngineError, prepareImage

addonHandler.initTranslation()

CONF_SECTION = "visionMate"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.abspath(os.path.join(PLUGIN_DIR, "..", ".."))
ENGINE_DIR = os.path.join(ADDON_DIR, "engine")
# Kept outside the add-on folder so the data survives add-on updates.
DATA_DIR = os.path.join(globalVars.appArgs.configPath, "visionMate")
PACK_DIR = os.path.join(DATA_DIR, "data")
UPDATE_INTERVAL = 24 * 3600

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
# Modes of a description.
QUICK, DETAILED, AUTO = "quick", "detailed", "auto"
AUTO_CACHE_SIZE = 300

confspec = {
	"autoDescribe": "boolean(default=False)",
	"useGpu": "boolean(default=True)",
	"preload": "boolean(default=True)",
	"answerInNvdaLanguage": "boolean(default=True)",
	"progressBeeps": "boolean(default=True)",
	"autoUpdate": "boolean(default=True)",
	"lastUpdateCheck": "integer(default=0)",
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


def _speak(text):
	queueHandler.queueFunction(queueHandler.eventQueue, ui.message, text)


def _beep(hz, ms):
	queueHandler.queueFunction(queueHandler.eventQueue, tones.beep, hz, ms)


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
		self._updating = False
		self._hasData = datapack.installedVersion(PACK_DIR) > 0
		self._autoCache = collections.OrderedDict()
		self._autoGeneration = 0
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
		else:
			wx.CallLater(3000, self.showDataDialog)
		if conf()["autoUpdate"]:
			wx.CallLater(30000, self._autoCheckForUpdates)

	def terminate(self):
		self._cancel.set()
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

	def _describe(self, image, mode, cacheKey=None):
		self._cancel.set()
		if not self._dataReady():
			self.showDataDialog()
			return
		cancel = self._cancel = threading.Event()
		if mode != AUTO:
			tones.beep(880, 25)
		threading.Thread(
			target=self._worker, args=(image, mode, cancel, cacheKey), name="visionMate-describe", daemon=True,
		).start()

	def _worker(self, image, mode, cancel, cacheKey=None):
		c = conf()
		detailed = mode == DETAILED
		prompt = {QUICK: QUICK_PROMPT, DETAILED: DETAIL_PROMPT, AUTO: AUTO_PROMPT}[mode] + _languageInstruction()
		size = c["detailSize"] if detailed else c["quickSize"]
		maxTokens = {QUICK: 200, DETAILED: 600, AUTO: 80}[mode]
		# Beep until speech starts, or until the detailed description window opens.
		# Automatic descriptions stay quiet so reading is not cluttered.
		stopBeeps = threading.Event()
		if c["progressBeeps"] and mode != AUTO:
			threading.Thread(target=self._progressBeeps, args=(cancel, stopBeeps), daemon=True).start()
		# Translators: Spoken before an automatic description of an image without a label.
		speaker = None if detailed else SentenceSpeaker(cancel, prefix=_("Image: ") if mode == AUTO else "")
		window = dialogs.StreamingResult(onOpened=stopBeeps.set) if detailed else None

		def onText(delta):
			if speaker is not None:
				stopBeeps.set()
				speaker.feed(delta)
			else:
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
			if not cancel.is_set() and mode != AUTO:
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
		if not text:
			if mode != AUTO:
				# Translators: Reported when no description was produced.
				_speak(_("No description was produced."))
		elif detailed:
			window.finish(_clean_paragraphs(text))
		else:
			speaker.flush()

	@staticmethod
	def _progressBeeps(cancel, stop):
		while not stop.wait(1.0):
			if cancel.is_set():
				return
			_beep(440, 20)

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
		obj = autodescribe.findUnlabeledGraphic(info)
		if obj is not None:
			# Give browse mode a moment to scroll the image into view before taking its picture.
			wx.CallLater(150, self._autoCapture, obj, self._autoGeneration)

	def _autoCapture(self, obj, generation):
		if generation != self._autoGeneration or scriptHandler.isScriptWaiting():
			return
		loc = obj.location
		if not autodescribe.bigEnough(loc):
			return
		image = self._grab((loc.left, loc.top, loc.left + loc.width, loc.top + loc.height))
		key = hashlib.sha1(image.tobytes()).hexdigest()
		cached = self._autoCache.get(key)
		if cached:
			self._autoCache.move_to_end(key)
			# Translators: Spoken before an automatic description of an image without a label.
			ui.message(_("Image: ") + _clean(cached))
			return
		self._describe(image, AUTO, cacheKey=key)

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

	# --- Image sources ---

	@staticmethod
	def _grab(bbox=None):
		from PIL import ImageGrab
		return ImageGrab.grab(bbox=bbox, all_screens=True)

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_("Describes the current element. Press twice for a detailed description in a window."),
		gesture="kb:NVDA+alt+a",
	)
	def script_describeElement(self, gesture):
		obj = api.getNavigatorObject()
		loc = obj.location if obj else None
		if not loc or loc.width <= 0 or loc.height <= 0:
			# Translators: Reported when the current element has no position on screen.
			ui.message(_("This element has no location on screen."))
			return
		bbox = (loc.left, loc.top, loc.left + loc.width, loc.top + loc.height)
		self._describe(self._grab(bbox), self._pressMode())

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_("Describes the whole screen. Press twice for a detailed description in a window."),
		gesture="kb:NVDA+alt+f",
	)
	def script_describeScreen(self, gesture):
		self._describe(self._grab(), self._pressMode())

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
		if isinstance(content, list):
			for path in content:
				try:
					img = Image.open(path)
					img.load()
					content = img
					break
				except Exception:
					continue
			else:
				content = None
		if content is None:
			# Translators: Reported when there is no image on the clipboard.
			ui.message(_("No image or image file on the clipboard."))
			return
		self._describe(content, self._pressMode())

	# --- Updates ---

	def _autoCheckForUpdates(self):
		if time.time() - conf()["lastUpdateCheck"] >= UPDATE_INTERVAL:
			self.checkForUpdates(manual=False)

	def checkForUpdates(self, manual=True):
		if self._updating:
			return

		def run():
			try:
				manifest = net.fetchJson(release.UPDATE_URL)
			except (OSError, ValueError):
				log.debugWarning("VisionMate: update check failed", exc_info=True)
				if manual:
					# Translators: Reported when the update check fails.
					_speak(_("Could not check for updates. Check your internet connection."))
				return
			conf()["lastUpdateCheck"] = int(time.time())
			wx.CallAfter(self._handleManifest, manifest, manual)

		threading.Thread(target=run, name="visionMate-update", daemon=True).start()

	def _handleManifest(self, manifest, manual):
		current = addonHandler.getCodeAddon().manifest["version"]
		addonInfo = manifest.get("addon") or {}
		dataInfo = manifest.get("data") or {}
		if addonInfo.get("version") and release.isNewer(addonInfo["version"], current):
			self._offerAddonUpdate(addonInfo, current)
		elif dataInfo.get("version", 0) > datapack.installedVersion(PACK_DIR) > 0:
			self.showDataDialog(dataInfo, isUpdate=True)
		elif manual:
			# Translators: Reported when no update is available. {version} is the installed version.
			ui.message(_("VisionMate {version} is up to date.").format(version=current))

	def _offerAddonUpdate(self, info, current):
		# Translators: Asks to install an update. {new} and {current} are versions, {changes} the release notes.
		message = _(
			"VisionMate {new} is available. You have version {current}.\n\n{changes}\n\nDownload and install it now?"
		).format(new=info["version"], current=current, changes=info.get("changes", "")).replace("\n\n\n\n", "\n\n")
		# Translators: Title of the update dialog.
		dlg = wx.MessageDialog(gui.mainFrame, message, _("VisionMate update"), wx.YES_NO | wx.ICON_INFORMATION)
		gui.mainFrame.prePopup()
		try:
			answer = dlg.ShowModal()
		finally:
			dlg.Destroy()
			gui.mainFrame.postPopup()
		if answer != wx.ID_YES:
			return
		self._updating = True
		# Translators: Reported when the update download starts.
		ui.message(_("Downloading the VisionMate update."))

		def run():
			path = os.path.join(tempfile.gettempdir(), f"VisionMate-{info['version']}.nvda-addon")
			try:
				net.download(info["url"], path, info.get("size"), info.get("sha256"))
			except (OSError, ValueError) as e:
				log.error("VisionMate: update download failed", exc_info=True)
				# Translators: Reported when the update download fails. {error} is the reason.
				_speak(_("The update could not be downloaded: {error}").format(error=e))
				self._updating = False
				return
			wx.CallAfter(self._installUpdate, path)

		threading.Thread(target=run, name="visionMate-update", daemon=True).start()

	def _installUpdate(self, path):
		from gui import addonGui
		try:
			if addonGui.installAddon(gui.mainFrame, path):
				addonGui.promptUserForRestart()
		finally:
			self._updating = False


def _clean_paragraphs(text):
	return "\n".join(_clean(line) for line in text.splitlines() if _clean(line))


if globalVars.appArgs.secure:
	# Do not run on secure screens such as the Windows sign-in screen.
	GlobalPlugin = globalPluginHandler.GlobalPlugin  # noqa: F811
