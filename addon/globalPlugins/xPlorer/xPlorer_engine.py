# xPlorer_engine.py

import globalPluginHandler
import ui
import api
import scriptHandler
from NVDAObjects import NVDAObject
from NVDAObjects.UIA import UIA
from controlTypes import Role, State
import addonHandler
from logHandler import log
import gui
import wx
import gui.guiHelper
from keyboardHandler import KeyboardInputGesture
import core
import tones
import threading
from threading import Timer, Thread
import winUser
import os
import sys
import time
import ctypes
import ctypes.wintypes
import urllib.parse
import importlib
from collections import deque

import comtypes.client
from comtypes import COMError
from . import update

addonHandler.initTranslation()
log.debug("xPlorer: Initializing add-on")

_imported_modules = {}

def _safe_import_module(module_name, class_name=None):
	try:
		mod = importlib.import_module('.' + module_name, package=__package__)
		if class_name is None:
			_imported_modules[module_name] = mod
			log.debug(f"xPlorer: {module_name} imported")
			return mod
		else:
			attr = getattr(mod, class_name)
			_imported_modules[module_name] = attr
			log.debug(f"xPlorer: {class_name} imported from {module_name}")
			return attr
	except Exception as e:
		log.exception(f"Failed to import {module_name} (class: {class_name})")
		_imported_modules[module_name] = None
		return None

try:
	from .xPlorerManager import xPlorerSettingsPanel, ExplorerManager, set_global_plugin
	_imported_modules['xPlorerManager'] = True
	log.debug("xPlorer: xPlorerManager imported")
except Exception as e:
	log.exception("Failed to import xPlorerManager - add-on cannot load")
	raise

FileOperations = _safe_import_module('fileOperations', 'FileOperations')
CompressionManager = _safe_import_module('compressionManager', 'CompressionManager')
ClipboardManager = _safe_import_module('clipboardManager', 'ClipboardManager')
SelectionManager = _safe_import_module('folderTools', 'SelectionManager')
RobocopyManager = _safe_import_module('robocopyManager', 'RobocopyManager')
TxtToFolder = _safe_import_module('folderTools', 'TxtToFolder')
CreateFileManager = _safe_import_module('createFile', 'CreateFileManager')
ContextMenuManager = _safe_import_module('contextMenu', 'ContextMenuManager')
PropertiesMenuManager = _safe_import_module('contextMenu', 'PropertiesMenuManager')
FolderInfoManager = _safe_import_module('folderTools', 'FolderInfoManager')
CaseConverter = _safe_import_module('folderTools', 'CaseConverter')
FolderCreationDialog = _safe_import_module('folderTools', 'FolderCreationDialog')
type_clipboard_into_rename_if_suitable = _safe_import_module('folderTools', 'type_clipboard_into_rename_if_suitable')
get_auto_paste_text = _safe_import_module('folderTools', 'get_auto_paste_text')
arm_auto_paste_speech_gate = _safe_import_module('folderTools', 'arm_auto_paste_speech_gate')
disarm_auto_paste_speech_gate = _safe_import_module('folderTools', 'disarm_auto_paste_speech_gate')
BatchRenameManager = _safe_import_module('batchRenameManager', 'BatchRenameManager')
FlatViewManager = _safe_import_module('flatViewManager', 'FlatViewManager')
SyncCompareManager = _safe_import_module('syncCompareManager', 'SyncCompareManager')
OperationHistoryManager = _safe_import_module('operationHistoryManager', 'OperationHistoryManager')
RecentLocationsManager = _safe_import_module('recentLocationsManager', 'RecentLocationsManager')
WorkspaceManager = _safe_import_module('workspaceManager', 'WorkspaceManager')
DuplicateFinderManager = _safe_import_module('duplicateFinderManager', 'DuplicateFinderManager')
FileBasketManager = _safe_import_module('fileBasketManager', 'FileBasketManager')

log.debug("xPlorer: All modules processed")

_double_tap_threshold = 0.5

_KNOWN_BREADCRUMB_CLASS_NAMES = ("Breadcrumb Parent",)
_KNOWN_ADDRESS_AUTOMATION_IDS = ("1001",)


class GestureDoubleTapHandler:
	def __init__(self, thresholdSeconds):
		self._thresholdSeconds = thresholdSeconds
		self._lastTapTime = 0.0
		self._tapCount = 0
		self._timer = None

	def registerTap(self, onTimeout, triggerAtCount):
		currentTime = time.time()
		if currentTime - self._lastTapTime > self._thresholdSeconds:
			self._tapCount = 0
		self._tapCount += 1
		self._lastTapTime = currentTime
		self._cancelTimer()
		if self._tapCount >= triggerAtCount:
			onTimeout()
		else:
			self._timer = core.callLater(int(self._thresholdSeconds * 1000), onTimeout)

	def consumeTapCount(self):
		self._cancelTimer()
		count = self._tapCount
		self._tapCount = 0
		return count

	def _cancelTimer(self):
		if self._timer:
			self._timer.Stop()
			self._timer = None

	def cleanup(self):
		self._cancelTimer()

