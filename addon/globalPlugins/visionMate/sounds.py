# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - short sounds instead of plain beeps. They play at NVDA's sound volume.

import os

from logHandler import log

SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "sounds")
# Used if a sound file cannot be played: (frequency, milliseconds).
_FALLBACK = {
	"quick": (880, 25), "detailed": (660, 40), "working": (440, 20), "done": (880, 40), "send": (1000, 25),
	"receive": (760, 40), "overlayOpen": (700, 40), "overlayClose": (520, 40), "click": (2000, 10), "error": (220, 300),
}


def play(name):
	"""Play one of the sounds made by tools/make_sounds.py, by name."""
	path = os.path.join(SOUNDS_DIR, name + ".wav")
	try:
		import nvwave
		nvwave.playWaveFile(path, asynchronous=True)
		return
	except ImportError:
		pass  # outside NVDA, in tests
	except Exception:
		log.debugWarning(f"VisionMate: could not play {name}", exc_info=True)
	try:
		import tones
		tones.beep(*_FALLBACK[name])
	except Exception:
		pass
