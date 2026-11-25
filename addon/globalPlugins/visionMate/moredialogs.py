# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Windows opened from VisionMate's settings: what VisionMate remembers, how it answers (its instructions), and the
portable copy."""
import os
import shutil
import threading

import addonHandler
import gui
import ui
import wx
from logHandler import log

from . import portable

addonHandler.initTranslation()


def _showModal(dialog):
	gui.mainFrame.prePopup()
	try:
		return dialog.ShowModal()
	finally:
		dialog.Destroy()
		gui.mainFrame.postPopup()


class MemoriesDialog(wx.Dialog):
	"""The list of memories, with Add, Remove and Remove all."""

	def __init__(self, parent, store):
		# Translators: Title of the window listing what VisionMate remembers.
		super().__init__(parent, title=_("What VisionMate remembers"))
		self._store = store
		main = wx.BoxSizer(wx.VERTICAL)
		# Translators: Explanation in the memories window.
		main.Add(wx.StaticText(self, label=_("VisionMate gives these to the vision data with every description and "
			"answer you ask for. They stay on this computer. In a description window you can also type "
			"\"remember that ...\", \"forget ...\" or \"what do you remember\".")), flag=wx.ALL, border=10)
		self.list = wx.ListBox(self, size=(520, 200))
		main.Add(self.list, proportion=1, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=10)
		row = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: Buttons in the memories window.
		add = wx.Button(self, label=_("&Add..."))
		remove = wx.Button(self, label=_("&Remove"))
		clear = wx.Button(self, label=_("Remove a&ll"))
		close = wx.Button(self, wx.ID_CLOSE, label=_("&Close"))
		for i, b in enumerate((add, remove, clear, close)):
			row.Add(b, flag=wx.LEFT if i else 0, border=10)
		main.Add(row, flag=wx.ALL | wx.ALIGN_RIGHT, border=10)
		self.SetSizerAndFit(main)
		self.SetEscapeId(wx.ID_CLOSE)
		add.Bind(wx.EVT_BUTTON, self._onAdd)
		remove.Bind(wx.EVT_BUTTON, self._onRemove)
		clear.Bind(wx.EVT_BUTTON, self._onClear)
		close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
		self._fill()
		self.list.SetFocus()
		self.CentreOnScreen()

	def _fill(self, select=0):
		items = self._store.items
		# Translators: Shown in the memories window when there are none.
		self.list.Set(items or [_("Nothing yet")])
		self.list.SetSelection(min(select, max(len(items), 1) - 1))

	def _onAdd(self, evt):
		# Translators: Title and prompt of the window for adding a memory.
		with wx.TextEntryDialog(self, _("What should VisionMate remember? For example: I am colour blind, always name "
				"colours."), _("Add a memory")) as dlg:
			if dlg.ShowModal() == wx.ID_OK and dlg.GetValue().strip():
				self._store.add(dlg.GetValue())
				self._fill(len(self._store.items) - 1)

	def _onRemove(self, evt):
		index = self.list.GetSelection()
		if self._store.items and index != wx.NOT_FOUND:
			self._store.remove(index)
			self._fill(index)

	def _onClear(self, evt):
		if not self._store.items:
			return
		# Translators: Question before all memories are removed.
		if wx.MessageBox(_("Remove everything VisionMate remembers?"), _("What VisionMate remembers"),
				wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) == wx.YES:
			self._store.clear()
			self._fill()

	@classmethod
	def run(cls, parent, store):
		_showModal(cls(parent, store))


class InstructionsDialog(wx.Dialog):
	"""Read and rewrite each instruction VisionMate gives the vision data, add your own, restore the originals."""

	def __init__(self, parent, store, defaults):
		"""defaults: a list of (name, label, default text). The name memories.Instructions.OWN is the user's own."""
		# Translators: Title of the window with VisionMate's instructions.
		super().__init__(parent, title=_("How VisionMate answers"))
		self._store = store
		self._defaults = defaults
		self._current = 0
		main = wx.BoxSizer(wx.VERTICAL)
		# Translators: Label of the list of instructions.
		main.Add(wx.StaticText(self, label=_("&Instruction:")), flag=wx.LEFT | wx.TOP, border=10)
		self.choice = wx.Choice(self, choices=[label for _n, label, _d in defaults])
		main.Add(self.choice, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=10)
		# Translators: Label of the box with the text of an instruction.
		main.Add(wx.StaticText(self, label=_("&Text:")), flag=wx.LEFT | wx.TOP, border=10)
		self.text = wx.TextCtrl(self, size=(560, 140), style=wx.TE_MULTILINE)
		main.Add(self.text, proportion=1, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=10)
		row = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: Buttons in the instructions window.
		restore = wx.Button(self, label=_("&Restore this one"))
		restoreAll = wx.Button(self, label=_("Restore &all"))
		ok = wx.Button(self, wx.ID_OK, label=_("OK"))
		cancel = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))
		for i, b in enumerate((restore, restoreAll, ok, cancel)):
			row.Add(b, flag=wx.LEFT if i else 0, border=10)
		main.Add(row, flag=wx.ALL | wx.ALIGN_RIGHT, border=10)
		self.SetSizerAndFit(main)
		self._edits = {name: store.overrides.get(name, default) for name, _l, default in defaults}
		self.choice.SetSelection(0)
		self._show(0)
		self.choice.Bind(wx.EVT_CHOICE, self._onChoice)
		restore.Bind(wx.EVT_BUTTON, self._onRestore)
		restoreAll.Bind(wx.EVT_BUTTON, self._onRestoreAll)
		ok.Bind(wx.EVT_BUTTON, self._onOk)
		self.choice.SetFocus()
		self.CentreOnScreen()

	def _show(self, index):
		self._current = index
		self.text.SetValue(self._edits[self._defaults[index][0]])

	def _keep(self):
		self._edits[self._defaults[self._current][0]] = self.text.GetValue()

	def _onChoice(self, evt):
		self._keep()
		self._show(self.choice.GetSelection())

	def _onRestore(self, evt):
		name, _label, default = self._defaults[self._current]
		self._edits[name] = default
		self.text.SetValue(default)
		# Translators: Reported after one instruction was restored.
		ui.message(_("Restored"))

	def _onRestoreAll(self, evt):
		self._edits = {name: default for name, _l, default in self._defaults}
		self._show(self._current)
		# Translators: Reported after all instructions were restored.
		ui.message(_("All restored"))

	def _onOk(self, evt):
		self._keep()
		for name, _label, default in self._defaults:
			self._store.set(name, self._edits[name], default)
		self.EndModal(wx.ID_OK)

	@classmethod
	def run(cls, parent, store, defaults):
		_showModal(cls(parent, store, defaults))


