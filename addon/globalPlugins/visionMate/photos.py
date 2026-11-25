# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

"""Photos and icons outside browse mode: focus events, chat photos, image viewers, File Explorer and button names."""
import addonHandler

from .common import *  # noqa: F401,F403

addonHandler.initTranslation()


class PhotosMixin:
	def event_gainFocus(self, obj, nextHandler):
		if self._overlayDoc is not None and self._holdOverlay(obj):
			return  # NVDA stays in the overlay, which updates in place
		if self._isQuiet(obj):
			return
		nextHandler()
		self._focusGeneration += 1
		try:
			localmedia.warmUp(obj.appModule.appName)
		except Exception:
			log.debug("VisionMate: could not prepare the app's photo list")
		try:
			self._sayChatPhoto(obj)
		except Exception:
			log.debugWarning("VisionMate: WinZapp photo check failed", exc_info=True)
		try:
			self._scheduleHelpOffer(obj)
		except Exception:
			log.debugWarning("VisionMate: help offer failed", exc_info=True)
		if not self._hasData:
			return
		try:
			self._checkFocus(obj, self._focusGeneration)
		except Exception:
			# Never let this break NVDA's own focus handling.
			log.debugWarning("VisionMate: focus check failed", exc_info=True)

	def event_foreground(self, obj, nextHandler):
		if self._isQuiet(obj):
			return
		nextHandler()

	def _isQuiet(self, obj):
		"""True for focus changes caused by fetching a WinZapp photo: the viewer it opens, which is hidden at once, and
		WinZapp getting the focus back on the same message."""
		if time.monotonic() > self._quietUntil:
			return False
		try:
			app = (obj.appModule.appName or "").lower()
			if app in winzapp.VIEWER_APPS:
				return True
			if winzapp.isWinZapp(app):
				# The window coming back to the front, or the message the user is still on.
				return obj.windowHandle == self._quietTop or (self._quietFocus is not None and obj == self._quietFocus)
		except Exception:
			log.debugWarning("VisionMate: quiet check failed", exc_info=True)
		return False

	def _chatPhotoTarget(self, obj):
		"""(WinZapp window, Open image button, message key) when obj is a selected photo message in WinZapp, else None."""
		appModule = _safe(lambda: obj.appModule)
		if appModule is None or not winzapp.isWinZapp(appModule.appName) or obj.role != controlTypes.Role.LISTITEM:
			return None
		if controlTypes.State.SELECTED not in obj.states:
			return None  # the button belongs to the selected message
		top = api.getForegroundObject().windowHandle
		appDir = os.path.dirname(_safe(lambda: appModule.appPath) or "")
		button = winzapp.openImageButton(top, winzapp.openImageNames(appDir))
		if not button:
			return None
		return top, button, winzapp.messageKey(winzapp.chatName(obj.windowHandle), obj.name)

	def _sayChatPhoto(self, obj):
		"""On a WinZapp photo message that was described before, say what the photo shows."""
		appName = _safe(lambda: obj.appModule.appName)
		if not winzapp.isWinZapp(appName) or obj.role != controlTypes.Role.LISTITEM:
			return
		text = self.chatPhotos.get(winzapp.messageKey(winzapp.chatName(obj.windowHandle), obj.name))
		if text:
			# Translators: Spoken after a WinZapp photo message, before what its photo shows.
			ui.message(_("Image: ") + text)

	def _describeChatPhoto(self, obj):
		"""NVDA+Alt+A on a photo message in WinZapp. Returns False if obj is not one."""
		target = self._chatPhotoTarget(obj)
		if target is None:
			return False
		key = target[2]
		mode = self._pressMode()
		fetch = self._chatFetch
		if fetch is not None and fetch["key"] == key and fetch["image"] is None and not fetch["cancel"].is_set():
			fetch["mode"] = mode  # a second press while the photo is still coming
			return True
		if mode == QUICK:
			saved = self.chatPhotos.get(key)
			if saved:
				ui.message(saved)
				return True
		elif self._chatPhoto is not None and self._chatPhoto[0] == key:
			self._describeChatPhotoNow(key, self._chatPhoto[1], mode)
			return True
		if not self._dataReady():
			self.showDataDialog()
			return True
		self._startChatFetch(target, mode)
		return True

	def _startChatFetch(self, target, mode):
		"""Get the photo of a WinZapp message in the background, then describe it."""
		top, button, key = target
		if self._chatFetch is not None:
			self._chatFetch["cancel"].set()
		focus = api.getFocusObject()
		fetch = self._chatFetch = {"key": key, "mode": mode, "image": None, "cancel": threading.Event(), "focus": focus}
		self._quietFocus = focus
		self._quietTop = top
		self._quietUntil = time.monotonic() + winzapp.FETCH_SECONDS + winzapp.VIEWER_SECONDS

		def onPhoto(image):
			fetch["image"] = image if image is not None else False
			wx.CallAfter(self._chatPhotoReady, fetch)

		def run():
			try:
				winzapp.fetchPhoto(top, button, fetch["cancel"], onPhoto)
			except Exception:
				log.error("VisionMate: could not get the photo from WinZapp", exc_info=True)
				if fetch["image"] is None:
					onPhoto(None)
			finally:
				if self._chatFetch is fetch:
					self._quietUntil = time.monotonic() + CHAT_PHOTO_QUIET_SECONDS

		def stillComing():
			if fetch["image"] is None and not fetch["cancel"].is_set() and self._chatFetch is fetch:
				# Translators: Spoken when a WinZapp photo takes a while, usually because it is being downloaded.
				ui.message(_("Getting the photo"))

		threading.Thread(target=run, name="visionMate-winzapp", daemon=True).start()
		if mode != AUTO:
			wx.CallLater(CHAT_PHOTO_WAIT_MS, stillComing)

	def _chatPhotoReady(self, fetch):
		if fetch["cancel"].is_set() or self._chatFetch is not fetch:
			return
		if fetch["image"] is False:
			if fetch["mode"] != AUTO:
				_sound("error")
				# Translators: Reported when WinZapp did not give VisionMate the photo of a message.
				ui.message(_("Could not get the photo from WinZapp."))
			return
		key, image = fetch["key"], fetch["image"]
		self._chatPhoto = (key, image)
		if fetch["mode"] == AUTO and api.getFocusObject() != fetch["focus"]:
			# The user moved on: describe it quietly, so it is ready when they come back.
			self._queueBackground(self._chatPhotoJob(key, image), ("chat", key))
			return
		self._describeChatPhotoNow(key, image, fetch["mode"])

	def _chatPhotoJob(self, key, image):
		prompt = _contextPrompt(CHAT_PHOTO_CONTEXT) + AUTO_PROMPT + HONESTY + _languageInstruction()

		def run(cancel):
			text = self._backgroundDescribe(image, prompt, 80, conf()["quickSize"], cancel)
			if text is None:
				return False
			if text and not self.chatPhotos.get(key):
				self.chatPhotos.set(key, " ".join(_clean(text).split()))
			return True
		return run

	def _describeChatPhotoNow(self, key, image, mode):
		def onDone(text, doneMode):
			# The short description is the one said on the message; a detailed one is kept only if there is none.
			if doneMode == QUICK or not self.chatPhotos.get(key):
				self.chatPhotos.set(key, " ".join(_clean(text).split()))

		self._describe(image, mode, context=CHAT_PHOTO_CONTEXT, onDone=onDone)

	def _checkFocus(self, obj, generation):
		c = conf()
		if c["autoDescribe"] and self._autoPhoto(obj, generation):
			return
		if not (c["iconLabeler"] or c["autoDescribe"]) or not autodescribe.isUnlabeled(obj.name):
			return
		role = obj.role
		if c["iconLabeler"] and role in ICON_ROLES and not (obj.description or "").strip():
			wx.CallLater(100, self._labelFocusedButton, obj, generation)
		elif c["autoDescribe"] and role == controlTypes.Role.GRAPHIC:
			ti = obj.treeInterceptor
			if ti is None or ti.passThrough:  # browse mode is handled while reading
				wx.CallLater(150, self._autoCapture, lambda: obj.location, self._autoGeneration, None, None,
					_windowContext())

	def _autoPhoto(self, obj, generation):
		"""Describe a photo where the focus landed, once the user stays there for a moment. Returns True if obj is a
		photo message or the focus is in an image viewer, so nothing else needs checking."""
		if self._viewerName(api.getForegroundObject()):
			wx.CallLater(VIEWER_DELAY_MS, self._autoViewer)
			return True
		if obj.role not in PHOTO_HOLDER_ROLES:
			return False
		if explorer.isExplorer(_safe(lambda: obj.appModule.appName)):
			# Image files in File Explorer and on the desktop are described from the file, not the thumbnail.
			wx.CallLater(AUTO_FOCUS_DELAY_MS, self._autoExplorerFile, obj, generation)
			return True
		target = self._chatPhotoTarget(obj)
		if target is not None:
			if not self.chatPhotos.get(target[2]):  # a described one was already said with the message
				wx.CallLater(AUTO_FOCUS_DELAY_MS, self._autoChatPhoto, obj, target, generation)
			return True
		loc = obj.location
		if winzapp.isWinZapp(_safe(lambda: obj.appModule.appName)) or not loc or loc.height < imaging.PHOTO_MIN_SIDE:
			return False
		wx.CallLater(AUTO_FOCUS_DELAY_MS, self._autoMessagePhoto, obj, generation)
		return False

	def _stillThere(self, generation):
		return generation == self._focusGeneration and not scriptHandler.isScriptWaiting()

	def _autoChatPhoto(self, obj, target, generation):
		if self._stillThere(generation) and self._dataReady():
			self._startChatFetch(target, AUTO)

	def _autoMessagePhoto(self, obj, generation):
		"""A message in a chat app that shows its photo on screen, like WhatsApp or Telegram."""
		if not self._stillThere(generation) or not self._dataReady():
			return
		loc = _safe(lambda: obj.location)
		if not loc or loc.width <= 0 or loc.height <= 0:
			return
		bbox = _bbox(loc)
		image = self._grabOrReport(bbox, quiet=True)
		if image is None:
			return
		photo = _safe(lambda: self._photoIn(obj, bbox, image))
		if not photo:
			return
		image = image.crop(photo)
		if autodescribe.isBlank(image):
			return
		key = hashlib.sha1(image.tobytes()).hexdigest()
		cached = self._autoCache.get(key)
		if cached:
			self._autoCache.move_to_end(key)
			ui.message(_("Image: ") + _clean(cached))
			return
		self._describeMessagePhoto(image, AUTO, _safe(lambda: obj.appModule.appName), cacheKey=key, generation=generation)

	def _describeMessagePhoto(self, preview, mode, appName, cacheKey=None, generation=None):
		"""Describe a photo cut from a chat message. If the app keeps the full-size photo as a file, like Unigram, that
		is found in the background and described instead, so small text can be read. With a focus generation, it is
		dropped if the user moved on meanwhile."""
		context = _windowContext() + [("shown", "a photo someone sent in a chat")]
		if not localmedia.folders(appName):
			self._describe(preview, mode, cacheKey=cacheKey, context=context, screen=True)
			return
		self._originalRequest += 1
		request = self._originalRequest

		def describe(image):
			# Only the newest request: a second press replaces the first.
			if request != self._originalRequest or (generation is not None and not self._stillThere(generation)):
				return
			self._describe(image, mode, cacheKey=cacheKey, context=context, screen=True)

		def find():
			path = localmedia.findOriginal(preview, appName)
			image = viewers.openImage(path) if path else None
			wx.CallAfter(describe, image if image is not None else preview)

		threading.Thread(target=find, name="visionMate-original", daemon=True).start()

	@staticmethod
	def _viewerName(fg):
		"""The image file name in the title of the window in front, like "beach.jpg - Photos", or None."""
		return viewers.imageName(_safe(lambda: fg.name))

	def _describeViewerImage(self):
		"""In an image viewer, describe the image file it shows at full quality. Returns False if not in one."""
		if not self._viewerName(api.getForegroundObject()):
			return False
		found = viewers.imageInWindow(_safe(lambda: api.getForegroundObject().name))
		# If the file was not found, the screen is described instead.
		return bool(found) and self._describeFile(found[0], self._pressMode())

	@staticmethod
	def _fileKey(path):
		try:
			return f"file:{path}:{os.path.getmtime(path)}"
		except OSError:
			return None

	def _describeFile(self, path, mode):
		"""Describe an image file. Returns False if it cannot be read, like a format VisionMate does not know."""
		key = self._fileKey(path)
		if mode == AUTO:
			cached = self._autoCache.get(key)
			if cached:
				self._autoCache.move_to_end(key)
				ui.message(_("Image: ") + _clean(cached))
				return True
		image = viewers.openImage(path)
		if image is None:
			return False
		self._describe(image, mode, cacheKey=key, context=[("file name", os.path.basename(path))])
		return True

	def _explorerImage(self, obj):
		"""The image file an item in File Explorer or on the desktop stands for, or None."""
		if not explorer.isExplorer(_safe(lambda: obj.appModule.appName)) or obj.role != controlTypes.Role.LISTITEM:
			return None
		fg = api.getForegroundObject()
		onDesktop = _safe(lambda: fg.windowClassName) in ("Progman", "WorkerW")
		return explorer.imageFile(_safe(lambda: fg.windowHandle), obj.name, onDesktop)

	def _autoExplorerFile(self, obj, generation):
		if not self._stillThere(generation) or not self._dataReady():
			return
		path = _safe(lambda: self._explorerImage(obj))
		if path:
			self._describeFile(path, AUTO)

	def _autoViewer(self):
		"""An image viewer is in front: describe its photo once."""
		if not conf()["autoDescribe"] or not self._dataReady() or time.monotonic() < self._quietUntil:
			return
		found = viewers.imageInWindow(_safe(lambda: api.getForegroundObject().name))
		if not found:
			return
		path = found[0]
		key = self._fileKey(path)
		if key is None or key == self._viewerShown:
			return  # the focus moved inside the viewer; this photo was already said
		self._viewerShown = key
		self._describeFile(path, AUTO)

	def event_nameChange(self, obj, nextHandler):
		nextHandler()
		# A viewer shows the next photo by changing its title.
		try:
			if conf()["autoDescribe"] and obj == api.getForegroundObject() and self._viewerName(obj):
				wx.CallLater(VIEWER_DELAY_MS, self._autoViewer)
		except Exception:
			log.debugWarning("VisionMate: viewer title check failed", exc_info=True)

	def _buttonImage(self, obj):
		"""A picture of a small button, or None."""
		loc = obj.location
		if not loc or not (ICON_MIN_SIDE <= loc.width <= ICON_MAX_SIDE and ICON_MIN_SIDE <= loc.height <= ICON_MAX_SIDE):
			return None
		return self._grabOrReport(_bbox(loc), quiet=True)

	def _labelFocusedButton(self, obj, generation):
		if generation != self._focusGeneration or scriptHandler.isScriptWaiting():
			return
		image = self._buttonImage(obj)
		if image is None:
			return
		app = _safe(lambda: obj.appModule.appName)
		key = labels.imageKey(image)
		name, byUser = self.labels.get(app, key)
		if name:
			# Translators: Spoken when a button without a name is focused. {name} is a guess from its icon.
			ui.message(name if byUser else _("Probably {name}").format(name=name))
			return

		def onDone(text):
			name = _iconName(text)
			if name:
				self.labels.setGuess(app, key, name)
				if generation == self._focusGeneration:
					_speak(_("Probably {name}").format(name=name))

		self._describe(image, ICON, context=[("app", app)], onDone=onDone)

	def _askName(self, current, onName):
		def show():
			# Translators: Title and prompt of the window for naming a button or overlay item.
			dlg = wx.TextEntryDialog(gui.mainFrame, _("Name (leave empty to remove your name):"), _("VisionMate name"),
				value=current)
			gui.mainFrame.prePopup()
			try:
				ok = dlg.ShowModal() == wx.ID_OK
				name = dlg.GetValue().strip()
			finally:
				dlg.Destroy()
				gui.mainFrame.postPopup()
			if ok:
				onName(name)
				# Translators: Reported after a name was saved or removed.
				ui.message(_("Name saved") if name else _("Name removed"))

		wx.CallAfter(show)
