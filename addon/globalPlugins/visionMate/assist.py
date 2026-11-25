# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Help around the descriptions: stopping (NVDA+Alt+X) and hearing how far a description is (NVDA+Alt+P), help
offered where a place tells NVDA little (NVDA+Alt+Y), the newest picture in a chat, memories typed in the question
box, and the portable copy."""
import addonHandler

from .common import *  # noqa: F401,F403
from . import helpoffer, memories, portable

addonHandler.initTranslation()

# Help offers wait until the focus stays this long.
HELP_DELAY_MS = 1200
# How many objects of a window are looked at, at most, to count its named controls and to find pictures.
HELP_WALK_OBJECTS = 80
PICTURE_WALK_OBJECTS = 600
PICTURE_MIN_SIDE = 80
DIALOG_ROLE_NAMES = ("DIALOG", "PROPERTYPAGE")


def _roleName(obj):
	role = _safe(lambda: obj.role)
	return getattr(role, "name", str(role or "")).upper()


class AssistMixin:
	def _initAssist(self):
		self._task = None
		self._helpGeneration = 0
		self._helpOffered = set()
		self._helpPending = None
		self.memories = memories.Memories(os.path.join(DATA_DIR, "memories.json"))
		self.instructions = memories.Instructions(os.path.join(DATA_DIR, "instructions.json"))

	# --- How far, and stop ---

	def _startTask(self, what, cancel):
		self._task = {"what": what, "start": time.monotonic(), "cancel": cancel, "stage": "start"}

	def _taskStage(self, cancel, stage):
		task = self._task
		if task is not None and task["cancel"] is cancel:
			task["stage"] = stage

	def _endTask(self, cancel):
		if self._task is not None and self._task["cancel"] is cancel:
			self._task = None

	def statusText(self):
		task = self._task
		if task is None or task["cancel"].is_set():
			# Translators: Said by NVDA+Alt+P when VisionMate is not working on anything.
			return _("VisionMate is not working on anything.")
		seconds = int(time.monotonic() - task["start"])
		stages = {
			# Translators: What a description is at, said by NVDA+Alt+P.
			"start": _("getting ready") if not self._engine.running else _("looking at the picture"),
			"text": _("reading the text with OCR"),
			"looking": _("looking at the picture"),
			"speaking": _("the answer is coming"),
		}
		# Translators: Said by NVDA+Alt+P. {what} is like "describing the screen", {seconds} a number, {stage} what
		# it is at now.
		return _("{what}, {seconds} seconds so far: {stage}.").format(
			what=task["what"], seconds=seconds, stage=stages.get(task["stage"], stages["looking"]))

	def sayStatus(self):
		ui.message(self.statusText())

	def stopAll(self):
		"""Stop a description, an answer or a held button."""
		stopped = False
		task = self._task
		if task is not None and not task["cancel"].is_set():
			task["cancel"].set()
			stopped = True
		if not self._actionCancel.is_set():
			self._actionCancel.set()
			stopped = True
		self._task = None
		speech.cancelSpeech()
		ui.message(
			# Translators: Reported when NVDA+Alt+X stopped something.
			_("Stopped") if stopped
			# Translators: Reported when NVDA+Alt+X is pressed and nothing is running.
			else _("Nothing to stop"))

	# --- Help offered where a place tells NVDA little ---

	def _scheduleHelpOffer(self, obj):
		self._helpGeneration += 1
		self._helpPending = None
		try:
			if not conf()["helpOffer"]:
				return
		except KeyError:
			return
		wx.CallLater(HELP_DELAY_MS, self._checkHelpOffer, obj, self._helpGeneration)

	def _mutedApps(self):
		try:
			return {a for a in conf()["helpMuted"].split(",") if a}
		except KeyError:
			return set()

	def _checkHelpOffer(self, obj, generation):
		if generation != self._helpGeneration or self._overlayDoc is not None or self._inputMode:
			return
		try:
			why = self._helpReason(obj)
		except Exception:
			log.debugWarning("VisionMate: help offer check failed", exc_info=True)
			return
		if why is None or (why == "unnamed" and conf()["iconLabeler"]):
			return  # button names already name it by themselves
		fg = api.getForegroundObject()
		app = _safe(lambda: obj.appModule.appName) or ""
		if app in self._mutedApps():
			return
		key = helpoffer.offerKey(app, _safe(lambda: fg.windowHandle), why)
		if key in self._helpOffered:
			self._helpPending = (why, obj)
			return
		self._helpOffered.add(key)
		self._helpPending = (why, obj)
		messages = {
			# Translators: Offers of help, said once per window.
			"window": _("This window tells NVDA little. NVDA+Alt+Y shows it as a list, on its most useful item."),
			"nofocus": _("Nothing has the focus in this dialog. NVDA+Alt+Y puts you on its most useful item."),
			"unnamed": _("This has no name. NVDA+Alt+Y names it from its picture."),
		}
		ui.message(messages[why])

	def _helpReason(self, obj):
		fg = api.getForegroundObject()
		if obj is None or fg is None:
			return None
		role = _roleName(obj)
		loc = _safe(lambda: fg.location)
		size = (loc.width, loc.height) if loc else (0, 0)
		inDialog = _roleName(fg) in DIALOG_ROLE_NAMES
		focusIsWindow = obj == fg
		named = 0
		if role in helpoffer.CONTAINERS:
			named = self._countNamed(fg)
		return helpoffer.reason(role, _safe(lambda: obj.name), focusIsWindow, size, named, inDialog)

	@staticmethod
	def _countNamed(fg):
		named, seen, todo = 0, 0, [fg]
		while todo and seen < HELP_WALK_OBJECTS and named <= helpoffer.MAX_NAMED:
			current = todo.pop(0)
			seen += 1
			if current is not fg and (_safe(lambda: current.name) or "").strip() and \
					_roleName(current) not in helpoffer.CONTAINERS:
				named += 1
			todo.extend(_safe(lambda: current.children) or ())
		return named

	def takeHelp(self, repeat):
		fg = api.getForegroundObject()
		app = _safe(lambda: fg.appModule.appName) or ""
		if repeat:
			muted = self._mutedApps()
			if app in muted:
				muted.discard(app)
				# Translators: Reported when help offers are turned back on for a program.
				message = _("Help offers back on in {app}").format(app=app)
			else:
				muted.add(app)
				# Translators: Reported when help offers are turned off for a program.
				message = _("No more help offers in {app}. Press NVDA+Alt+Y twice there to have them back.").format(app=app)
			conf()["helpMuted"] = ",".join(sorted(muted))
			ui.message(message)
			return
		pending = self._helpPending
		if pending is not None and pending[0] == "unnamed":
			obj = pending[1]
			image = self._buttonImage(obj)
			if image is not None:
				self._focusGeneration += 1
				self._labelFocusedButton(obj, self._focusGeneration)
				return
		self.openOverlay(best=True)

	# --- The newest picture in a chat ---

	def _newestPicture(self, fg):
		best, seen, todo = None, 0, [fg]
		while todo and seen < PICTURE_WALK_OBJECTS:
			current = todo.pop(0)
			seen += 1
			children = _safe(lambda: current.children) or ()
			if current is not fg and _isPhotoElement(current, children):
				loc = _safe(lambda: current.location)
				if loc and min(loc.width, loc.height) >= PICTURE_MIN_SIDE:
					key = (loc.top + loc.height, loc.width * loc.height)
					if best is None or key > best[0]:
						best = (key, current)
			todo.extend(children)
		return best[1] if best else None

	def describeNewestPicture(self, mode):
		"""The newest picture in a chat: the lowest picture in the window that is bigger than emoji and the little
		faces next to names. It is brought into view, cut out and described."""
		fg = api.getForegroundObject()
		obj = self._newestPicture(fg)
		if obj is None:
			image = self._grabOrReport(_bbox(_windowBox(fg)))
			box = imaging.findPhoto(image) if image is not None else None
			if box is None:
				# Translators: Reported when no picture was found in the window.
				ui.message(_("No picture found in this window."))
				return
			self._describe(image.crop(box), mode, context=_windowContext() + [("shown", "the newest picture in a chat")],
				what=_("describing the newest picture"))
			return
		_safe(lambda: obj.scrollIntoView())

		def describe():
			loc = _safe(lambda: obj.location)
			if not loc:
				ui.message(_("This element has no location on screen."))
				return
			image = self._grabOrReport(_bbox(loc))
			if image is not None:
				self._describe(image, mode, context=_windowContext() + [("shown", "the newest picture in a chat")],
					what=_("describing the newest picture"))

		wx.CallLater(300, describe)

	# --- Memories typed in the question box ---

	def _memoryCommand(self, question, dialog):
		"""Handle "remember that...", "forget...", "what do you remember". Returns True if it was one."""
		found = memories.command(question)
		if found is None:
			return False
		what, value = found
		if what == "remember":
			fact = self.memories.add(value)
			# Translators: Reply when a memory was kept. {fact} is the user's words.
			reply = _("I will remember: {fact}").format(fact=fact)
		elif what == "recall":
			items = self.memories.items
			# Translators: Reply listing what VisionMate remembers.
			reply = (_("I remember: {items}").format(items=" ".join(items)) if items
				# Translators: Reply when nothing is remembered.
				else _("I do not remember anything about you yet."))
		elif what == "forgetAll":
			self.memories.clear()
			# Translators: Reply after all memories were removed.
			reply = _("I forgot everything you asked me to remember.")
		else:
			removed = self.memories.forget(value)
			# Translators: Reply after memories were removed. {items} is what was removed.
			reply = (_("Forgotten: {items}").format(items=" ".join(removed)) if removed
				# Translators: Reply when nothing matched what to forget.
				else _("I do not remember anything like that."))
		_sound("receive")
		_speak(reply)
		wx.CallAfter(dialog.addAnswer, question, reply)
		return True

	def _userPromptPart(self):
		"""Memories and the user's own instruction, for descriptions and answers the user asked for."""
		return self.memories.promptPart()

	# --- Portable copy ---

	def makePortable(self):
		from . import moredialogs
		if not self._dataReady():
			# Translators: Reported when a portable copy is asked for before the vision data is installed.
			ui.message(_("The vision data is not installed yet, so there is nothing to copy."))
			return
		moredialogs.PortableDialog.run(gui.mainFrame, ADDON_DIR, PACK_DIR)

	def installPortable(self, folder, onProgress, cancel):
		ok = portable.install(folder, PACK_DIR, onProgress, cancel)
		if ok:
			wx.CallAfter(self._onDataInstalled)
		return ok
