# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Builds the VisionMate add-on and its update.json.

Usage:
  python build.py --changes "What's new in this version"

Needs dist/data.json from tools/make_datapack.py. Writes to dist/:
  VisionMate-<version>.nvda-addon   the add-on (used by the updater)
  VisionMate.nvda-addon             the same file under a fixed name, for the README's direct download link
  update.json                       tells installed copies about the new add-on and data versions
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "addon")
PLUGIN = os.path.join(SRC, "globalPlugins", "visionMate")
DIST = os.path.join(ROOT, "dist")
sys.path.insert(0, PLUGIN)
import release  # noqa: E402


def sha256(path):
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for block in iter(lambda: f.read(1 << 20), b""):
			h.update(block)
	return h.hexdigest()


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--changes", default="", help="Release notes shown in the update prompt")
	ap.add_argument("--allow-placeholder", action="store_true", help="Build even if GITHUB_REPO is not set (testing)")
	a = ap.parse_args()
	if release.GITHUB_REPO.startswith("OWNER/") and not a.allow_placeholder:
		sys.exit("Set GITHUB_REPO in addon/globalPlugins/visionMate/release.py first.")
	manifest = open(os.path.join(SRC, "manifest.ini"), encoding="utf-8").read()
	version = re.search(r"^version\s*=\s*(\S+)", manifest, re.M).group(1)
	with open(os.path.join(DIST, "data.json"), encoding="utf-8") as f:
		data = json.load(f)
	base = f"https://github.com/{release.GITHUB_REPO}/releases/download"
	dataInfo = {
		"version": data["version"], "size": data["size"], "sha256": data["sha256"],
		"url": f"{base}/data-{data['version']}/{data['file']}",
	}
	# The add-on carries the data download details so the welcome window works without an update check.
	with open(os.path.join(PLUGIN, "datainfo.json"), "w", encoding="utf-8") as f:
		json.dump(dataInfo, f, indent=2)

	out = os.path.join(DIST, f"VisionMate-{version}.nvda-addon")
	with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
		for dirpath, dirnames, files in os.walk(SRC):
			dirnames[:] = [d for d in dirnames if d != "__pycache__"]
			for name in files:
				full = os.path.join(dirpath, name)
				z.write(full, os.path.relpath(full, SRC))
	# releases/latest/download/VisionMate.nvda-addon then always downloads the newest version.
	shutil.copyfile(out, os.path.join(DIST, "VisionMate.nvda-addon"))
	update = {
		"addon": {
			"version": version, "changes": a.changes, "size": os.path.getsize(out), "sha256": sha256(out),
			"url": f"{base}/v{version}/{os.path.basename(out)}",
		},
		"data": dataInfo,
	}
	with open(os.path.join(DIST, "update.json"), "w", encoding="utf-8") as f:
		json.dump(update, f, indent=2)
	print(f"Built {out} ({os.path.getsize(out) // 2**20} MB) and dist/update.json")


if __name__ == "__main__":
	main()
