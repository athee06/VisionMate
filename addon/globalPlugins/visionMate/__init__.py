# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - fast, fully offline image description for NVDA.
# Images never leave the computer: a vision model runs locally through a bundled engine.

import addonHandler
import globalPluginHandler

from .common import *  # noqa: F401,F403
from .background import BackgroundMixin
from .autoimages import AutoImagesMixin
from .photos import PhotosMixin
from .overlayglue import OverlayMixin
from .assist import AssistMixin
from .actions import ActionsMixin
from .pointermode import PointerMixin
from .controller import ControllerMixin


# The parts live in their own modules; scripts (key commands) stay here so NVDA binds their gestures.
class GlobalPlugin(BackgroundMixin, AutoImagesMixin, PhotosMixin, OverlayMixin, AssistMixin,
		ActionsMixin, PointerMixin, ControllerMixin, globalPluginHandler.GlobalPlugin):
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
		# Failed requests on the graphics card in a row; at GPU_FAILURES_BEFORE_CPU the processor is used.
		self._gpuFailures = 0
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
		total = hardware.memoryGb()
		self._smallMemory = total is not None and total <= SMALL_MEMORY_GB
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
		self._lastFind = None
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
		self._initAssist()
		self._initActions()
		self._initPointer()
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
				wx.CallLater(EARLY_LOAD_DELAY_MS, self._earlyLoad)
			# Add-on updates come from the Add-on Store; one that needs newer vision data offers it here.
			bundled = _bundledDataInfo()
			if bundled and bundled.get("version", 0) > datapack.installedVersion(PACK_DIR):
				wx.CallLater(3000, self.showDataDialog, bundled, True)
		else:
			wx.CallLater(3000, self.showDataDialog)
		threading.Thread(target=_cleanLeftovers, args=([DATA_DIR, PACK_DIR],), name="visionMate-cleanup",
			daemon=True).start()
		threading.Thread(target=self._unloadWhenIdle, name="visionMate-idle", daemon=True).start()
		threading.Thread(target=self._backgroundLoop, name="visionMate-background", daemon=True).start()
		self._initController()

	def terminate(self):
		self._stopped.set()
		self._cancel.set()
		self._actionCancel.set()
		self._inputMode = None
		self._controllerMode = False
		self._restoreMouseTracking()
		if self._holding:
			from . import inputs
			inputs.release()
			self._holding = False
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

	def _engineFailed(self):
		"""The engine stopped or failed during a request (graphics driver reset, out of memory). The next
		request starts it again; after the graphics card fails twice in a row, the processor is used instead."""
		usedGpu = self._engine.usingGpu
		crashed = not self._engine.running
		log.warning(f"VisionMate: engine failed during a request (stopped: {crashed}, GPU: {usedGpu})", exc_info=True)
		self._engine.stop()
		if usedGpu:
			self._gpuFailures += 1
			if self._gpuFailures >= GPU_FAILURES_BEFORE_CPU:
				log.warning("VisionMate: the graphics card failed twice; using the processor from now on")
				self._gpuFailed = True

	def _startEngineInBackground(self):
		def run():
			try:
				self._ensureEngine()
			except EngineError:
				log.error("VisionMate: could not start the engine", exc_info=True)

		threading.Thread(target=run, name="visionMate-preload", daemon=True).start()

	def _earlyLoad(self):
		"""Without "Get ready", load the engine anyway a little after NVDA starts on PCs with memory to spare, so the
		first description is fast. Like any unused engine without "Get ready", it is freed after 10 idle minutes."""
		if self._stopped.is_set() or conf()["preload"] or not self._dataReady() or self._busy or self._engine.running:
			return
		total, free = hardware.memoryGb(), hardware.freeMemoryGb()
		if total is None or free is None or total < EARLY_LOAD_TOTAL_GB or free < RELOAD_MEMORY_GB:
			log.debug(f"VisionMate: not loading early (memory {total} GB, free {free} GB)")
			return
		log.debug("VisionMate: loading early so the first description is fast")
		self._lastUse = time.monotonic()
		self._startEngineInBackground()

	def _unloadWhenIdle(self):
		"""Gives the memory back when Windows runs low, or after a while unused if the user did not ask
		VisionMate to stay ready. Gets ready again once memory is free, if it should stay ready."""
		while not self._stopped.wait(IDLE_CHECK_SECONDS):
			try:
				free = hardware.freeMemoryGb()
			except Exception:
				log.debugWarning("VisionMate: could not read free memory", exc_info=True)
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
				elif self._smallMemory and idle >= SMALL_MEMORY_IDLE_SECONDS:
					# Even with "Get ready", PCs with 16 GB or less get the memory back after a long idle time.
					log.debug("VisionMate: freeing memory after 30 idle minutes on a PC with little memory")
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
		self._dataDialog = dialogs.DataDialog(gui.mainFrame, info, PACK_DIR, self._onDataInstalled, isUpdate,
			installPortable=self.installPortable)
		dialogs.show(self._dataDialog)

	# --- Describing ---

	def _onSpeechCanceled(self):
		# Control (or anything else that silences NVDA) also stops a spoken description.
		if self._speakingCancel is not None:
			self._speakingCancel.set()

	def _describe(self, image, mode, cacheKey=None, context=(), screen=False, onDone=None, what=None):
		"""Describe a picture in the background. screen means it shows part of the screen, so OCR helps.
		onDone(text) is called with the result of an icon description, and onDone(text, mode) with any other.
		what says what is described, for NVDA+Alt+P, like "describing the screen"."""
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
			# Pressing again soon on a picture that did not really change sends the same picture, so the engine's
			# work on it is reused: speech starts in about 0.4 s instead of 2.
			last = self._lastQuick
			if (last and now - last[0] < REUSE_SIMILAR_SECONDS and last[2] == screen
					and imaging.nearlySame(last[1], image)):
				image = last[1]
			self._lastQuick = (now, image, screen)
		elif mode == DETAILED and self._lastQuick and now - self._lastQuick[0] < REUSE_PICTURE_SECONDS:
			image, screen = self._lastQuick[1], self._lastQuick[2]
		if mode != QUICK:
			self._lastQuick = None
		if mode not in (AUTO, ICON):
			sounds.play("detailed" if mode == DETAILED else "quick")
			# Translators: What VisionMate is doing, said by NVDA+Alt+P, when nothing more exact is known.
			self._startTask(what or _("describing a picture"), cancel)
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
			self._endTask(cancel)

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
				self._taskStage(cancel, "text")
				lines = ocr.recognize(image)
				if cancel.is_set():
					return
				textPart = ocr.promptPart(lines)
				if len(ocr.linesText(lines).strip()) < PHOTO_MAX_OCR_CHARS:
					size = int(size * PHOTO_SIZE_FACTOR)
		ins = self.instructions
		if mode == ICON:
			size = ICON_SIZE
			prompt = _contextPrompt(context) + ins.get("icon", ICON_PROMPT) + _languageInstruction()
		else:
			asked = mode in (QUICK, DETAILED)
			prompt = (
				_contextPrompt(context) + (self._userPromptPart() if asked else "") + textPart
				+ {QUICK: ins.get("quick", QUICK_PROMPT), DETAILED: ins.get("detailed", DETAIL_PROMPT),
					AUTO: ins.get("auto", AUTO_PROMPT)}[mode]
				+ " " + ins.get("honesty", HONESTY.strip()) + (ins.own() if asked else "") + _languageInstruction()
			)
		maxTokens = {QUICK: 200, DETAILED: 600, AUTO: 80, ICON: 8}[mode]
		# Beep until speech starts, or until the detailed description window opens.
		# Automatic descriptions stay quiet so reading is not cluttered.
		stopBeeps = threading.Event()
		if not quiet:
			threading.Thread(target=self._progressBeeps, args=(cancel, stopBeeps, c["progressBeeps"]),
				daemon=True).start()
		# Translators: Spoken before an automatic description of an image without a label.
		prefix = {AUTO: _("Image: ")}.get(mode, "")
		speaker = None if detailed or mode == ICON else SentenceSpeaker(cancel, prefix=prefix)
		conversation = {"start": None, "history": [], "image": image}
		# Translators: Button in the description window that reads all the text in the image with Windows OCR.
		readText = (_("Read all &text"), lambda dialog: self._readAllText(image, dialog))
		window = dialogs.StreamingResult(
			onOpened=stopBeeps.set,
			onAsk=lambda question, dialog, trusted=False: self._askFollowUp(conversation, question, dialog, trusted),
			actions=[readText],
		) if detailed else None

		self._taskStage(cancel, "looking")

		def onText(delta):
			self._taskStage(cancel, "speaking")
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
					self._gpuFailures = 0
					break
				except EngineError:
					# Only a stopped engine, or a failure on the graphics card, is worth a restart.
					if (attempt or cancel.is_set() or (speaker and speaker.spokeAnything)
							or (self._engine.running and not self._engine.usingGpu)):
						raise
					self._engineFailed()
					if not quiet:
						# Translators: Reported when the description engine stopped and was started again.
						_speak(_("VisionMate restarted"))
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

	def _readAllText(self, image, dialog):
		"""Read every bit of text in the picture with Windows OCR, exactly as written, into the window."""
		sounds.play("send")

		def run():
			lines = ocr.recognize(image)
			text = ocr.rowsText(lines).strip() if lines else ""
			if lines is None:
				# Translators: Reported when Windows OCR can't run, for example when no OCR language is installed.
				text = _("Windows OCR is not available.")
			elif not text:
				# Translators: Reported when the image has no text.
				text = _("No text found.")
			_sound("receive")
			_speak(text.splitlines()[0])
			# Translators: Title above the text read from the image.
			wx.CallAfter(dialog.addSection, _("Text in the image:"), text)

		threading.Thread(target=run, name="visionMate-ocr", daemon=True).start()

	def _askFollowUp(self, conversation, question, dialog, trusted=False):
		sounds.play("send")
		if not trusted and self._memoryCommand(question, dialog):
			return
		if not trusted and followup.clearlyOffTopic(question):
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
		# Translators: What VisionMate is doing, said by NVDA+Alt+P.
		self._startTask(_("answering your question"), cancel)
		threading.Thread(
			target=self._answer, args=(conversation, question, dialog, cancel, trusted), name="visionMate-describe",
			daemon=True,
		).start()

	@staticmethod
	def _declineQuestion(question, dialog):
		"""Say plainly that only questions about the image are answered, so silence is never mistaken for a hang."""
		# Translators: Reply to a question that is not about the described image.
		reply = _("I can only answer questions about this image.")
		_sound("receive")
		_speak(reply)
		wx.CallAfter(dialog.addAnswer, question, reply)

	def _answer(self, conversation, question, dialog, cancel, trusted=False):
		try:
			self._answerParts(conversation, question, dialog, cancel, trusted)
		finally:
			self._endTask(cancel)

	def _answerParts(self, conversation, question, dialog, cancel, trusted=False):
		"""A question in several parts, like "what is in it, and is there any text", is asked one part at a time,
		each with the rule of its kind. A question about colours first gets the colours measured from the pixels."""
		parts = [question] if trusted else questions.split(question) or [question]
		measured = ""
		if any(questions.kind(p) == "colour" for p in parts) and conversation.get("image") is not None:
			try:
				measured = colours.sentence(colours.mainColours(conversation["image"]))
			except Exception:
				log.debugWarning("VisionMate: could not measure colours", exc_info=True)
		if measured:
			_sound("receive")
			_speak(measured)
		answers = []
		for i, part in enumerate(parts):
			if cancel.is_set():
				break
			answer = self._answerOne(conversation, part, cancel, trusted or i > 0, checkQuestion=question)
			if answer is False:
				self._declineQuestion(question, dialog)
				return
			if answer:
				answers.append(answer)
		text = " ".join(answers) or None
		if text and measured:
			text = measured + " " + text
		wx.CallAfter(dialog.addAnswer, question, text)

	def _answerOne(self, conversation, question, cancel, trusted=False, checkQuestion=None):
		"""Answer one question. Returns the answer, None if there was none, or False if it is not about the image."""
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
				# Questions from the window's quick buttons are about the image, so they skip the check.
				check = "yes" if trusted else self._engine.chat(
					messages + [{"role": "user", "content": followup.CHECK.format(question=checkQuestion or question)}], 2,
					cancel=cancel,
				)
				if check is not None and not check.strip().lower().startswith("yes"):
					declined = True
				elif check is not None and not cancel.is_set():
					self._taskStage(cancel, "looking")
					answer = self._engine.chat(
						messages + [{"role": "user", "content": self._userPromptPart() + questions.withRule(question)
							+ followup.ANSWER + self.instructions.own()}], 150, onText, cancel,
					)
		except EngineError as e:
			log.error("VisionMate: follow-up question failed", exc_info=True)
			if not self._engine.running or self._engine.usingGpu:
				self._engineFailed()  # the next question starts the engine again
			if not cancel.is_set():
				# Translators: Reported when a question about the image could not be answered. {error} is the reason.
				_speak(_("Could not answer the question: {error}").format(error=e))
		finally:
			if self._speakingCancel is cancel:
				self._speakingCancel = None
		if declined or refused.is_set() or (answer and answer.strip().upper().startswith(NOT_IMAGE)):
			return False
		if not answer:
			return None
		if not state["open"]:
			_sound("receive")
			speaker.feed(state["held"])
		speaker.flush()
		answer = _clean(answer)
		conversation["history"] = (conversation["history"] + [(question, answer)])[-FOLLOWUP_HISTORY:]
		return answer

	# --- Automatic descriptions of unlabeled images ---

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

	# --- Naming buttons and items yourself, and the automatic icon labeler ---

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
				log.debug("VisionMate: no caret offset in the overlay")
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

	# --- The overlay for inaccessible windows ---

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

	@script(
		# Translators: Description of a command in Input Gestures.
		description=_(
			"Finds something in the current window, like the Save button: says roughly where it is and offers to "
			"click it or move the mouse there"
		),
		gesture="kb:NVDA+alt+e",
	)
	def script_findOnScreen(self, gesture):
		self.findOnScreen()

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
		# Translators: What VisionMate is doing, said by NVDA+Alt+P.
		self._describe(image, self._pressMode(), context=context, screen=True, what=_("describing the element"))

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
			# Translators: What VisionMate is doing, said by NVDA+Alt+P.
			self._describe(image, self._pressMode(), context=_windowContext(), screen=True, what=_("describing the window"))

	@script(
		# Translators: Description of a command in the Input Gestures dialog.
		description=_("Describes the whole screen. Press twice for a detailed description in a window."),
		gesture="kb:NVDA+alt+f",
	)
	def script_describeScreen(self, gesture):
		image = self._grabOrReport()
		if image is not None:
			# Translators: What VisionMate is doing, said by NVDA+Alt+P.
			self._describe(image, self._pressMode(), context=_windowContext(), screen=True, what=_("describing the screen"))

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
					log.debugWarning(f"VisionMate: clipboard file is not a picture: {path}", exc_info=True)
					continue
			else:
				content = None
		if content is None:
			# Translators: Reported when there is no image on the clipboard.
			ui.message(_("No image or image file on the clipboard."))
			return
		# Translators: What VisionMate is doing, said by NVDA+Alt+P.
		self._describe(content, self._pressMode(), context=context, what=_("describing the clipboard"))

	# --- Stop, how far, help, pointer and controller modes, the newest picture ---

	@script(
		# Translators: Description of a command in Input Gestures.
		description=_("Stops a description or an answer that is still coming, or a held mouse button"),
		gesture="kb:NVDA+alt+x",
	)
	def script_stop(self, gesture):
		self.stopAll()

	@script(
		# Translators: Description of a command in Input Gestures.
		description=_("Says how far VisionMate is with a description or an answer"),
		gesture="kb:NVDA+alt+p",
	)
	def script_status(self, gesture):
		self.sayStatus()

	@script(
		# Translators: Description of a command in Input Gestures.
		description=_(
			"Takes the help VisionMate offers where a window, dialog or control tells NVDA little. Press twice for no "
			"more offers in this program, or to have them back"
		),
		gesture="kb:NVDA+alt+y",
	)
	def script_takeHelp(self, gesture):
		self.takeHelp(scriptHandler.getLastScriptRepeatCount() > 0)

	@script(
		# Translators: Description of a command in Input Gestures.
		description=_(
			"Pointer mode: the arrow keys move the mouse pointer, Enter clicks, Space holds the button for dragging, "
			"A opens more actions, G switches to the game mouse, Escape leaves"
		),
		gesture="kb:NVDA+alt+u",
	)
	def script_pointerMode(self, gesture):
		self.setPointerMode(self._inputMode != "pointer")

	@script(
		# Translators: Description of a command in Input Gestures.
		description=_("Controller mode: a connected game controller works the mouse pointer in any window"),
		gesture="kb:NVDA+alt+q",
	)
	def script_controllerMode(self, gesture):
		self.setControllerMode(not self._controllerMode)

	@script(
		# Translators: Description of a command in Input Gestures.
		description=_(
			"Describes the newest picture in a chat, leaving out emoji and the little pictures next to names. "
			"Press twice for a detailed description in a window."
		),
		gesture="kb:NVDA+alt+shift+a",
	)
	def script_newestPicture(self, gesture):
		self.describeNewestPicture(self._pressMode())




if globalVars.appArgs.secure:
	# Do not run on secure screens such as the Windows sign-in screen.
	GlobalPlugin = globalPluginHandler.GlobalPlugin  # noqa: F811
