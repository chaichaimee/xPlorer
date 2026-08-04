# __init__.py
# Copyright (C) 2026 Chai Chaimee
# Licensed under GNU General Public License. See COPYING.txt for details.

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

addonHandler.initTranslation()
log.debug("xPlorer: Initializing add-on")

# ----------------------------------------------------------------------
# Graceful import helper using importlib
# ----------------------------------------------------------------------
_imported_modules = {}

def _safe_import_module(module_name, class_name=None):
	"""Import a submodule or a class from it using relative import.
	Returns the imported class/function if successful, else None.
	"""
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

# ----------------------------------------------------------------------
# Core module – must succeed
# ----------------------------------------------------------------------
try:
	from .xPlorerManager import xPlorerSettingsPanel, ExplorerManager, set_global_plugin
	_imported_modules['xPlorerManager'] = True
	log.debug("xPlorer: xPlorerManager imported")
except Exception as e:
	log.exception("Failed to import xPlorerManager - add-on cannot load")
	raise

# ----------------------------------------------------------------------
# Optional modules – failure does not stop the add-on
# ----------------------------------------------------------------------
FileOperations = _safe_import_module('fileOperations', 'FileOperations')
CompressionManager = _safe_import_module('compressionManager', 'CompressionManager')
ClipboardManager = _safe_import_module('clipboardManager', 'ClipboardManager')
SelectionManager = _safe_import_module('folderTools', 'SelectionManager')
RobocopyManager = _safe_import_module('robocopyManager', 'RobocopyManager')
TxtToFolder = _safe_import_module('folderTools', 'TxtToFolder')
CreateFileManager = _safe_import_module('createFile', 'CreateFileManager')
ContextMenuManager = _safe_import_module('contextMenu', 'ContextMenuManager')
FolderInfoManager = _safe_import_module('folderTools', 'FolderInfoManager')
CaseConverter = _safe_import_module('folderTools', 'CaseConverter')
FolderCreationDialog = _safe_import_module('folderTools', 'FolderCreationDialog')
type_clipboard_into_rename_if_suitable = _safe_import_module('folderTools', 'type_clipboard_into_rename_if_suitable')

log.debug("xPlorer: All modules processed")

# ----------------------------------------------------------------------
# Multi-tap state
# ----------------------------------------------------------------------
_last_tap_time_compress = 0
_tap_count_compress = 0
_compress_timer = None

_last_tap_time_copy = 0
_tap_count_copy = 0
_copy_timer = None

_last_tap_time_invert = 0
_tap_count_invert = 0
_invert_timer = None

_last_tap_time_robocopy = 0
_tap_count_robocopy = 0
_robocopy_timer = None

_double_tap_threshold = 0.5

# ----------------------------------------------------------------------
# Active-tab breadcrumb resolver
#
# Windows tabbed Explorer (Windows 10 21H2+/Windows 11) registers one
# Shell.Application COM window entry PER TAB, but every tab in the same
# top-level window reports the SAME hwnd. Code that matches purely on
# hwnd (as the previous version of this file did) cannot tell which tab
# is actually visible, so it silently returns whichever tab's entry the
# COM collection happens to enumerate first - in practice this is often
# the first tab that was opened (frequently the "main" folder), which is
# exactly the symptom reported: focus/paths snapping back to the main
# folder when switching between tabs (e.g. into userConfig\addon\xPlorer).
#
# This resolver is only consulted when more than one Shell.Application
# window shares the foreground hwnd (i.e. tabs are actually in play), so
# it adds no overhead for users on single-tab/classic Explorer windows.
#
# The primary strategy makes no assumption about Windows build, UI
# language, or class/automationId naming: only one control in a visible
# Explorer tab exposes an accessible "value" that is itself an existing
# directory path (the address/breadcrumb bar), so scanning for that value
# is more portable across every user's machine than matching a specific
# identifier. The class-name/automationId lookups only serve as a
# fallback for unusual shells where that generic scan comes up empty.
# ----------------------------------------------------------------------
_KNOWN_BREADCRUMB_CLASS_NAMES = ("Breadcrumb Parent",)
_KNOWN_ADDRESS_AUTOMATION_IDS = ("1001",)


