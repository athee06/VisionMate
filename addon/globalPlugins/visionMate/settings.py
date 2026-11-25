# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - settings panel in NVDA's Settings dialog.

import re

import addonHandler
import config
import gui
import wx
from gui import guiHelper

addonHandler.initTranslation()

CONF_SECTION = "visionMate"
# "Still working" after this many seconds; 0 is never.
STATUS_CHOICES = (5, 10, 15, 30, 0)
CONTROLLER_CHOICES = ("announce", "quiet", "off")
VOICE_KEYS = ("voicePitch", "voiceRate", "voiceVolume")


def defaultValue(key):
	"""The default of a VisionMate setting, from its spec like "boolean(default=True)"."""
	spec = config.conf.spec[CONF_SECTION][key]
	value = re.search(r"default=([^,)]+)", spec).group(1).strip()
	if spec.startswith("boolean"):
		return value == "True"
	if spec.startswith("integer"):
		return int(value)
	return value.strip("'\"")


class VisionMatePanel(gui.settingsDialogs.SettingsPanel):
	# Translators: Title of the VisionMate settings panel.
	title = _("VisionMate")
	# Set by the global plugin.
	plugin = None

	def makeSettings(self, settingsSizer):
		c = config.conf[CONF_SECTION]
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self._boxes = {}
		self._choices = {}
		self._spins = {}

		def group(label):
			sizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=label)
			box = guiHelper.BoxSizerHelper(sizer.GetStaticBox(), sizer=sizer)
			helper.addItem(box)
			return box

		def checkbox(where, label, key):
			box = where.addItem(wx.CheckBox(where.sizer.GetStaticBox(), label=label))
			box.SetValue(c[key])
			self._boxes[key] = box
			return box

		def choice(where, label, key, values, labels):
			parent = where.sizer.GetStaticBox()
			row = wx.BoxSizer(wx.HORIZONTAL)
			row.Add(wx.StaticText(parent, label=label), flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=8)
			ctrl = wx.Choice(parent, choices=list(labels))
			row.Add(ctrl)
			where.addItem(row)
			ctrl.SetSelection(values.index(c[key]) if c[key] in values else 0)
			self._choices[key] = (ctrl, values)
			return ctrl

		def spin(where, label, key):
			parent = where.sizer.GetStaticBox()
			row = wx.BoxSizer(wx.HORIZONTAL)
			row.Add(wx.StaticText(parent, label=label), flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=8)
			ctrl = wx.SpinCtrl(parent, min=-50, max=50, initial=c[key])
			row.Add(ctrl)
			where.addItem(row)
			self._spins[key] = ctrl
			return ctrl

		def button(where, label, handler):
			btn = where.addItem(wx.Button(where.sizer.GetStaticBox(), label=label))
			btn.Bind(wx.EVT_BUTTON, handler)
			return btn

		# Translators: Group of settings in the VisionMate settings panel.
		describing = group(_("Descriptions"))
		self.autoDescribe = checkbox(describing,
			# Translators: Checkbox in settings.
			_("&Automatically describe images without a label, photos in chats and photos in image viewers (NVDA+Alt+G)"), "autoDescribe")
		self.readAhead = checkbox(describing,
			# Translators: Checkbox in settings.
			_("Describe images further down the page in the bac&kground, so they are ready sooner"), "readAhead")
		self.iconLabeler = checkbox(describing,
			# Translators: Checkbox in settings.
			_("Name buttons that have no &name, from their icon (NVDA+Alt+B)"), "iconLabeler")
		self.useOcr = checkbox(describing,
			# Translators: Checkbox in settings.
			_("Use Windows &OCR to read screen text exactly"), "useOcr")
		# Translators: Checkbox in settings.
		self.answerInNvdaLanguage = checkbox(describing, _("Answer in NVDA's &language"), "answerInNvdaLanguage")
		# Translators: Checkbox in settings.
		self.progressBeeps = checkbox(describing, _("Play a soft &tick while waiting for a description"), "progressBeeps")
		# Translators: Button in settings that opens the window of things VisionMate remembers.
		button(describing, _("What VisionMate &remembers about you..."), self._onMemories)
		# Translators: Button in settings that opens the window of VisionMate's instructions.
		button(describing, _("How VisionMate answers, and your own &instructions..."), self._onInstructions)

		# Translators: Group of settings in the VisionMate settings panel.
		overlayGroup = group(_("Overlay"))
		self.overlayLive = checkbox(overlayGroup,
			# Translators: Checkbox in settings.
			_("Keep the o&verlay up to date as the window changes"), "overlayLive")

		# Translators: Group of settings in the VisionMate settings panel.
		helpGroup = group(_("Status and help"))
		choice(helpGroup,
			# Translators: Label of a choice in settings: when "Still working" is said during a long wait.
			_("Say \"Still working\" after:"), "statusSeconds", STATUS_CHOICES,
			# Translators: Choices for when "Still working" is said.
			[_("5 seconds"), _("10 seconds"), _("15 seconds"), _("30 seconds"), _("Never (NVDA+Alt+P asks)")])
		checkbox(helpGroup,
			# Translators: Checkbox in settings.
			_("Offer &help when a window, dialog or control tells NVDA little (NVDA+Alt+Y takes it)"), "helpOffer")
		choice(helpGroup,
			# Translators: Label of a choice in settings about game controllers.
			_("Game &controller:"), "controller", CONTROLLER_CHOICES,
			# Translators: Choices for game controllers.
			[_("Tell me when one is connected; View and Menu held together for controller mode"),
				_("Listen for View and Menu, but say nothing when one is connected"),
				_("Do not look for a game controller")])

		# Translators: Group of settings in the VisionMate settings panel.
		voiceGroup = group(_("VisionMate's voice, for descriptions and answers"))
		# Translators: Labels of VisionMate's voice settings: changes from NVDA's own voice, -50 to 50.
		spin(voiceGroup, _("&Pitch change:"), "voicePitch")
		spin(voiceGroup, _("Ra&te change:"), "voiceRate")
		spin(voiceGroup, _("Vol&ume change:"), "voiceVolume")
		# Translators: Button in settings that speaks a sample with VisionMate's voice.
		button(voiceGroup, _("&Hear VisionMate's voice"), self._onHearVoice)

		# Translators: Group of settings in the VisionMate settings panel.
		performance = group(_("Speed and memory"))
		# Translators: Checkbox in settings.
		self.useGpu = checkbox(performance, _("Use the &graphics card (much faster)"), "useGpu")
		self.preload = checkbox(performance,
			# Translators: Checkbox in settings.
			_("Get &ready when NVDA starts (fastest first description, uses memory)"), "preload")
		# Translators: Button in settings that makes a portable copy of VisionMate.
		button(performance, _("Make a portable &copy, for a flash drive or another computer..."), self._onPortable)

		# Translators: Button in settings that sets every VisionMate setting back to how it was when installed.
		reset = helper.addItem(wx.Button(self, label=_("Reset to &defaults")))
		reset.Bind(wx.EVT_BUTTON, self._onReset)

	def _onMemories(self, evt):
		if self.plugin is not None:
			from .moredialogs import MemoriesDialog
			MemoriesDialog.run(self, self.plugin.memories)

	def _onInstructions(self, evt):
		if self.plugin is not None:
			from . import common
			from .memories import Instructions
			from .moredialogs import InstructionsDialog
			defaults = [
				# Translators: Names of VisionMate's instructions, in the instructions window.
				(Instructions.OWN, _("Your own instruction, added to every description and answer you ask for"), ""),
				("quick", _("Quick description (press once)"), common.QUICK_PROMPT),
				("detailed", _("Detailed description (press twice)"), common.DETAIL_PROMPT),
				("auto", _("Automatic descriptions of images"), common.AUTO_PROMPT),
				("icon", _("Names for buttons from their icon"), common.ICON_PROMPT),
				("honesty", _("Honesty, added to every description"), common.HONESTY.strip()),
			]
			InstructionsDialog.run(self, self.plugin.instructions, defaults)

	def _onPortable(self, evt):
		if self.plugin is not None:
			self.plugin.makePortable()

	def _onHearVoice(self, evt):
		import speech
		try:
			from speech.commands import PitchCommand, RateCommand, VolumeCommand
			p, r, v = (self._spins[k].GetValue() for k in VOICE_KEYS)
			# Translators: Sample spoken with VisionMate's voice in settings.
			speech.speak([PitchCommand(offset=p), RateCommand(offset=r), VolumeCommand(offset=v),
				_("This is how VisionMate describes pictures.")])
		except ImportError:
			pass

	def _onReset(self, evt):
		"""Set the controls to the defaults. Nothing is saved until OK or Apply."""
		for key, box in self._boxes.items():
			box.SetValue(defaultValue(key))
		for key, (ctrl, values) in self._choices.items():
			ctrl.SetSelection(values.index(defaultValue(key)))
		for key, ctrl in self._spins.items():
			ctrl.SetValue(defaultValue(key))
		try:
			import ui
			# Translators: Reported after Reset to defaults. The settings still need OK or Apply.
			ui.message(_("Settings reset to defaults. Press OK to keep them."))
		except ImportError:
			pass

	def onSave(self):
		c = config.conf[CONF_SECTION]
		if self.plugin is not None:
			self.plugin.setAutoDescribe(self.autoDescribe.GetValue())
		else:
			c["autoDescribe"] = self.autoDescribe.GetValue()
		for key, box in self._boxes.items():
			if key != "autoDescribe":
				c[key] = box.GetValue()
		for key, (ctrl, values) in self._choices.items():
			c[key] = values[max(ctrl.GetSelection(), 0)]
		for key, ctrl in self._spins.items():
			c[key] = ctrl.GetValue()
		if self.plugin is not None:
			self.plugin.onSettingsSaved()
