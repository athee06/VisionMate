# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - the vision data pack (.vmdata).
# A pack is: MAGIC, 4-byte header length, JSON header, then all files concatenated and scrambled.
# It is not compressed: the model weights are already dense, so compression saved only about 3%.
# Scrambling keeps the pack from being recognised while hosted or downloaded. It is obfuscation, not
# strong encryption: the files must be readable on the user's computer for the engine to load them.
# No NVDA dependencies; also used by tools/make_datapack.py.

import hashlib
import json
import os
import struct

MAGIC = b"VMDATA\x01\x00"
_KEY_SEED = b"VisionMate data pack v1 \xe2\x9c\xa8 2f7c1a9e"
_KEY_LEN = 1 << 20
_BLOCK = 1 << 20
# Files the engine needs, by role.
CORE = "core.bin"
VISION = "vision.bin"
_STATE = "data.json"

_key = None


def _keyBytes():
	global _key
	if _key is None:
		out = bytearray()
		counter = 0
		while len(out) < _KEY_LEN:
			out += hashlib.sha256(_KEY_SEED + counter.to_bytes(8, "little")).digest()
			counter += 1
		_key = bytes(out[:_KEY_LEN])
	return _key


def _xor(data, offset):
	"""XOR data with the key stream starting at payload offset. Scrambling and unscrambling are the same."""
	key = _keyBytes()
	start = offset % _KEY_LEN
	ks = key[start:start + len(data)]
	while len(ks) < len(data):
		ks += key[:len(data) - len(ks)]
	n = len(data)
	return (int.from_bytes(data, "little") ^ int.from_bytes(ks, "little")).to_bytes(n, "little")


def create(outPath, files, version):
	"""Write a pack. files is a list of (sourcePath, nameInPack)."""
	entries = []
	for src, name in files:
		h = hashlib.sha256()
		with open(src, "rb") as f:
			for block in iter(lambda: f.read(_BLOCK), b""):
				h.update(block)
		entries.append({"name": name, "size": os.path.getsize(src), "sha256": h.hexdigest()})
	header = json.dumps({"version": version, "files": entries}).encode("utf-8")
	offset = 0
	with open(outPath, "wb") as out:
		out.write(MAGIC + struct.pack("<I", len(header)) + header)
		for src, _name in files:
			with open(src, "rb") as f:
				for block in iter(lambda: f.read(_BLOCK), b""):
					out.write(_xor(block, offset))
					offset += len(block)


def readHeader(packPath):
	with open(packPath, "rb") as f:
		if f.read(len(MAGIC)) != MAGIC:
			raise ValueError("This is not a VisionMate data file.")
		(n,) = struct.unpack("<I", f.read(4))
		return json.loads(f.read(n).decode("utf-8")), len(MAGIC) + 4 + n


def install(packPath, dataDir, onProgress=None, cancel=None):
	"""Unpack a downloaded pack into dataDir, verifying every file. Calls onProgress(done, total)."""
	header, payloadStart = readHeader(packPath)
	total = sum(e["size"] for e in header["files"])
	os.makedirs(dataDir, exist_ok=True)
	done = 0
	with open(packPath, "rb") as f:
		f.seek(payloadStart)
		for entry in header["files"]:
			name = os.path.basename(entry["name"])
			tmp = os.path.join(dataDir, name + ".tmp")
			h = hashlib.sha256()
			remaining = entry["size"]
			with open(tmp, "wb") as out:
				while remaining:
					if cancel is not None and cancel.is_set():
						out.close()
						os.remove(tmp)
						return False
					block = f.read(min(_BLOCK, remaining))
					if not block:
						raise ValueError("The data file is incomplete.")
					plain = _xor(block, done)
					out.write(plain)
					h.update(plain)
					done += len(plain)
					remaining -= len(plain)
					if onProgress is not None:
						onProgress(done, total)
			if h.hexdigest() != entry["sha256"]:
				os.remove(tmp)
				raise ValueError("The data file is damaged. Please download it again.")
			os.replace(tmp, os.path.join(dataDir, name))
	with open(os.path.join(dataDir, _STATE), "w", encoding="utf-8") as s:
		json.dump({"version": header["version"], "files": [e["name"] for e in header["files"]]}, s)
	return True


def installedVersion(dataDir):
	"""Version of the installed data, or 0 if it is missing or incomplete."""
	try:
		with open(os.path.join(dataDir, _STATE), encoding="utf-8") as s:
			state = json.load(s)
	except (OSError, ValueError):
		return 0
	if not all(os.path.isfile(os.path.join(dataDir, n)) for n in state.get("files", ())):
		return 0
	return int(state.get("version", 0))


def enginePaths(dataDir):
	return os.path.join(dataDir, CORE), os.path.join(dataDir, VISION)
