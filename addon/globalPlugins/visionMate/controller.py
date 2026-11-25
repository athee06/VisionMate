# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Controller mode (NVDA+Alt+Q, or View and Menu held together): a game controller works the mouse pointer in any
window. Left stick moves, right stick scrolls, A clicks, B right-clicks, X double-clicks, Y says what is under the
pointer, LB holds the button for dragging, RB hovers, the D-pad moves a little. Outside controller mode the
controller only goes to the game; VisionMate just notices it."""
import addonHandler

from .common import *  # noqa: F401,F403
from . import gamepad, inputs

addonHandler.initTranslation()

# Seconds between looks: in controller mode, with a controller connected, and with none.
POLL_ACTIVE = 0.016
POLL_CONNECTED = 0.1
POLL_SEARCH = 2.0
COMBO_SECONDS = 1.0
DPAD_STEP = 5
WHEEL_EVERY = 0.12
CONTROLLER_CHOICES = ("announce", "quiet", "off")


class ControllerMixin:
	def _initController(self):
		self._controllerMode = False
		self._padIndex = None
		threading.Thread(target=self._controllerLoop, name="visionMate-controller", daemon=True).start()

	def _controllerSetting(self):
		try:
			value = conf()["controller"]
		except KeyError:
			value = "announce"
		return value if value in CONTROLLER_CHOICES else "announce"

	def setControllerMode(self, on):
		if on and self._padIndex is None:
			# Translators: Reported when controller mode is asked for but no controller is connected.
			_speak(_("No game controller is connected."))
			return
		if on == self._controllerMode:
			return
		self._controllerMode = on
		if self._holding:
			inputs.release()
			self._holding = False
		_sound("overlayOpen" if on else "overlayClose")
		_speak(
			# Translators: Reported when controller mode turns on.
			_("Controller mode. Left stick moves the pointer, A clicks, B right-clicks, Y says what is there. "
				"View and Menu together to leave.") if on
			# Translators: Reported when controller mode turns off.
			else _("Controller mode off"))

	def _controllerLoop(self):
		comboSince = None
		previous = set()
		lastWheel = 0
		while not self._stopped.is_set():
			setting = self._controllerSetting()
			if setting == "off":
				if self._padIndex is not None:
					self._padIndex = None
					if self._controllerMode:
						self._controllerMode = False
				self._stopped.wait(POLL_SEARCH)
				continue
			try:
				found = gamepad.read(self._padIndex)
			except Exception:
				log.debugWarning("VisionMate: could not read the game controller", exc_info=True)
				found = None
			if found is None:
				if self._padIndex is not None:
					self._padIndex = None
					if self._controllerMode:
						self._controllerMode = False
					if setting == "announce":
						# Translators: Reported when the game controller is disconnected.
						_speak(_("Game controller disconnected"))
				self._stopped.wait(POLL_SEARCH)
				continue
			index, pad = found
			if self._padIndex is None:
				self._padIndex = index
				if setting == "announce":
					# Translators: Reported when a game controller is connected.
					_speak(_("Game controller connected. Hold View and Menu together for controller mode."))
			buttons = gamepad.pressed(pad)
			now = time.monotonic()
			if {"view", "menu"} <= buttons:
				if comboSince is None:
					comboSince = now
				elif now - comboSince >= COMBO_SECONDS:
					comboSince = float("inf")  # once per hold
					self.setControllerMode(not self._controllerMode)
			else:
				comboSince = None
			if self._controllerMode:
				new = buttons - previous
				try:
					self._controllerStep(pad, new, now, lastWheel)
					if gamepad.stickNotches(pad.sThumbRY) and now - lastWheel >= WHEEL_EVERY:
						lastWheel = now
				except Exception:
					log.debugWarning("VisionMate: controller step failed", exc_info=True)
			previous = buttons
			self._stopped.wait(POLL_ACTIVE if self._controllerMode else POLL_CONNECTED)

	def _controllerStep(self, pad, new, now, lastWheel):
		dx, dy = gamepad.stickSpeed(pad.sThumbLX, pad.sThumbLY)
		for name, (sx, sy) in (("dpadUp", (0, -1)), ("dpadDown", (0, 1)), ("dpadLeft", (-1, 0)), ("dpadRight", (1, 0))):
			if name in new:
				dx, dy = dx + sx * DPAD_STEP, dy + sy * DPAD_STEP
		if dx or dy:
			if self._gameMouse:
				inputs.moveBy(dx, dy)
			else:
				x, y = inputs.position()
				(nx, ny), _edge = inputs.clamp(x + dx, y + dy)
				inputs.moveTo(nx, ny)
		notches = gamepad.stickNotches(pad.sThumbRY)
		if notches and now - lastWheel >= WHEEL_EVERY:
			inputs.wheel(notches)
		if "a" in new:
			_sound("click")
			inputs.click()
		if "b" in new:
			_sound("click")
			inputs.click("right")
		if "x" in new:
			_sound("click")
			inputs.click("left", 2)
		if "y" in new:
			queueHandler.queueFunction(queueHandler.eventQueue, self.sayUnderPointer, True)
		if "rb" in new:
			pos = inputs.position()
			queueHandler.queueFunction(queueHandler.eventQueue, self.hoverAt, pos)
		if "lb" in new:
			queueHandler.queueFunction(queueHandler.eventQueue, self._pointerHold)
