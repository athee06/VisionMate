# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - welcome/download window and the description window.

import os
import re
import threading

import addonHandler
import api
import gui
import ui
import wx
from logHandler import log

from . import datapack, hardware, net, sounds

addonHandler.initTranslation()

# Translators: Usage guide shown after the vision data is installed.
USAGE = _(
	"How to use VisionMate:\n"
	"NVDA+Alt+A: describe the current element.\n"
	"NVDA+Alt+W: describe the current window.\n"
	"NVDA+Alt+F: describe the whole screen.\n"
	"NVDA+Alt+D: describe the image or image file on the clipboard.\n"
	"Press a command once to hear a quick description. "
	"Press it twice quickly to get a detailed description in a window you can read, copy and close, "
	"and where you can ask questions about the image.\n"
	"NVDA+Alt+O: open the overlay, which makes a window NVDA cannot read into a list of its texts and icons. "
	"Press Enter on an item to click it, and Escape to close.\n"
	"NVDA+Alt+G: turn automatic descriptions on or off. When on, images that have no label "
	"are described as you read web pages and documents.\n"
	"NVDA+Alt+B: turn button names on or off. When on, buttons that have no name are named from their icon.\n"
	"NVDA+Alt+N: give your own name to the current button, or to the current item in the overlay.\n"
	"Press Control to stop speaking.\n"
	"VisionMate uses AI, and AI can make mistakes, so please double-check anything important.\n"
	"Everything runs on your computer. Images are never sent to the internet."
)


def _mb(n):
	return round(n / 1048576)


