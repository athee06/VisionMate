# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Mouse and keyboard input sent through Windows, as a hand on the mouse would: moving, clicking, holding a button,
dragging, the wheel, relative moves for games that read the mouse itself, and typing text.
No NVDA modules here."""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
MOUSEEVENTF_VIRTUALDESK, MOUSEEVENTF_ABSOLUTE = 0x4000, 0x8000
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
WHEEL_DELTA = 120
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
	_fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
		("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
	_fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
		("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
	_fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
	_fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
	_fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def _send(*inputs):
	array = (INPUT * len(inputs))(*inputs)
	return user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
	return INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(dx, dy, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0, 0)))


def screen():
	"""The whole screen over all monitors: (left, top, width, height)."""
	return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77), user32.GetSystemMetrics(78),
		user32.GetSystemMetrics(79))


def position():
	p = wintypes.POINT()
	user32.GetCursorPos(ctypes.byref(p))
	return p.x, p.y


def clamp(x, y):
	"""A point kept on the screen; and whether it had to be moved to stay there."""
	left, top, w, h = screen()
	cx, cy = min(max(x, left), left + w - 1), min(max(y, top), top + h - 1)
	return (cx, cy), (cx, cy) != (x, y)


def moveTo(x, y):
	"""Move the pointer to a point on the screen, as a real mouse move, so programs and NVDA's mouse tracking see it."""
	left, top, w, h = screen()
	ax = int(round((x - left) * 65535 / max(w - 1, 1)))
	ay = int(round((y - top) * 65535 / max(h - 1, 1)))
	_send(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay))


def moveBy(dx, dy):
	"""A relative move, as games that turn the view with the mouse read it. Windows' pointer speed applies."""
	_send(_mouse(MOUSEEVENTF_MOVE, int(dx), int(dy)))


_BUTTONS = {"left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP), "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)}


def press(button="left"):
	_send(_mouse(_BUTTONS[button][0]))


def release(button="left"):
	_send(_mouse(_BUTTONS[button][1]))


def click(button="left", count=1):
	down, up = _BUTTONS[button]
	for i in range(count):
		_send(_mouse(down), _mouse(up))
		if i + 1 < count:
			time.sleep(0.05)


def wheel(notches, horizontal=False):
	"""Turn the wheel: positive is up (or right), negative down (or left)."""
	_send(_mouse(MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, data=int(notches * WHEEL_DELTA)))


def dragPath(start, end, steps=12):
	"""Points from start to end, for a drag that programs see as a hand moving."""
	(x0, y0), (x1, y1) = start, end
	return [(int(round(x0 + (x1 - x0) * i / steps)), int(round(y0 + (y1 - y0) * i / steps))) for i in range(1, steps + 1)]


def drag(start, end, steps=12, pause=0.02, button="left"):
	"""Press at start, move to end step by step, and let go."""
	moveTo(*start)
	time.sleep(0.05)
	press(button)
	time.sleep(0.08)
	for point in dragPath(start, end, steps):
		moveTo(*point)
		time.sleep(pause)
	time.sleep(0.08)
	release(button)


def circlePath(center, radius, degrees, steps=12, startDegrees=-90):
	"""Points along an arc around center, for knobs turned in a circle. Positive degrees go clockwise."""
	import math
	cx, cy = center
	return [(int(round(cx + radius * math.cos(math.radians(startDegrees + degrees * i / steps)))),
		int(round(cy + radius * math.sin(math.radians(startDegrees + degrees * i / steps)))))
		for i in range(0, steps + 1)]


def dragAlong(points, pause=0.02, button="left"):
	moveTo(*points[0])
	time.sleep(0.05)
	press(button)
	time.sleep(0.05)
	for point in points[1:]:
		moveTo(*point)
		time.sleep(pause)
	release(button)


def typeText(text):
	"""Type text as key presses of its characters, into whatever has the keyboard focus."""
	for ch in text:
		if ch == "\n":
			vk = 0x0D
			_send(INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(vk, 0, 0, 0, 0))),
				INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0))))
			continue
		for unit in _utf16(ch):
			_send(INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, 0))),
				INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))))
		time.sleep(0.005)


def _utf16(ch):
	data = ch.encode("utf-16-le")
	return [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
