# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Builds the VisionMate add-on. Updates reach users through the NVDA Add-on Store.

Usage:
  python build.py

Needs dist/data.json from tools/make_datapack.py. Writes to dist/:
  VisionMate-<version>.nvda-addon   the add-on (submit this to the Add-on Store)
  VisionMate.nvda-addon             the same file under a fixed name, for the README's direct download link
"""
import argparse
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


def main():
	ap = argparse.ArgumentParser()
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
	print(f"Built {out} ({os.path.getsize(out) // 2**20} MB)")


if __name__ == "__main__":
	main()