class ActiveTabPathResolver:
	def __init__(self):
		self._workingStrategyName = None

	def resolveActivePath(self, foregroundObj, thorough=False):
		"""Best-effort synchronous lookup, intended for the small UIA subtree
		walk this needs - callers on the main thread should keep foregroundObj
		shallow. Returns None if no strategy could confirm the active tab.

		thorough=True widens the value-scan budget for the rare case where
		the normal shallow scan comes up empty (e.g. a UI transition right
		after alt+tab has momentarily deepened where the breadcrumb sits in
		the tree). Callers should only opt into this as a last resort before
		giving up, since it costs more UIA round-trips."""
		strategies = (
			("value_scan", self._resolveByValueScan),
			("class_name", self._resolveByClassName),
			("automation_id", self._resolveByAutomationId),
		)
		orderedStrategies = sorted(
			strategies, key=lambda item: item[0] != self._workingStrategyName
		)
		for strategyName, strategyFn in orderedStrategies:
			try:
				if thorough and strategyName == "value_scan":
					resolvedPath = strategyFn(foregroundObj, maxNodes=150, maxDepth=10)
				else:
					resolvedPath = strategyFn(foregroundObj)
				if resolvedPath:
					self._workingStrategyName = strategyName
					return resolvedPath
			except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError) as e:
				log.debug(f"xPlorer: breadcrumb strategy '{strategyName}' failed: {e}")
		return None

	def _resolveByValueScan(self, foregroundObj, maxNodes=60, maxDepth=6):
		"""Walk the visible Explorer window's UI tree looking for any control
		whose accessible value is itself an existing directory - this is, in
		practice, the address/breadcrumb bar. Since only the ACTIVE tab's
		content is present in the visible tree at all (inactive tabs are not
		rendered), this naturally finds the right tab without needing to
		know its exact class name or automationId ahead of time.

		Breadth-first on purpose: the breadcrumb bar is always shallow
		(a handful of levels down from the window), while the file LIST can
		be arbitrarily large. A depth-first walk that dives into the first
		child's subtree before trying siblings could burn its entire node
		budget inside the file list without ever reaching the breadcrumb -
		slow (each property read is a cross-process UIA call) and prone to
		simply not finding the answer. BFS finds shallow controls first, and
		list rows are skipped entirely below since they cannot contain it."""
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
				value = getattr(current, "value", None)
				if value and isinstance(value, str) and len(value) > 2 and os.path.isdir(value):
					return os.path.normpath(value)
			except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
				pass
			try:
				if getattr(current, "role", None) == Role.LISTITEM:
					continue
			except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
				pass
			if depth >= maxDepth:
				continue
			try:
				child = current.firstChild
				while child is not None:
					queue.append((child, depth + 1))
					child = child.next
			except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
				pass
		return None

	def _resolveByClassName(self, foregroundObj):
		breadcrumbObj = self._findDescendant(
			foregroundObj,
			lambda o: getattr(o, "windowClassName", None) in _KNOWN_BREADCRUMB_CLASS_NAMES,
		)
		return self._pathFromBreadcrumbSegments(breadcrumbObj)

	def _resolveByAutomationId(self, foregroundObj):
		breadcrumbObj = self._findDescendant(
			foregroundObj,
			lambda o: getattr(o, "UIAAutomationId", None) in _KNOWN_ADDRESS_AUTOMATION_IDS,
		)
		return self._pathFromBreadcrumbSegments(breadcrumbObj)

	def _findDescendant(self, obj, matchFn, maxDepth=6):
		if obj is None or maxDepth <= 0:
			return None
		try:
			if matchFn(obj):
				return obj
			child = obj.firstChild
			while child is not None:
				found = self._findDescendant(child, matchFn, maxDepth - 1)
				if found:
					return found
				child = child.next
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
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
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
			return None


