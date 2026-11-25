# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Help offered where a place tells NVDA little: a window with almost nothing NVDA can read, a dialog where nothing
has the focus, or a control without a name. The decision is plain code on what NVDA reports, so it can be tested on
its own; nothing is done unless the user takes the offer."""

# A window this big with at most this many named things tells NVDA little.
MIN_WINDOW_SIDE = 200
MAX_NAMED = 2
# Roles (by name) that are only containers, never something to work.
CONTAINERS = {"PANE", "WINDOW", "CLIENT", "UNKNOWN", "GROUPING", "DOCUMENT", "FRAME", "APPLICATION"}
DIALOGS = {"DIALOG", "PROPERTYPAGE"}
WORKABLE = {"BUTTON", "TOGGLEBUTTON", "MENUBUTTON", "DROPDOWNBUTTON", "SPLITBUTTON", "LINK", "GRAPHIC", "ICON",
	"CHECKBOX", "RADIOBUTTON", "TAB", "MENUITEM", "LISTITEM", "TREEVIEWITEM"}


def reason(focusRole, focusName, focusIsWindow, windowSize, namedInWindow, inDialog):
	"""Why a place tells NVDA little: "window", "nofocus", "unnamed", or None.
	focusRole is the role's name like "BUTTON"; namedInWindow counts the named controls NVDA found in the window."""
	name = (focusName or "").strip()
	width, height = windowSize or (0, 0)
	big = width >= MIN_WINDOW_SIDE and height >= MIN_WINDOW_SIDE
	if inDialog and (focusIsWindow or focusRole in DIALOGS):
		return "nofocus"
	if big and focusRole in CONTAINERS and namedInWindow <= MAX_NAMED:
		return "window"
	if focusRole in WORKABLE and not name:
		return "unnamed"
	return None


def offerKey(app, window, why):
	"""Each offer is made once per window and reason."""
	return (app or "", window, why)
