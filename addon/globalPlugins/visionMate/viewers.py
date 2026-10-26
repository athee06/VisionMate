# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - image viewers. Viewers like Windows Photos put the file name in their title. The file itself is
# found, so the whole photo is described at full quality instead of a picture of the screen.

import glob
import os
import re
import tempfile

from logHandler import log

IMAGE_FILE = re.compile(r"[^\\/:*?\"<>|\r\n]+\.(?:jpe?g|png|webp|gif|bmp|tiff?|heic|heif|avif|jfif)", re.IGNORECASE)
# Windows keeps a shortcut to each recently opened file here, which says where the file is.
RECENT_DIR = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Recent")


# Titles join the file and the app name with a dash or bar, and may hold invisible direction marks.
_TITLE_PARTS = re.compile(r"\s+[-\u2013\u2014|]\s+")
_MARKS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def imageName(title):
	"""The image file name in a window title, like "beach.jpg - Photos" or "Photos - beach.jpg", or None."""
	title = _MARKS.sub("", title or "")
	for part in _TITLE_PARTS.split(title):
		part = part.strip()
		if IMAGE_FILE.fullmatch(part):
			return part
	return None


def _folders():
	home = os.path.expanduser("~")
	folders = [tempfile.gettempdir()]
	for name in ("Downloads", "Pictures", "Desktop", "Documents", "Videos"):
		folders.append(os.path.join(home, name))
		folders.append(os.path.join(home, "OneDrive", name))
	folders.append(os.path.join(home, "Pictures", "Screenshots"))
	folders.append(os.path.join(home, "Pictures", "Camera Roll"))
	return [f for f in folders if os.path.isdir(f)]


def _fromRecent(name):
	"""Where a recently opened file is, from Windows' shortcut to it."""
	link = os.path.join(RECENT_DIR, name + ".lnk")
	if not os.path.isfile(link):
		return None
	try:
		import comtypes.client
		target = comtypes.client.CreateObject("WScript.Shell").CreateShortcut(link).TargetPath
	except Exception:
		log.debugWarning("VisionMate: could not read a recent file shortcut", exc_info=True)
		return None
	return target if target and os.path.isfile(target) else None


def findImage(name):
	"""The newest file with this name: from Windows' recent files, else from the usual folders. None if not found."""
	if not name:
		return None
	found = _fromRecent(name)
	if found:
		return found
	matches = []
	for folder in _folders():
		pattern = glob.escape(name)
		matches.extend(glob.glob(os.path.join(folder, pattern)))
		matches.extend(glob.glob(os.path.join(folder, "*", pattern)))
	matches = [m for m in matches if os.path.isfile(m)]
	return max(matches, key=os.path.getmtime) if matches else None


def imageInWindow(title):
	"""(path, name) of the image file a viewer window shows, from its title, or None."""
	name = imageName(title)
	path = findImage(name)
	return (path, name) if path else None


def openImage(path):
	"""The picture in a file, or None if it cannot be read."""
	from PIL import Image
	try:
		with Image.open(path) as image:
			image.load()
			return image.copy()
	except Exception:
		log.debugWarning("VisionMate: could not open an image file", exc_info=True)
		return None
