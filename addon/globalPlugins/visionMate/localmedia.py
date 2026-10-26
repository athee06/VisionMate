# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - full-size photos for chat apps that only show a small preview. Some apps keep each downloaded photo
# as a plain file, like Unigram (Telegram). The file that matches the preview on screen is found by its shape, then
# by a small fingerprint, then by comparing the best few closely, so small text can be read from the full photo.

import glob
import os
import threading

from logHandler import log

# App name in NVDA: folders with the app's downloaded photos. Unigram keeps one folder per account.
_APP_FOLDERS = {
	"telegram": [r"%LOCALAPPDATA%\Packages\*Unigram*\LocalState\*\photos"],
	"unigram": [r"%LOCALAPPDATA%\Packages\*Unigram*\LocalState\*\photos"],
}
# Width divided by height may differ this much, because the preview's edges are cut to the pixel.
SHAPE_TOLERANCE = 0.04
FINGERPRINT_SIDE = 16
CLOSE_CHECKS = 6
# Average difference per pixel, 0 to 255, for the preview and the file to be the same photo.
MAX_DIFFERENCE = 6
# The next best file must differ at least this many times more, or the match is not sure.
MIN_MARGIN = 2
# Two files whose fingerprints differ less than this are the same photo.
SAME_PHOTO = 1.0
# Only worth it if the file is bigger than the preview.
MIN_GAIN = 1.2

_lock = threading.Lock()
# path: (modified time, width, height, fingerprint or None)
_index = {}


def folders(appName):
	found = []
	for pattern in _APP_FOLDERS.get((appName or "").lower(), ()):
		found.extend(f for f in glob.glob(os.path.expandvars(pattern)) if os.path.isdir(f))
	return found


def _fingerprint(image):
	from PIL import ImageOps
	small = ImageOps.grayscale(image.convert("RGB")).resize((FINGERPRINT_SIDE, FINGERPRINT_SIDE))
	return small.tobytes()


def _distance(a, b):
	return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _entries(folderList):
	"""(path, width, height) of every photo in the folders. Sizes are kept, so only new files are opened."""
	from PIL import Image
	entries = []
	for folder in folderList:
		try:
			listing = list(os.scandir(folder))
		except OSError:
			continue
		for entry in listing:
			try:
				mtime = entry.stat().st_mtime
			except OSError:
				continue
			with _lock:
				known = _index.get(entry.path)
			if known is None or known[0] != mtime:
				try:
					with Image.open(entry.path) as image:
						width, height = image.size
				except Exception:
					width = height = 0  # not a picture, or still being written
				known = (mtime, width, height, None)
				with _lock:
					_index[entry.path] = known
			if known[1] and known[2]:
				entries.append((entry.path, known[1], known[2]))
	return entries


def _filePrint(path):
	from PIL import Image
	with _lock:
		known = _index.get(path)
	if known is not None and known[3] is not None:
		return known[3]
	with Image.open(path) as image:
		image.draft("RGB", (FINGERPRINT_SIDE * 4, FINGERPRINT_SIDE * 4))  # JPEG decodes small, which is fast
		fingerprint = _fingerprint(image)
	if known is not None:
		with _lock:
			_index[path] = known[:3] + (fingerprint,)
	return fingerprint


_warmed = set()


def warmUp(appName):
	"""Read the sizes of the app's photos in the background the first time the app is used, so the first search is
	quick too."""
	appName = (appName or "").lower()
	if appName in _warmed or appName not in _APP_FOLDERS:
		return
	_warmed.add(appName)

	def run():
		try:
			_entries(folders(appName))
		except Exception:
			log.debugWarning("VisionMate: could not read the app's photos", exc_info=True)

	threading.Thread(target=run, name="visionMate-media", daemon=True).start()


def findOriginal(preview, appName):
	"""The path of the full-size photo the preview shows, or None if the app keeps none or no match is sure."""
	from PIL import Image, ImageChops, ImageOps, ImageStat
	folderList = folders(appName)
	if not folderList or preview.width < 16 or preview.height < 16:
		return None
	shape = preview.width / preview.height
	try:
		candidates = [(p, w, h) for p, w, h in _entries(folderList)
			if abs(w / h - shape) / shape < SHAPE_TOLERANCE and w >= preview.width * MIN_GAIN]
		if not candidates:
			return None
		wanted = _fingerprint(preview)
		ranked = sorted(candidates, key=lambda c: _distance(wanted, _filePrint(c[0])))[:CLOSE_CHECKS]
		gray = ImageOps.grayscale(preview.convert("RGB"))
		checked = []
		for path, _w, _h in ranked:
			with Image.open(path) as image:
				image.draft("RGB", preview.size)
				other = ImageOps.grayscale(image.convert("RGB")).resize(preview.size)
			checked.append((ImageStat.Stat(ImageChops.difference(gray, other)).mean[0], path))
	except Exception:
		log.debugWarning("VisionMate: could not search the app's photos", exc_info=True)
		return None
	checked.sort()
	best, path = checked[0]
	if best > MAX_DIFFERENCE:
		return None
	if len(checked) > 1 and checked[1][0] < best * MIN_MARGIN:
		# Two files look like the preview. If they are the same photo, like one sent twice, either will do.
		if _distance(_filePrint(path), _filePrint(checked[1][1])) > SAME_PHOTO:
			return None
	return path
