# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - image files in File Explorer and on the desktop. Windows says which file has the focus in each
# Explorer window, so the file itself is described without opening or copying it.

import os

from logHandler import log

from . import viewers

APP_NAME = "explorer"
_shell = None


def isExplorer(appName):
	return (appName or "").lower() == APP_NAME


def _windows():
	global _shell
	if _shell is None:
		import comtypes.client
		_shell = comtypes.client.CreateObject("Shell.Application", dynamic=True)
	return _shell.Windows()


def _sameName(itemName, path):
	"""Explorer may hide file extensions, so "beach" names beach.jpg."""
	base = os.path.basename(path)
	return itemName in (base, os.path.splitext(base)[0])


def focusedFile(hwnd, itemName):
	"""The path of the item with the focus in the Explorer window hwnd, or None. With several tabs in one window,
	the tab whose focused item has this name is used."""
	found = []
	try:
		windows = _windows()
		for i in range(windows.Count):
			window = windows.Item(i)
			if window is None:
				continue
			try:
				if int(window.HWND) != hwnd:
					continue
				item = window.Document.FocusedItem
				if item is not None and not item.IsFolder:
					found.append(item.Path)
			except Exception:
				continue  # a tab that is not a folder, like Home, or one that is closing
	except Exception:
		global _shell
		_shell = None
		log.debugWarning("VisionMate: could not ask Explorer for the focused file", exc_info=True)
		return None
	named = [p for p in found if _sameName(itemName or "", p)]
	if named:
		return named[0]
	return found[0] if len(found) == 1 else None


def _desktopFolders():
	home = os.path.expanduser("~")
	public = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop")
	return [f for f in (os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop"), public)
		if os.path.isdir(f)]


def desktopFile(itemName):
	"""The path of a desktop item by its name, or None. The extension may be hidden."""
	if not itemName:
		return None
	for folder in _desktopFolders():
		path = os.path.join(folder, itemName)
		if os.path.isfile(path):
			return path
		for name in os.listdir(folder):
			if os.path.splitext(name)[0] == itemName and os.path.isfile(os.path.join(folder, name)):
				return os.path.join(folder, name)
	return None


def imageFile(hwnd, itemName, onDesktop):
	"""The path of the focused item if it is an image file, else None."""
	path = desktopFile(itemName) if onDesktop else focusedFile(hwnd, itemName)
	return path if path and viewers.IMAGE_FILE.fullmatch(os.path.basename(path)) else None
