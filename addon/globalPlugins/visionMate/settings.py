# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - settings panel in NVDA's Settings dialog.

import addonHandler
import config
import gui
import wx
from gui import guiHelper

addonHandler.initTranslation()

CONF_SECTION = "visionMate"


class VisionMatePanel(gui.settingsDialogs.SettingsPanel):
	# Translators: Title of the VisionMate settings panel.
	title = _("VisionMate")
	# Set by the global plugin.
	plugin = None

	def makeSettings(self, settingsSizer):
		c = config.conf[CONF_SECTION]
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		def checkbox(label, key):
			box = helper.addItem(wx.CheckBox(self, label=label))
			box.SetValue(c[key])
			return box

		self.autoDescribe = checkbox(
			# Translators: Checkbox in settings.
			_("&Automatically describe images that have no label (NVDA+Alt+G)"), "autoDescribe")
		self.readAhead = checkbox(
			# Translators: Checkbox in settings.
			_("Describe images further down the page in the bac&kground, so they are ready sooner"), "readAhead")
		self.iconLabeler = checkbox(
			# Translators: Checkbox in settings.
			_("Name buttons that have no &name, from their icon (NVDA+Alt+B)"), "iconLabeler")
		self.useOcr = checkbox(
			# Translators: Checkbox in settings.
			_("Use Windows &OCR to read screen text exactly"), "useOcr")
		self.overlayLive = checkbox(
			# Translators: Checkbox in settings.
			_("Keep the o&verlay up to date as the window changes"), "overlayLive")
		# Translators: Checkbox in settings.
		self.useGpu = checkbox(_("Use the &graphics card (much faster)"), "useGpu")
		self.preload = checkbox(
			# Translators: Checkbox in settings.
			_("Get &ready when NVDA starts (fastest first description, uses memory)"), "preload")
		# Translators: Checkbox in settings.
		self.answerInNvdaLanguage = checkbox(_("Answer in NVDA's &language"), "answerInNvdaLanguage")
		# Translators: Checkbox in settings.
		self.progressBeeps = checkbox(_("Play a soft &tick while waiting for a description"), "progressBeeps")

	def onSave(self):
		c = config.conf[CONF_SECTION]
		if self.plugin is not None:
			self.plugin.setAutoDescribe(self.autoDescribe.GetValue())
		else:
			c["autoDescribe"] = self.autoDescribe.GetValue()
		c["readAhead"] = self.readAhead.GetValue()
		c["iconLabeler"] = self.iconLabeler.GetValue()
		c["useOcr"] = self.useOcr.GetValue()
		c["overlayLive"] = self.overlayLive.GetValue()
		c["useGpu"] = self.useGpu.GetValue()
		c["preload"] = self.preload.GetValue()
		c["answerInNvdaLanguage"] = self.answerInNvdaLanguage.GetValue()
		c["progressBeeps"] = self.progressBeeps.GetValue()
		if self.plugin is not None:
			self.plugin.onSettingsSaved()
