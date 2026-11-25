# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Working the mouse from the keyboard: pointer mode (NVDA+Alt+U), the game mouse for games that read the mouse
itself, and dial mode for knobs and sliders that are only worked by dragging. While a mode is on, its keys go to
VisionMate; every other key works as usual."""
import addonHandler

from .common import *  # noqa: F401,F403
from . import inputs, knob

addonHandler.initTranslation()

# Pixels per arrow key press: normal, with Shift (fine) and with Control (far). The game mouse moves in mouse units.
STEPS = {"": 20, "shift": 3, "control": 100}
GAME_STEPS = {"": 40, "shift": 8, "control": 160}
# After the pointer stops this long, what is under it is said.
SAY_UNDER_MS = 60
# The window's text is read with OCR once and reused for this long, or until a click, the wheel or another window.
OCR_CACHE_SECONDS = 6
# A line of text counts as under the pointer within this many pixels.
NEAR_TEXT = 14
# Over these, the text right under the pointer is read with OCR, not the big control's name.
BIG_ROLES = {"PANE", "WINDOW", "CLIENT", "UNKNOWN", "DOCUMENT", "EDITABLETEXT", "FRAME", "APPLICATION", "GROUPING",
	"LIST", "TABLE", "TREEVIEW", "TERMINAL", "PANEL"}
DIAL_METHODS = ("wheel", "dragUp", "dragRight", "dragCircle")
DIAL_DRAG = 6
DIAL_SETTLE = 0.25


def _methodName(method):
	return {
		# Translators: Ways to work a dial or slider in dial mode.
		"wheel": _("mouse wheel"), "dragUp": _("dragging up and down"), "dragRight": _("dragging sideways"),
		"dragCircle": _("turning in a circle"),
	}[method]


class PointerMixin:
	def _initPointer(self):
		self._inputMode = None  # None, "pointer" or "dial"
		self._gameMouse = False
		self._holding = False
		self._lastUnder = None
		self._sayUnderTimer = None
		self._dial = None
		# The window's OCR lines: {"hwnd", "left", "top", "lines", "at"}, and whether a read is running.
		self._ocrCache = None
		self._ocrReading = False
		self._underGeneration = 0
		# While pointer or controller mode or the overlay is on, VisionMate says what is under the pointer, so NVDA's own mouse
		# tracking is quiet: both at once spoke twice and cut each other off.
		self._origMouseMove = None
		try:
			import mouseHandler
			original = mouseHandler.executeMouseMoveEvent

			def mouseMove(*args, **kwargs):
				if (self._inputMode == "pointer" or getattr(self, "_controllerMode", False)
						or getattr(self, "_overlayDoc", None) is not None):
					return None
				return original(*args, **kwargs)

			mouseHandler.executeMouseMoveEvent = mouseMove
			self._origMouseMove = (mouseHandler, original, mouseMove)
		except Exception:
			log.debugWarning("VisionMate: could not pause NVDA's mouse tracking in pointer mode", exc_info=True)

	def _restoreMouseTracking(self):
		if self._origMouseMove is not None:
			module, original, ours = self._origMouseMove
			if module.executeMouseMoveEvent is ours:
				module.executeMouseMoveEvent = original
			self._origMouseMove = None

	# --- Keys while a mode is on ---

	def getScript(self, gesture):
		mode = getattr(self, "_inputMode", None)
		if mode:
			table = self._pointerKeys() if mode == "pointer" else self._dialKeys()
			for ident in gesture.normalizedIdentifiers:
				action = table.get(ident.lower())
				if action is not None:
					return lambda g, action=action: action()
		return super().getScript(gesture)

	def _pointerKeys(self):
		keys = {}
		for mods in ("", "shift", "control"):
			prefix = "kb:" + (mods + "+" if mods else "")
			for name, (dx, dy) in (("uparrow", (0, -1)), ("downarrow", (0, 1)), ("leftarrow", (-1, 0)),
					("rightarrow", (1, 0))):
				keys[prefix + name] = lambda dx=dx, dy=dy, mods=mods: self._pointerMove(dx, dy, mods)
		keys.update({
			"kb:enter": lambda: self._pointerClick("left", 1),
			"kb:shift+enter": lambda: self._pointerClick("left", 2),
			"kb:applications": lambda: self._pointerClick("right", 1),
			"kb:shift+f10": lambda: self._pointerClick("right", 1),
			"kb:space": self._pointerHold,
			"kb:pageup": lambda: self._pointerWheel(1, False),
			"kb:pagedown": lambda: self._pointerWheel(-1, False),
			"kb:shift+pageup": lambda: self._pointerWheel(-1, True),
			"kb:shift+pagedown": lambda: self._pointerWheel(1, True),
			"kb:home": self._pointerCentre,
			"kb:h": lambda: self.hoverAt(inputs.position()),
			"kb:s": lambda: self.sayUnderPointer(force=True),
			"kb:t": lambda: self.touchMenu(inputs.position()),
			"kb:a": lambda: self.pointerActions(),
			"kb:g": self._toggleGameMouse,
			"kb:escape": lambda: self.setPointerMode(False),
		})
		return keys

	def setPointerMode(self, on):
		if on == (self._inputMode == "pointer"):
			return
		if self._holding:
			inputs.release()
			self._holding = False
		self._inputMode = "pointer" if on else None
		if on:
			sounds.play("overlayOpen")
			# Translators: Reported when pointer mode turns on.
			ui.message(_("Pointer mode. Arrows move the mouse, Enter clicks, A for more, Escape to leave."))
			self._lastUnder = None
		else:
			sounds.play("overlayClose")
			# Translators: Reported when pointer mode turns off.
			ui.message(_("Pointer mode off"))

	def _pointerMove(self, dx, dy, mods):
		if self._gameMouse:
			step = GAME_STEPS[mods]
			inputs.moveBy(dx * step, dy * step)
			return
		x, y = inputs.position()
		step = STEPS[mods]
		(nx, ny), atEdge = inputs.clamp(x + dx * step, y + dy * step)
		inputs.moveTo(nx, ny)
		if atEdge:
			import tones
			tones.beep(220, 40)
		self._sayUnderSoon()

	def _pointerClick(self, button, count):
		sounds.play("click")
		inputs.click(button, count)
		self._ocrCache = None  # the window may change

	def _pointerHold(self):
		"""Space holds the left button down, for dragging with the arrow keys; Space again lets go."""
		if self._holding:
			inputs.release()
			self._holding = False
			# Translators: Reported when the held mouse button is let go.
			ui.message(_("Let go"))
		else:
			inputs.press()
			self._holding = True
			# Translators: Reported when the left mouse button is held down for dragging.
			ui.message(_("Holding. Move with the arrows, Space lets go."))

	def _pointerWheel(self, notches, horizontal):
		inputs.wheel(notches, horizontal)
		self._ocrCache = None
		self._sayUnderSoon()

	def _pointerCentre(self):
		box = _windowBox(api.getForegroundObject())
		inputs.moveTo(box.left + box.width // 2, box.top + box.height // 2)
		# Translators: Reported when the pointer is moved to the middle of the window.
		ui.message(_("Middle of the window"))
		self._sayUnderSoon()

	def _toggleGameMouse(self):
		self._gameMouse = not self._gameMouse
		ui.message(
			# Translators: Reported when the game mouse turns on: the arrows move the mouse itself, as games read it.
			_("Game mouse on: the arrows move the mouse the way a game reads it.") if self._gameMouse
			# Translators: Reported when the game mouse turns off.
			else _("Game mouse off"))

	# --- What is under the pointer ---

	def _sayUnderSoon(self):
		# Always said by VisionMate: NVDA's own mouse tracking says nothing for many of these moves.
		if self._sayUnderTimer is not None:
			self._sayUnderTimer.Stop()
		self._sayUnderTimer = wx.CallLater(SAY_UNDER_MS, self.sayUnderPointer)

	def sayUnderPointer(self, force=False):
		"""Say what is under the pointer: NVDA's name for a control, or the line of text right there when the pointer is
		over text, a document or a window NVDA cannot read. The window's text is read with OCR once and reused, so
		moving on is quick. The same thing is not said twice in a row."""
		self._underGeneration += 1
		x, y = inputs.position()
		obj = _safe(lambda: api.getDesktopObject().objectFromPoint(x, y))
		name = (_safe(lambda: obj.name) or "").strip() if obj else ""
		role = _safe(lambda: obj.role.displayString) if obj else ""
		roleName = getattr(_safe(lambda: obj.role), "name", "") if obj else ""
		if name and roleName.upper() not in BIG_ROLES:
			self._sayIfNew((name, role), f"{name} {role}".strip(), force)
			return
		fallback = f"{name} {role}".strip()
		# The window under the pointer, which need not be the one in front, like the taskbar or the desktop.
		hwnd, box = _windowAt(x, y)
		cache = self._ocrCache
		if cache and cache["hwnd"] == hwnd and time.monotonic() - cache["at"] < OCR_CACHE_SECONDS:
			self._sayText(cache, x, y, fallback, force)
			return
		if self._ocrReading:
			return  # said when the read in progress ends
		image = self._grabOrReport((box.left, box.top, box.left + box.width, box.top + box.height), quiet=True)
		if image is None:
			self._sayIfNew(("text", fallback), fallback or _("Nothing"), force)
			return
		self._ocrReading = True
		generation = self._underGeneration

		def run():
			try:
				lines = ocr.recognize(image) or []
			finally:
				self._ocrReading = False
			fresh = {"hwnd": hwnd, "left": box.left, "top": box.top, "lines": lines, "at": time.monotonic()}

			def done():
				self._ocrCache = fresh
				if self._inputMode != "pointer" and not force:
					return
				# Say what is under the pointer now, which may have moved while the window was read.
				if generation == self._underGeneration:
					self._sayText(fresh, *inputs.position(), fallback, force)
				else:
					self.sayUnderPointer(force)

			queueHandler.queueFunction(queueHandler.eventQueue, done)

		threading.Thread(target=run, name="visionMate-under", daemon=True).start()

	def _sayText(self, cache, x, y, fallback, force):
		text = _wordsAt(cache["lines"], x - cache["left"], y - cache["top"])
		# Translators: Said for what is under the pointer when NVDA knows nothing there and there is no text.
		said = text or fallback or _("Blank")
		self._sayIfNew(("text", said), said, force)

	def _sayIfNew(self, key, text, force):
		if not force and key == self._lastUnder:
			return
		self._lastUnder = key
		speech.cancelSpeech()
		ui.message(text)

	# --- Dial mode: a knob or slider worked with the arrow keys ---

	def startDial(self, point, box, name):
		"""Work a control at point with the arrow keys, reading the number next to it after each step."""
		self._dial = {"point": point, "box": box, "name": name, "method": 0}
		self._inputMode = "dial"
		sounds.play("overlayOpen")
		# Translators: Reported when dial mode starts. {name} is the control, {method} how it is moved.
		ui.message(_("Dial mode for {name}. Up and down arrows change it, by {method}. M for another way, "
			"Escape to leave.").format(name=name, method=_methodName(DIAL_METHODS[0])))

	def _dialKeys(self):
		return {
			"kb:uparrow": lambda: self._dialStep(1), "kb:rightarrow": lambda: self._dialStep(1),
			"kb:downarrow": lambda: self._dialStep(-1), "kb:leftarrow": lambda: self._dialStep(-1),
			"kb:m": self._dialMethod,
			"kb:escape": self._dialEnd,
		}

	def _dialMethod(self):
		d = self._dial
		d["method"] = (d["method"] + 1) % len(DIAL_METHODS)
		# Translators: Reported when dial mode changes how the control is moved.
		ui.message(_("By {method}").format(method=_methodName(DIAL_METHODS[d["method"]])))

	def _dialEnd(self):
		self._inputMode = None
		self._dial = None
		sounds.play("overlayClose")
		# Translators: Reported when dial mode ends.
		ui.message(_("Dial mode off"))

	def _dialStep(self, direction):
		d = self._dial
		method = DIAL_METHODS[d["method"]]

		def run():
			stepControl(d["point"], d["box"], method, direction)
			time.sleep(DIAL_SETTLE)
			value = self.readControlNumber(d["box"])
			if value is None:
				# Translators: Said in dial mode when no number shows next to the control.
				_speak(_("No number shows"))
			else:
				_speak(_formatValue(value))

		threading.Thread(target=run, name="visionMate-dial", daemon=True).start()

	def readControlNumber(self, box):
		"""The number shown next to a control at screen box, read with OCR: (value, unit) or None.
		Call from a background thread."""
		left, top, right, bottom = box
		w, h = right - left, bottom - top
		pad = (int(w * knob.NEAR), int(h * knob.NEAR))
		area = (left - pad[0], top - pad[1], right + pad[0], bottom + pad[1])
		try:
			image = self._grab(area)
		except Exception:
			return None
		lines = ocr.recognize(image)
		if not lines:
			return None
		from .overlay import splitItems
		items = splitItems(lines)
		local = (box[0] - area[0], box[1] - area[1], box[2] - area[0], box[3] - area[1])
		found = knob.numberNear(local, items)
		return None if found is None else (found[0], found[1])


def _windowAt(x, y):
	"""The top-level window under a screen point: (handle, box with left, top, width, height), kept on the screen."""
	import ctypes
	from ctypes import wintypes
	user32 = ctypes.windll.user32
	user32.WindowFromPoint.argtypes = (wintypes.POINT,)
	user32.WindowFromPoint.restype = wintypes.HWND
	user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
	user32.GetAncestor.restype = wintypes.HWND
	handle = user32.WindowFromPoint(wintypes.POINT(x, y))
	root = user32.GetAncestor(handle, 2) if handle else None  # GA_ROOT
	rect = wintypes.RECT()
	if root and user32.GetWindowRect(root, ctypes.byref(rect)) and rect.right > rect.left and rect.bottom > rect.top:
		left, top, sw, sh = inputs.screen()
		l, t = max(rect.left, left), max(rect.top, top)
		r, b = min(rect.right, left + sw), min(rect.bottom, top + sh)
		if r - l >= 16 and b - t >= 16:
			return root, _Box(l, t, r - l, b - t)
	left, top, sw, sh = inputs.screen()
	return None, _Box(left, top, sw, sh)


def _wordsAt(lines, x, y):
	"""The OCR line nearest to the point (x, y) of the picture, as text."""
	best = None
	for line in lines:
		if not line:
			continue
		top = min(w["y"] for w in line)
		bottom = max(w["y"] + w["height"] for w in line)
		left = min(w["x"] for w in line)
		right = max(w["x"] + w["width"] for w in line)
		dy = 0 if top <= y <= bottom else min(abs(y - top), abs(y - bottom))
		dx = 0 if left <= x <= right else min(abs(x - left), abs(x - right))
		if dy > NEAR_TEXT or dx > NEAR_TEXT * 3:
			continue
		d = dy * 3 + dx
		if best is None or d < best[0]:
			best = (d, " ".join(w["text"] for w in line))
	return best[1] if best else ""


def _formatValue(value):
	number, unit = value
	text = f"{number:g}"
	if unit == "%":
		# Translators: A value in percent, like "35 percent".
		return _("{number} percent").format(number=text)
	return f"{text} {unit}".strip()


def stepControl(point, box, method, direction):
	"""Move a control one step: direction +1 is up or more, -1 down or less."""
	x, y = point
	if method == "wheel":
		inputs.moveTo(x, y)
		time.sleep(0.03)
		inputs.wheel(direction)
	elif method == "dragUp":
		inputs.drag((x, y), (x, y - direction * DIAL_DRAG), steps=3)
	elif method == "dragRight":
		inputs.drag((x, y), (x + direction * DIAL_DRAG, y), steps=3)
	elif method == "dragCircle":
		left, top, right, bottom = box
		radius = max(6, min(right - left, bottom - top) // 2 - 2)
		centre = ((left + right) // 2, (top + bottom) // 2)
		inputs.dragAlong(inputs.circlePath(centre, radius, direction * 15, steps=4))