class DataDialog(wx.Dialog):
	"""Downloads and installs the vision data. Enter starts, Space reads progress while working."""

	def __init__(self, parent, dataInfo, dataDir, onInstalled, isUpdate=False):
		# Translators: Title of the VisionMate data download window.
		super().__init__(parent, title=_("VisionMate"))
		self._info = dataInfo
		self._dataDir = dataDir
		self._onInstalled = onInstalled
		self._cancel = threading.Event()
		self._working = False
		self._progress = ""
		sizeMb = _mb(dataInfo["size"])
		if isUpdate:
			# Translators: Shown when new vision data is available. {size} is in megabytes.
			intro = _(
				"A new version of the VisionMate vision data is available ({size} MB). "
				"Press Enter to download it now."
			).format(size=sizeMb)
		else:
			# Translators: Welcome text shown after installing VisionMate. {size} is in megabytes.
			intro = _(
				"Welcome to VisionMate. VisionMate describes images, screens and on-screen elements "
				"fully offline, on your own computer.\n\n"
				"To work, VisionMate needs its vision data ({size} MB). It is downloaded only once. "
				"Press Enter to download it now."
			).format(size=sizeMb)
			warnings = hardware.warnings()
			if warnings:
				intro += "\n\n" + "\n".join(warnings)

		main = wx.BoxSizer(wx.VERTICAL)
		self.text = wx.TextCtrl(self, value=intro, size=(520, 160), style=wx.TE_MULTILINE | wx.TE_READONLY)
		main.Add(self.text, flag=wx.ALL | wx.EXPAND, border=10)
		self.gauge = wx.Gauge(self, range=100)
		self.gauge.Hide()
		main.Add(self.gauge, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=10)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: Button that starts the vision data download. {size} is in megabytes.
		self.startBtn = wx.Button(self, label=_("&Download ({size} MB)").format(size=sizeMb))
		# Translators: Button that closes the window without downloading.
		self.closeBtn = wx.Button(self, wx.ID_CANCEL, label=_("&Later"))
		buttons.Add(self.startBtn)
		buttons.Add(self.closeBtn, flag=wx.LEFT, border=10)
		main.Add(buttons, flag=wx.ALL | wx.ALIGN_RIGHT, border=10)
		self.SetSizerAndFit(main)
		self.CentreOnScreen()
		self.startBtn.SetDefault()
		self.startBtn.Bind(wx.EVT_BUTTON, lambda e: self._start())
		self.closeBtn.Bind(wx.EVT_BUTTON, self._onClose)
		self.Bind(wx.EVT_CLOSE, self._onClose)
		self.Bind(wx.EVT_CHAR_HOOK, self._onKey)
		self.startBtn.SetFocus()

	def _after(self, fn, *args):
		# The window may be closed while the worker thread is still reporting progress.
		wx.CallAfter(lambda: fn(*args) if self else None)

	def _onKey(self, evt):
		key = evt.GetKeyCode()
		if self._working and key == wx.WXK_SPACE:
			ui.message(self._progress)
			return
		if not self._working and key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self.startBtn.IsShown() \
				and self.FindFocus() is not self.closeBtn:
			self._start()
			return
		evt.Skip()

	def _setText(self, text, focus=True):
		self.text.SetValue(text)
		if focus:
			self.text.SetFocus()
			self.text.SetInsertionPoint(0)

	def _start(self):
		if self._working:
			return
		self._working = True
		self._cancel.clear()
		self.startBtn.Hide()
		# Translators: Button that cancels the download.
		self.closeBtn.SetLabel(_("&Cancel"))
		self.gauge.SetValue(0)
		self.gauge.Show()
		# Translators: Reported when the download begins.
		self._progress = _("Starting download.")
		# Translators: Shown while downloading.
		self._setText(_("Downloading the VisionMate vision data. Press Space to hear the progress."))
		self.Layout()
		self.Fit()
		threading.Thread(target=self._work, name="visionMate-data", daemon=True).start()

	def _work(self):
		os.makedirs(self._dataDir, exist_ok=True)
		pack = os.path.join(self._dataDir, "download.vmdata")
		total = self._info["size"]

		def downloaded(done, _total):
			pct = done * 100 // total
			# Translators: Download progress. {pct} percent, {done} of {total} megabytes.
			self._progress = _("Downloading, {pct} percent, {done} of {total} MB.").format(
				pct=pct, done=_mb(done), total=_mb(total))
			self._after(lambda v: self.gauge.SetValue(v), min(pct, 100))

		def unpacked(done, allBytes):
			pct = done * 100 // allBytes
			# Translators: Progress while preparing the downloaded data. {pct} is a percentage.
			self._progress = _("Preparing the data, {pct} percent.").format(pct=pct)
			self._after(lambda v: self.gauge.SetValue(v), min(pct, 100))

		try:
			net.download(self._info["url"], pack, total, self._info.get("sha256"), downloaded, self._cancel)
			ok = datapack.install(pack, self._dataDir, unpacked, self._cancel)
			os.remove(pack)
		except net.Cancelled:
			ok = False
		except (OSError, ValueError) as e:
			log.error("VisionMate: data download failed", exc_info=True)
			self._after(self._failed, str(e))
			return
		if ok:
			self._after(self._finished)

	def _finished(self):
		self._working = False
		self.gauge.Hide()
		self.closeBtn.SetLabel(_("&Close"))
		# Translators: Shown when the vision data is installed, followed by the usage guide.
		self._setText(_("Download complete. VisionMate is ready to use.") + "\n\n" + USAGE)
		self.Layout()
		self._onInstalled()

	def _failed(self, error):
		self._working = False
		self.gauge.Hide()
		# Translators: Button to retry a failed download.
		self.startBtn.SetLabel(_("&Try again"))
		self.startBtn.Show()
		self.closeBtn.SetLabel(_("&Close"))
		# Translators: Shown when the download fails. {error} is the reason.
		self._setText(_(
			"The download did not finish: {error}\n\n"
			"Check your internet connection and press Enter to try again. "
			"The download continues from where it stopped."
		).format(error=error))
		self.Layout()

	def _onClose(self, evt):
		if self._working:
			# Keep the partial download so the next attempt resumes.
			self._cancel.set()
			# Translators: Reported when the download is cancelled.
			ui.message(_("Download cancelled."))
		self.Destroy()


