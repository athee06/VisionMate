# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Connects the overlay for inaccessible windows to NVDA and the plugin."""
import addonHandler

from .common import *  # noqa: F401,F403

addonHandler.initTranslation()


class OverlayMixin:
	def captureForOverlay(self, box):
		try:
			return self._grab(box)
		except curtain.CurtainBlocked:
			raise RuntimeError(_curtainBlockedMessage())

	def openOverlay(self, restore=False, best=False):
		"""Open the overlay for the window in front. best puts the cursor on its most useful item."""
		try:
			from contentRecog import RecogImageInfo, recogUi
			from . import overlay
		except ImportError:
			log.debugWarning("VisionMate: content recognition is not available", exc_info=True)
			return
		focus = api.getFocusObject()
		if isinstance(focus, overlay.OverlayDocument):
			if not restore:
				# Pressing NVDA+Alt+O again closes the overlay.
				focus.script_exit(None)
			return
		fg = api.getForegroundObject()
		loc = _windowBox(fg)
		app = _safe(lambda: fg.appModule.appName) or "?"
		recognizer = overlay.OverlayRecognizer(self, app, live=conf()["overlayLive"], underCurtain=curtain.isOn(),
			title=_safe(lambda: fg.name) or "")
		try:
			imageInfo = RecogImageInfo.createFromRecognizer(loc.left, loc.top, loc.width, loc.height, recognizer)
		except ValueError:
			ui.message(_("This window has no location on screen."))
			return
		# The same steps as NVDA's own recognizeNavigatorObject, but with the overlay's own document.
		if getattr(recogUi, "_activeRecog", None):
			recogUi._activeRecog.cancel()
		recogUi._activeRecog = recognizer
		if not restore:
			sounds.play("overlayOpen")
			# Translators: Reported while the overlay is being prepared.
			ui.message(_("Overlay"))
		try:
			# NVDA creates its objects from keyword arguments only.
			document = overlay.OverlayDocument(
				plugin=self, restoreText=self._overlayItem if restore else None, startBest=best and not restore,
				recognizer=recognizer, imageInfo=imageInfo,
			)
			document.start()
		except Exception:
			log.error("VisionMate: could not open the overlay", exc_info=True)
			self.overlayClosed()
			sounds.play("error")
			# Translators: Reported when the overlay could not be opened.
			ui.message(_("Could not open the overlay."))
			return
		self._overlayWindow = _safe(lambda: fg.windowHandle)
		self._overlayDoc = document

	def overlayClicked(self, itemText):
		"""An item was clicked. A click can open another window, so for a moment the overlay follows the window
		in front. Without live updates, show the result of the click once the window has reacted."""
		self._overlayItem = itemText
		self._overlayFollowUntil = time.monotonic() + OVERLAY_FOLLOW_SECONDS
		doc = self._overlayDoc
		if doc is not None and not doc.recognizer.allowAutoRefresh:
			wx.CallLater(OVERLAY_REOPEN_MS, self._refreshOverlayNow, doc)

	def _overlayLeft(self):
		"""True if the user has moved to another window, not just clicked something that opened one."""
		fg = api.getForegroundObject()
		return (_safe(lambda: fg.windowHandle) != self._overlayWindow
			and time.monotonic() > self._overlayFollowUntil)

	def overlayClosed(self):
		# Icons not named yet are not needed now; naming them would only hold up the next description.
		icons = [item for item in list(self._background) if item[1][0] == "icon"]
		for item in icons:
			try:
				self._background.remove(item)
			except ValueError:
				pass
			self._backgroundKeys.discard(item[1])
		key = self._backgroundKey
		if key is not None and key[0] == "icon":
			self._backgroundKeys.discard(key)
			self._backgroundCancel.set()
		self._iconsQueued.clear()
		self._overlayWindow = None
		self._overlayItem = None
		self._overlayFollowUntil = 0
		self._overlayDoc = None

	def _holdOverlay(self, obj):
		"""The real window took the focus, for example after a click. Keep NVDA in the overlay, silently, and
		update it in place: the same window refreshes, a new window replaces the contents.
		Returns False if the overlay should close, because the user moved to another program."""
		from . import overlay
		doc = self._overlayDoc
		if isinstance(obj, overlay.OverlayDocument):
			return False
		if self._overlayLeft():
			self.overlayClosed()
			return False
		fg = api.getForegroundObject()
		# Escape goes back to the real control that has the focus now. Set first: NVDA builds the focus
		# ancestors from it.
		doc.parent = obj
		try:
			api.setFocusObject(doc)
		except Exception:
			log.debugWarning("VisionMate: could not keep the overlay", exc_info=True)
			self.overlayClosed()
			return False
		handle = _safe(lambda: fg.windowHandle)
		if handle != self._overlayWindow:
			self._retargetOverlay(doc, fg)
			self._overlayWindow = handle
		doc.recognizer.namesChanged()  # read the window again even if it looks the same
		doc.keepAlive()
		return True

	def _retargetOverlay(self, doc, fg):
		"""Point the overlay at a new window."""
		from contentRecog import RecogImageInfo
		loc = _windowBox(fg)
		recognizer = doc.recognizer
		recognizer.app = _safe(lambda: fg.appModule.appName) or "?"
		recognizer.title = _safe(lambda: fg.name) or ""
		try:
			doc.imageInfo = RecogImageInfo.createFromRecognizer(loc.left, loc.top, loc.width, loc.height, recognizer)
		except ValueError:
			return
		doc.newWindow()

	def _refreshOverlayNow(self, doc):
		if doc is self._overlayDoc and api.getFocusObject() is doc:
			doc.refreshNow()

	# --- Finding something on the screen ---

	def findOnScreen(self):
		"""Ask what to look for in the window in front, say roughly where it is, and offer to click it or move the
		mouse there. The window is read while the user types."""
		try:
			from contentRecog import RecogImageInfo
			from . import overlay
		except ImportError:
			log.debugWarning("VisionMate: content recognition is not available", exc_info=True)
			return
		fg = api.getForegroundObject()
		loc = _windowBox(fg)
		app = _safe(lambda: fg.appModule.appName) or "?"
		try:
			image = self.captureForOverlay((loc.left, loc.top, loc.left + loc.width, loc.top + loc.height))
		except Exception as e:
			log.debugWarning("VisionMate: could not capture the window to find something", exc_info=True)
			_sound("error")
			ui.message(str(e))
			return
		info = RecogImageInfo(loc.left, loc.top, loc.width, loc.height, 1)
		read = {"result": None, "done": threading.Event()}

		def readWindow():
			try:
				lines = ocr.recognize(image)
				recognizer = overlay.OverlayRecognizer(self, app, live=False, underCurtain=False)
				read["result"] = recognizer._makeResult(image, lines or [], info)
			except Exception:
				log.error("VisionMate: could not read the window to find something", exc_info=True)
			finally:
				read["done"].set()

		threading.Thread(target=readWindow, name="visionMate-find", daemon=True).start()
		self._askFind(lambda query: threading.Thread(
			target=self._findResult, args=(query, read, image.size), name="visionMate-find", daemon=True).start())

	def _askFind(self, onQuery):
		def show():
			# Translators: Title and prompt of the window for finding something on the screen.
			dlg = wx.TextEntryDialog(gui.mainFrame, _("What are you looking for? For example: Save button"),
				_("VisionMate find on screen"), value=self._lastFind or "")
			gui.mainFrame.prePopup()
			try:
				ok = dlg.ShowModal() == wx.ID_OK
				query = dlg.GetValue().strip()
			finally:
				dlg.Destroy()
				gui.mainFrame.postPopup()
			if ok and query:
				self._lastFind = query
				onQuery(query)

		wx.CallAfter(show)

	def _findResult(self, query, read, size):
		read["done"].wait(FIND_WAIT_SECONDS)
		result = read["result"]
		if result is None:
			_sound("error")
			# Translators: Reported when the window could not be read to find something.
			_speak(_("Could not read this window."))
			return
		found = findonscreen.find(query, result.items)
		if not found:
			_sound("error")
			# Translators: Reported when nothing matches. {query} is what the user typed, {count} the window's items.
			_speak(_("Not found: {query}. This window has {count} items; NVDA+Alt+O lists them.").format(
				query=query, count=len(result.items)))
			return
		choices = [(item, _("{item}, {place}").format(item=item["text"], place=findonscreen.place(item["box"], size)))
			for item in found]
		wx.CallAfter(self._showFound, result, choices)

	def _showFound(self, result, choices):
		if len(choices) > 1:
			# Translators: Title and prompt of the list when several things match. {count} is how many.
			dlg = wx.SingleChoiceDialog(gui.mainFrame, _("{count} matches. Choose one:").format(count=len(choices)),
				_("VisionMate find on screen"), [text for _item, text in choices])
			gui.mainFrame.prePopup()
			try:
				if dlg.ShowModal() != wx.ID_OK:
					return
				item, text = choices[dlg.GetSelection()]
			finally:
				dlg.Destroy()
				gui.mainFrame.postPopup()
		else:
			item, text = choices[0]
		dlg = FoundDialog(gui.mainFrame, text)
		gui.mainFrame.prePopup()
		try:
			action = dlg.ShowModal()
		finally:
			dlg.Destroy()
			gui.mainFrame.postPopup()
		if action in (FoundDialog.CLICK, FoundDialog.MOVE):
			# Let the window in front come back before the mouse moves.
			wx.CallLater(FIND_ACT_DELAY_MS, self._actOnFound, result.screenPoint(item), action == FoundDialog.CLICK,
				item["plain"] or item["text"])
		elif action == FoundDialog.MORE:
			left, top, right, bottom = item["box"]
			info = result.imageInfo
			box = (info.convertXToScreen(left), info.convertYToScreen(top), info.convertXToScreen(right),
				info.convertYToScreen(bottom))
			isText = item.get("kind") == "text" and bool((item.get("plain") or "").strip())
			self.itemActions(result.screenPoint(item), box, item["plain"] or item["text"], isText)

	def _actOnFound(self, point, click, name):
		import core
		import mouseHandler
		import winUser
		x, y = point
		log.debug(f"VisionMate: found {name!r} at {point}, click: {click}")
		old = winUser.getCursorPos()
		winUser.setCursorPos(x, y)
		if click:
			sounds.play("click")
			mouseHandler.doPrimaryClick()
			core.callLater(FIND_CLICK_SETTLE_MS, winUser.setCursorPos, *old)
		else:
			# Translators: Reported after the mouse was moved to what was found.
			ui.message(_("Mouse moved to {name}").format(name=name))


