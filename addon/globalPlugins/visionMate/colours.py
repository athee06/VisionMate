# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Colours measured from the pixels, without AI: the main colours of a picture, and the colour of a plain swatch.
A model can get "navy or black" wrong; the pixels do not. No NVDA modules here, so it can be tested on its own."""
import addonHandler

addonHandler.initTranslation()

# Colours with plain names, as RGB. Names are said to the user, so they are translated.
_PALETTE = [
	("black", (20, 20, 20)), ("dark grey", (70, 70, 70)), ("grey", (128, 128, 128)), ("light grey", (200, 200, 200)),
	("white", (250, 250, 250)), ("dark red", (128, 10, 20)), ("red", (220, 30, 30)), ("pink", (245, 160, 190)),
	("hot pink", (230, 60, 140)), ("orange", (245, 130, 30)), ("brown", (120, 70, 30)), ("beige", (225, 205, 165)),
	("tan", (200, 160, 110)), ("yellow", (245, 225, 40)), ("gold", (210, 170, 40)), ("olive", (120, 120, 40)),
	("light green", (150, 220, 120)), ("green", (40, 160, 60)), ("dark green", (20, 80, 35)), ("teal", (0, 128, 128)),
	("turquoise", (60, 210, 200)), ("light blue", (160, 200, 240)), ("sky blue", (90, 170, 230)),
	("blue", (30, 90, 210)), ("navy blue", (20, 30, 90)), ("purple", (110, 40, 140)), ("lavender", (190, 170, 230)),
	("magenta", (210, 40, 200)), ("maroon", (90, 20, 35)), ("cream", (250, 245, 220)),
]
# The picture is made this small first; colours do not need more.
SAMPLE_SIDE = 96
# Colours found per picture before similar ones are joined.
QUANTIZE = 10
# A colour must cover at least this share of the picture to be said.
MIN_SHARE = 0.06
MAX_COLOURS = 4
# A swatch: this share of its pixels within SWATCH_TOLERANCE of its main colour.
SWATCH_SHARE = 0.97
SWATCH_TOLERANCE = 28


def _names():
	return {
		# Translators: Colour names, said when colours are measured from a picture.
		"black": _("black"), "dark grey": _("dark grey"), "grey": _("grey"), "light grey": _("light grey"),
		"white": _("white"), "dark red": _("dark red"), "red": _("red"), "pink": _("pink"), "hot pink": _("hot pink"),
		"orange": _("orange"), "brown": _("brown"), "beige": _("beige"), "tan": _("tan"), "yellow": _("yellow"),
		"gold": _("gold"), "olive": _("olive"), "light green": _("light green"), "green": _("green"),
		"dark green": _("dark green"), "teal": _("teal"), "turquoise": _("turquoise"), "light blue": _("light blue"),
		"sky blue": _("sky blue"), "blue": _("blue"), "navy blue": _("navy blue"), "purple": _("purple"),
		"lavender": _("lavender"), "magenta": _("magenta"), "maroon": _("maroon"), "cream": _("cream"),
	}


def _lab(rgb):
	"""CIE Lab, where distances match how different colours look."""
	def lin(c):
		c /= 255
		return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
	r, g, b = (lin(float(c)) for c in rgb)
	x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
	y = 0.2126 * r + 0.7152 * g + 0.0722 * b
	z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

	def f(t):
		return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
	fx, fy, fz = f(x), f(y), f(z)
	return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


_PALETTE_LAB = [(name, _lab(rgb)) for name, rgb in _PALETTE]


def nameOf(rgb):
	"""The plain English key of the nearest named colour, like "navy blue"."""
	l, a, b = _lab(rgb)
	return min(_PALETTE_LAB, key=lambda p: (p[1][0] - l) ** 2 + (p[1][1] - a) ** 2 + (p[1][2] - b) ** 2)[0]


def say(key):
	"""A colour key in the user's language."""
	return _names().get(key, key)


def mainColours(image):
	"""The main colours of a picture, biggest first, as [(key, share)] with share from 0 to 1."""
	rgb = image.convert("RGB")
	rgb.thumbnail((SAMPLE_SIDE, SAMPLE_SIDE))
	quantized = rgb.quantize(colors=QUANTIZE)
	palette = quantized.getpalette()
	counts = quantized.getcolors(QUANTIZE * 4) or []
	total = sum(n for n, _i in counts) or 1
	shares = {}
	for n, index in counts:
		colour = tuple(palette[index * 3:index * 3 + 3])
		key = nameOf(colour)
		shares[key] = shares.get(key, 0) + n / total
	found = sorted(shares.items(), key=lambda kv: -kv[1])
	return [(k, s) for k, s in found if s >= MIN_SHARE][:MAX_COLOURS]


def sentence(found):
	"""Words for measured colours, like "Measured colours: navy blue 60 percent, white 25 percent."."""
	if not found:
		return ""
	parts = [_("{colour} {percent} percent").format(colour=say(k), percent=int(round(s * 100))) for k, s in found]
	# Translators: Colours measured from the picture's pixels. {colours} is a list like "navy blue 60 percent".
	return _("Measured colours: {colours}.").format(colours=", ".join(parts))


def swatch(image):
	"""The colour key of a plain one-colour swatch, like a colour choice on a shopping page, or None."""
	rgb = image.convert("RGB")
	w, h = rgb.size
	if w < 6 or h < 6:
		return None
	# Leave out the border, which is often a frame or a highlight.
	inset = max(1, min(w, h) // 6)
	rgb = rgb.crop((inset, inset, w - inset, h - inset))
	rgb.thumbnail((32, 32))
	pixels = list(rgb.getdata())
	if not pixels:
		return None
	counts = {}
	for p in pixels:
		q = (p[0] // 8, p[1] // 8, p[2] // 8)
		counts[q] = counts.get(q, 0) + 1
	q = max(counts, key=counts.get)
	main = (q[0] * 8 + 4, q[1] * 8 + 4, q[2] * 8 + 4)
	close = sum(1 for p in pixels if max(abs(p[0] - main[0]), abs(p[1] - main[1]), abs(p[2] - main[2])) <= SWATCH_TOLERANCE)
	if close / len(pixels) < SWATCH_SHARE:
		return None
	return nameOf(main)
