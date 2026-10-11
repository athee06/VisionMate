# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - resumable, verified downloads. No NVDA dependencies.

import hashlib
import json
import os
import urllib.request

USER_AGENT = "VisionMate"
_BLOCK = 1 << 20


class Cancelled(Exception):
	pass


def fetchJson(url, timeout=20):
	req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
	with urllib.request.urlopen(req, timeout=timeout) as r:
		return json.loads(r.read().decode("utf-8"))


def download(url, dest, size=None, sha256=None, onProgress=None, cancel=None):
	"""Download url to dest, resuming from dest + '.part' if a previous attempt was interrupted.
	Calls onProgress(doneBytes, totalBytes). Raises Cancelled, OSError, or ValueError if the file is corrupt."""
	part = dest + ".part"
	digest = hashlib.sha256()
	done = 0
	if os.path.isfile(part):
		# Re-hash what we already have so the final checksum covers the whole file.
		with open(part, "rb") as f:
			for block in iter(lambda: f.read(_BLOCK), b""):
				digest.update(block)
				done += len(block)
		if size and done > size:
			os.remove(part)
			digest, done = hashlib.sha256(), 0
	headers = {"User-Agent": USER_AGENT}
	if done:
		headers["Range"] = f"bytes={done}-"
	if not (size and done == size):
		with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
			if done and r.status != 206:
				# Server ignored the range request; start again.
				digest, done = hashlib.sha256(), 0
				mode = "wb"
			else:
				mode = "ab" if done else "wb"
			total = size or (done + int(r.headers.get("Content-Length") or 0)) or None
			with open(part, mode) as f:
				while True:
					if cancel is not None and cancel.is_set():
						raise Cancelled()
					block = r.read(_BLOCK)
					if not block:
						break
					f.write(block)
					digest.update(block)
					done += len(block)
					if onProgress is not None:
						onProgress(done, total)
	if size and done != size:
		raise OSError(f"Download incomplete: got {done} of {size} bytes.")
	if sha256 and digest.hexdigest().lower() != sha256.lower():
		os.remove(part)
		raise ValueError("The downloaded file is damaged. Please try again.")
	os.replace(part, dest)
	return dest