class ResultDialog(wx.Dialog):
	"""Shows a description so it can be read line by line, copied and closed.
	With onAsk, it also has a box for questions about the image: onAsk(question, dialog)."""

	def __init__(self, parent, text, onAsk=None):
		# Translators: Title of the window showing a detailed description.
		super().__init__(parent, title=_("VisionMate description"))
		self._text = text
		self._onAsk = onAsk
		self.asking = False
		main = wx.BoxSizer(wx.VERTICAL)
		self.textCtrl = wx.TextCtrl(self, value=text, size=(600, 320), style=wx.TE_MULTILINE | wx.TE_READONLY)
		main.Add(self.textCtrl, proportion=1, flag=wx.ALL | wx.EXPAND, border=10)
		self.question = None
		if onAsk is not None:
			ask = wx.BoxSizer(wx.HORIZONTAL)
			# Translators: Label of the box for questions about the described image.
			ask.Add(wx.StaticText(self, label=_("&Question about this image:")), flag=wx.ALIGN_CENTER_VERTICAL)
			self.question = wx.TextCtrl(self, size=(380, -1), style=wx.TE_PROCESS_ENTER)
			ask.Add(self.question, proportion=1, flag=wx.LEFT, border=8)
			# Translators: Button that asks the typed question about the image.
			askBtn = wx.Button(self, label=_("As&k"))
			ask.Add(askBtn, flag=wx.LEFT, border=8)
			main.Add(ask, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=10)
			self.question.Bind(wx.EVT_TEXT_ENTER, lambda e: self.ask())
			askBtn.Bind(wx.EVT_BUTTON, lambda e: self.ask())
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: Button that copies the description to the clipboard.
		copyBtn = wx.Button(self, label=_("&Copy"))
		# Translators: Button that closes the description window.
		closeBtn = wx.Button(self, wx.ID_CLOSE, label=_("C&lose"))
		buttons.Add(copyBtn)
		buttons.Add(closeBtn, flag=wx.LEFT, border=10)
		main.Add(buttons, flag=wx.ALL | wx.ALIGN_RIGHT, border=10)
		self.SetSizerAndFit(main)
		self.SetEscapeId(wx.ID_CLOSE)
		self.CentreOnScreen()
		copyBtn.Bind(wx.EVT_BUTTON, lambda e: api.copyToClip(self.textCtrl.GetValue(), notify=True))
		closeBtn.Bind(wx.EVT_BUTTON, lambda e: self.Destroy())
		self.Bind(wx.EVT_CLOSE, lambda e: self.Destroy())
		self.textCtrl.SetFocus()
		self.textCtrl.SetInsertionPoint(0)

	def ask(self):
		question = self.question.GetValue().strip() if self.question else ""
		if not question or self.asking or self._onAsk is None:
			return
		self.question.Clear()
		self.asking = True
		self._onAsk(question, self)

	def addAnswer(self, question, answer):
		"""Called on the GUI thread when an answer is complete."""
		self.asking = False
		if answer:
			# Translators: A question and its answer, added to the description window.
			self.appendText(_("\n\nQuestion: {question}\nAnswer: {answer}").format(question=question, answer=answer))

	def appendText(self, text):
		"""Add streamed text without moving the reading position."""
		pos = self.textCtrl.GetInsertionPoint()
		self.textCtrl.AppendText(text)
		self.textCtrl.SetInsertionPoint(pos)

	def setFinalText(self, text):
		pos = self.textCtrl.GetInsertionPoint()
		self.textCtrl.SetValue(text)
		self.textCtrl.SetInsertionPoint(min(pos, self.textCtrl.GetLastPosition()))


class StreamingResult:
	"""Opens a ResultDialog as soon as the first sentence arrives and keeps adding the rest.
	feed() and finish() are called from the worker thread."""

	_FIRST = re.compile(r"[.!?。！？]\s")

	def __init__(self, onOpened, onAsk=None):
		self._text = ""
		self._shown = 0
		self._requested = False
		self._dialog = None
		self._onOpened = onOpened
		self._onAsk = onAsk

	def feed(self, delta):
		self._text += delta
		if not self._requested:
			if self._FIRST.search(self._text) or len(self._text) > 160:
				self._requested = True
				wx.CallAfter(self._open)
		else:
			wx.CallAfter(self._sync)

	def finish(self, finalText):
		wx.CallAfter(self._finish, finalText)

	def _open(self):
		self._dialog = ResultDialog(gui.mainFrame, _streamClean(self._text), self._onAsk)
		self._shown = len(self._text)
		show(self._dialog)
		self._onOpened()

	def _sync(self):
		if self._dialog and self._shown < len(self._text):
			self._dialog.appendText(_streamClean(self._text[self._shown:]))
			self._shown = len(self._text)

	def _finish(self, finalText):
		if self._dialog is None:
			self._open()
		if self._dialog:
			self._dialog.setFinalText(finalText)
			sounds.play("done")


def _streamClean(text):
	return text.replace("**", "").replace("`", "").replace("##", "")


def show(dialog):
	"""Show a modeless dialog in front, the way NVDA's own windows appear."""
	gui.mainFrame.prePopup()
	dialog.Show()
	dialog.Raise()
	gui.mainFrame.postPopup()
