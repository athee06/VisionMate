# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - photos in WinZapp, an accessible WhatsApp app. WinZapp shows a photo message as text only and keeps
# its media encrypted, so the photo is never on screen. Its "Open image" button writes the photo to a temporary
# file and opens it in the default viewer. VisionMate presses the button without moving the focus, reads the file,
# and hides and closes the viewer at once, so the user stays on the message and only hears the description.

import ctypes
import gettext
import glob
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from ctypes import wintypes

from logHandler import log

APP_NAME = "winzapp"
# WinZapp's translation key for the button; its text is read from WinZapp's own translations.
OPEN_IMAGE_KEY = "open_image"
OPEN_IMAGE_NAMES = {"Open image"}
PHOTO_PATTERNS = ("tmp*.jpeg", "tmp*.jpg", "tmp*.png", "tmp*.webp", "tmp*.gif", "tmp*.bmp")
# A photo that is not downloaded yet can take a while.
FETCH_SECONDS = 30
# After the photo is read, the viewer is still waited for this long, so it can be closed.
VIEWER_SECONDS = 8
POLL_SECONDS = 0.01
# The closed viewer may hold the photo file for a moment before it can be deleted.
REMOVE_TRIES = 30
REMOVE_WAIT_SECONDS = 0.1
# The Windows Photos app, which WinZapp opens photos in. Other viewers are recognised by the file name in their title.
VIEWER_EXES = {"photos.exe", "microsoft.photos.exe"}
VIEWER_APPS = {"photos", "microsoft.photos"}
STORE_SIZE = 1000

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010
SW_HIDE = 0
GW_HWNDNEXT = 2
_ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Parts of a message's name that change by themselves: the date appears the next day, and the state of your
# own messages goes from sent to delivered to read.
_DATE = re.compile(r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b")
_STATE = re.compile(r",?\s*(read|delivered|sent|pending|played)\s*$", re.IGNORECASE)


def isWinZapp(appName):
	return (appName or "").lower() == APP_NAME


def _text(hwnd):
	buf = ctypes.create_unicode_buffer(256)
	_user32.GetWindowTextW(hwnd, buf, 256)
	return buf.value


def _className(hwnd):
	buf = ctypes.create_unicode_buffer(64)
	_user32.GetClassNameW(hwnd, buf, 64)
	return buf.value


def _plain(label):
	"""A control's text without the & of its shortcut key."""
	return label.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


_namesCache = {}


def openImageNames(appDir):
	"""The text of the "Open image" button in every language WinZapp has."""
	if appDir in _namesCache:
		return _namesCache[appDir]
	names = set(OPEN_IMAGE_NAMES)
	for path in glob.glob(os.path.join(appDir or "", "languages", "*", "LC_MESSAGES", "*.mo")):
		try:
			with open(path, "rb") as f:
				catalog = gettext.GNUTranslations(f)._catalog
		except Exception:
			continue
		for key, value in catalog.items():
			if isinstance(key, str) and key.split("\x04")[0] == OPEN_IMAGE_KEY and isinstance(value, str):
				names.add(_plain(value))
	_namesCache[appDir] = names
	return names


def openImageButton(top, names):
	"""The visible "Open image" button in a WinZapp window, or None. It is there when a photo message is selected."""
	found = []

	@_ENUM
	def check(hwnd, _):
		if _user32.IsWindowVisible(hwnd) and _className(hwnd) == "Button" and _plain(_text(hwnd)) in names:
			found.append(hwnd)
			return False
		return True

	_user32.EnumChildWindows(top, check, 0)
	return found[0] if found else None


def chatName(listHwnd):
	"""The label after the message list, like "Type a message to Ann", which names the chat."""
	hwnd = listHwnd
	for _ in range(20):
		hwnd = _user32.GetWindow(hwnd, GW_HWNDNEXT)
		if not hwnd:
			break
		if _user32.IsWindowVisible(hwnd) and _className(hwnd) == "Static":
			return _plain(_text(hwnd))
	return ""


def messageKey(chat, name):
	"""A key for a message that stays the same from day to day. Only a hash is kept, never the message."""
	name = _STATE.sub("", _DATE.sub("", name or ""))
	name = " ".join(name.replace(" ,", ",").split()).strip(" ,")
	return hashlib.sha1(f"{chat}\n{name}".encode("utf-8")).hexdigest()


def _photoFiles():
	folder = tempfile.gettempdir()
	return {p for pattern in PHOTO_PATTERNS for p in glob.glob(os.path.join(folder, pattern))}


def _processExe(pid):
	handle = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
	if not handle:
		return ""
	try:
		buf = ctypes.create_unicode_buffer(400)
		size = wintypes.DWORD(400)
		if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
			return os.path.basename(buf.value).lower()
		return ""
	finally:
		_kernel32.CloseHandle(handle)


def _topWindows():
	"""{handle: process id} of visible top-level windows."""
	windows = {}

	@_ENUM
	def add(hwnd, _):
		if _user32.IsWindowVisible(hwnd):
			pid = wintypes.DWORD()
			_user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
			windows[hwnd] = pid.value
		return True

	_user32.EnumWindows(add, 0)
	return windows


def _isViewer(hwnd, pid, photoName):
	if photoName and photoName.lower() in _text(hwnd).lower():
		return True
	return _processExe(pid) in VIEWER_EXES and bool(_text(hwnd))


def bringToFront(hwnd):
	"""Put a window in front again. Windows only lets the program in front do this, so its input is joined first."""
	if _user32.GetForegroundWindow() == hwnd:
		return True
	front = _user32.GetForegroundWindow()
	me = _kernel32.GetCurrentThreadId()
	them = _user32.GetWindowThreadProcessId(front, None) if front else 0
	joined = bool(them and them != me and _user32.AttachThreadInput(me, them, True))
	try:
		_user32.SetForegroundWindow(hwnd)
	finally:
		if joined:
			_user32.AttachThreadInput(me, them, False)
	return _user32.GetForegroundWindow() == hwnd


def _readPhoto(path):
	from PIL import Image
	try:
		with Image.open(path) as image:
			image.load()
			return image.copy()
	except Exception:
		return None  # still being written


def _remove(path):
	"""Delete a file the viewer may still hold open for a moment."""
	for _ in range(REMOVE_TRIES):
		try:
			os.remove(path)
			return
		except FileNotFoundError:
			return
		except OSError:
			time.sleep(REMOVE_WAIT_SECONDS)
	log.debugWarning("VisionMate: could not remove WinZapp's copy of a photo")


def fetchPhoto(top, button, cancel, onPhoto, onViewer=None):
	"""Press "Open image" in WinZapp window top, without moving the focus. onPhoto(image or None) is called as soon as
	the photo can be read, or when it does not come. The viewer WinZapp opens is hidden and closed, and the window
	that was in front, normally WinZapp, is put back; onViewer(handle) is called first. WinZapp's copy of the photo
	is deleted afterwards. Runs until the viewer is handled, so call it on a background thread."""
	ownPid = wintypes.DWORD()
	_user32.GetWindowThreadProcessId(top, ctypes.byref(ownPid))
	filesBefore = _photoFiles()
	windowsBefore = set(_topWindows())
	frontBefore = _user32.GetForegroundWindow()
	started = time.monotonic()
	# WM_COMMAND to the parent is what a click sends, but a real click would move the focus to the button.
	_user32.PostMessageW(_user32.GetParent(button), WM_COMMAND, _user32.GetDlgCtrlID(button) & 0xFFFF, button)
	photo = photoPath = None
	photoAt = None
	viewerDone = False
	try:
		while not cancel.is_set():
			now = time.monotonic()
			if photo is None:
				if now - started > FETCH_SECONDS:
					onPhoto(None)
					return
				for path in _photoFiles() - filesBefore:
					if os.path.getmtime(path) < started - 2:
						continue
					photo = _readPhoto(path)
					if photo is not None:
						photoPath, photoAt = path, now
						onPhoto(photo)
						break
			if not viewerDone:
				photoName = os.path.basename(photoPath) if photoPath else None
				for hwnd, pid in _topWindows().items():
					if hwnd in windowsBefore or pid == ownPid.value or not _isViewer(hwnd, pid, photoName):
						continue
					if onViewer is not None:
						onViewer(hwnd)
					_user32.ShowWindow(hwnd, SW_HIDE)
					_user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
					# Only take the front back from the viewer, not from a program the user switched to meanwhile.
					front = _user32.GetForegroundWindow()
					frontPid = wintypes.DWORD()
					_user32.GetWindowThreadProcessId(front, ctypes.byref(frontPid))
					if not front or front == hwnd or frontPid.value == pid:
						bringToFront(frontBefore or top)
					viewerDone = True
					break
			if photo is not None and (viewerDone or now - photoAt > VIEWER_SECONDS):
				if not viewerDone:
					log.debugWarning("VisionMate: WinZapp's viewer was not found to close")
				return
			time.sleep(POLL_SECONDS)
	finally:
		# WinZapp never removes the copy it writes for the viewer. This one was made for VisionMate and is already
		# read, so it is removed, also when the fetch was cancelled.
		if photoPath:
			_remove(photoPath)


class DescriptionStore:
	"""Descriptions of WinZapp photos by message key, so a message says what its photo shows when it is reached
	again. Only the key and the description are kept, never the photo or the message."""

	def __init__(self, path):
		self.path = path
		self._lock = threading.Lock()
		self._items = {}
		try:
			with open(path, encoding="utf-8") as f:
				data = json.load(f)
			if isinstance(data, dict):
				self._items = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
		except FileNotFoundError:
			pass
		except Exception:
			log.debugWarning("VisionMate: could not read WinZapp photo descriptions", exc_info=True)

	def get(self, key):
		with self._lock:
			return self._items.get(key)

	def set(self, key, text):
		with self._lock:
			self._items.pop(key, None)
			self._items[key] = text
			while len(self._items) > STORE_SIZE:
				self._items.pop(next(iter(self._items)))
			items = dict(self._items)
		try:
			tmp = self.path + ".tmp"
			with open(tmp, "w", encoding="utf-8") as f:
				json.dump(items, f, ensure_ascii=False)
			os.replace(tmp, self.path)
		except Exception:
			log.debugWarning("VisionMate: could not save WinZapp photo descriptions", exc_info=True)

	def clear(self):
		with self._lock:
			self._items = {}
		try:
			os.remove(self.path)
		except FileNotFoundError:
			pass