class ActiveTabPathResolver:
	def __init__(self):
		self._workingStrategyName = None

	def resolveActivePath(self, foregroundObj, thorough=False):
		deadline = time.monotonic() + 0.15
		strategies = (
			("class_name", self._resolveByClassName),
			("automation_id", self._resolveByAutomationId),
			("value_scan", self._resolveByValueScan),
		)
		orderedStrategies = sorted(
			strategies, key=lambda item: item[0] != self._workingStrategyName
		)
		for strategyName, strategyFn in orderedStrategies:
			try:
				if strategyName in ("class_name", "automation_id"):
					resolvedPath = strategyFn(foregroundObj, deadline)
				elif thorough and strategyName == "value_scan":
					resolvedPath = strategyFn(foregroundObj, maxNodes=40, maxDepth=5)
				else:
					resolvedPath = strategyFn(foregroundObj)
				if resolvedPath:
					self._workingStrategyName = strategyName
					return resolvedPath
			except (COMError, AttributeError, RuntimeError) as e:
				log.debug(f"xPlorer: breadcrumb strategy '{strategyName}' failed: {e}")
		return None

	def _resolveByValueScan(self, foregroundObj, maxNodes=30, maxDepth=4):
		if foregroundObj is None:
			return None
		visited = 0
		queue = deque([(foregroundObj, 0)])
		while queue:
			current, depth = queue.popleft()
			visited += 1
			if visited > maxNodes:
				break
			if current is None:
				continue
			try:
				currentRole = getattr(current, "role", None)
			except (COMError, AttributeError, RuntimeError):
				currentRole = None
			if currentRole in (Role.TREE, Role.TREEITEM):
				continue
			try:
				value = getattr(current, "value", None)
				if value and isinstance(value, str) and len(value) > 2 and os.path.isdir(value):
					return os.path.normpath(value)
			except (COMError, AttributeError, RuntimeError):
				pass
			if currentRole == Role.LISTITEM:
				continue
			if depth >= maxDepth:
				continue
			try:
				child = current.firstChild
				while child is not None:
					queue.append((child, depth + 1))
					child = child.next
			except (COMError, AttributeError, RuntimeError):
				pass
		return None

	def _resolveByClassName(self, foregroundObj, deadline=None):
		breadcrumbObj = self._findDescendant(
			foregroundObj,
			lambda o: getattr(o, "windowClassName", None) in _KNOWN_BREADCRUMB_CLASS_NAMES,
			deadline=deadline,
		)
		return self._pathFromBreadcrumbSegments(breadcrumbObj)

	def _resolveByAutomationId(self, foregroundObj, deadline=None):
		breadcrumbObj = self._findDescendant(
			foregroundObj,
			lambda o: getattr(o, "UIAAutomationId", None) in _KNOWN_ADDRESS_AUTOMATION_IDS,
			deadline=deadline,
		)
		return self._pathFromBreadcrumbSegments(breadcrumbObj)

	def _findDescendant(self, obj, matchFn, maxDepth=5, maxNodes=60, _visited=None, deadline=None):
		# Unlike _resolveByValueScan (which already caps total nodes
		# visited), this recursive walk previously only bounded depth, not
		# sibling count at each level - a wide Explorer UI tree could still
		# force an unbounded number of cross-process UIA property reads
		# (.firstChild/.next), which is exactly what showed up in the field
		# as real watchdog freeze-recovery events, not just slow responses.
		# Capping total visited nodes bounds the worst case regardless of
		# tree shape while leaving normal, shallow breadcrumb bars untouched.
		# A wall-clock deadline is checked on top of the node cap: on a
		# slow/loaded system (e.g. a XAML-hosted Windows 11 Explorer window
		# under heavy load) even a capped number of nodes can each take long
		# enough for the total walk to still show up as a freeze, so time
		# is bounded directly rather than trusting node count as a proxy
		# for wall-clock cost.
		if _visited is None:
			_visited = [0]
		if obj is None or maxDepth <= 0 or _visited[0] >= maxNodes:
			return None
		if deadline is not None and time.monotonic() > deadline:
			return None
		try:
			_visited[0] += 1
			if matchFn(obj):
				return obj
			child = obj.firstChild
			while child is not None:
				found = self._findDescendant(child, matchFn, maxDepth - 1, maxNodes, _visited, deadline)
				if found:
					return found
				if _visited[0] >= maxNodes:
					return None
				if deadline is not None and time.monotonic() > deadline:
					return None
				child = child.next
		except (COMError, AttributeError, RuntimeError):
			pass
		return None

	def _pathFromBreadcrumbSegments(self, breadcrumbObj):
		if breadcrumbObj is None:
			return None
		try:
			segmentNames = []
			child = breadcrumbObj.firstChild
			while child is not None:
				segmentName = getattr(child, "name", None)
				if segmentName:
					segmentNames.append(segmentName)
				child = child.next
			if not segmentNames:
				return None
			candidatePath = segmentNames[0]
			if not candidatePath.endswith("\\"):
				candidatePath += "\\"
			if len(segmentNames) > 1:
				candidatePath = os.path.join(candidatePath, *segmentNames[1:])
			candidatePath = os.path.normpath(candidatePath)
			return candidatePath if os.path.isdir(candidatePath) else None
		except (COMError, AttributeError, RuntimeError):
			return None

_WM_NULL = 0x0000
_SMTO_ABORTIFHUNG = 0x0002
_SMTO_BLOCK = 0x0001

def _isExplorerWindowResponsive(hwnd, timeoutMs=100):
	try:
		result = ctypes.wintypes.DWORD()
		sent = ctypes.windll.user32.SendMessageTimeoutW(
			hwnd, _WM_NULL, 0, 0,
			_SMTO_ABORTIFHUNG | _SMTO_BLOCK, timeoutMs, ctypes.byref(result)
		)
		return bool(sent)
	except (AttributeError, OSError, ValueError) as e:
		log.debug(f"xPlorer: responsiveness probe failed, assuming responsive: {e}")
		return True

_GA_ROOT = 2

