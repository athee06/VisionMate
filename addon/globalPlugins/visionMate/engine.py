# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - local image description for NVDA.
# Runs the bundled engine (llama.cpp server) and streams image descriptions from it.
# This module has no NVDA dependencies so it can be tested on its own.

import base64
import ctypes
import http.client
import io
import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes

try:
	from logHandler import log
except ImportError:
	import logging
	log = logging.getLogger("visionMate")
	log.debugWarning = log.warning

CREATE_NO_WINDOW = 0x08000000


class EngineError(Exception):
	pass


# --- Job object: makes Windows kill llama-server if NVDA exits or crashes. ---

class _IoCounters(ctypes.Structure):
	_fields_ = [(n, ctypes.c_ulonglong) for n in (
		"ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
		"ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
	_fields_ = [
		("PerProcessUserTimeLimit", ctypes.c_longlong),
		("PerJobUserTimeLimit", ctypes.c_longlong),
		("LimitFlags", wintypes.DWORD),
		("MinimumWorkingSetSize", ctypes.c_size_t),
		("MaximumWorkingSetSize", ctypes.c_size_t),
		("ActiveProcessLimit", wintypes.DWORD),
		("Affinity", ctypes.c_size_t),
		("PriorityClass", wintypes.DWORD),
		("SchedulingClass", wintypes.DWORD),
	]


class _ExtendedLimits(ctypes.Structure):
	_fields_ = [
		("BasicLimitInformation", _BasicLimits),
		("IoInfo", _IoCounters),
		("ProcessMemoryLimit", ctypes.c_size_t),
		("JobMemoryLimit", ctypes.c_size_t),
		("PeakProcessMemoryUsed", ctypes.c_size_t),
		("PeakJobMemoryUsed", ctypes.c_size_t),
	]


_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9


def _createKillOnCloseJob():
	k32 = ctypes.WinDLL("kernel32", use_last_error=True)
	k32.CreateJobObjectW.restype = wintypes.HANDLE
	k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
	k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
	k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
	job = k32.CreateJobObjectW(None, None)
	if not job:
		return None, k32
	info = _ExtendedLimits()
	info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	k32.SetInformationJobObject(job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info))
	return job, k32


def prepareImage(image, maxSide):
	"""Shrink a PIL image so its longest side is at most maxSide and return JPEG bytes.
	Smaller images are the biggest speed win: fewer image tokens for the model to read."""
	image = image.convert("RGB")
	if max(image.size) > maxSide:
		image = image.copy()
		image.thumbnail((maxSide, maxSide), _lanczos())
	buf = io.BytesIO()
	image.save(buf, "JPEG", quality=90)
	return buf.getvalue()


def _lanczos():
	from PIL import Image
	return getattr(Image, "Resampling", Image).LANCZOS


def _freePort():
	with socket.socket() as s:
		s.bind(("127.0.0.1", 0))
		return s.getsockname()[1]


class Engine:
	"""Owns one llama-server process. Thread safe; all methods may block."""

	def __init__(self, engineDir, logPath=None):
		self._exe = os.path.join(engineDir, "vmengine.exe")
		self._logPath = logPath
		self._lock = threading.RLock()
		self._proc = None
		self._port = None
		self._config = None
		self._job, self._k32 = _createKillOnCloseJob()

	@property
	def running(self):
		return self._proc is not None and self._proc.poll() is None

	@property
	def usingGpu(self):
		return bool(self._config and self._config[2])

	def ensure(self, modelPath, mmprojPath, useGpu):
		"""Start the server with this configuration unless it is already running with it."""
		config = (modelPath, mmprojPath, useGpu)
		with self._lock:
			if self.running and self._config == config:
				return
			self.stop()
			self._start(config)

	def _start(self, config):
		modelPath, mmprojPath, useGpu = config
		self._port = _freePort()
		args = [
			self._exe, "-m", modelPath, "--mmproj", mmprojPath,
			"--host", "127.0.0.1", "--port", str(self._port),
			"-c", "4096", "-np", "1", "--no-webui",
		]
		args += ["-ngl", "99"] if useGpu else ["-ngl", "0", "--device", "none", "--no-mmproj-offload"]
		log.debug(f"VisionMate: starting {args}")
		logFile = open(self._logPath, "w", encoding="utf-8", errors="replace") if self._logPath else subprocess.DEVNULL
		try:
			self._proc = subprocess.Popen(
				args, cwd=os.path.dirname(self._exe), stdin=subprocess.DEVNULL,
				stdout=subprocess.DEVNULL, stderr=logFile, creationflags=CREATE_NO_WINDOW,
			)
		finally:
			if logFile is not subprocess.DEVNULL:
				logFile.close()
		if self._job:
			self._k32.AssignProcessToJobObject(self._job, int(self._proc._handle))
		self._config = config
		self._waitHealthy(timeout=180)
		self._warmUp()

	def _waitHealthy(self, timeout):
		deadline = time.monotonic() + timeout
		while time.monotonic() < deadline:
			if self._proc.poll() is not None:
				self._proc = None
				raise EngineError("The description engine stopped while loading the model.")
			try:
				with urllib.request.urlopen(self._url("/health"), timeout=2) as r:
					if json.load(r).get("status") == "ok":
						return
			except (urllib.error.URLError, OSError, ValueError):
				pass
			time.sleep(0.2)
		self.stop()
		raise EngineError("The description engine took too long to load the model.")

	def _warmUp(self):
		# The first image request compiles GPU shaders; do it now instead of on the user's first press.
		from PIL import Image
		try:
			self.describe(prepareImage(Image.new("RGB", (64, 64), "gray"), 64), "Hi", 1)
		except EngineError:
			log.debugWarning("VisionMate: warm-up failed", exc_info=True)

	def stop(self):
		with self._lock:
			if self._proc is not None:
				try:
					self._proc.kill()
					self._proc.wait(timeout=5)
				except Exception:
					log.debugWarning("VisionMate: could not stop engine", exc_info=True)
			self._proc = None
			self._config = None

	def _url(self, path):
		return f"http://127.0.0.1:{self._port}{path}"

	def describe(self, jpegBytes, prompt, maxTokens, onText=None, cancel=None):
		"""Send one image and prompt. Calls onText(delta) as text streams in.
		Returns the full text, or None if cancelled."""
		if not self.running:
			raise EngineError("The description engine is not running.")
		b64 = base64.b64encode(jpegBytes).decode("ascii")
		body = {
			"messages": [{"role": "user", "content": [
				{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
				{"type": "text", "text": prompt},
			]}],
			"max_tokens": maxTokens,
			"temperature": 0,
			"stream": True,
		}
		conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=300)
		finished = threading.Event()
		if cancel is not None:
			threading.Thread(target=self._abortOnCancel, args=(conn, cancel, finished), daemon=True).start()
		parts = []
		try:
			conn.request(
				"POST", "/v1/chat/completions", body=json.dumps(body).encode("utf-8"),
				headers={"Content-Type": "application/json"},
			)
			resp = conn.getresponse()
			if resp.status != 200:
				raise EngineError(f"The description engine returned an error: {resp.read()[:300]!r}")
			for raw in resp:
				if cancel is not None and cancel.is_set():
					return None
				line = raw.decode("utf-8", "replace").strip()
				if not line.startswith("data:") or line.endswith("[DONE]"):
					continue
				msg = json.loads(line[5:])
				if "error" in msg:
					raise EngineError(str(msg["error"].get("message", msg["error"])))
				delta = msg["choices"][0]["delta"].get("content")
				if delta:
					parts.append(delta)
					if onText is not None:
						onText(delta)
		except (http.client.HTTPException, OSError) as e:
			if cancel is not None and cancel.is_set():
				return None
			raise EngineError(f"Lost connection to the description engine: {e}")
		finally:
			finished.set()
			conn.close()
		return "".join(parts).strip()

	@staticmethod
	def _abortOnCancel(conn, cancel, finished):
		# Closing the socket makes llama-server drop the request at once, so the next one is not queued behind it.
		while not finished.is_set():
			if cancel.wait(0.05):
				if conn.sock is not None:
					try:
						conn.sock.shutdown(socket.SHUT_RDWR)
					except OSError:
						pass
				return
