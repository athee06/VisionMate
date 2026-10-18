# Copyright (C) 2026 Athiban Vijay
# This file is licensed under the GNU General Public License, version 2 or later.
# See LICENSE for the full terms.

# VisionMate - checks the computer at setup, so slow computers hear about it before the big download.

import ctypes
from ctypes import wintypes

import addonHandler

addonHandler.initTranslation()

# VisionMate uses about 3 GB while it is ready.
MIN_MEMORY_GB = 8
# Display adapters that cannot run the vision data.
_NO_GPU = ("microsoft basic", "remote display", "remotefx", "virtual", "vmware svga", "hyper-v", "citrix", "parsec")


class _MemoryStatus(ctypes.Structure):
	_fields_ = [
		("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
		("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
		("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
		("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
		("ullAvailExtendedVirtual", ctypes.c_ulonglong),
	]


class _DisplayDevice(ctypes.Structure):
	_fields_ = [
		("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32), ("DeviceString", wintypes.WCHAR * 128),
		("StateFlags", wintypes.DWORD), ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128),
	]


def _memoryStatus():
	status = _MemoryStatus()
	status.dwLength = ctypes.sizeof(status)
	if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
		return None
	return status


def memoryGb():
	status = _memoryStatus()
	return status.ullTotalPhys / 1024 ** 3 if status else None


def freeMemoryGb():
	"""Memory other programs can still get, in gigabytes, or None if Windows does not say."""
	status = _memoryStatus()
	return status.ullAvailPhys / 1024 ** 3 if status else None


def graphicsAdapters():
	names = []
	device = _DisplayDevice()
	device.cb = ctypes.sizeof(device)
	i = 0
	while ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(device), 0):
		if device.DeviceString and device.DeviceString not in names:
			names.append(device.DeviceString)
		i += 1
	return names


def hasUsableGpu(adapters):
	return any(not any(bad in name.lower() for bad in _NO_GPU) for name in adapters)


def warnings(memory=None, adapters=None):
	"""Plain-language warnings about this computer, or an empty list if it should be fine."""
	try:
		memory = memoryGb() if memory is None else memory
		adapters = graphicsAdapters() if adapters is None else adapters
	except Exception:
		return []
	found = []
	if memory is not None and memory < MIN_MEMORY_GB - 0.5:
		found.append(_(
			# Translators: Warning at setup. {gb} is the computer's memory in gigabytes.
			"This computer has {gb} GB of memory. VisionMate uses about 3 GB while it is ready, "
			"so it may be slow, and other programs may slow down. You can turn off "
			"\"Get ready when NVDA starts\" in VisionMate settings to save memory."
		).format(gb=round(memory)))
	if not hasUsableGpu(adapters):
		found.append(_(
			# Translators: Warning at setup when no graphics chip was found.
			"No graphics chip was found that VisionMate can use, so descriptions will run on the processor "
			"and may take 5 to 15 seconds."
		))
	return found
