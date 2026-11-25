# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""A portable copy of VisionMate, for a flash drive or another computer: the add-on file and the vision data in one
folder, so the other computer needs no 1.5 GB download. No NVDA modules here, so it can be tested on its own."""
import json
import os
import shutil
import string
import zipfile

FOLDER = "VisionMate portable"
DATA_FOLDER = "vision data"
ADDON_FILE = "VisionMate.nvda-addon"
STATE = "data.json"
README = "Read me.txt"
_BLOCK = 1 << 20
DRIVE_REMOVABLE, DRIVE_FIXED = 2, 3


class Cancelled(Exception):
	pass


def _files(dataDir):
	with open(os.path.join(dataDir, STATE), encoding="utf-8") as f:
		state = json.load(f)
	return state, [os.path.basename(n) for n in state.get("files", ())]


def size(addonDir, dataDir):
	"""Bytes a portable copy needs."""
	total = 0
	for dirpath, dirnames, files in os.walk(addonDir):
		dirnames[:] = [d for d in dirnames if d != "__pycache__"]
		total += sum(os.path.getsize(os.path.join(dirpath, n)) for n in files if not n.endswith(".pyc"))
	_state, names = _files(dataDir)
	return total + sum(os.path.getsize(os.path.join(dataDir, n)) for n in names)


def _copy(src, dst, onBytes, cancel):
	with open(src, "rb") as i, open(dst + ".tmp", "wb") as o:
		for block in iter(lambda: i.read(_BLOCK), b""):
			if cancel is not None and cancel.is_set():
				o.close()
				os.remove(dst + ".tmp")
				raise Cancelled()
			o.write(block)
			onBytes(len(block))
	os.replace(dst + ".tmp", dst)


def make(addonDir, dataDir, target, readme, onProgress=None, cancel=None):
	"""Write the portable copy into target/VisionMate portable. Returns its folder."""
	out = os.path.join(target, FOLDER)
	data = os.path.join(out, DATA_FOLDER)
	os.makedirs(data, exist_ok=True)
	total = size(addonDir, dataDir)
	done = [0]

	def onBytes(n):
		done[0] += n
		if onProgress is not None:
			onProgress(done[0], total)

	addon = os.path.join(out, ADDON_FILE)
	with zipfile.ZipFile(addon + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
		for dirpath, dirnames, files in os.walk(addonDir):
			dirnames[:] = [d for d in dirnames if d != "__pycache__"]
			for name in files:
				if name.endswith(".pyc"):
					continue
				full = os.path.join(dirpath, name)
				z.write(full, os.path.relpath(full, addonDir))
				onBytes(os.path.getsize(full))
				if cancel is not None and cancel.is_set():
					z.close()
					os.remove(addon + ".tmp")
					raise Cancelled()
	os.replace(addon + ".tmp", addon)
	state, names = _files(dataDir)
	for name in names:
		_copy(os.path.join(dataDir, name), os.path.join(data, name), onBytes, cancel)
	with open(os.path.join(data, STATE), "w", encoding="utf-8") as f:
		json.dump(state, f)
	with open(os.path.join(out, README), "w", encoding="utf-8-sig") as f:
		f.write(readme)
	return out


def isCopy(folder):
	"""True if folder is a portable copy's vision data, or a portable copy holding it."""
	return findData(folder) is not None


def findData(folder):
	"""The vision data folder of a portable copy at folder, or None."""
	for candidate in (folder, os.path.join(folder, DATA_FOLDER), os.path.join(folder, FOLDER, DATA_FOLDER)):
		try:
			_state, names = _files(candidate)
		except (OSError, ValueError):
			continue
		if names and all(os.path.isfile(os.path.join(candidate, n)) for n in names):
			return candidate
	return None


def findOnDrives():
	"""A portable copy's vision data on the root of any drive, like a flash drive, or None."""
	try:
		import ctypes
		getType = ctypes.windll.kernel32.GetDriveTypeW
	except (ImportError, AttributeError, OSError):
		return None
	for letter in string.ascii_uppercase[2:]:
		root = f"{letter}:\\"
		# Only flash drives and local disks: a network drive that is gone can keep Windows waiting for a long time.
		if getType(root) not in (DRIVE_REMOVABLE, DRIVE_FIXED):
			continue
		folder = os.path.join(root, FOLDER, DATA_FOLDER)
		try:
			if os.path.isfile(os.path.join(folder, STATE)):
				found = findData(folder)
				if found:
					return found
		except OSError:
			continue
	return None


def install(source, dataDir, onProgress=None, cancel=None):
	"""Copy a portable copy's vision data into dataDir. Returns True when done."""
	source = findData(source)
	if source is None:
		raise ValueError("This folder has no VisionMate vision data.")
	state, names = _files(source)
	total = sum(os.path.getsize(os.path.join(source, n)) for n in names)
	existing = os.path.abspath(dataDir)
	while not os.path.exists(existing) and os.path.dirname(existing) != existing:
		existing = os.path.dirname(existing)
	free = shutil.disk_usage(existing).free
	if free < total:
		raise OSError("There is not enough free space for the vision data.")
	os.makedirs(dataDir, exist_ok=True)
	done = [0]

	def onBytes(n):
		done[0] += n
		if onProgress is not None:
			onProgress(done[0], total)

	try:
		os.remove(os.path.join(dataDir, STATE))  # the data counts as missing until the copy is complete
	except OSError:
		pass
	for name in names:
		_copy(os.path.join(source, name), os.path.join(dataDir, name), onBytes, cancel)
	with open(os.path.join(dataDir, STATE), "w", encoding="utf-8") as f:
		json.dump(state, f)
	return True