def portableReadme():
	# Translators: The read-me file of a portable copy.
	return _(
		"VisionMate portable copy\r\n\r\n"
		"This folder holds the VisionMate add-on and its vision data, so another computer needs no download.\r\n\r\n"
		"1. On the other computer, open VisionMate.nvda-addon and install it in NVDA, then restart NVDA.\r\n"
		"2. When VisionMate's welcome window opens, choose \"From a portable copy\", and choose this folder. "
		"If this folder is on a flash drive, VisionMate finds it by itself.\r\n\r\n"
		"The vision data is licensed under the Apache License 2.0; its notice is in the vision data folder.\r\n"
	)


class PortableDialog:
	"""Choose where, check the space, and copy with a progress window."""

	@staticmethod
	def run(parent, addonDir, dataDir):
		# Translators: Title of the window for choosing where a portable copy goes.
		with wx.DirDialog(parent, _("Where should the portable copy go? For example a flash drive")) as dlg:
			gui.mainFrame.prePopup()
			try:
				if dlg.ShowModal() != wx.ID_OK:
					return
				target = dlg.GetPath()
			finally:
				gui.mainFrame.postPopup()
		try:
			needed = portable.size(addonDir, dataDir)
			free = shutil.disk_usage(target).free
		except OSError as e:
			ui.message(str(e))
			return
		if free < needed:
			# Translators: Reported when there is not enough space for a portable copy. Sizes in megabytes.
			ui.message(_("Not enough space there: the copy needs {needed} MB and {free} MB is free.").format(
				needed=needed // 1048576, free=free // 1048576))
			return
		# Translators: Title of the progress window while a portable copy is made.
		progress = wx.ProgressDialog(_("VisionMate portable copy"), _("Copying..."), maximum=100, parent=parent,
			style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE)
		cancel = threading.Event()
		state = {"pct": 0}

		def onProgress(done, total):
			pct = min(99, done * 100 // max(total, 1))
			if pct != state["pct"]:
				state["pct"] = pct

				def update():
					if progress:
						keep, _skip = progress.Update(pct, _("Copying, {pct} percent.").format(pct=pct))
						if not keep:
							cancel.set()
				wx.CallAfter(update)

		def say(text):
			wx.CallAfter(ui.message, text)

		def work():
			try:
				out = portable.make(addonDir, dataDir, target, portableReadme(), onProgress, cancel)
			except portable.Cancelled:
				wx.CallAfter(progress.Destroy)
				# Translators: Reported when the portable copy was cancelled.
				say(_("Portable copy cancelled."))
				return
			except (OSError, ValueError) as e:
				log.error("VisionMate: portable copy failed", exc_info=True)
				wx.CallAfter(progress.Destroy)
				# Translators: Reported when the portable copy failed. {error} is the reason.
				say(_("The portable copy failed: {error}").format(error=e))
				return
			wx.CallAfter(progress.Destroy)
			# Translators: Reported when the portable copy is ready. {folder} is where it is.
			say(_("The portable copy is ready in {folder}.").format(folder=out))

		threading.Thread(target=work, name="visionMate-portable", daemon=True).start()
