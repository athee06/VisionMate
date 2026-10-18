# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - reads text in images with Windows OCR, the same engine as NVDA+R.

import ctypes
import threading

import wx
from logHandler import log

# Windows OCR reads small screen text better when the picture is enlarged.
UPSCALE_BELOW_PIXELS = 1500000
TIMEOUT_SECONDS = 5
# The most OCR text added to a prompt.
MAX_PROMPT_CHARS = 1500


def _recognizer():
	try:
		from contentRecog import uwpOcr
		return uwpOcr.UwpOcr()
	except Exception:  # Windows OCR missing, no OCR language installed, or an NVDA without it
		log.debugWarning("VisionMate: Windows OCR is not available", exc_info=True)
		return None


def recognizeAsync(image, onLines):
	"""Read the text in a PIL image. Must be called on NVDA's main thread.
	onLines(lines) is called later, from another thread, with a list of lines; each line is a list of words like
	{"x": 10, "y": 5, "width": 40, "height": 12, "text": "Play"} in image pixels. It gets None if OCR failed."""
	recognizer = _recognizer()
	try:
		from contentRecog import RecogImageInfo
	except ImportError:
		recognizer = None
	if recognizer is None:
		onLines(None)
		return None
	w, h = image.size
	factor = 2 if w * h < UPSCALE_BELOW_PIXELS else 1
	if factor > 1:
		image = image.resize((w * factor, h * factor))
	data = image.convert("RGBA").tobytes("raw", "BGRA")
	pixels = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
	info = RecogImageInfo(0, 0, w * factor, h * factor, 1)

	def onResult(result):
		lines = getattr(result, "data", None)
		if isinstance(result, Exception) or lines is None:
			log.debugWarning(f"VisionMate: OCR failed: {result!r}")
			onLines(None)
			return
		if factor > 1:
			lines = [[dict(word, x=word["x"] // factor, y=word["y"] // factor, width=word["width"] // factor,
				height=word["height"] // factor) for word in line] for line in lines]
		onLines(lines)

	try:
		recognizer.recognize(pixels, info, onResult)
	except Exception:
		log.debugWarning("VisionMate: OCR could not start", exc_info=True)
		onLines(None)
		return None
	return recognizer


def recognize(image, timeout=TIMEOUT_SECONDS):
	"""Read the text in a PIL image and wait for it. Call from a background thread, never the main one.
	Returns lines as in recognizeAsync, or None."""
	done = threading.Event()
	box = []

	def onLines(lines):
		box.append(lines)
		done.set()

	wx.CallAfter(recognizeAsync, image, onLines)
	if not done.wait(timeout):
		log.debugWarning("VisionMate: OCR timed out")
		return None
	return box[0]


def linesText(lines):
	return "\n".join(" ".join(word["text"] for word in line) for line in lines or ())


def rows(lines):
	"""Put OCR lines into visual rows, top to bottom and left to right.
	OCR reads columns separately, so a label and its value would otherwise end up far apart."""
	lines = [line for line in lines or () if line]
	if not lines:
		return []
	heights = sorted(min(w["height"] for w in line) for line in lines)
	band = max(4, heights[len(heights) // 2] * 0.6)
	result = []
	for line in sorted(lines, key=lambda line: (line[0]["y"], line[0]["x"])):
		center = line[0]["y"] + line[0]["height"] / 2
		if result and abs(result[-1][0] - center) <= band:
			result[-1][1].append(line)
		else:
			result.append([center, [line]])
	return [sorted(group, key=lambda line: line[0]["x"]) for _center, group in result]


def rowsText(lines):
	return "\n".join("   ".join(" ".join(w["text"] for w in line) for line in row) for row in rows(lines))


def promptPart(lines):
	"""OCR text for a prompt, so the vision data reads text exactly."""
	text = rowsText(lines).strip()
	if len(text) < 3:
		return ""
	if len(text) > MAX_PROMPT_CHARS:
		text = text[:MAX_PROMPT_CHARS].rsplit(" ", 1)[0] + " ..."
	return (
		"Text found on the screen by OCR, row by row. Screen text is spelled right here, so use it when you "
		"read text, but it may miss stylised text:\n\"\"\"\n" + text + "\n\"\"\"\n"
	)
