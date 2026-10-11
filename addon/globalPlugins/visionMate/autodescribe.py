# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - finds images without a useful label as NVDA reads a document,
# so they can be described automatically.

import re

import controlTypes
import textInfos

# A label that is only a file name or a generic word does not describe the image.
_USELESS_LABEL = re.compile(
	r"^\s*(image|img|graphic|picture|photo|icon|spacer|logo|banner|untitled|unlabeled)?[\s_-]*\d*\s*$"
	r"|\.(png|jpe?g|gif|webp|svg|bmp|ico|avif)(\?.*)?\s*$"
	r"|^\s*(img|dsc|dscn|pxl|screenshot|photo|image)[\s_-]*\d",
	re.IGNORECASE,
)
# Smaller images are usually icons, bullets or spacers.
MIN_SIDE = 40


def isUnlabeled(name):
	return not name or not name.strip() or bool(_USELESS_LABEL.search(name))


def findUnlabeledGraphic(info):
	"""Return the NVDAObject of the first unlabeled image in a browse mode TextInfo, or None."""
	document = getattr(info, "obj", None)
	getObject = getattr(document, "getNVDAObjectFromIdentifier", None)
	if getObject is None:
		return None
	for item in info.getTextWithFields():
		if not isinstance(item, textInfos.FieldCommand) or item.command != "controlStart":
			continue
		attrs = item.field
		if attrs.get("role") != controlTypes.Role.GRAPHIC or not isUnlabeled(attrs.get("name")):
			continue
		try:
			return getObject(int(attrs["controlIdentifier_docHandle"]), int(attrs["controlIdentifier_ID"]))
		except Exception:  # missing IDs, COM errors, or a document that is going away
			continue
	return None


def bigEnough(location):
	return bool(location) and location.width >= MIN_SIDE and location.height >= MIN_SIDE
