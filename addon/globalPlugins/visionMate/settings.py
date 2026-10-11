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
		# Translators: Checkbox in settings.
		self.useGpu = checkbox(_("Use the &graphics card (much faster)"), "useGpu")
		self.preload = checkbox(
			# Translators: Checkbox in settings.
			_("&Get ready when NVDA starts (fastest first description, uses memory)"), "preload")
		# Translators: Checkbox in settings.
		self.answerInNvdaLanguage = checkbox(_("Answer in NVDA's &language"), "answerInNvdaLanguage")
		# Translators: Checkbox in settings.
		self.progressBeeps = checkbox(_("&Beep while waiting for a description"), "progressBeeps")
		# Translators: Checkbox in settings.
		self.autoUpdate = checkbox(_("Check for &updates automatically"), "autoUpdate")
		# Translators: Button in settings.
		checkBtn = helper.addItem(wx.Button(self, label=_("&Check for updates now")))
		checkBtn.Bind(wx.EVT_BUTTON, lambda e: self.plugin and self.plugin.checkForUpdates(manual=True))

	def onSave(self):
		c = config.conf[CONF_SECTION]
		if self.plugin is not None:
			self.plugin.setAutoDescribe(self.autoDescribe.GetValue())
		else:
			c["autoDescribe"] = self.autoDescribe.GetValue()
		c["useGpu"] = self.useGpu.GetValue()
		c["preload"] = self.preload.GetValue()
		c["answerInNvdaLanguage"] = self.answerInNvdaLanguage.GetValue()
		c["progressBeeps"] = self.progressBeeps.GetValue()
		c["autoUpdate"] = self.autoUpdate.GetValue()
		if self.plugin is not None:
			self.plugin.onSettingsSaved()
