# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Checks how streamed text is split into spoken pieces."""
import os
import re
import threading

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "addon", "globalPlugins", "visionMate", "__init__.py")
src = open(SRC, encoding="utf-8").read()
out = []
ns = {"re": re, "_speak": out.append}
exec(src[src.index("_MARKDOWN ="):src.index("class GlobalPlugin")], ns)

text = (
	'The VAT number:\n"MwSt Nr.: 430 234"\nPhone number:\n"Tel.: 033 853 67 16"\n'
	"**Email:** a@b.ch. The name is Familie R. Müller, printed at the top. "
	"The total is CHF 54.50 for four items. Done."
)
sp = ns["SentenceSpeaker"](threading.Event())
for ch in text:  # one character at a time, like the worst-case stream
	sp.feed(ch)
sp.flush()
for o in out:
	print(repr(o))
assert all("**" not in o for o in out)
assert not any(o.endswith("R.") or o.endswith("Tel.:") for o in out)
assert any("54.50 for four items." in o for o in out)
print("OK")