# ----------------------------------------------------------------------
# Explorer responsiveness probe (freeze prevention)
#
# shell.Windows() and every property read on a Shell.Application window
# object (Document.Folder, LocationURL, ...) are marshaled through the
# message queue of the Explorer window that owns them. If that window is
# still busy - for example right after opening a folder with a lot of
# items, or a folder on a slow network path - the window's queue is not
# being pumped, and the COM call blocks on NVDA's main thread until
# Explorer catches up. That is the multi-second freeze reported when
# opening folders: nothing is wrong with the COM code itself, it is just
# waiting for a message queue that is not being serviced yet.
#
# SendMessageTimeoutW with SMTO_ABORTIFHUNG gives a cheap, bounded way to
# check whether that queue is currently being pumped BEFORE making the
# expensive COM call, so xPlorer can fall back to the last known path
# instead of hanging the main thread until Explorer becomes responsive.
# ----------------------------------------------------------------------
_WM_NULL = 0x0000
_SMTO_ABORTIFHUNG = 0x0002
_SMTO_BLOCK = 0x0001


def _isExplorerWindowResponsive(hwnd, timeoutMs=150):
	"""Best-effort, bounded (<= timeoutMs) check of whether hwnd's message
	queue is currently being pumped. Returns True if we cannot determine
	this (e.g. the API call itself fails) so a probe failure never blocks
	legitimate path lookups - it only ever skips them when Explorer is
	confirmed to be busy."""
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

			# Create instances only if modules imported successfully
			self.fileOps = FileOperations(self) if FileOperations else None
			self.compression = CompressionManager(self) if CompressionManager else None
			self.clipboard = ClipboardManager(self) if ClipboardManager else None
			self.selection = SelectionManager(self) if SelectionManager else None
			self.robocopy = RobocopyManager(self) if RobocopyManager else None
			self.txt2folder = TxtToFolder(self) if TxtToFolder else None
			self.createFileManager = CreateFileManager(self) if CreateFileManager else None
			self.contextMenuManager = ContextMenuManager(self) if ContextMenuManager else None
			self.folderInfo = FolderInfoManager(self) if FolderInfoManager else None
			self.caseConverter = CaseConverter() if CaseConverter else None

			self._last_window = None
			self._last_window_hwnd = None
			self._last_window_time = 0
			self._last_path = None

			self._cached_explorer_hwnd = None
			self._cached_explorer_time = 0
			self._cached_explorer_path = None
			self._cache_valid_duration = 0.8
			self._tabPathResolver = ActiveTabPathResolver()

			self._striprtf_available = None
			tools_dir = os.path.join(os.path.dirname(__file__), "tools")
			if os.path.exists(tools_dir) and tools_dir not in sys.path:
				sys.path.insert(0, tools_dir)

			self._cached_selected_folder_paths = []
			self._case_cache_valid = False
			self._suppress_counter = 0

			set_global_plugin(self)

			log.debug("xPlorer GlobalPlugin initialized successfully")
		except Exception as e:
			log.exception("Error in xPlorer GlobalPlugin.__init__")
			raise

	def terminate(self):
		log.debug("xPlorer GlobalPlugin.terminate starting")
		try:
			super().terminate()
			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(xPlorerSettingsPanel)

			for mgr in (self.fileOps, self.compression, self.selection,
						self.robocopy, self.createFileManager, self.folderInfo):
				if mgr and hasattr(mgr, 'cleanup'):
					mgr.cleanup()

			if self.manager:
				self.manager.terminate()

			self._cancelAllTimers()
			self._cached_selected_folder_paths = []
			self._case_cache_valid = False
			self.objShellApp = None
			self.objFSO = None

			log.debug("xPlorer GlobalPlugin terminated successfully")
		except Exception as e:
			log.exception("Error in xPlorer GlobalPlugin.terminate")

	def _cancelAllTimers(self):
		global _compress_timer, _copy_timer, _invert_timer, _robocopy_timer
		for timer in (_compress_timer, _copy_timer, _invert_timer, _robocopy_timer):
			if timer:
				timer.Stop()
		_compress_timer = _copy_timer = _invert_timer = _robocopy_timer = None

	def _invalidatePathCache(self):
		"""Clear cached explorer path so the next retrieval re-fetches from COM."""
		self._cached_explorer_hwnd = None
		self._cached_explorer_path = None
		self._cached_explorer_time = 0

	def _getCachedExplorerPath(self, target_hwnd):
		# A cached path only ever belongs to the window it was captured from.
		# Handing it out for a different hwnd is how switching windows makes
		# the reported path silently jump back to whatever window was cached last.
		if not self._cached_explorer_path:
			return None
		if target_hwnd is not None and self._cached_explorer_hwnd != target_hwnd:
			return None
		return self._cached_explorer_path

	# ------------------------------------------------------------------
	# Helper methods (unchanged)
	# ------------------------------------------------------------------
	def _getStriprtfModule(self):
		if self._striprtf_available is None:
			try:
				from striprtf.striprtf import rtf_to_text
				self._striprtf_available = rtf_to_text
				log.info("striprtf module loaded successfully")
			except ImportError:
				log.warning("striprtf module not available")
				self._striprtf_available = False
			except Exception as e:
				log.error(f"Error loading striprtf: {e}")
				self._striprtf_available = False
		return self._striprtf_available

	def _getCurrentPathDeferred(self, callback, delay=200, retryCount=0):
		"""Asynchronously get the current explorer path with retry during foreground transition."""
		def do_get():
			path = self._getCurrentPathFromExplorer()
			if path is None and self.manager._foregroundTransition and retryCount < 5:
				# Transition still active, retry after a short delay
				core.callLater(100, lambda: self._getCurrentPathDeferred(callback, delay=0, retryCount=retryCount+1))
			else:
				callback(path)
		core.callLater(delay, do_get)

	def _getSelectedItemsDeferred(self, callback, delay=200):
		core.callLater(delay, lambda: callback(self._getSelectedItems()))

	def _getCurrentPathFromExplorer(self):
		if self.manager._foregroundTransition:
			log.debug("Foreground transition active, skipping path retrieval")
			return None

		current_time = time.time()
		target_hwnd = None
		try:
			fg = api.getForegroundObject()
			if not fg or not fg.appModule or fg.appModule.appName != "explorer":
				if self._cached_explorer_path and current_time - self._cached_explorer_time < 0.3:
					return self._cached_explorer_path
				return None

			target_hwnd = fg.windowHandle
			if not winUser.isWindow(target_hwnd):
				return self._getCachedExplorerPath(target_hwnd)

			# Explorer is momentarily busy (e.g. it just finished loading a
			# heavy folder) and not pumping messages - a COM call right now
			# would block the main thread until it catches up. Use the
			# cached path this cycle instead of freezing NVDA; the next
			# focus/foreground event will retry once Explorer is free again.
			if not _isExplorerWindowResponsive(target_hwnd):
				log.debug("xPlorer: Explorer window busy, using cached path to avoid blocking")
				return self._getCachedExplorerPath(target_hwnd)

			shell = self.objShellApp
			if not shell:
				return self._getCachedExplorerPath(target_hwnd)

			# Collect every Shell.Application window entry that shares this
			# hwnd. On a tabbed Explorer window there can be more than one -
			# one per open tab - and only the breadcrumb bar of the actually
			# visible tab can tell them apart. Trusting the cache or taking
			# the first COM match (as before) is exactly what made the path
			# "stick" to whichever tab was opened first after switching tabs.
			matchingPaths = []
			try:
				for window in shell.Windows():
					try:
						if not window or window.hwnd != target_hwnd:
							continue
						windowPath = self._extractPathFromShellWindow(window)
						if windowPath:
							matchingPaths.append(windowPath)
					except (COMError, AttributeError):
						continue
			except COMError as e:
				log.debug(f"COM error enumerating windows: {e}")
				return self._getCachedExplorerPath(target_hwnd)

			if len(matchingPaths) == 1:
				# Unambiguous: safe to use the short-lived cache here.
				if (self._cached_explorer_hwnd == target_hwnd
						and self._cached_explorer_path == matchingPaths[0]
						and current_time - self._cached_explorer_time < self._cache_valid_duration):
					return self._cached_explorer_path
				self._cached_explorer_hwnd = target_hwnd
				self._cached_explorer_time = current_time
				self._cached_explorer_path = matchingPaths[0]
				return matchingPaths[0]

			if len(matchingPaths) > 1:
				# Multiple tabs share this hwnd - the cache cannot be trusted
				# at all here (it has no notion of "which tab"), so always
				# re-resolve which one is actually visible via the breadcrumb.
				# Exception: reuse a breadcrumb result from moments ago (e.g.
				# _getActiveExplorerWindow calling straight back into this
				# during the same event) instead of scanning the tree twice.
				if (self._cached_explorer_hwnd == target_hwnd
						and self._cached_explorer_path in matchingPaths
						and current_time - self._cached_explorer_time < 0.25):
					return self._cached_explorer_path
				breadcrumbPath = self._tabPathResolver.resolveActivePath(fg)
				if breadcrumbPath and breadcrumbPath in matchingPaths:
					self._cached_explorer_hwnd = target_hwnd
					self._cached_explorer_time = current_time
					self._cached_explorer_path = breadcrumbPath
					return breadcrumbPath
				# One more, wider attempt before giving up: a UI transition
				# (e.g. right after alt+tab) can momentarily leave the normal
				# shallow scan without a hit even though the breadcrumb bar
				# is present a little deeper in the tree.
				breadcrumbPath = self._tabPathResolver.resolveActivePath(fg, thorough=True)
				if breadcrumbPath and breadcrumbPath in matchingPaths:
					self._cached_explorer_hwnd = target_hwnd
					self._cached_explorer_time = current_time
					self._cached_explorer_path = breadcrumbPath
					return breadcrumbPath
				# Could not confirm which tab is active. Falling back to
				# "the cache if it happens to match one of the open tabs" is
				# NOT safe here: matching one of the tabs doesn't mean it's
				# the ACTIVE one, and in practice this reliably re-reported
				# whichever tab (typically the main folder) had been visited
				# previously - that is the "bounces back to the main folder"
				# symptom. Refuse to guess instead of risking a wrong answer.
				log.debug("xPlorer: multiple tabs share this hwnd and the active one "
						"could not be confirmed; refusing to guess a path")
				return None

		except COMError as e:
			log.debug(f"COM error in _getCurrentPathFromExplorer: {e}")
		except Exception as e:
			log.error(f"Error in _getCurrentPathFromExplorer: {e}")

		return self._getCachedExplorerPath(target_hwnd)

	def _extractPathFromShellWindow(self, window):
		"""Read the folder path a single Shell.Application window object points
		to, without assuming it is the active tab - callers decide that."""
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
			log.debug("Foreground transition active, skipping window retrieval")
			return None
		try:
			current_time = time.time()
			fg = api.getForegroundObject()
			if not fg or not fg.appModule or fg.appModule.appName != "explorer":
				return None

			target_hwnd = fg.windowHandle
			if not winUser.isWindow(target_hwnd):
				return None

			# Same freeze-prevention probe as _getCurrentPathFromExplorer:
			# skip the COM enumeration entirely while Explorer's message
			# queue is busy rather than blocking on it.
			if not _isExplorerWindowResponsive(target_hwnd):
				log.debug("xPlorer: Explorer window busy, skipping window retrieval to avoid blocking")
				return None

			shell = self.objShellApp
			if not shell:
				return None

			matchingWindows = []
			try:
				for window in shell.Windows():
					try:
						if window and window.hwnd == target_hwnd and hasattr(window, "Document") and window.Document:
							matchingWindows.append(window)
					except (COMError, AttributeError):
						continue
			except COMError:
				pass

			if not matchingWindows:
				return None

			if len(matchingWindows) == 1:
				# Unambiguous: the 1s cache is safe here since there is only
				# ever one tab for this hwnd.
				if (self._last_window and self._last_window_hwnd == target_hwnd and
						current_time - self._last_window_time < 1.0 and
						winUser.isWindow(self._last_window_hwnd)):
					return self._last_window
				chosenWindow = matchingWindows[0]
			else:
				# Multiple tabs share this hwnd - the 1s cache cannot be
				# trusted (it has no notion of "which tab"), so always
				# cross-check against the confirmed active path.
				activePath = self._getCurrentPathFromExplorer()
				chosenWindow = None
				if activePath:
					for window in matchingWindows:
						windowPath = self._extractPathFromShellWindow(window)
						if windowPath == activePath:
							chosenWindow = window
							break
				if chosenWindow is None:
					log.debug("xPlorer: multiple tabs share this hwnd and the active "
							"one could not be confirmed; refusing to guess a window")
					return None

			self._last_window = chosenWindow
			self._last_window_hwnd = target_hwnd
			self._last_window_time = current_time
			return chosenWindow
		except Exception as e:
			log.error(f"Error getting active Explorer window: {e}")
			return None

	def _getCurrentPath(self):
		return self._getCurrentPathFromExplorer()

	def _getSelectedItems(self):
		if self.manager._foregroundTransition:
			log.debug("Foreground transition active, skipping selected items")
			return None, None
		try:
			shellWindow = self._getActiveExplorerWindow()
			if not shellWindow:
				return None, None
			try:
				if not hasattr(shellWindow, "document") or not shellWindow.document:
					return None, None
				document = shellWindow.document
				if self.manager.lastExplorerDocument != document:
					self.manager.lastExplorerDocument = document
			except (COMError, AttributeError):
				return None, None
			selectedItems = []
			try:
				if hasattr(document, 'SelectedItems'):
					selectedItemsCount = document.SelectedItems().Count
					for i in range(selectedItemsCount):
						item = document.SelectedItems().Item(i)
						selectedItems.append((item.Name, item.Path))
			except (COMError, AttributeError):
				pass
			return selectedItems if selectedItems else None, shellWindow
		except Exception as e:
			log.debug(f"Error in _getSelectedItems: {e}")
			return None, None

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
			log.debug(f"Error sending original key: {e}")

	# ------------------------------------------------------------------
	# Script functions – all check availability of required managers
	# ------------------------------------------------------------------

	def script_copySelectedNamesOrAddressBar(self, gesture):
		if not self.clipboard:
			ui.message(_("Clipboard manager not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		global _last_tap_time_copy, _tap_count_copy, _copy_timer
		current_time = time.time()
		if current_time - _last_tap_time_copy > _double_tap_threshold:
			_tap_count_copy = 0
			if _copy_timer:
				_copy_timer.Stop()
				_copy_timer = None
		_tap_count_copy += 1
		_last_tap_time_copy = current_time
		if _tap_count_copy == 1:
			_copy_timer = core.callLater(int(_double_tap_threshold * 1000), self._processCopyTap)
		elif _tap_count_copy >= 2:
			if _copy_timer:
				_copy_timer.Stop()
				_copy_timer = None
			self._processCopyTap()

	script_copySelectedNamesOrAddressBar.__doc__ = _("Copy selected names (single tap) or copy address bar (double tap)")
	script_copySelectedNamesOrAddressBar.category = _("xPlorer")
	script_copySelectedNamesOrAddressBar.gestures = ["kb(desktop):NVDA+shift+c"]

	def _processCopyTap(self):
		global _tap_count_copy, _copy_timer
		if _copy_timer:
			_copy_timer.Stop()
			_copy_timer = None
		if _tap_count_copy == 1:
			self._executeWithSilence(self.clipboard.copySelectedNames)
		elif _tap_count_copy >= 2:
			self._executeWithSilence(self._copyAddressBar)
		_tap_count_copy = 0

	def script_invertSelection_double_tap(self, gesture):
		if not self.clipboard or not self.selection:
			ui.message(_("Required manager not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		global _last_tap_time_invert, _tap_count_invert, _invert_timer
		current_time = time.time()
		if current_time - _last_tap_time_invert > _double_tap_threshold:
			_tap_count_invert = 0
			if _invert_timer:
				_invert_timer.Stop()
				_invert_timer = None
		_tap_count_invert += 1
		_last_tap_time_invert = current_time
		if _tap_count_invert == 1:
			_invert_timer = core.callLater(int(_double_tap_threshold * 1000), self._processInvertTap)
		elif _tap_count_invert >= 2:
			if _invert_timer:
				_invert_timer.Stop()
				_invert_timer = None
			self._processInvertTap()

	script_invertSelection_double_tap.__doc__ = _("Copy content (single tap) or invert selection (double tap)")
	script_invertSelection_double_tap.category = _("xPlorer")
	script_invertSelection_double_tap.gestures = ["kb(desktop):NVDA+shift+v"]

	def _processInvertTap(self):
		global _tap_count_invert, _invert_timer
		if _invert_timer:
			_invert_timer.Stop()
			_invert_timer = None
		if _tap_count_invert == 1:
			self._executeWithSilence(self.clipboard.copyFileContent)
		elif _tap_count_invert >= 2:
			self._executeWithSilence(self.selection.invertSelection)
		_tap_count_invert = 0

	def script_compressZip_double_tap(self, gesture):
		if not self.fileOps or not self.compression:
			ui.message(_("Compression manager not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		global _last_tap_time_compress, _tap_count_compress, _compress_timer
		current_time = time.time()
		if current_time - _last_tap_time_compress > _double_tap_threshold:
			_tap_count_compress = 0
			if _compress_timer:
				_compress_timer.Stop()
				_compress_timer = None
		_tap_count_compress += 1
		_last_tap_time_compress = current_time
		if _tap_count_compress == 1:
			_compress_timer = core.callLater(int(_double_tap_threshold * 1000), self._processCompressTap)
		elif _tap_count_compress >= 2:
			if _compress_timer:
				_compress_timer.Stop()
				_compress_timer = None
			self._processCompressTap()

	script_compressZip_double_tap.__doc__ = _("Say size (single tap) or compress zip (double tap)")
	script_compressZip_double_tap.category = _("xPlorer")
	script_compressZip_double_tap.gestures = ["kb(desktop):NVDA+shift+z"]

	def _processCompressTap(self):
		global _tap_count_compress, _compress_timer
		if _compress_timer:
			_compress_timer.Stop()
			_compress_timer = None
		if _tap_count_compress == 1:
			self._executeWithSilence(self.fileOps.saySize)
		elif _tap_count_compress >= 2:
			core.callLater(50, self._executeWithSilence, self.compression.compressZip)
		_tap_count_compress = 0

	def script_robocopyMultitap(self, gesture):
		if not self.robocopy:
			ui.message(_("Robocopy manager not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		global _last_tap_time_robocopy, _tap_count_robocopy, _robocopy_timer
		current_time = time.time()
		if current_time - _last_tap_time_robocopy > _double_tap_threshold:
			_tap_count_robocopy = 0
			if _robocopy_timer:
				_robocopy_timer.Stop()
				_robocopy_timer = None
		_tap_count_robocopy += 1
		_last_tap_time_robocopy = current_time
		if _tap_count_robocopy == 1:
			_robocopy_timer = core.callLater(int(_double_tap_threshold * 1000), self._processRobocopyTap)
		elif _tap_count_robocopy >= 3:
			if _robocopy_timer:
				_robocopy_timer.Stop()
				_robocopy_timer = None
			self._processRobocopyTap()

	script_robocopyMultitap.__doc__ = _("Robocopy: single tap copy, double tap paste, triple tap move")
	script_robocopyMultitap.category = _("xPlorer")
	script_robocopyMultitap.gestures = ["kb(desktop):NVDA+shift+r"]

	def _processRobocopyTap(self):
		global _tap_count_robocopy, _robocopy_timer
		if _robocopy_timer:
			_robocopy_timer.Stop()
			_robocopy_timer = None
		if _tap_count_robocopy == 1:
			self._executeWithSilence(self.robocopy.copy)
		elif _tap_count_robocopy == 2:
			self._executeWithSilence(self.robocopy.paste)
		elif _tap_count_robocopy == 3:
			self._executeWithSilence(self.robocopy.move)
		_tap_count_robocopy = 0

	def _cache_selected_folders_for_case(self):
		self._cached_selected_folder_paths = []
		self._case_cache_valid = False
		try:
			selected_items, _ = self._getSelectedItems()
			if selected_items:
				folder_paths = []
				for name, path in selected_items:
					if os.path.isdir(path):
						folder_paths.append(path)
				if folder_paths:
					self._cached_selected_folder_paths = folder_paths
					self._case_cache_valid = True
					log.debug(f"Cached {len(folder_paths)} folders for case conversion")
		except Exception as e:
			log.debug(f"Failed to cache selected folders: {e}")

	def _get_cached_or_selected_folders(self):
		if self._case_cache_valid and self._cached_selected_folder_paths:
			return self._cached_selected_folder_paths
		selected_items, _ = self._getSelectedItems()
		if selected_items:
			return [path for name, path in selected_items if os.path.isdir(path)]
		return []

	def script_openXPlorerContextMenu(self, gesture):
		if not self.contextMenuManager:
			ui.message(_("Context menu manager not available"))
			return
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		self._cache_selected_folders_for_case()
		self._showContextMenu()

	script_openXPlorerContextMenu.__doc__ = _("Open xPlorer context menu")
	script_openXPlorerContextMenu.category = _("xPlorer")
	script_openXPlorerContextMenu.gestures = ["kb(desktop):NVDA+shift+x"]

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
		self._renameFile()

	script_renameFile.__doc__ = _("Rename selected file")
	script_renameFile.category = _("xPlorer")
	script_renameFile.gestures = ["kb(desktop):NVDA+shift+f2"]

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
			core.callLater(600, type_clipboard_into_rename_if_suitable)

	script_createFolderWithAutoPaste.__doc__ = _("Create new folder and paste clipboard content into rename field")
	script_createFolderWithAutoPaste.category = _("xPlorer")
	script_createFolderWithAutoPaste.gestures = ["kb(desktop):control+shift+n"]

	def _openSettings(self):
		try:
			core.callLater(0, self._showSettingsDialog)
		except Exception as e:
			log.error(f"Error opening settings dialog: {e}")
			ui.message(_("Cannot open settings dialog"))

	def _showSettingsDialog(self):
		try:
			gui.mainFrame.popupSettingsDialog(gui.settingsDialogs.NVDASettingsDialog, xPlorerSettingsPanel)
		except Exception as e:
			log.error(f"Error showing settings dialog: {e}")
			ui.message(_("Error opening settings"))

	def _showContextMenu(self):
		if self.contextMenuManager:
			self.contextMenuManager.showContextMenu()
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
					if dlg.ShowModal() == wx.ID_OK:
						dlg.process_input()
					dlg.Destroy()
				except Exception as e:
					log.error(f"Error in folder creation dialog: {e}")
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

		cached_folders = self._get_cached_or_selected_folders()
		if cached_folders:
			do_convert(cached_folders)
			return

		def get_path_callback(path):
			if path and os.path.isdir(path):
				do_convert([path])
			else:
				ui.message(_("No folders selected or current folder not available"))
			self._case_cache_valid = False

		self._getCurrentPathDeferred(get_path_callback, 200)

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
			log.error(f"Error converting folder names: {e}")
			ui.message(_("Error during conversion"))

	def script_dumpExplorerTreeForDiagnostics(self, gesture):
		"""Dump the focused Explorer window's automation tree to the NVDA log.
		Use this when a user reports the active-tab detection is not working
		on their machine: their Windows build/UI language may expose a
		different breadcrumb class name/automationId than the ones this
		add-on currently recognizes. Ask them to run this, then send the
		relevant lines from the NVDA log (Tools > View Log)."""
		fg = api.getForegroundObject()
		if not fg or not fg.appModule or fg.appModule.appName != "explorer":
			ui.message(_("Not focused on File Explorer"))
			return

		def dump(obj, depth, lines):
			if obj is None or depth > 8:
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
			except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
				pass

		treeLines = []
		dump(fg, 0, treeLines)
		log.info("xPlorer diagnostic tree dump:\n" + "\n".join(treeLines))
		ui.message(_("Explorer tree dumped to NVDA log"))

	# ------------------------------------------------------------------
	# Event handlers
	# ------------------------------------------------------------------
	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		self.manager.chooseNVDAObjectOverlayClasses(obj, clsList)

	def event_gainFocus(self, obj, nextHandler):
		try:
			if obj and obj.appModule and obj.appModule.appName == "explorer":
				if hasattr(obj, 'windowHandle'):
					if obj.windowHandle != self._last_window_hwnd:
						self._last_window = None
						self._last_window_hwnd = None
					if obj.windowHandle != self._cached_explorer_hwnd:
						self._invalidatePathCache()
			self.manager.event_gainFocus(obj, nextHandler)
		except Exception as e:
			log.error(f"event_gainFocus error: {e}")
			nextHandler()

	def event_focusEntered(self, obj, nextHandler):
		self.manager.event_focusEntered(obj, nextHandler)

	def event_foreground(self, obj, nextHandler):
		self._last_window = None
		self._last_window_hwnd = None
		self._invalidatePathCache()
		self.manager.event_foreground(obj, nextHandler)

	def event_UIA_elementSelected(self, obj, nextHandler):
		self.manager.event_UIA_elementSelected(obj, nextHandler)

	def event_selection(self, obj, nextHandler):
		self.manager.event_selection(obj, nextHandler)