def _getTopLevelExplorerHwnd(hwnd):
	# Windows 11's newer XAML-hosted Explorer window exposes an inner
	# XamlExplorerHostIslandWindow that NVDA sometimes reports as the
	# foreground/focused window, but Shell.Application.Windows() only ever
	# knows about the outer CabinetWClass top-level window. Matching
	# selection/path lookups against the raw hwnd NVDA handed back silently
	# fails whenever those two disagree, which is common on Windows 11 -
	# walking up to the true top-level window first keeps the match working
	# regardless of which one NVDA happened to report.
	try:
		rootHwnd = ctypes.windll.user32.GetAncestor(hwnd, _GA_ROOT)
		if rootHwnd:
			return rootHwnd
	except (AttributeError, OSError) as e:
		log.debug(f"xPlorer: GetAncestor failed, using original hwnd: {e}")
	return hwnd

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = _("xPlorer")

	def __init__(self):
		log.debug("xPlorer GlobalPlugin.__init__ starting")
		try:
			super().__init__()

			self.objShellApp = comtypes.client.CreateObject("Shell.Application")
			self.objFSO = comtypes.client.CreateObject("scripting.FileSystemObject")

			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(xPlorerSettingsPanel)

			self.manager = ExplorerManager(self)

			self.fileOps = FileOperations(self) if FileOperations else None
			self.compression = CompressionManager(self) if CompressionManager else None
			self.clipboard = ClipboardManager(self) if ClipboardManager else None
			self.selection = SelectionManager(self) if SelectionManager else None
			self.robocopy = RobocopyManager(self) if RobocopyManager else None
			self.txt2folder = TxtToFolder(self) if TxtToFolder else None
			self.createFileManager = CreateFileManager(self) if CreateFileManager else None
			self.contextMenuManager = ContextMenuManager(self) if ContextMenuManager else None
			self.propertiesMenuManager = PropertiesMenuManager(self) if PropertiesMenuManager else None
			self.folderInfo = FolderInfoManager(self) if FolderInfoManager else None
			self.caseConverter = CaseConverter() if CaseConverter else None
			self.batchRename = BatchRenameManager(self) if BatchRenameManager else None
			self.flatView = FlatViewManager(self) if FlatViewManager else None
			self.syncCompare = SyncCompareManager(self) if SyncCompareManager else None
			self.operationHistory = OperationHistoryManager(self) if OperationHistoryManager else None
			self.recentLocations = RecentLocationsManager(self) if RecentLocationsManager else None
			self.workspaceManager = WorkspaceManager(self) if WorkspaceManager else None
			self.duplicateFinder = DuplicateFinderManager(self) if DuplicateFinderManager else None
			self.fileBasket = FileBasketManager(self) if FileBasketManager else None

			self._last_window = None
			self._last_window_hwnd = None
			self._last_window_time = 0
			self._last_path = None

			self._cached_explorer_hwnd = None
			self._cached_explorer_time = 0
			self._cached_explorer_path = None
			self._cache_valid_duration = 0.4
			self._shell_enum_timeout = 0.4
			self._tabPathResolver = ActiveTabPathResolver()
			self._pathResolveLock = threading.Lock()
			self._selectedItemsLock = threading.Lock()
			self._copyTapState = GestureDoubleTapHandler(_double_tap_threshold)
			self._invertTapState = GestureDoubleTapHandler(_double_tap_threshold)
			self._compressTapState = GestureDoubleTapHandler(_double_tap_threshold)
			self._robocopyTapState = GestureDoubleTapHandler(_double_tap_threshold)
			self._contextMenuTapState = GestureDoubleTapHandler(0.3)
			self._renameTapState = GestureDoubleTapHandler(_double_tap_threshold)
			self._fileBasketTapState = GestureDoubleTapHandler(_double_tap_threshold)
			self._workspaceTapState = GestureDoubleTapHandler(_double_tap_threshold)
			self._searchTapState = GestureDoubleTapHandler(_double_tap_threshold)

			# Multi-select: while active, Ctrl is genuinely held down at the
			# OS level so the user's own unmodified arrow/space/enter/
			# Ctrl+C/Ctrl+X presses arrive at Explorer already combined
			# with Ctrl. See _enterMultiSelectLayer for why this replaced
			# the earlier getScript-based interception approach.
			self._multiSelectActive = False
			self._multiSelectWatchdog = None

			self._striprtf_available = None
			libs_dir = os.path.join(os.path.dirname(__file__), "libs")
			if os.path.exists(libs_dir) and libs_dir not in sys.path:
				sys.path.insert(0, libs_dir)

			self._cached_selected_folder_paths = []
			self._case_cache_valid = False
			self._suppress_counter = 0

			set_global_plugin(self)
			log.debug("xPlorer GlobalPlugin initialized successfully")
			update.start()
		except Exception as e:
			log.exception("Error in xPlorer GlobalPlugin.__init__")
			raise

	def terminate(self):
		update.stop()
		log.debug("xPlorer GlobalPlugin.terminate starting")
		try:
			super().terminate()
			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(xPlorerSettingsPanel)

			for mgr in (self.fileOps, self.compression, self.selection,
						self.robocopy, self.createFileManager, self.folderInfo,
						self.batchRename, self.flatView, self.syncCompare,
						self.operationHistory, self.recentLocations, self.workspaceManager,
						self.duplicateFinder, self.fileBasket):
				if mgr and hasattr(mgr, 'cleanup'):
					mgr.cleanup()

			if self.manager:
				self.manager.terminate()

			if disarm_auto_paste_speech_gate:
				disarm_auto_paste_speech_gate()
			self._cancelAllTimers()
			if self._multiSelectActive:
				self._exitMultiSelectLayer(silent=True, reason="addon_terminating")
			self._cached_selected_folder_paths = []
			self._case_cache_valid = False
			self.objShellApp = None
			self.objFSO = None
			log.debug("xPlorer GlobalPlugin terminated successfully")
		except Exception as e:
			log.exception("Error in xPlorer GlobalPlugin.terminate")

	def _cancelAllTimers(self):
		for tapState in (self._copyTapState, self._invertTapState, self._compressTapState,
						self._robocopyTapState, self._contextMenuTapState, self._workspaceTapState,
						self._searchTapState):
			tapState.cleanup()

	def _invalidatePathCache(self):
		self._cached_explorer_hwnd = None
		self._cached_explorer_path = None
		self._cached_explorer_time = 0

	def _getCachedExplorerPath(self, target_hwnd, breadcrumbPath=None):
		if not self._cached_explorer_path:
			return None
		if target_hwnd is not None and self._cached_explorer_hwnd != target_hwnd:
			return None
		if breadcrumbPath and self._cached_explorer_path != breadcrumbPath:
			return None
		if not os.path.isdir(self._cached_explorer_path):
			log.debug("xPlorer: cached explorer path no longer valid, clearing cache")
			self._invalidatePathCache()
			return None
		return self._cached_explorer_path

	def _getStriprtfModule(self):
		if self._striprtf_available is None:
			try:
				from striprtf.striprtf import rtf_to_text
				self._striprtf_available = rtf_to_text
			except ImportError:
				self._striprtf_available = False
			except Exception as e:
				self._striprtf_available = False
		return self._striprtf_available

	def _getCurrentPathDeferred(self, callback, delay=200, retryCount=0):
		def do_get():
			def handlePath(path):
				if path is None and self.manager._foregroundTransition and retryCount < 5:
					core.callLater(100, lambda: self._getCurrentPathDeferred(callback, delay=0, retryCount=retryCount+1))
				else:
					callback(path)
			self._getCurrentPathFromExplorerAsync(handlePath)
		core.callLater(delay, do_get)

	def _getSelectedItemsDeferred(self, callback, delay=200):
		core.callLater(delay, lambda: self._getSelectedItemsAsync(callback))

	def _recordRecentLocationDeferred(self):
		if not self.recentLocations:
			return

		def do_record():
			def handlePath(path):
				if path:
					self.recentLocations.recordPath(path)
			# skipBreadcrumb=True: this is opportunistic background
			# bookkeeping on every foreground transition, not a
			# user-waiting-on-a-menu action - it doesn't need the
			# breadcrumb walk's extra precision, and running it here
			# unconditionally on every single window switch is exactly what
			# showed up in the field as a watchdog freeze/recovery cycle.
			self._getCurrentPathFromExplorerAsync(handlePath, skipBreadcrumb=True)
		core.callLater(250, do_record)

	def _getCurrentPathFromExplorerAsync(self, callback, skipBreadcrumb=False):
		"""Resolves the current Explorer path without blocking the caller.
		The breadcrumb walk is a live, synchronous UIA tree traversal on
		whatever thread calls this - cheap on a normal Explorer window, but
		still a real (bounded) block on a slow/loaded system. Callers doing
		opportunistic background bookkeeping that doesn't need the freshest
		possible path (e.g. recording a recent location on every foreground
		change) should pass skipBreadcrumb=True to go straight to the
		properly backgrounded COM fallback instead. Cache lookups are cheap
		and resolve synchronously either way; the COM shell-window fallback
		runs on a background thread and delivers its result to callback via
		wx.CallAfter."""
		if self.manager._foregroundTransition:
			callback(None)
			return

		current_time = time.time()
		target_hwnd = None
		try:
			fg = api.getForegroundObject()
			if not fg or not fg.appModule or fg.appModule.appName != "explorer":
				if (self._cached_explorer_path and current_time - self._cached_explorer_time < 0.2
						and os.path.isdir(self._cached_explorer_path)):
					callback(self._cached_explorer_path)
				else:
					callback(None)
				return

			target_hwnd = fg.windowHandle
			if not winUser.isWindow(target_hwnd):
				callback(self._getCachedExplorerPath(target_hwnd))
				return

			if not _isExplorerWindowResponsive(target_hwnd):
				callback(self._getCachedExplorerPath(target_hwnd))
				return

			if not skipBreadcrumb:
				breadcrumbPath = self._tabPathResolver.resolveActivePath(fg)
				if breadcrumbPath:
					self._cached_explorer_hwnd = target_hwnd
					self._cached_explorer_time = current_time
					self._cached_explorer_path = breadcrumbPath
					callback(breadcrumbPath)
					return

			focusedItemNameHint = None
			try:
				focusObj = api.getFocusObject()
				if focusObj:
					focusedItemNameHint = getattr(focusObj, "name", None)
			except Exception as e:
				log.debug(f"xPlorer: could not resolve focused item name hint for path disambiguation: {e}")

			self._resolvePathViaShellWindowsAsync(target_hwnd, current_time, callback, focusedItemNameHint)

		except COMError as e:
			log.debug(f"xPlorer: _getCurrentPathFromExplorerAsync COM error: {e}")
			callback(self._getCachedExplorerPath(target_hwnd))
		except Exception as e:
			log.debug(f"xPlorer: _getCurrentPathFromExplorerAsync unexpected error: {e}")
			callback(self._getCachedExplorerPath(target_hwnd))

	def _resolvePathViaShellWindowsAsync(self, target_hwnd, current_time, callback, focusedItemNameHint=None):
		if not self._pathResolveLock.acquire(blocking=False):
			log.debug("xPlorer: path resolution already in progress, using cached path instead of stacking a new COM call")
			callback(self._getCachedExplorerPath(target_hwnd))
			return

		comMatchHwnd = _getTopLevelExplorerHwnd(target_hwnd)

		def enumerate_worker():
			candidatePath = None
			try:
				comtypes.CoInitialize()
			except OSError:
				pass
			try:
				localShell = comtypes.client.CreateObject("Shell.Application")
				candidates = []
				for window in localShell.Windows():
					try:
						if window and window.hwnd == comMatchHwnd:
							candidates.append(window)
					except (COMError, AttributeError):
						continue

				# Shell.Application.Windows() returns one entry per TAB, not
				# one per top-level window - a multi-tab Explorer window has
				# several entries that all share the same hwnd. Matching on
				# hwnd alone and taking the first hit (as this used to)
				# grabs whichever entry happens to come first in COM's
				# enumeration order, not the actually active tab. This is
				# the same class of bug already root-caused for
				# _getSelectedItemsAsync (see the comment there), just
				# reached from the path-resolution fallback instead - it
				# surfaced as a cross-addon symptom where another add-on
				# reading the current folder path via this method got a
				# stale path from the previously-active tab after switching
				# with control+tab, even though copy/paste of the actual
				# selection worked correctly.
				chosenWindow = None
				if len(candidates) == 1:
					chosenWindow = candidates[0]
				elif len(candidates) > 1:
					if focusedItemNameHint:
						for candidate in candidates:
							try:
								document = getattr(candidate, "document", None)
								if not document or not hasattr(document, "SelectedItems"):
									continue
								items = document.SelectedItems()
								matched = False
								for i in range(items.Count):
									if items.Item(i).Name == focusedItemNameHint:
										matched = True
										break
								if matched:
									chosenWindow = candidate
									break
							except (COMError, AttributeError):
								continue
					if chosenWindow is None:
						log.debug("xPlorer: multiple tabs share this window and none matched the focused item name hint, using the first candidate")
						chosenWindow = candidates[0]

				if chosenWindow is not None:
					candidatePath = self._extractPathFromShellWindow(chosenWindow)
			except COMError as e:
				log.debug(f"xPlorer: background shell enumeration COM error: {e}")
			except Exception as e:
				log.debug(f"xPlorer: background shell enumeration failed: {e}")
			finally:
				try:
					comtypes.CoUninitialize()
				except OSError:
					pass
				self._pathResolveLock.release()

				def deliver():
					resolvedPath = candidatePath
					if resolvedPath and os.path.isdir(resolvedPath):
						self._cached_explorer_hwnd = target_hwnd
						self._cached_explorer_time = current_time
						self._cached_explorer_path = resolvedPath
					else:
						resolvedPath = self._getCachedExplorerPath(target_hwnd)
					callback(resolvedPath)

				wx.CallAfter(deliver)

		threading.Thread(target=enumerate_worker, daemon=True).start()

	def _extractPathFromShellWindow(self, window):
		try:
			if hasattr(window, "Document") and window.Document:
				folder = window.Document.Folder
				if folder and hasattr(folder, "Self"):
					path = folder.Self.Path
					if path and os.path.isdir(path):
						return os.path.normpath(path)
			if hasattr(window, "LocationURL") and window.LocationURL:
				url = window.LocationURL
				if url.startswith("file:///"):
					try:
						path = urllib.parse.unquote(url[8:])
					except Exception:
						path = url[8:]
					path = path.replace("/", "\\")
					if os.path.isdir(path):
						return os.path.normpath(path)
		except (COMError, AttributeError):
			pass
		return None

	def _getActiveExplorerWindow(self):
		if self.manager._foregroundTransition:
			return None
		try:
			current_time = time.time()
			fg = api.getForegroundObject()
			if not fg or not fg.appModule or fg.appModule.appName != "explorer":
				return None

			target_hwnd = fg.windowHandle
			if not winUser.isWindow(target_hwnd):
				return None

			if not _isExplorerWindowResponsive(target_hwnd):
				return None

			shell = self.objShellApp
			if not shell:
				return None

			matchingWindows = []
			enumerationDeadline = time.monotonic() + self._shell_enum_timeout
			try:
				for window in shell.Windows():
					if time.monotonic() > enumerationDeadline:
						log.debug("xPlorer: window enumeration exceeded deadline, stopping early")
						break
					try:
						if window and window.hwnd == target_hwnd and hasattr(window, "Document") and window.Document:
							matchingWindows.append(window)
							break
					except (COMError, AttributeError):
						continue
			except COMError as e:
				log.debug(f"xPlorer: _getActiveExplorerWindow enumeration COM error: {e}")

			if not matchingWindows:
				return None

			chosenWindow = matchingWindows[0]
			self._last_window = chosenWindow
			self._last_window_hwnd = target_hwnd
			self._last_window_time = current_time
			return chosenWindow
		except Exception as e:
			log.debug(f"xPlorer: _getActiveExplorerWindow unexpected error: {e}")
			return None

	def _getCurrentPathAsync(self, callback):
		self._getCurrentPathFromExplorerAsync(callback)

	def _getSelectedItemsAsync(self, callback):
		"""Non-blocking replacement for the old synchronous _getSelectedItems.
		Resolves selected items on a background worker thread and delivers
		(items, hwnd) to callback via wx.CallAfter. Callback receives
		(None, None) immediately whenever the fast checks fail or a fetch is
		already in flight, so the caller never waits on the main thread."""
		if self.manager._foregroundTransition:
			callback(None, None)
			return

		try:
			fg = api.getForegroundObject()
		except Exception as e:
			log.debug(f"xPlorer: _getSelectedItemsAsync could not read foreground object: {e}")
			callback(None, None)
			return
		if not fg or not fg.appModule or fg.appModule.appName != "explorer":
			callback(None, None)
			return

		target_hwnd = fg.windowHandle
		if not winUser.isWindow(target_hwnd) or not _isExplorerWindowResponsive(target_hwnd):
			callback(None, None)
			return

		if not self._selectedItemsLock.acquire(blocking=False):
			log.debug("xPlorer: selected-items fetch already in progress, skipping duplicate COM call")
			callback(None, None)
			return

		comMatchHwnd = _getTopLevelExplorerHwnd(target_hwnd)
		# Shell.Application.Windows() returns one entry per TAB, not one per
		# top-level window - a multi-tab Explorer window has several
		# entries that all share the same hwnd. Matching on hwnd alone
		# (as this used to) just grabs whichever entry happens to come
		# first in COM's enumeration order, regardless of which tab is
		# actually active - confirmed in the field by say-size
		# consistently reporting a stale value from a different tab after
		# switching with control+tab.
		#
		# The first fix for this tried disambiguating by comparing each
		# candidate's folder path against a breadcrumb-resolved "active
		# path" hint - but breadcrumb resolution fails outright on this
		# Explorer variant (all three strategies fail, confirmed by
		# 'value_scan' TREE errors in the field), so that hint was always
		# None and disambiguation always fell through to "first candidate"
		# regardless of which tab was actually active.
		#
		# api.getFocusObject() is not subject to that same breadcrumb
		# fragility - NVDA's own tab-label and item-position announcements
		# throughout the field logs are consistently correct, proving focus
		# tracking itself is reliable here. The focused item's own name is
		# therefore a much sturdier disambiguator: whichever candidate's
		# SelectedItems() actually contains an item with that name is the
		# active tab, regardless of enumeration order.
		focusedItemNameHint = None
		try:
			focusObj = api.getFocusObject()
			if focusObj:
				focusedItemNameHint = getattr(focusObj, "name", None)
		except Exception as e:
			log.debug(f"xPlorer: could not resolve focused item name hint for selection disambiguation: {e}")

		def fetch_worker():
			selectedItems = None
			try:
				comtypes.CoInitialize()
			except OSError:
				pass
			try:
				localShell = comtypes.client.CreateObject("Shell.Application")
				candidates = []
				for window in localShell.Windows():
					try:
						if window and window.hwnd == comMatchHwnd and hasattr(window, "Document") and window.Document:
							candidates.append(window)
					except (COMError, AttributeError):
						continue

				chosenWindow = None
				chosenItems = None
				if len(candidates) == 1:
					chosenWindow = candidates[0]
				elif len(candidates) > 1:
					if focusedItemNameHint:
						for candidate in candidates:
							try:
								document = getattr(candidate, "document", None)
								if not document or not hasattr(document, "SelectedItems"):
									continue
								items = document.SelectedItems()
								collected = []
								matched = False
								for i in range(items.Count):
									item = items.Item(i)
									collected.append((item.Name, item.Path))
									if item.Name == focusedItemNameHint:
										matched = True
								if matched:
									chosenWindow = candidate
									chosenItems = collected if collected else None
									break
							except (COMError, AttributeError):
								continue
					if chosenWindow is None:
						log.debug("xPlorer: multiple tabs share this window and none matched the focused item name hint, using the first candidate")
						chosenWindow = candidates[0]

				if chosenItems is not None:
					selectedItems = chosenItems
				elif chosenWindow is not None:
					document = getattr(chosenWindow, "document", None)
					if document and hasattr(document, "SelectedItems"):
						items = document.SelectedItems()
						collected = []
						for i in range(items.Count):
							item = items.Item(i)
							collected.append((item.Name, item.Path))
						selectedItems = collected if collected else None
			except COMError as e:
				log.debug(f"xPlorer: background selected-items fetch COM error: {e}")
			except Exception as e:
				log.debug(f"xPlorer: background selected-items fetch failed: {e}")
			finally:
				try:
					comtypes.CoUninitialize()
				except OSError:
					pass
				self._selectedItemsLock.release()
				wx.CallAfter(callback, selectedItems, target_hwnd)

		threading.Thread(target=fetch_worker, daemon=True).start()

	def _executeWithSilence(self, func):
		import speech
		speech.cancelSpeech()
		self._suppress_counter += 1
		self.manager.suppressAllAnnouncements = True
		try:
			func()
		finally:
			self._suppress_counter -= 1
			if self._suppress_counter == 0:
				core.callLater(1000, lambda: setattr(self.manager, 'suppressAllAnnouncements', False))

	def _copyAddressBar(self):
		def do_copy(path):
			if path:
				if wx.TheClipboard.Open():
					try:
						wx.TheClipboard.SetData(wx.TextDataObject(path))
						ui.message(_("Copied: {path}").format(path=path))
					finally:
						wx.TheClipboard.Close()
				else:
					ui.message(_("Could not open clipboard"))
			else:
				ui.message(_("Unable to get current path"))
		self._getCurrentPathDeferred(do_copy, 200)

	def _handleNonExplorerGesture(self, gesture):
		try:
			display_name = gesture.displayName
			if ":" in display_name:
				key_name = display_name.split(":", 1)[1]
				KeyboardInputGesture.fromName(key_name).send()
		except Exception as e:
			log.debug(f"xPlorer: _handleNonExplorerGesture could not replay gesture: {e}")

	def script_copySelectedNamesOrAddressBar(self, gesture):
		if not self.clipboard:
			ui.message(_("Clipboard manager not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		self._copyTapState.registerTap(self._processCopyTap, triggerAtCount=3)

	script_copySelectedNamesOrAddressBar.__doc__ = _("Clipboard Operations: Copy selected names (single tap), copy content (double tap), or copy address bar (triple tap)")
	script_copySelectedNamesOrAddressBar.category = _("xPlorer")
	script_copySelectedNamesOrAddressBar.gestures = ["kb(desktop):NVDA+shift+c"]

	def _processCopyTap(self):
		tapCount = self._copyTapState.consumeTapCount()
		if tapCount == 1:
			self._executeWithSilence(self.clipboard.copySelectedNames)
		elif tapCount == 2:
			self._executeWithSilence(self.clipboard.copyFileContent)
		elif tapCount >= 3:
			self._executeWithSilence(self._copyAddressBar)

	def script_invertSelection_double_tap(self, gesture):
		if not self.selection:
			ui.message(_("Selection manager not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		self._invertTapState.registerTap(self._processInvertTap, triggerAtCount=3)

	script_invertSelection_double_tap.__doc__ = _("Selection: Select by extension (single tap), invert selection (double tap), or multi-select (triple tap)")
	script_invertSelection_double_tap.category = _("xPlorer")
	script_invertSelection_double_tap.gestures = ["kb(desktop):NVDA+shift+v"]

	def _processInvertTap(self):
		tapCount = self._invertTapState.consumeTapCount()
		if tapCount == 1:
			self._executeWithSilence(self.selection.selectByExtension)
		elif tapCount == 2:
			self._executeWithSilence(self.selection.invertSelection)
		elif tapCount >= 3:
			self._executeWithSilence(self._enterMultiSelectLayer)

	def script_openSelectBySearch(self, gesture):
		self._searchTapState.registerTap(self._processSearchTap, triggerAtCount=3)

	script_openSelectBySearch.__doc__ = _("Select by Search: Opens Select by Search (single tap), Flat View (double tap), or Batch Rename Tool (triple tap)")
	script_openSelectBySearch.category = _("xPlorer")
	script_openSelectBySearch.gestures = ["kb(desktop):NVDA+shift+a"]

	def _processSearchTap(self):
		tapCount = self._searchTapState.consumeTapCount()
		if tapCount == 1:
			if not self.selection:
				ui.message(_("Selection manager not available"))
				return
			self.selection.showSearchSelectionDialog()
		elif tapCount == 2:
			if self.flatView:
				self.flatView.show_dialog()
			else:
				ui.message(_("Flat view tool not available"))
		elif tapCount >= 3:
			if self.batchRename:
				self.batchRename.show_dialog()
			else:
				ui.message(_("Batch rename manager not available"))

	def script_compressZip_double_tap(self, gesture):
		if not self.fileOps or not self.compression:
			ui.message(_("Compression manager not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		self._compressTapState.registerTap(self._processCompressTap, triggerAtCount=4)

	script_compressZip_double_tap.__doc__ = _("Say size (single tap), compress zip (double tap), unzip (triple tap), or folder to ISO (quadruple tap)")
	script_compressZip_double_tap.category = _("xPlorer")
	script_compressZip_double_tap.gestures = ["kb(desktop):NVDA+shift+z"]

	def _processCompressTap(self):
		tapCount = self._compressTapState.consumeTapCount()
		if tapCount == 1:
			self._executeWithSilence(self.fileOps.saySize)
		elif tapCount == 2:
			core.callLater(50, self._executeWithSilence, self.compression.compressZip)
		elif tapCount == 3:
			core.callLater(50, self._executeWithSilence, self.compression.unzipSelected)
		elif tapCount >= 4:
			core.callLater(50, self._executeWithSilence, self.fileOps.convertFolderToIso)

	def script_robocopyMultitap(self, gesture):
		if not self.robocopy:
			ui.message(_("Robocopy manager not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		self._robocopyTapState.registerTap(self._processRobocopyTap, triggerAtCount=3)

	script_robocopyMultitap.__doc__ = _("Robocopy: single tap copy, double tap paste, triple tap move")
	script_robocopyMultitap.category = _("xPlorer")
	script_robocopyMultitap.gestures = ["kb(desktop):NVDA+shift+r"]

	def _processRobocopyTap(self):
		tapCount = self._robocopyTapState.consumeTapCount()
		if tapCount == 1:
			self._executeWithSilence(self.robocopy.copy)
		elif tapCount == 2:
			self._executeWithSilence(self.robocopy.paste)
		elif tapCount == 3:
			self._executeWithSilence(self.robocopy.move)

	def _cache_selected_folders_for_case(self):
		self._cached_selected_folder_paths = []
		self._case_cache_valid = False

		def handleSelection(selected_items, _hwnd):
			try:
				if selected_items:
					folder_paths = [path for name, path in selected_items if os.path.isdir(path)]
					if folder_paths:
						self._cached_selected_folder_paths = folder_paths
						self._case_cache_valid = True
			except Exception as e:
				log.debug(f"xPlorer: _cache_selected_folders_for_case failed: {e}")

		self._getSelectedItemsAsync(handleSelection)

	def script_openXPlorerContextMenu(self, gesture):
		if not self.contextMenuManager:
			ui.message(_("Context menu manager not available"))
			return
		focus = api.getFocusObject()
		inExplorer = bool(focus and focus.appModule and focus.appModule.appName == "explorer")
		if inExplorer:
			self._cache_selected_folders_for_case()
		self._contextMenuTapState.registerTap(
			lambda: self._processContextMenuTap(inExplorer, gesture), triggerAtCount=3
		)

	script_openXPlorerContextMenu.__doc__ = _("Open xPlorer context menu (single tap), Recent Locations (double tap), or Current folder size list (triple tap)")
	script_openXPlorerContextMenu.category = _("xPlorer")
	script_openXPlorerContextMenu.gestures = ["kb(desktop):NVDA+shift+x"]

	def _processContextMenuTap(self, inExplorer, gesture):
		tapCount = self._contextMenuTapState.consumeTapCount()
		if tapCount == 1:
			# The main menu itself is useful outside Explorer too (Workspace
			# Manager, xPlorer Settings, Recent Locations, Operation History
			# don't need an Explorer selection at all) - only the
			# Explorer-dependent entries get hidden inside menu
			# construction. Recent Locations (double tap) stays
			# Explorer-only since it fundamentally needs a current
			# Explorer folder to act on.
			self._showContextMenu()
		elif tapCount == 2:
			if not inExplorer:
				self._handleNonExplorerGesture(gesture)
				return
			self._showRecentLocationsMenu()
		elif tapCount >= 3:
			if not inExplorer:
				self._handleNonExplorerGesture(gesture)
				return
			if not self.fileOps:
				ui.message(_("File operations manager not available"))
				return
			self._executeWithSilence(self.fileOps.showFolderSizeList)

	def _renameFile(self):
		if not self.fileOps:
			ui.message(_("File operations manager not available"))
			return
		self._executeWithSilence(self.fileOps.renameFile)

	def script_renameFile(self, gesture):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		self._renameTapState.registerTap(self._processRenameTap, triggerAtCount=3)

	script_renameFile.__doc__ = _("Rename selected file (single tap), rename using clipboard text (double tap), or undo the last batch rename operation (triple tap)")
	script_renameFile.category = _("xPlorer")
	script_renameFile.gestures = ["kb(desktop):NVDA+shift+f2"]

	def _processRenameTap(self):
		tapCount = self._renameTapState.consumeTapCount()
		if tapCount == 1:
			self._renameFile()
		elif tapCount == 2:
			if not self.fileOps:
				ui.message(_("File operations manager not available"))
				return
			self._executeWithSilence(self.fileOps.autoPasteRenameFromClipboard)
		elif tapCount >= 3:
			if not self.batchRename:
				ui.message(_("Batch rename manager not available"))
				return
			self._executeWithSilence(self.batchRename.undoLastRename)

	def script_fileBasket(self, gesture):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		self._fileBasketTapState.registerTap(self._processFileBasketTap, triggerAtCount=3)

	script_fileBasket.__doc__ = _("File Basket: Add selected item(s) to the file basket (single tap), open the file basket (double tap), or clear the file basket (triple tap)")
	script_fileBasket.category = _("xPlorer")
	script_fileBasket.gestures = ["kb(desktop):NVDA+shift+n"]

	def _processFileBasketTap(self):
		tapCount = self._fileBasketTapState.consumeTapCount()
		if not self.fileBasket:
			ui.message(_("File basket manager not available"))
			return
		if tapCount == 1:
			self.fileBasket.addSelectedToBasket()
		elif tapCount == 2:
			self.fileBasket.showBasketDialog()
		elif tapCount >= 3:
			self.fileBasket.clearBasketWithAnnouncement()

	def script_openWorkspaceMenu(self, gesture):
		if not self.contextMenuManager or not self.workspaceManager:
			ui.message(_("Workspace manager not available"))
			return
		# Unlike most other xPlorer gestures, the workspace menu, the save
		# dialog, and the workspace editor are all standalone wx GUI, so
		# none of the three tap actions actually require Explorer focus -
		# this gesture is intentionally not gated behind an Explorer check.
		self._workspaceTapState.registerTap(self._processWorkspaceTap, triggerAtCount=3)

	script_openWorkspaceMenu.__doc__ = _("Workspace: Open menu (single tap), add selected folder or save current as workspace (double tap), or edit saved workspaces (triple tap)")
	script_openWorkspaceMenu.category = _("xPlorer")
	script_openWorkspaceMenu.gestures = ["kb(desktop):NVDA+shift+m"]

	def _processWorkspaceTap(self):
		tapCount = self._workspaceTapState.consumeTapCount()
		if tapCount == 1:
			self._executeWithSilence(self.contextMenuManager.showWorkspaceMenu)
		elif tapCount == 2:
			self._handleWorkspaceAddFolderTap()
		elif tapCount >= 3:
			self._executeWithSilence(self.workspaceManager.showWorkspaceList)

	def _handleWorkspaceAddFolderTap(self):
		focus = api.getFocusObject()
		if focus and getattr(focus, "appModule", None) and focus.appModule.appName == "explorer":
			def afterSelection(selected_items, _hwnd):
				folderPaths = [path for name, path in selected_items if os.path.isdir(path)] if selected_items else []
				if folderPaths:
					for folderPath in folderPaths:
						self.workspaceManager.addFolderToWorkspaceSession(folderPath)
				else:
					self._executeWithSilence(self.workspaceManager.showSaveDialog)
			self._getSelectedItemsAsync(afterSelection)
		else:
			self._executeWithSilence(self.workspaceManager.showSaveDialog)

	# Virtual-key code and flag used to hold/release Ctrl at the OS level -
	# see _enterMultiSelectLayer for why.
	_VK_CONTROL = 0x11
	_KEYEVENTF_KEYUP = 0x0002
	_MULTISELECT_WATCHDOG_MS = 5 * 60 * 1000  # 5 minutes

	def _enterMultiSelectLayer(self):
		# Multi-select was previously built as an NVDA "layer command" via
		# getScript(), intercepting Space/arrows/Ctrl+C/Ctrl+X. That proved
		# unreliable in practice - a global plugin's getScript is only
		# consulted after every other registered handler has had a chance
		# to claim the same gesture first, and other installed add-ons can
		# and did claim some of these gestures at a higher priority,
		# silently preventing our handling from ever running.
		#
		# This replaces that entirely: instead of intercepting anything,
		# Ctrl is genuinely held down at the OS level (a real key-down
		# event with no matching key-up) for as long as the layer is
		# active. The user's own completely unmodified arrow/space/enter/
		# Ctrl+C/Ctrl+X presses then arrive at Explorer already combined
		# with Ctrl, exactly as if they were physically holding it - which
		# is genuinely how Explorer's native non-contiguous multi-select
		# already works, so nothing needs to be reimplemented or
		# rerouted, and there is no other add-on to race against.
		if self._multiSelectActive:
			self._exitMultiSelectLayer(reason="triple_tap_toggle_off")
			return
		focus = api.getFocusObject()
		if not focus or not focus.appModule or focus.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			return
		if self.selection:
			self.selection.clearSelection()
		try:
			ctypes.windll.user32.keybd_event(self._VK_CONTROL, 0, 0, 0)
		except OSError as e:
			log.error(f"xPlorer: keybd_event failed while entering multi-select: {e}")
			ui.message(_("Could not start multi-select"))
			return
		self._multiSelectActive = True
		self._multiSelectWatchdog = core.callLater(
			self._MULTISELECT_WATCHDOG_MS,
			lambda: self._exitMultiSelectLayer(reason="watchdog_timeout")
		)
		tones.beep(100, 100)

	def _exitMultiSelectLayer(self, silent=False, reason="unspecified"):
		if not self._multiSelectActive:
			return
		log.debug(f"xPlorer: exiting multi-select layer (reason={reason}, silent={silent})")
		self._multiSelectActive = False
		if self._multiSelectWatchdog:
			self._multiSelectWatchdog.Stop()
			self._multiSelectWatchdog = None
		try:
			ctypes.windll.user32.keybd_event(self._VK_CONTROL, 0, self._KEYEVENTF_KEYUP, 0)
		except OSError as e:
			log.error(f"xPlorer: keybd_event failed while releasing Ctrl after multi-select: {e}")
		if not silent:
			tones.beep(300, 100)

	# Gestures that keep the Multi-select layer running - anything else
	# cancels it by default, per the requested behavior.
	_MULTISELECT_ALLOWED_IDENTIFIERS = frozenset({
		"kb:space", "kb:enter", "kb:numpadenter", "kb:downarrow", "kb:uparrow",
		"kb:home", "kb:end",
	})

	def script_multiSelectExitDelete(self, gesture):
		self._exitMultiSelectLayer()
		KeyboardInputGesture.fromName("delete").send()

	def script_multiSelectExitShiftDelete(self, gesture):
		self._exitMultiSelectLayer()
		KeyboardInputGesture.fromName("shift+delete").send()

	def getScript(self, gesture):
		# This only ever WATCHES gestures while Multi-select is active - it
		# never returns a script of its own for anything besides Delete/
		# Shift+Delete below, so it can never block, replace, or race
		# another add-on for a gesture's real handling (that is exactly
		# what made the earlier getScript-based interception design
		# unreliable). It exists solely to update our own
		# _multiSelectActive bookkeeping: any key other than space, enter,
		# or the arrows cancels the layer, since the user is clearly done
		# with non-contiguous selection at that point.
		if self._multiSelectActive:
			try:
				identifiers = set(gesture.normalizedIdentifiers)
			except AttributeError:
				identifiers = set()
			# Delete/Shift+Delete need special handling, unlike Ctrl+C/
			# Ctrl+X: Ctrl is still physically held at the moment this
			# keydown is seen, so simply letting it fall through (as
			# Ctrl+C/Ctrl+X do) would deliver "Ctrl+Delete" to Explorer
			# instead of the plain Delete/Shift+Delete the user actually
			# pressed - Ctrl+C/Ctrl+X want that combo, Delete doesn't.
			# Releasing Ctrl first and resending a clean key fixes that.
			if "kb:delete" in identifiers:
				return self.script_multiSelectExitDelete
			if "kb:shift+delete" in identifiers:
				return self.script_multiSelectExitShiftDelete
			if not identifiers & self._MULTISELECT_ALLOWED_IDENTIFIERS:
				log.debug(f"xPlorer: multi-select watcher saw disallowed identifiers {identifiers!r}")
				self._exitMultiSelectLayer(reason=f"other_key:{sorted(identifiers)}")
		return super().getScript(gesture)

	def script_createFolderWithAutoPaste(self, gesture):
		if not type_clipboard_into_rename_if_suitable:
			ui.message(_("Folder creator helper not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		gesture.send()
		from .folderTools import loadConfig
		conf = loadConfig()
		if conf.get("autoPasteClipboardToRename", True):
			preparedText = get_auto_paste_text() if get_auto_paste_text else None
			if preparedText and arm_auto_paste_speech_gate:
				arm_auto_paste_speech_gate(preparedText, 1800)
			core.callLater(600, type_clipboard_into_rename_if_suitable, preparedText)

	script_createFolderWithAutoPaste.__doc__ = _("Create new folder and paste clipboard content into rename field")
	script_createFolderWithAutoPaste.category = _("xPlorer")
	script_createFolderWithAutoPaste.gestures = ["kb(desktop):control+shift+n"]

	def _openSettings(self):
		try:
			core.callLater(0, self._showSettingsDialog)
		except Exception as e:
			ui.message(_("Cannot open settings dialog"))

	def _showSettingsDialog(self):
		try:
			gui.mainFrame.popupSettingsDialog(gui.settingsDialogs.NVDASettingsDialog, xPlorerSettingsPanel)
		except Exception as e:
			ui.message(_("Error opening settings"))

	def _showContextMenu(self):
		if self.contextMenuManager:
			self.contextMenuManager.showContextMenu()
		else:
			ui.message(_("Context menu manager not available"))

	def _showPropertiesMenu(self):
		if self.propertiesMenuManager:
			self.propertiesMenuManager.show_properties_menu()
		else:
			ui.message(_("Properties menu not available"))

	def _showRecentLocationsMenu(self):
		if self.contextMenuManager:
			self.contextMenuManager.showRecentLocationsMenu()
		else:
			ui.message(_("Context menu manager not available"))

	def _createMultipleFolders(self):
		if not FolderCreationDialog:
			ui.message(_("Folder creation dialog not available"))
			return
		def do_create(path):
			if not path:
				ui.message(_("No Explorer folder detected"))
				return
			def show_dialog():
				try:
					dlg = FolderCreationDialog(gui.mainFrame, path)
					dlg.Raise()
					dlg.SetFocus()
					gui.mainFrame.prePopup()
					try:
						if dlg.ShowModal() == wx.ID_OK:
							dlg.process_input()
					finally:
						gui.mainFrame.postPopup()
					dlg.Destroy()
				except Exception as e:
					ui.message(_("Error creating folders"))
			core.callLater(0, show_dialog)
		self._getCurrentPathDeferred(do_create, 200)

	def _convertFolderNames(self, conversion_type):
		if not self.caseConverter:
			ui.message(_("Case converter not available"))
			return
		def do_convert(folder_paths):
			if not folder_paths:
				ui.message(_("No folders selected"))
				self._case_cache_valid = False
				return
			self._perform_conversion(conversion_type, folder_paths)
			self._case_cache_valid = False

		if self._case_cache_valid and self._cached_selected_folder_paths:
			do_convert(self._cached_selected_folder_paths)
			return

		def get_path_callback(path):
			if path and os.path.isdir(path):
				do_convert([path])
			else:
				ui.message(_("No folders selected or current folder not available"))
			self._case_cache_valid = False

		def afterSelection(selected_items, _hwnd):
			folder_paths = [path for name, path in selected_items if os.path.isdir(path)] if selected_items else []
			if folder_paths:
				do_convert(folder_paths)
				return
			self._getCurrentPathDeferred(get_path_callback, 200)

		self._getSelectedItemsAsync(afterSelection)

	def _perform_conversion(self, conversion_type, folders_to_convert):
		if not self.caseConverter:
			return
		try:
			if conversion_type == "uppercase":
				self.caseConverter.convert_folder_to_uppercase(folders_to_convert)
			elif conversion_type == "lowercase":
				self.caseConverter.convert_folder_to_lowercase(folders_to_convert)
			elif conversion_type == "titlecase":
				self.caseConverter.convert_folder_to_titlecase(folders_to_convert)
			elif conversion_type == "headlinecase":
				self.caseConverter.convert_folder_to_headlinecase(folders_to_convert)
		except Exception as e:
			log.debug(f"xPlorer: _perform_conversion ({conversion_type}) failed: {e}")
			ui.message(_("Error during conversion"))

	def script_dumpExplorerTreeForDiagnostics(self, gesture):
		fg = api.getForegroundObject()
		if not fg or not fg.appModule or fg.appModule.appName != "explorer":
			ui.message(_("Not focused on File Explorer"))
			return

		def dump(obj, depth, lines):
			if obj is None or depth > 6:
				return
			try:
				lines.append(
					"{indent}role={role} class={cls} automationId={autoId} name={name!r}".format(
						indent="  " * depth,
						role=obj.role,
						cls=getattr(obj, "windowClassName", None),
						autoId=getattr(obj, "UIAAutomationId", None),
						name=getattr(obj, "name", None),
					)
				)
				child = obj.firstChild
				while child is not None:
					dump(child, depth + 1, lines)
					child = child.next
			except (COMError, AttributeError, RuntimeError):
				pass

		treeLines = []
		dump(fg, 0, treeLines)
		log.info("xPlorer diagnostic tree dump:\n" + "\n".join(treeLines))
		ui.message(_("Explorer tree dumped to NVDA log"))

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		self.manager.chooseNVDAObjectOverlayClasses(obj, clsList)

	def event_gainFocus(self, obj, nextHandler):
		if self._multiSelectActive and (not obj or not getattr(obj, "appModule", None) or obj.appModule.appName != "explorer"):
			newAppName = getattr(getattr(obj, "appModule", None), "appName", None)
			log.debug(f"xPlorer: multi-select focus safety net triggered, new focus appModule.appName={newAppName!r}")
			self._exitMultiSelectLayer(silent=True, reason=f"focus_left_explorer:{newAppName}")

		if self.manager and not getattr(self.manager, "_explorer_focused", False):
			return nextHandler()

		nextHandlerFired = False
		def callNextHandlerOnce():
			nonlocal nextHandlerFired
			if nextHandlerFired:
				return
			nextHandlerFired = True
			nextHandler()

		try:
			if obj and getattr(obj, "appModule", None) and obj.appModule.appName == "explorer":
				if hasattr(obj, 'windowHandle'):
					if obj.windowHandle != self._last_window_hwnd:
						self._last_window = None
						self._last_window_hwnd = None
					if obj.windowHandle != self._cached_explorer_hwnd:
						self._invalidatePathCache()
			self.manager.event_gainFocus(obj, callNextHandlerOnce)
		except (COMError, AttributeError, RuntimeError) as e:
			log.debug(f"event_gainFocus error in __init__: {e}")
			callNextHandlerOnce()

	def event_focusEntered(self, obj, nextHandler):
		self.manager.event_focusEntered(obj, nextHandler)

	def event_foreground(self, obj, nextHandler):
		self._last_window = None
		self._last_window_hwnd = None
		self._invalidatePathCache()
		self.manager.event_foreground(obj, nextHandler)

