# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""What can be done with a thing on the screen besides a click: hovering and hearing what appeared, dragging,
pressing and holding, setting a drawn knob or slider to a number, writing on a scanned form next to its label, and
touch and pen gestures. Opened with A in the overlay or in pointer mode, and with More in find on screen."""
import addonHandler

from .common import *  # noqa: F401,F403
from . import inputs, knob, paperform, pointermode, touch

addonHandler.initTranslation()

# Hover: how long the pointer rests before the window is read again.
HOVER_WAIT_SECONDS = 0.9
# Pause before acting, so the window in front is back after the choice window closed.
ACT_DELAY_SECONDS = 0.4
KNOB_SETTLE = 0.25
DRAG_LITTLE, DRAG_LOT = 40, 160
# After typing on a scanned form, the part around the line that is read again to check.
CHECK_AREA = (420, 90)


def _gestureName(key):
	return {
		# Translators: Touch and pen gestures in VisionMate's touch menu.
		"tap": _("Tap"), "doubleTap": _("Double tap"), "longPress": _("Long press"),
		"swipeLeft": _("Swipe left"), "swipeRight": _("Swipe right"), "swipeUp": _("Swipe up"),
		"swipeDown": _("Swipe down"), "twoSwipeLeft": _("Swipe left with two fingers"),
		"twoSwipeRight": _("Swipe right with two fingers"), "twoSwipeUp": _("Swipe up with two fingers"),
		"twoSwipeDown": _("Swipe down with two fingers"), "threeSwipeLeft": _("Swipe left with three fingers"),
		"threeSwipeRight": _("Swipe right with three fingers"), "threeSwipeUp": _("Swipe up with three fingers"),
		"threeSwipeDown": _("Swipe down with three fingers"), "pinch": _("Pinch (zoom out)"),
		"spread": _("Spread two fingers (zoom in)"), "rotateRight": _("Turn two fingers to the right"),
		"rotateLeft": _("Turn two fingers to the left"), "penLight": _("Pen, light press"),
		"penMedium": _("Pen, medium press"), "penHard": _("Pen, hard press"),
	}[key]


def _choose(title, message, labels):
	"""Ask for one of labels on the GUI thread; returns its index or None."""
	dlg = wx.SingleChoiceDialog(gui.mainFrame, message, title, labels)
	gui.mainFrame.prePopup()
	try:
		if dlg.ShowModal() != wx.ID_OK:
			return None
		return dlg.GetSelection()
	finally:
		dlg.Destroy()
		gui.mainFrame.postPopup()


def _askText(title, message, value=""):
	dlg = wx.TextEntryDialog(gui.mainFrame, message, title, value=value)
	gui.mainFrame.prePopup()
	try:
		if dlg.ShowModal() != wx.ID_OK:
			return None
		return dlg.GetValue().strip() or None
	finally:
		dlg.Destroy()
		gui.mainFrame.postPopup()


def _later(fn, *args):
	"""Run fn in the background after the choice window has closed and the window in front is back."""
	def run():
		time.sleep(ACT_DELAY_SECONDS)
		try:
			fn(*args)
		except Exception:
			log.error("VisionMate: action failed", exc_info=True)
			_sound("error")
	threading.Thread(target=run, name="visionMate-action", daemon=True).start()


class ActionsMixin:
	def _initActions(self):
		self._dragFrom = None
		# Set while no action runs, so NVDA+Alt+X knows there is nothing to stop.
		self._actionCancel = threading.Event()
		self._actionCancel.set()

	def itemActions(self, point, box, name, isText=False, afterClick=None):
		"""The actions window for a thing on the screen at point (and screen box), named name."""
		entries = [
			# Translators: Actions for a thing on the screen.
			(_("Click"), lambda: _later(self._doClick, point, "left", 1, afterClick)),
			(_("Double-click"), lambda: _later(self._doClick, point, "left", 2, afterClick)),
			(_("Right-click"), lambda: _later(self._doClick, point, "right", 1, afterClick)),
			(_("Hover, and say what appears"), lambda: _later(self.hoverAt, point)),
			(_("Move the mouse here"), lambda: _later(self._moveHere, point, name)),
		]
		if self._dragFrom is None:
			entries.append((_("Start a drag here, then choose Drop on another item"),
				lambda: self._startDrag(point, name)))
		else:
			entries.append((_("Drop here what is being dragged ({name})").format(name=self._dragFrom[1]),
				lambda: _later(self._drop, point, name)))
			entries.append((_("Cancel the drag"), self._cancelDrag))
		entries += [
			(_("Drag it a little or a lot, in a direction..."), lambda: self._dragByMenu(point, name)),
			(_("Press and hold..."), lambda: self._holdMenu(point, name)),
			(_("Set it to a number (a knob, dial or slider)..."), lambda: self._setNumber(point, box, name)),
			(_("Work it with the arrow keys (a knob, dial or slider)"),
				lambda: wx.CallLater(int(ACT_DELAY_SECONDS * 1000), self.startDial, point, box, name)),
		]
		if isText:
			entries.append((_("Write on the line next to this label (a scanned form)..."),
				lambda: self._writeNextTo(box, name)))
		entries += [
			(_("Touch or pen gesture here..."), lambda: self.touchMenu(point)),
			(_("Pointer mode from here"), lambda: self._pointerFrom(point)),
		]

		def show():
			# Translators: Title and prompt of the actions window. {name} is the thing on the screen.
			index = _choose(_("VisionMate actions"), _("What to do with {name}?").format(name=name),
				[label for label, _fn in entries])
			if index is not None:
				entries[index][1]()

		wx.CallAfter(show)

	def pointerActions(self):
		x, y = inputs.position()
		obj = _safe(lambda: api.getDesktopObject().objectFromPoint(x, y))
		# Translators: The thing under the pointer, in the actions window.
		name = (_safe(lambda: obj.name) or "").strip() if obj else ""
		self.itemActions((x, y), (x - 20, y - 20, x + 20, y + 20), name or _("the place under the pointer"))

	# --- Clicks and moving ---

	def _doClick(self, point, button, count, afterClick=None):
		old = inputs.position()
		inputs.moveTo(*point)
		time.sleep(0.05)
		sounds.play("click")
		inputs.click(button, count)
		time.sleep(0.3)
		inputs.moveTo(*old)
		if afterClick is not None:
			wx.CallAfter(afterClick)

	def _moveHere(self, point, name):
		inputs.moveTo(*point)
		# Translators: Reported after the mouse was moved to a thing. {name} is the thing.
		_speak(_("Mouse moved to {name}").format(name=name))

	def _pointerFrom(self, point):
		inputs.moveTo(*point)
		wx.CallLater(int(ACT_DELAY_SECONDS * 1000), self.setPointerMode, True)

	# --- Hover ---

	def _windowTexts(self, box):
		image = self._grab((box.left, box.top, box.left + box.width, box.top + box.height))
		lines = ocr.recognize(image)
		if lines is None:
			return None
		from .overlay import splitItems
		return [item["text"] for item in splitItems(lines)]

	def hoverAt(self, point):
		"""Rest the pointer on a point, then say the text that appeared, like a tip or a menu that opens by itself.
		The pointer stays there. Runs in the background."""
		def run():
			box = _windowBox(api.getForegroundObject())
			try:
				before = self._windowTexts(box)
			except Exception:
				before = None
			if before is None:
				_sound("error")
				# Translators: Reported when the window could not be read with OCR before hovering.
				_speak(_("Could not read this window."))
				return
			inputs.moveTo(*point)
			time.sleep(HOVER_WAIT_SECONDS)
			after = self._windowTexts(box) or []
			new = findonscreen.appeared(before, after)
			if new:
				# Translators: Said after hovering, followed by the text that came up.
				_speak(_("Appeared: {text}").format(text=". ".join(new)))
			else:
				# Translators: Said after hovering when nothing new showed.
				_speak(_("Nothing appeared"))

		threading.Thread(target=run, name="visionMate-hover", daemon=True).start()

	# --- Dragging ---

	def _startDrag(self, point, name):
		self._dragFrom = (point, name)
		# Translators: Reported when a drag starts. {name} is what is dragged.
		ui.message(_("Dragging {name}. Open the actions on another item and choose Drop.").format(name=name))

	def _cancelDrag(self):
		self._dragFrom = None
		# Translators: Reported when a drag is cancelled.
		ui.message(_("Drag cancelled"))

	def _drop(self, point, name):
		start, what = self._dragFrom
		self._dragFrom = None
		old = inputs.position()
		inputs.drag(start, point)
		time.sleep(0.2)
		inputs.moveTo(*old)
		# Translators: Reported after a drag. {what} was dragged onto {name}.
		_speak(_("Dragged {what} onto {name}").format(what=what, name=name))
		wx.CallAfter(self._refreshAfterAction)

	def _dragByMenu(self, point, name):
		choices = [
			# Translators: Directions and distances to drag a thing.
			(_("Right a little"), (DRAG_LITTLE, 0)), (_("Right a lot"), (DRAG_LOT, 0)),
			(_("Left a little"), (-DRAG_LITTLE, 0)), (_("Left a lot"), (-DRAG_LOT, 0)),
			(_("Up a little"), (0, -DRAG_LITTLE)), (_("Up a lot"), (0, -DRAG_LOT)),
			(_("Down a little"), (0, DRAG_LITTLE)), (_("Down a lot"), (0, DRAG_LOT)),
		]
		# Translators: Title and prompt of the window for dragging in a direction.
		index = _choose(_("VisionMate drag"), _("Drag {name}:").format(name=name), [c[0] for c in choices])
		if index is None:
			return
		label, (dx, dy) = choices[index]

		def run():
			old = inputs.position()
			inputs.drag(point, (point[0] + dx, point[1] + dy))
			time.sleep(0.2)
			inputs.moveTo(*old)
			# Translators: Reported after dragging in a direction. {name} is the thing, {how} like "Right a little".
			_speak(_("Dragged {name}: {how}").format(name=name, how=label.lower()))
			wx.CallAfter(self._refreshAfterAction)

		_later(run)

	def _holdMenu(self, point, name):
		choices = [(_("For 3 seconds"), 3), (_("For 5 seconds"), 5), (_("For 10 seconds"), 10), (_("For 15 seconds"), 15)]
		# Translators: Title and prompt of the window for pressing and holding a thing.
		index = _choose(_("VisionMate press and hold"), _("Press and hold {name}:").format(name=name),
			[c[0] for c in choices])
		if index is None:
			return
		seconds = choices[index][1]

		def run():
			self._actionCancel.clear()
			old = inputs.position()
			inputs.moveTo(*point)
			time.sleep(0.05)
			inputs.press()
			# Translators: Reported while holding the mouse button down. NVDA+Alt+X lets go early.
			_speak(_("Holding. NVDA+Alt+X lets go."))
			end = time.monotonic() + seconds
			try:
				while time.monotonic() < end and not self._actionCancel.wait(0.1):
					pass
			finally:
				inputs.release()
			time.sleep(0.2)
			inputs.moveTo(*old)
			# Translators: Reported when the held mouse button is let go.
			_speak(_("Let go"))
			self._actionCancel.set()
			wx.CallAfter(self._refreshAfterAction)

		_later(run)

	def _refreshAfterAction(self):
		doc = self._overlayDoc
		if doc is not None:
			self._refreshOverlayNow(doc)

	# --- A knob, dial or slider set to a number ---

	def _setNumber(self, point, box, name):
		# Translators: Title and prompt of the window for setting a knob or slider to a number.
		text = _askText(_("VisionMate set to a number"), _("Set {name} to which number? For example: 35").format(name=name))
		if not text:
			return
		target = knob.parse(text)
		if target is None:
			# Translators: Reported when the typed text has no number.
			ui.message(_("That is not a number."))
			return
		_later(self._runKnob, point, box, name, target[0])

	def _setByWindows(self, point, target):
		"""Set the value through Windows itself where the program offers it (UI Automation's range value)."""
		obj = _safe(lambda: api.getDesktopObject().objectFromPoint(*point))
		element = getattr(obj, "UIAElement", None)
		if element is None:
			return False
		try:
			import UIAHandler
			pattern = element.GetCurrentPattern(UIAHandler.UIA_RangeValuePatternId)
			if not pattern:
				return False
			pattern = pattern.QueryInterface(UIAHandler.IUIAutomationRangeValuePattern)
			low, high = pattern.CurrentMinimum, pattern.CurrentMaximum
			if not low <= target <= high:
				return False
			pattern.SetValue(float(target))
			return True
		except Exception:
			log.debug("VisionMate: no range value for this control", exc_info=True)
			return False

	def _runKnob(self, point, box, name, target):
		if self._setByWindows(point, target):
			# Translators: Reported after a control was set to a number. {name} is the control.
			_speak(_("{name} set to {value}").format(name=name, value=f"{target:g}"))
			return
		start = self.readControlNumber(box)
		if start is None:
			_sound("error")
			# Translators: Reported when no number shows next to a knob, so it is not moved.
			_speak(_("No number shows next to {name}, so it was left as it is. Try Work it with the arrow keys.")
				.format(name=name))
			return
		value, unit = start
		old = inputs.position()
		step = "done"
		self._actionCancel.clear()
		try:
			for method in pointermode.DIAL_METHODS:
				stepper = knob.Stepper(value, target)
				step = stepper.first()
				while step not in ("done", "stuck", "limit") and not self._actionCancel.is_set():
					if step == "back":
						pointermode.stepControl(point, box, method, stepper.direction)
						time.sleep(KNOB_SETTLE)
						read = self.readControlNumber(box)
						value = read[0] if read else value
						step = "done"
						break
					pointermode.stepControl(point, box, method, step)
					time.sleep(KNOB_SETTLE)
					read = self.readControlNumber(box)
					step = stepper.next(read[0] if read else None)
					if read:
						value = read[0]
				if step != "stuck":
					break
		finally:
			inputs.moveTo(*old)
			self._actionCancel.set()
		shown = pointermode._formatValue((value, unit))
		if value == target or step == "done":
			# Translators: Reported after a knob was moved to the asked number, or as near as its steps allow.
			_speak(_("{name} is now {value}").format(name=name, value=shown))
		elif step == "stuck":
			_sound("error")
			# Translators: Reported when no way of moving the knob changed its number.
			_speak(_("{name} did not move. It shows {value}.").format(name=name, value=shown))
		else:
			# Translators: Reported when the knob stopped before the asked number.
			_speak(_("Stopped. {name} shows {value}.").format(name=name, value=shown))

	# --- Scanned forms ---

	def _writeNextTo(self, box, name):
		"""Find the blank line or box that belongs to a printed label, click it, type, and check it shows."""
		fg = api.getForegroundObject()
		win = _windowBox(fg)
		area = (win.left, win.top, win.left + win.width, win.top + win.height)
		image = self._grabOrReport(area)
		if image is None:
			return
		label = (box[0] - win.left, box[1] - win.top, box[2] - win.left, box[3] - win.top)

		def find():
			lines = ocr.recognize(image) or []
			from .overlay import splitItems
			boxes = [it["box"] for it in splitItems(lines)]
			return paperform.findBlank(image, label, boxes)

		def run():
			found = find()
			if found is None:
				_sound("error")
				# Translators: Reported when no line or box to write on was found next to a label.
				_speak(_("No line or box to write on was found next to {name}.").format(name=name))
				return
			(x, y), where = found
			wx.CallAfter(self._askAndWrite, (win.left + x, win.top + y), where, name)

		threading.Thread(target=run, name="visionMate-form", daemon=True).start()

	def _askAndWrite(self, point, where, name):
		places = {
			# Translators: Where the line to write on is, next to its label.
			"right": _("to the right of"), "below": _("under"), "above": _("above"),
		}
		# Translators: Title and prompt of the window for writing on a scanned form.
		text = _askText(_("VisionMate write on the form"),
			_("A line is {place} {name}. What should be typed there?").format(place=places[where], name=name))
		if not text:
			return

		def run():
			inputs.moveTo(*point)
			time.sleep(0.05)
			inputs.click()
			time.sleep(0.4)
			inputs.typeText(text)
			time.sleep(0.8)
			w, h = CHECK_AREA
			try:
				check = self._grab((point[0] - 30, point[1] - h // 2, point[0] + w, point[1] + h // 2))
				lines = ocr.recognize(check)
			except Exception:
				lines = None
			seen = " ".join(ocr.linesText(lines).split()).lower() if lines else ""
			wanted = " ".join(text.split()).lower()
			import difflib
			if wanted and (wanted in seen or difflib.SequenceMatcher(None, wanted, seen[:len(wanted) + 10]).ratio() > 0.75):
				# Translators: Reported after typing on a scanned form when the text shows on the page.
				_speak(_("Typed, and it shows on the page."))
			else:
				# Translators: Reported after typing on a scanned form when the text can't be seen on the page.
				_speak(_("Typed, but VisionMate cannot see it on the page. The program may need its typing tool first."))

		_later(run)

	# --- Touch and pen ---

	def touchMenu(self, point):
		keys = list(touch.GESTURES) + list(touch.PEN)

		def show():
			# Translators: Title and prompt of the touch and pen window.
			index = _choose(_("VisionMate touch and pen"), _("Which gesture, at the pointer's place?"),
				[_gestureName(k) for k in keys])
			if index is None:
				return
			_later(self._doTouch, keys[index], point)

		wx.CallAfter(show)

	def _doTouch(self, key, point):
		try:
			touch.perform(key, *point)
		except touch.TouchError as e:
			_sound("error")
			if str(e) == "pen":
				# Translators: Reported when Windows does not allow a pen to be simulated.
				_speak(_("Windows on this computer does not allow a pen to be simulated. It needs Windows 10 "
					"version 1809 or later."))
			else:
				# Translators: Reported when Windows does not allow touch to be simulated.
				_speak(_("Windows did not allow the touch."))
			return
		# Translators: Reported after a touch or pen gesture. {gesture} is its name.
		_speak(_("Done: {gesture}").format(gesture=_gestureName(key)))
		wx.CallAfter(self._refreshAfterAction)
