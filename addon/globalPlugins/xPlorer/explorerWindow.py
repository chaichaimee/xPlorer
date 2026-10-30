# explorerWindow.py

import ctypes
import subprocess
import threading
import time
from ctypes import wintypes

import addonHandler
import ui
import wx
from logHandler import log

from .folderTools import loadConfig

addonHandler.initTranslation()

_SW_MAXIMIZE = 3
_EXPLORER_FRAME_CLASS = "CabinetWClass"
_POLL_SECONDS = 0.15
_WATCH_SECONDS = 6.0
_MAX_MAXIMIZE_ATTEMPTS = 20

_enumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_stateLock = threading.Lock()
_watcherRunning = False
_watchDeadline = 0.0
_pendingLaunches = 0
_knownFrames = set()


def _listExplorerFrames():
	user32 = ctypes.windll.user32
	frames = set()
	classBuffer = ctypes.create_unicode_buffer(64)

	def onWindow(hwnd, _lparam):
		if (
			user32.GetClassNameW(hwnd, classBuffer, 64)
			and classBuffer.value == _EXPLORER_FRAME_CLASS
			and user32.IsWindowVisible(hwnd)
		):
			frames.add(hwnd)
		return True

	user32.EnumWindows(_enumWindowsProc(onWindow), 0)
	return frames


def _announceMaximized(frame):
	if ctypes.windll.user32.GetForegroundWindow() != frame:
		return
	wx.CallAfter(ui.message, _("maximized"))


def _advanceTrackedFrame(frame, attemptsByFrame):
	user32 = ctypes.windll.user32
	if not user32.IsWindow(frame):
		return True
	if user32.IsZoomed(frame):
		log.debug("xPlorer: explorer window %s is maximized" % frame)
		_announceMaximized(frame)
		return True
	if attemptsByFrame[frame] >= _MAX_MAXIMIZE_ATTEMPTS:
		log.debug("xPlorer: explorer window %s could not be maximized" % frame)
		return True
	attemptsByFrame[frame] += 1
	user32.ShowWindowAsync(frame, _SW_MAXIMIZE)
	return False


def _stopWatching():
	global _watcherRunning, _pendingLaunches
	with _stateLock:
		_watcherRunning = False
		_pendingLaunches = 0


def _watchNewFrames():
	global _watcherRunning, _pendingLaunches
	attemptsByFrame = {}
	while True:
		time.sleep(_POLL_SECONDS)
		with _stateLock:
			expired = time.time() > _watchDeadline
		if expired:
			_stopWatching()
			return
		try:
			currentFrames = _listExplorerFrames()
		except OSError as e:
			log.debug("xPlorer: explorer frame enumeration failed, maximize stopped: %s" % e)
			_stopWatching()
			return
		with _stateLock:
			for frame in currentFrames - _knownFrames:
				attemptsByFrame.setdefault(frame, 0)
		for frame in list(attemptsByFrame):
			if not _advanceTrackedFrame(frame, attemptsByFrame):
				continue
			del attemptsByFrame[frame]
			with _stateLock:
				_knownFrames.add(frame)
				_pendingLaunches = max(0, _pendingLaunches - 1)
		with _stateLock:
			finished = _pendingLaunches <= 0 and not attemptsByFrame
			if finished:
				_watcherRunning = False
		if finished:
			return


def _beginWatching():
	global _watcherRunning, _watchDeadline, _pendingLaunches
	try:
		framesBeforeLaunch = _listExplorerFrames()
	except OSError as e:
		log.debug(f"xPlorer: explorer frame snapshot failed, maximize skipped: {e}")
		return False
	startWatcher = False
	with _stateLock:
		if not _watcherRunning:
			_knownFrames.clear()
			_knownFrames.update(framesBeforeLaunch)
			_pendingLaunches = 0
			_watcherRunning = True
			startWatcher = True
		_pendingLaunches += 1
		_watchDeadline = time.time() + _WATCH_SECONDS
	if startWatcher:
		threading.Thread(target=_watchNewFrames, daemon=True).start()
	return True


def _cancelPendingLaunch():
	global _pendingLaunches
	with _stateLock:
		_pendingLaunches = max(0, _pendingLaunches - 1)


def launchExplorer(arguments):
	maximizeWanted = bool(loadConfig().get("openExplorerMaximized", True)) and _beginWatching()
	try:
		subprocess.Popen(["explorer.exe"] + list(arguments))
	except OSError:
		if maximizeWanted:
			_cancelPendingLaunch()
		raise
