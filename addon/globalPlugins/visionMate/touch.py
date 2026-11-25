# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Fingers and pressure without a touch screen or a pen: Windows lets a program touch the screen as fingers would
(InjectTouchInput, Windows 8 and later) and press as a pen would (synthetic pointer devices, Windows 10 1809 and
later). No touch screen or pen is needed. The gesture paths are plain code, so they can be tested on their own."""
import ctypes
import math
import time
from ctypes import wintypes

# Gestures: (key, fingers). Keys are also the names in the touch menu.
GESTURES = (
	"tap", "doubleTap", "longPress", "swipeLeft", "swipeRight", "swipeUp", "swipeDown",
	"twoSwipeLeft", "twoSwipeRight", "twoSwipeUp", "twoSwipeDown", "threeSwipeLeft", "threeSwipeRight",
	"threeSwipeUp", "threeSwipeDown", "pinch", "spread", "rotateRight", "rotateLeft",
)
PEN = ("penLight", "penMedium", "penHard")
PEN_PRESSURE = {"penLight": 256, "penMedium": 600, "penHard": 1024}
# Distances in pixels, and how many frames a moving gesture has.
SWIPE_DISTANCE = 300
FINGER_SPACING = 60
PINCH_FROM, PINCH_TO = 200, 50
ROTATE_RADIUS = 100
ROTATE_DEGREES = 90
FRAMES = 16
FRAME_SECONDS = 0.012
LONG_PRESS_SECONDS = 1.0


def _fingers(key):
	if key.startswith("two") or key in ("pinch", "spread") or key.startswith("rotate"):
		return 2
	if key.startswith("three"):
		return 3
	return 1


def _direction(key):
	for word, d in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1))):
		if key.endswith(word):
			return d
	return (0, 0)


def frames(key, x, y):
	"""Where each finger is, frame by frame: a list of frames, each a list of (x, y), one per finger.
	The first frame puts the fingers down and the last lifts them."""
	n = _fingers(key)
	if key in ("tap", "doubleTap", "longPress") or key in PEN:
		return [[(x, y)], [(x, y)]]
	if key.startswith(("swipe", "twoSwipe", "threeSwipe")):
		dx, dy = _direction(key)
		# Fingers side by side, across the direction of the swipe.
		offsets = [((i - (n - 1) / 2) * FINGER_SPACING) for i in range(n)]
		starts = [(x + (o if dy else 0) - dx * SWIPE_DISTANCE / 2, y + (o if dx else 0) - dy * SWIPE_DISTANCE / 2)
			for o in offsets]
		return [[(int(round(sx + dx * SWIPE_DISTANCE * f / FRAMES)), int(round(sy + dy * SWIPE_DISTANCE * f / FRAMES)))
			for sx, sy in starts] for f in range(FRAMES + 1)]
	if key in ("pinch", "spread"):
		a, b = (PINCH_FROM, PINCH_TO) if key == "pinch" else (PINCH_TO, PINCH_FROM)
		result = []
		for f in range(FRAMES + 1):
			half = (a + (b - a) * f / FRAMES) / 2
			result.append([(int(round(x - half)), y), (int(round(x + half)), y)])
		return result
	if key.startswith("rotate"):
		sign = 1 if key == "rotateRight" else -1
		result = []
		for f in range(FRAMES + 1):
			angle = math.radians(sign * ROTATE_DEGREES * f / FRAMES)
			dx, dy = ROTATE_RADIUS * math.cos(angle), ROTATE_RADIUS * math.sin(angle)
			result.append([(int(round(x - dx)), int(round(y - dy))), (int(round(x + dx)), int(round(y + dy)))])
		return result
	raise ValueError(key)


# --- Windows ---

PT_TOUCH, PT_PEN = 2, 3
POINTER_FLAG_NEW = 0x1
POINTER_FLAG_INRANGE = 0x2
POINTER_FLAG_INCONTACT = 0x4
POINTER_FLAG_FIRSTBUTTON = 0x10
POINTER_FLAG_PRIMARY = 0x2000
POINTER_FLAG_DOWN = 0x10000
POINTER_FLAG_UPDATE = 0x20000
POINTER_FLAG_UP = 0x40000
TOUCH_MASK_CONTACTAREA, TOUCH_MASK_ORIENTATION, TOUCH_MASK_PRESSURE = 0x1, 0x2, 0x4
PEN_MASK_PRESSURE = 0x1
TOUCH_FEEDBACK_DEFAULT = 0x1
POINTER_FEEDBACK_DEFAULT = 1
MAX_TOUCHES = 3


class POINTER_INFO(ctypes.Structure):
	_fields_ = [
		("pointerType", ctypes.c_uint32), ("pointerId", ctypes.c_uint32), ("frameId", ctypes.c_uint32),
		("pointerFlags", ctypes.c_uint32), ("sourceDevice", wintypes.HANDLE), ("hwndTarget", wintypes.HWND),
		("ptPixelLocation", wintypes.POINT), ("ptHimetricLocation", wintypes.POINT),
		("ptPixelLocationRaw", wintypes.POINT), ("ptHimetricLocationRaw", wintypes.POINT),
		("dwTime", wintypes.DWORD), ("historyCount", ctypes.c_uint32), ("InputData", ctypes.c_int32),
		("dwKeyStates", wintypes.DWORD), ("PerformanceCount", ctypes.c_uint64), ("ButtonChangeType", ctypes.c_int),
	]


class POINTER_TOUCH_INFO(ctypes.Structure):
	_fields_ = [
		("pointerInfo", POINTER_INFO), ("touchFlags", ctypes.c_uint32), ("touchMask", ctypes.c_uint32),
		("rcContact", wintypes.RECT), ("rcContactRaw", wintypes.RECT), ("orientation", ctypes.c_uint32),
		("pressure", ctypes.c_uint32),
	]


class POINTER_PEN_INFO(ctypes.Structure):
	_fields_ = [
		("pointerInfo", POINTER_INFO), ("penFlags", ctypes.c_uint32), ("penMask", ctypes.c_uint32),
		("pressure", ctypes.c_uint32), ("rotation", ctypes.c_uint32), ("tiltX", ctypes.c_int32),
		("tiltY", ctypes.c_int32),
	]


class _TYPEUNION(ctypes.Union):
	_fields_ = [("touchInfo", POINTER_TOUCH_INFO), ("penInfo", POINTER_PEN_INFO)]


class POINTER_TYPE_INFO(ctypes.Structure):
	_fields_ = [("type", ctypes.c_uint32), ("u", _TYPEUNION)]


class TouchError(Exception):
	pass


_touchReady = False
_penDevice = None


def _user32():
	return ctypes.windll.user32


def _initTouch():
	global _touchReady
	if _touchReady:
		return
	u = _user32()
	if not hasattr(u, "InitializeTouchInjection"):
		raise TouchError("touch")
	if not u.InitializeTouchInjection(MAX_TOUCHES, TOUCH_FEEDBACK_DEFAULT):
		raise TouchError("touch")
	_touchReady = True


def _touchFrame(points, flags):
	contacts = (POINTER_TOUCH_INFO * len(points))()
	for i, (x, y) in enumerate(points):
		c = contacts[i]
		c.pointerInfo.pointerType = PT_TOUCH
		c.pointerInfo.pointerId = i
		c.pointerInfo.ptPixelLocation = wintypes.POINT(x, y)
		c.pointerInfo.pointerFlags = flags | (POINTER_FLAG_PRIMARY if i == 0 else 0)
		c.touchMask = TOUCH_MASK_CONTACTAREA | TOUCH_MASK_ORIENTATION | TOUCH_MASK_PRESSURE
		c.rcContact = wintypes.RECT(x - 2, y - 2, x + 2, y + 2)
		c.orientation = 90
		c.pressure = 32000
	if not _user32().InjectTouchInput(len(points), contacts):
		raise TouchError("touch")


def _touchPath(path, hold=0.0):
	inContact = POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT
	_touchFrame(path[0], POINTER_FLAG_DOWN | inContact)
	time.sleep(FRAME_SECONDS)
	held = time.monotonic() + hold
	for points in path[1:]:
		_touchFrame(points, POINTER_FLAG_UPDATE | inContact)
		time.sleep(FRAME_SECONDS)
	while time.monotonic() < held:
		_touchFrame(path[-1], POINTER_FLAG_UPDATE | inContact)
		time.sleep(0.05)
	_touchFrame(path[-1], POINTER_FLAG_UP)


def _pen(x, y, pressure):
	global _penDevice
	u = _user32()
	if _penDevice is None:
		if not hasattr(u, "CreateSyntheticPointerDevice"):
			raise TouchError("pen")
		u.CreateSyntheticPointerDevice.restype = wintypes.HANDLE
		_penDevice = u.CreateSyntheticPointerDevice(PT_PEN, 1, POINTER_FEEDBACK_DEFAULT)
		if not _penDevice:
			_penDevice = None
			raise TouchError("pen")
	u.InjectSyntheticPointerInput.argtypes = (wintypes.HANDLE, ctypes.POINTER(POINTER_TYPE_INFO), ctypes.c_uint32)

	def frame(flags, p):
		info = POINTER_TYPE_INFO()
		info.type = PT_PEN
		pen = info.u.penInfo
		pen.pointerInfo.pointerType = PT_PEN
		pen.pointerInfo.pointerId = 0
		pen.pointerInfo.ptPixelLocation = wintypes.POINT(x, y)
		pen.pointerInfo.pointerFlags = flags
		pen.penMask = PEN_MASK_PRESSURE
		pen.pressure = p
		if not u.InjectSyntheticPointerInput(_penDevice, ctypes.byref(info), 1):
			raise TouchError("pen")

	frame(POINTER_FLAG_INRANGE | POINTER_FLAG_UPDATE, 0)
	time.sleep(0.03)
	frame(POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT | POINTER_FLAG_FIRSTBUTTON | POINTER_FLAG_DOWN, pressure)
	for _i in range(8):
		time.sleep(0.03)
		frame(POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT | POINTER_FLAG_FIRSTBUTTON | POINTER_FLAG_UPDATE, pressure)
	frame(POINTER_FLAG_INRANGE | POINTER_FLAG_UP, 0)
	time.sleep(0.03)
	frame(POINTER_FLAG_UPDATE, 0)


def perform(key, x, y):
	"""Do a gesture at a point on the screen. Raises TouchError when Windows does not allow it."""
	if key in PEN:
		_pen(x, y, PEN_PRESSURE[key])
		return
	_initTouch()
	path = frames(key, x, y)
	if key == "doubleTap":
		_touchPath(path)
		time.sleep(0.08)
		_touchPath(path)
	elif key == "longPress":
		_touchPath(path, hold=LONG_PRESS_SECONDS)
	else:
		_touchPath(path)
