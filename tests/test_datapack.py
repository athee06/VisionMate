# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Tests the data pack format and resumable, verified downloads (no NVDA needed)."""
import hashlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "addon", "globalPlugins", "visionMate"))
sys.path.insert(0, HERE)
import datapack  # noqa: E402
import net  # noqa: E402
import rangeserver  # noqa: E402

tmp = tempfile.mkdtemp()
src = {}
for name, size in (("core.bin", 3_500_001), ("vision.bin", 1_048_576), ("NOTICE.txt", 123)):
	p = os.path.join(tmp, "src_" + name)
	with open(p, "wb") as f:
		f.write(os.urandom(size))
	src[name] = p
pack = os.path.join(tmp, "www", "pack.vmdata")
os.makedirs(os.path.dirname(pack))
datapack.create(pack, [(src[n], n) for n in ("core.bin", "vision.bin", "NOTICE.txt")], 7)

# The pack must not contain the original bytes in the clear.
raw = open(pack, "rb").read()
assert open(src["core.bin"], "rb").read()[:4096] not in raw
packSha = hashlib.sha256(raw).hexdigest()
print("1 OK: pack written and scrambled")

# Interrupted download, then resume.
url, server = rangeserver.serve(os.path.dirname(pack), failAfterBytes=2_000_000)
dest = os.path.join(tmp, "dl", "pack.vmdata")
os.makedirs(os.path.dirname(dest))
try:
	net.download(url + "/pack.vmdata", dest, len(raw), packSha)
	raise AssertionError("expected the first attempt to fail")
except OSError as e:
	print("2 OK: first attempt cut off:", type(e).__name__, os.path.getsize(dest + ".part"), "bytes kept")
seen = []
net.download(url + "/pack.vmdata", dest, len(raw), packSha, lambda d, t: seen.append(d))
assert seen[0] > 2_000_000, "should have resumed, not restarted"
print("3 OK: resumed from", seen[0] - (seen[1] - seen[0]) if len(seen) > 1 else seen[0], "and checksum matched")

# Unpack and verify.
out = os.path.join(tmp, "data")
assert datapack.install(dest, out)
for name, p in src.items():
	assert open(os.path.join(out, name), "rb").read() == open(p, "rb").read(), name
assert datapack.installedVersion(out) == 7
print("4 OK: unpacked files identical, version", datapack.installedVersion(out))

# Damaged download is rejected and removed.
os.remove(dest)
try:
	net.download(url + "/pack.vmdata", dest, len(raw), "0" * 64)
	raise AssertionError("expected checksum failure")
except ValueError:
	assert not os.path.exists(dest + ".part") and not os.path.exists(dest)
print("5 OK: damaged download rejected")

# Missing file makes the data count as not installed.
os.remove(os.path.join(out, "vision.bin"))
assert datapack.installedVersion(out) == 0
print("6 OK: incomplete data detected")
server.shutdown()
print("ALL OK")