class FoundDialog(wx.Dialog):
	"""Says what was found and where, with Click, Move the mouse there and Cancel."""
	CLICK, MOVE, MORE = wx.ID_HIGHEST + 1, wx.ID_HIGHEST + 2, wx.ID_HIGHEST + 3

	def __init__(self, parent, text):
		# Translators: Title of the window that shows what was found on the screen.
		super().__init__(parent, title=_("VisionMate found"))
		main = wx.BoxSizer(wx.VERTICAL)
		self.message = wx.TextCtrl(self, value=text, size=(420, -1), style=wx.TE_READONLY)
		main.Add(self.message, flag=wx.ALL | wx.EXPAND, border=10)
		buttons = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: Button that clicks what was found on the screen.
		click = wx.Button(self, self.CLICK, label=_("&Click"))
		# Translators: Button that moves the mouse to what was found on the screen.
		move = wx.Button(self, self.MOVE, label=_("&Move the mouse there"))
		# Translators: Button that opens more actions for what was found: hover, drag, set to a number and more.
		more = wx.Button(self, self.MORE, label=_("M&ore..."))
		cancel = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))
		for i, b in enumerate((click, move, more, cancel)):
			buttons.Add(b, flag=wx.LEFT if i else 0, border=10)
			if b is not cancel:
				b.Bind(wx.EVT_BUTTON, lambda e, code=b.GetId(): self.EndModal(code))
		main.Add(buttons, flag=wx.ALL | wx.ALIGN_RIGHT, border=10)
		self.SetSizerAndFit(main)
		self.SetEscapeId(wx.ID_CANCEL)
		click.SetDefault()
		self.message.SetFocus()
		self.CentreOnScreen()
