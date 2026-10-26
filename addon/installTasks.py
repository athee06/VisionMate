# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - shows what is new when the add-on is installed or updated.

import addonHandler
import gui
import wx

addonHandler.initTranslation()


def _showWhatsNew(version, changelog):
	# Translators: Title of the window shown after VisionMate is installed or updated. {version} is the version.
	title = _("What's new in VisionMate {version}").format(version=version)
	gui.mainFrame.prePopup()
	try:
		gui.messageBox(changelog, title, wx.OK | wx.ICON_INFORMATION)
	finally:
		gui.mainFrame.postPopup()


def onInstall():
	manifest = addonHandler.getCodeAddon().manifest
	changelog = (manifest.get("changelog") or "").strip()
	if changelog:
		wx.CallAfter(_showWhatsNew, manifest["version"], changelog)
