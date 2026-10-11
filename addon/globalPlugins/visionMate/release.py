# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - where updates and the vision data are published.
# Set GITHUB_REPO to your "owner/repository" before building a release. See docs/PUBLISHING.md.

import os

GITHUB_REPO = "athee06/VisionMate"

# update.json is attached to every add-on release; "latest" always points to the newest one.
# VISIONMATE_UPDATE_URL overrides it for testing against a local server.
UPDATE_URL = os.environ.get(
	"VISIONMATE_UPDATE_URL",
	f"https://github.com/{GITHUB_REPO}/releases/latest/download/update.json",
)


def parseVersion(text):
	parts = []
	for p in str(text).split("."):
		digits = "".join(ch for ch in p if ch.isdigit())
		parts.append(int(digits) if digits else 0)
	return tuple(parts)


def isNewer(candidate, current):
	return parseVersion(candidate) > parseVersion(current)
