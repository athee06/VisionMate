# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - finds images without a useful label as NVDA reads a document,
# so they can be described automatically.

import re

import controlTypes
import textInfos

# A label that is only a file name, a link, a code or a generic word does not describe the image.
_GENERIC = (
	"image|img|images|graphic|graphics|picture|pic|photo|photograph|foto|icon|spacer|logo|banner|untitled"
	"|unlabeled|unlabelled|unnamed|thumbnail|thumb|placeholder|blank|default|dummy|null|undefined|none"
	"|alt|alt text|no alt|pixel|transparent|clear|download|attachment|media|figure|screen shot|screenshot"
)
_USELESS_LABEL = re.compile(
	rf"^\W*(?:(?:{_GENERIC})[\s_-]*)*\d*\W*$"
	r"|\.(png|jpe?g|gif|webp|svg|bmp|ico|avif|tiff?|heic)(\?.*)?\s*$"
	r"|^\s*(img|dsc|dscn|pxl|screenshot|screen shot|photo|image|whatsapp image|pexels|unsplash)[\s_-]*\d"
	r"|^\s*https?://\S*\s*$"
	r"|^\s*[0-9a-f-]{16,}\s*$",
	re.IGNORECASE,
)
# Smaller images are usually icons, bullets or spacers.
MIN_SIDE = 40
# Long thin images are lines, dividers or borders.
MAX_ASPECT = 10
# Nearly one colour: a spacer, a blank image, or one that has not loaded yet.
MIN_CONTRAST = 4
# The same picture in this many places on a page is a bullet, a rating star or another repeated icon.
REPEATS = 3


def isUnlabeled(name):
	if not name or not name.strip():
		return True
	# A long label is a real description (and checking it could be slow).
	return len(name) <= 200 and bool(_USELESS_LABEL.search(name))


def findUnlabeledGraphics(info, limit=1):
	"""Find unlabeled images in a TextInfo. Returns up to limit pairs of (locate, place):
	locate() gives the image's location on screen (or None), and place identifies the image in the document.
	Browse mode documents name each image; in other documents, like Word or Outlook, the image's
	position in the text is used."""
	document = getattr(info, "obj", None)
	getObject = getattr(document, "getNVDAObjectFromIdentifier", None)
	found = []
	offset = 0
	for item in info.getTextWithFields():
		if isinstance(item, str):
			offset += len(item)
			continue
		if not isinstance(item, textInfos.FieldCommand) or item.command != "controlStart":
			continue
		attrs = item.field
		if attrs.get("role") != controlTypes.Role.GRAPHIC or not isUnlabeled(attrs.get("name")):
			continue
		if getObject is not None:
			try:
				ident = (int(attrs["controlIdentifier_docHandle"]), int(attrs["controlIdentifier_ID"]))
				obj = getObject(*ident)
			except Exception:  # missing IDs, COM errors, or a document that is going away
				continue
			found.append((lambda obj=obj: obj.location, ident))
		else:
			found.append((lambda offset=offset: _locateAt(info, offset), ("offset", offset, _bookmark(info))))
		if len(found) >= limit:
			break
	return found


def findUnlabeledGraphic(info):
	"""The first unlabeled image, as (locate, place), or None."""
	found = findUnlabeledGraphics(info, limit=1)
	return found[0] if found else None


def _bookmark(info):
	try:
		return repr(info.bookmark)
	except Exception:
		return None


def _locateAt(info, offset):
	"""Where the character at offset in info is on screen. An inline picture is one character."""
	try:
		char = info.copy()
		char.collapse()
		if offset:
			char.move(textInfos.UNIT_CHARACTER, offset)
		char.expand(textInfos.UNIT_CHARACTER)
		rects = char.boundingRects
	except Exception:  # not supported by this kind of document
		return None
	return rects[0] if rects else None


def bigEnough(location):
	if not location or location.width < MIN_SIDE or location.height < MIN_SIDE:
		return False
	return max(location.width, location.height) <= MAX_ASPECT * min(location.width, location.height)


def isBlank(image):
	"""True if the image is nearly a single colour."""
	from PIL import ImageStat
	small = image.convert("L").resize((32, 32))
	return ImageStat.Stat(small).stddev[0] < MIN_CONTRAST


class RepeatTracker:
	"""Remembers in how many places of each document an image appears."""

	def __init__(self):
		self._document = None
		self._places = {}

	def seen(self, document, imageKey, place):
		"""Record the image at this place. Returns True if it is a repeated decorative image."""
		if document is not self._document:
			self._document = document
			self._places = {}
		places = self._places.setdefault(imageKey, set())
		places.add(place)
		return len(places) >= REPEATS
