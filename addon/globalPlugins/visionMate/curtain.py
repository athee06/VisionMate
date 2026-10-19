# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - takes pictures of the screen while NVDA's screen curtain is on, without lifting the curtain.
# With the curtain on, a normal screenshot is black, but each window can still draw itself into a picture.

import ctypes
from ctypes import wintypes

from logHandler import log


class CurtainBlocked(Exception):
	"""The screen curtain is on and the picture came out black anyway, so the user must turn the curtain off."""


class _Curtain2026:
	"""NVDA 2026 and later: the screenCurtain module."""

	def __init__(self, curtain):
		self._curtain = curtain

	@property
	def enabled(self):
		return self._curtain.enabled


class _CurtainProvider:
	"""Older NVDA: the screen curtain is a vision enhancement provider."""

	def __init__(self, info):
		import vision
		self._handler = vision.handler
		self._info = info

	@property
	def enabled(self):
		return self._handler.getProviderInstance(self._info) is not None


def _find():
	try:
		import screenCurtain
		curtain = getattr(screenCurtain, "screenCurtain", None)
		return _Curtain2026(curtain) if curtain is not None else None
	except ImportError:
		pass
	try:
		import vision
		info = vision.handler.getProviderInfo("screenCurtain") if vision.handler else None
		return _CurtainProvider(info) if info is not None else None
	except ImportError:
		return None
	except Exception:
		log.debugWarning("VisionMate: could not find the screen curtain", exc_info=True)
		return None


def isOn():
	curtain = _find()
	try:
		return curtain is not None and curtain.enabled
	except Exception:
		return False


def isBlack(image):
	small = image.convert("L").resize((64, 64))
	return small.getextrema()[1] < 16


# Windows can draw each window into a picture of its own (PrintWindow), and that still works under the
# screen curtain, so the curtain never has to be lifted. The windows are painted bottom to top.
PW_RENDERFULLCONTENT = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_LAYERED = 0x80000


class _RECT(ctypes.Structure):
	_fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _BITMAPINFOHEADER(ctypes.Structure):
	_fields_ = [
		("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
		("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
		("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
		("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
	]


def _screenBox():
	metric = ctypes.windll.user32.GetSystemMetrics
	left, top = metric(76), metric(77)
	return left, top, left + metric(78), top + metric(79)


def _shown(hwnd):
	"""The visible part of a top-level window on screen, or None if it isn't drawn."""
	user32 = ctypes.windll.user32
	# A hung window would never finish drawing itself.
	if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or user32.IsHungAppWindow(hwnd):
		return None
	exStyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
	if exStyle & WS_EX_TRANSPARENT:
		return None
	if exStyle & WS_EX_LAYERED:
		alpha, flags = ctypes.c_ubyte(), wintypes.DWORD()
		if user32.GetLayeredWindowAttributes(hwnd, None, ctypes.byref(alpha), ctypes.byref(flags)) \
				and flags.value & 2 and alpha.value == 0:
			return None
	dwm = ctypes.windll.dwmapi
	cloaked = wintypes.DWORD()
	if dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
		return None
	window, frame = _RECT(), _RECT()
	if not user32.GetWindowRect(hwnd, ctypes.byref(window)):
		return None
	if dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(frame), ctypes.sizeof(frame)) != 0:
		frame = window
	if frame.right <= frame.left or frame.bottom <= frame.top:
		return None
	return (window.left, window.top, window.right, window.bottom), (frame.left, frame.top, frame.right, frame.bottom)


def _printWindow(hwnd, size):
	from PIL import Image
	user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
	width, height = size
	screenDC = user32.GetDC(None)
	memDC = gdi32.CreateCompatibleDC(screenDC)
	bitmap = gdi32.CreateCompatibleBitmap(screenDC, width, height)
	old = gdi32.SelectObject(memDC, bitmap)
	try:
		if not user32.PrintWindow(hwnd, memDC, PW_RENDERFULLCONTENT):
			return None
		info = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
		data = ctypes.create_string_buffer(width * height * 4)
		if not gdi32.GetDIBits(memDC, bitmap, 0, height, data, ctypes.byref(info), 0):
			return None
		return Image.frombuffer("RGB", size, data, "raw", "BGRX", 0, 1)
	finally:
		gdi32.SelectObject(memDC, old)
		gdi32.DeleteObject(bitmap)
		gdi32.DeleteDC(memDC)
		user32.ReleaseDC(None, screenDC)


def grabWindows(bbox=None):
	"""A picture of the screen (or of bbox, in screen coordinates) built from the windows on it."""
	from PIL import Image
	user32 = ctypes.windll.user32
	box = bbox or _screenBox()
	windows = []

	@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
	def collect(hwnd, lParam):
		windows.append(hwnd)
		return True

	user32.EnumWindows(collect, 0)
	canvas = Image.new("RGB", (box[2] - box[0], box[3] - box[1]))
	for hwnd in reversed(windows):
		try:
			shown = _shown(hwnd)
			if shown is None:
				continue
			window, frame = shown
			if frame[2] <= box[0] or frame[0] >= box[2] or frame[3] <= box[1] or frame[1] >= box[3]:
				continue
			picture = _printWindow(hwnd, (window[2] - window[0], window[3] - window[1]))
			if picture is None:
				continue
			# Only the visible frame, without the invisible resize borders around it.
			picture = picture.crop((frame[0] - window[0], frame[1] - window[1], frame[2] - window[0], frame[3] - window[1]))
			canvas.paste(picture, (frame[0] - box[0], frame[1] - box[1]))
		except Exception:
			log.debugWarning("VisionMate: could not draw a window", exc_info=True)
	return canvas


def capture(bbox=None):
	"""A picture of the screen, or of bbox in screen coordinates. Never lifts the screen curtain.
	Raises CurtainBlocked if the curtain is on and the windows could not be drawn."""
	if not isOn():
		from PIL import ImageGrab
		return ImageGrab.grab(bbox=bbox, all_screens=True)
	image = grabWindows(bbox)
	if isBlack(image):
		raise CurtainBlocked()
	return image
