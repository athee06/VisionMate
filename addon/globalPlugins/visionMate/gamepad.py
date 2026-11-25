# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Game controllers through XInput: Xbox controllers and any controller Windows reads the same way. Reading a
controller never takes its input away from a game. The mapping from sticks to pointer speed is plain code, so it can
be tested on its own."""
import ctypes
from ctypes import wintypes

BUTTONS = {
	"dpadUp": 0x0001, "dpadDown": 0x0002, "dpadLeft": 0x0004, "dpadRight": 0x0008, "menu": 0x0010, "view": 0x0020,
	"leftStick": 0x0040, "rightStick": 0x0080, "lb": 0x0100, "rb": 0x0200, "a": 0x1000, "b": 0x2000, "x": 0x4000,
	"y": 0x8000,
}
# Sticks report -32768 to 32767. Inside the dead zone a stick counts as centred.
DEAD_ZONE = 7849
STICK_MAX = 32767
# Pointer speed in pixels per poll at full tilt; the curve gives fine control near the centre.
MAX_SPEED = 28
CURVE = 2.0


class XINPUT_GAMEPAD(ctypes.Structure):
	_fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
		("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
		("sThumbRY", ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
	_fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


_dll = None


def _xinput():
	global _dll
	if _dll is None:
		for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
			try:
				_dll = getattr(ctypes.windll, name)
				break
			except OSError:
				continue
		else:
			_dll = False
	return _dll or None


def read(index=None):
	"""(index, state) of the first connected controller, or of the one at index, or None."""
	dll = _xinput()
	if dll is None:
		return None
	for i in ([index] if index is not None else range(4)):
		state = XINPUT_STATE()
		if dll.XInputGetState(i, ctypes.byref(state)) == 0:
			return i, state.Gamepad
	return None


def pressed(pad):
	"""The names of the buttons held down."""
	return {name for name, bit in BUTTONS.items() if pad.wButtons & bit}


def stickSpeed(x, y):
	"""Pixels to move this poll for a stick at (x, y): (dx, dy), with screen y going down."""
	magnitude = (x * x + y * y) ** 0.5
	if magnitude <= DEAD_ZONE:
		return 0, 0
	scale = min((magnitude - DEAD_ZONE) / (STICK_MAX - DEAD_ZONE), 1.0) ** CURVE * MAX_SPEED
	return int(round(x / magnitude * scale)), int(round(-y / magnitude * scale))


def stickNotches(y):
	"""Wheel notches for the right stick this poll: -1, 0 or 1, scrolling while it is tilted well up or down."""
	if y > STICK_MAX * 0.6:
		return 1
	if y < -STICK_MAX * 0.6:
		return -1
	return 0
