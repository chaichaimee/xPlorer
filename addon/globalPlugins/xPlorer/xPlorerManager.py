# xPlorerManager.py

import ui
import api
import speech
import ctypes
import ctypes.wintypes
from NVDAObjects import NVDAObject
from NVDAObjects.UIA import UIA
from controlTypes import Role, State, OutputReason
import addonHandler
from logHandler import log
import config
import gui
import wx
import gui.guiHelper
from gui.settingsDialogs import SettingsPanel
from .folderTools import loadConfig, saveConfig
import core
import speechDictHandler
from speechDictHandler import SpeechDictEntry
import time
import logging
import eventHandler
import UIAHandler
from comtypes import COMError as ComTypesCOMError
from _ctypes import COMError as CtypesCOMError

addonHandler.initTranslation()
log.debug("xPlorerManager module loaded")

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


_global_plugin_instance = None

def set_global_plugin(plugin):
	global _global_plugin_instance
	_global_plugin_instance = plugin



_user32Private = ctypes.WinDLL("user32")
_user32Private.FindWindowExW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HWND, ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPCWSTR]
_user32Private.FindWindowExW.restype = ctypes.wintypes.HWND
_user32Private.GetClassNameW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int]
_user32Private.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
_enumChildProc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
_user32Private.EnumChildWindows.argtypes = [ctypes.wintypes.HWND, _enumChildProc, ctypes.wintypes.LPARAM]


def _findItemsViewHwnd(frameHwnd):
	found = []
	classBuffer = ctypes.create_unicode_buffer(64)

	def onChild(childHwnd, lParam):
		_user32Private.GetClassNameW(childHwnd, classBuffer, 64)
		if classBuffer.value == "SHELLDLL_DefView" and _user32Private.IsWindowVisible(childHwnd):
			itemsViewHwnd = _user32Private.FindWindowExW(childHwnd, None, "DirectUIHWND", None)
			if itemsViewHwnd:
				found.append(itemsViewHwnd)
				return 0
		return 1

	_user32Private.EnumChildWindows(frameHwnd, _enumChildProc(onChild), 0)
	return found[0] if found else None

class LaconicFocusAncestor(NVDAObject):
	isPresentableFocusAncestor = False
	def _get_windowClassName(self):
		conf = loadConfig()
		if conf.get("suppressDirectUIAnnounce", True):
			windowClass = super().windowClassName
			if windowClass == "DirectUIHWND":
				return "FakeDirectUIHWND"
		return super().windowClassName

class EmptyFolderStaticText(NVDAObject):
	__gestures = {
		"kb:uparrow": "repeatEmptyFolder",
		"kb:downarrow": "repeatEmptyFolder",
	}

	def _isHookEnabled(self):
		rawName = super().name
		conf = loadConfig()
		if rawName == "Working on it...":
			return conf.get("hookWorkingOnIt", True)
		return conf.get("announceEmptyFolder", True)

	def _get_name(self):
		if self._isHookEnabled():
			return "Empty Folder"
		return super().name

	def script_repeatEmptyFolder(self, gesture):
		if not self._isHookEnabled():
			gesture.send()
			return
		log.debug("xPlorer TRACE: empty folder arrow key announce")
		speech.cancelSpeech()
		ui.message("Empty Folder")


class SingleItemArrowOverlay(NVDAObject):
	__gestures = {
		"kb:uparrow": "arrowOnPossibleSoleItem",
		"kb:downarrow": "arrowOnPossibleSoleItem",
	}

	def script_arrowOnPossibleSoleItem(self, gesture):
		gesture.send()
		manager = getattr(_global_plugin_instance, "manager", None)
		if manager is not None:
			manager.scheduleSoleItemAnnounce(self)


class FolderEntryOverlay(NVDAObject):
	__gestures = {
		"kb:enter": "enterFolderArmSelect",
		"kb:numpadenter": "enterFolderArmSelect",
	}

	def script_enterFolderArmSelect(self, gesture):
		manager = getattr(_global_plugin_instance, "manager", None)
		if manager is not None:
			manager.armLandingSelect()
		gesture.send()


class xPlorerSettingsPanel(SettingsPanel):
	title = "xPlorer"
	def makeSettings(self, settingsSizer):
		conf = loadConfig()
		sHelper = gui.guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self.autoSelectFirstItem = sHelper.addItem(wx.CheckBox(self, label="Automatically select the first item"))
		self.autoSelectFirstItem.SetValue(conf["autoSelectFirstItem"])
		self.announceEmptyFolder = sHelper.addItem(wx.CheckBox(self, label="Announce 'Empty Folder' when entering an empty folder"))
		self.announceEmptyFolder.SetValue(conf["announceEmptyFolder"])
		self.suppressDirectUIAnnounce = sHelper.addItem(wx.CheckBox(self, label="Suppress announcement of DirectUIHWND class"))
		self.suppressDirectUIAnnounce.SetValue(conf["suppressDirectUIAnnounce"])
		self.announceSingleItem = sHelper.addItem(wx.CheckBox(self, label="Announce and select the item when it is the only one in a folder"))
		self.announceSingleItem.SetValue(conf.get("announceSingleItem", True))
		self.hookWorkingOnIt = sHelper.addItem(wx.CheckBox(self, label="Announce Empty Folder instead of Working on it in an empty folder"))
		self.hookWorkingOnIt.SetValue(conf.get("hookWorkingOnIt", True))
		self.showItemSize = sHelper.addItem(wx.CheckBox(self, label="Announce the size of files and folders when moving through the list"))
		self.showItemSize.SetValue(conf.get("showItemSize", False))
		self.itemSizeScopeChoices = [
			("files", "File only"),
			("folders", "Folder only"),
			("all", "All files and folders"),
		]
		self.itemSizeScopeLabel = wx.StaticText(self, label="Announce the size of:")
		sHelper.addItem(self.itemSizeScopeLabel)
		self.itemSizeScope = sHelper.addItem(wx.Choice(
			self, choices=[label for _key, label in self.itemSizeScopeChoices]
		))
		scopeKeys = [key for key, _label in self.itemSizeScopeChoices]
		storedScope = conf.get("itemSizeScope", "all")
		self.itemSizeScope.SetSelection(scopeKeys.index(storedScope) if storedScope in scopeKeys else scopeKeys.index("all"))
		self.showItemSize.Bind(wx.EVT_CHECKBOX, self._onShowItemSizeToggled)
		self._onShowItemSizeToggled(None)
		self.reportItemPosition = None
		self._initialPositionSetting = None
		try:
			self._initialPositionSetting = bool(config.conf["presentation"]["reportObjectPositionInformation"])
		except KeyError:
			log.debug("xPlorer: NVDA object position setting not found, item position option hidden")
		if self._initialPositionSetting is not None:
			self.reportItemPosition = sHelper.addItem(wx.CheckBox(
				self, label="Announce item position, same as the NVDA Object Presentation setting"
			))
			self.reportItemPosition.SetValue(self._initialPositionSetting)
		self.recoverExplorerFocus = sHelper.addItem(wx.CheckBox(self, label="Move focus into the file list when Explorer is activated with focus stuck on the window frame"))
		self.recoverExplorerFocus.SetValue(conf.get("recoverExplorerFocus", True))
		self.sayFileExplorer = sHelper.addItem(wx.CheckBox(self, label="Suppress announcement of '- File Explorer' in window titles"))
		self.sayFileExplorer.SetValue(conf["sayFileExplorer"])
		self.suppressTaskSwitchingAnnounce = sHelper.addItem(wx.CheckBox(self, label="Suppress announcement of 'Task Switching'"))
		self.suppressTaskSwitchingAnnounce.SetValue(conf.get("suppressTaskSwitchingAnnounce", True))
		self.autoPasteClipboardToRename = sHelper.addItem(wx.CheckBox(self, label="Automatically paste clipboard content into rename field"))
		self.autoPasteClipboardToRename.SetValue(conf.get("autoPasteClipboardToRename", True))
		self.autoPasteClipboardToRename.Bind(wx.EVT_CHECKBOX, self._onAutoPasteClipboardToRenameChanged)

		self.forbiddenCharReplacementLabel = wx.StaticText(self, label="Replace forbidden characters in the pasted name with:")
		sHelper.addItem(self.forbiddenCharReplacementLabel)
		self.forbiddenCharReplacementChoices = [
			("-", "Hyphen (-)"),
			("_", "Underscore (_)"),
			("none", "Remove them (no replacement)"),
		]
		self.forbiddenCharReplacement = sHelper.addItem(wx.Choice(
			self, choices=[label for _key, label in self.forbiddenCharReplacementChoices]
		))
		storedReplacement = conf.get("forbiddenCharReplacement", "-")
		replacementKeys = [key for key, _label in self.forbiddenCharReplacementChoices]
		replacementIndex = replacementKeys.index(storedReplacement) if storedReplacement in replacementKeys else 0
		self.forbiddenCharReplacement.SetSelection(replacementIndex)

		self._updateForbiddenCharReplacementVisibility()

		self.showUncompressDialog = sHelper.addItem(wx.CheckBox(self, label="Show uncompress dialog"))
		self.showUncompressDialog.SetValue(conf.get("showUncompressDialog", True))
		self.showUncompressDialog.Bind(wx.EVT_CHECKBOX, self._onShowUncompressDialogChanged)

		self.uncompressDefaultActionLabel = wx.StaticText(self, label="When the dialog is hidden, extract using:")
		sHelper.addItem(self.uncompressDefaultActionLabel)
		self.uncompressDefaultActionChoices = [
			("extract_to", "Extract to a subfolder named after the archive"),
			("extract_here", "Extract here"),
		]
		self.uncompressDefaultAction = sHelper.addItem(wx.Choice(
			self, choices=[label for _key, label in self.uncompressDefaultActionChoices]
		))
		storedAction = conf.get("uncompressDefaultAction", "extract_to")
		actionKeys = [key for key, _label in self.uncompressDefaultActionChoices]
		selectionIndex = actionKeys.index(storedAction) if storedAction in actionKeys else 0
		self.uncompressDefaultAction.SetSelection(selectionIndex)

		self._updateUncompressDefaultActionVisibility()

	def _onAutoPasteClipboardToRenameChanged(self, event):
		self._updateForbiddenCharReplacementVisibility()
		event.Skip()

	def _updateForbiddenCharReplacementVisibility(self):
		showControl = self.autoPasteClipboardToRename.GetValue()
		self.forbiddenCharReplacementLabel.Show(showControl)
		self.forbiddenCharReplacement.Show(showControl)
		self.Layout()

	def _onShowUncompressDialogChanged(self, event):
		self._updateUncompressDefaultActionVisibility()
		event.Skip()

	def _updateUncompressDefaultActionVisibility(self):
		showDefaultActionControl = not self.showUncompressDialog.GetValue()
		self.uncompressDefaultActionLabel.Show(showDefaultActionControl)
		self.uncompressDefaultAction.Show(showDefaultActionControl)
		self.Layout()

	def _onShowItemSizeToggled(self, event):
		sizeEnabled = self.showItemSize.GetValue()
		self.itemSizeScopeLabel.Enable(sizeEnabled)
		self.itemSizeScope.Enable(sizeEnabled)

	def onSave(self):
		actionKeys = [key for key, _label in self.uncompressDefaultActionChoices]
		replacementKeys = [key for key, _label in self.forbiddenCharReplacementChoices]
		conf = loadConfig()
		conf.update({
			"autoSelectFirstItem": self.autoSelectFirstItem.GetValue(),
			"announceEmptyFolder": self.announceEmptyFolder.GetValue(),
			"suppressDirectUIAnnounce": self.suppressDirectUIAnnounce.GetValue(),
			"announceSingleItem": self.announceSingleItem.GetValue(),
			"recoverExplorerFocus": self.recoverExplorerFocus.GetValue(),
			"hookWorkingOnIt": self.hookWorkingOnIt.GetValue(),
			"showItemSize": self.showItemSize.GetValue(),
			"itemSizeScope": self.itemSizeScopeChoices[self.itemSizeScope.GetSelection()][0],
			"sayFileExplorer": self.sayFileExplorer.GetValue(),
			"suppressTaskSwitchingAnnounce": self.suppressTaskSwitchingAnnounce.GetValue(),
			"autoPasteClipboardToRename": self.autoPasteClipboardToRename.GetValue(),
			"forbiddenCharReplacement": replacementKeys[self.forbiddenCharReplacement.GetSelection()],
			"showUncompressDialog": self.showUncompressDialog.GetValue(),
			"uncompressDefaultAction": actionKeys[self.uncompressDefaultAction.GetSelection()],
		})
		saveConfig(conf)
		if self.reportItemPosition is not None:
			wantPosition = self.reportItemPosition.GetValue()
			if wantPosition != self._initialPositionSetting:
				config.conf["presentation"]["reportObjectPositionInformation"] = wantPosition
		if _global_plugin_instance and hasattr(_global_plugin_instance, 'manager'):
			_global_plugin_instance.manager._invalidateConfigCache()
			_global_plugin_instance.manager._update_speech_dict_for_title()


class ExplorerManager:
	def __init__(self, plugin):
		log.debug("ExplorerManager.__init__")
		self.plugin = plugin
		self.lastParent = None
		self.currentFolderPath = None
		self.suppressAnnouncements = False
		self.lastExplorerDocument = None
		self.contextMenuActive = False
		self.suppressAllAnnouncements = False

		self._temp_entry = None
		self._taskSwitchingTempEntry = None
		self._explorer_focused = False

		self._last_processed_key = None
		self._last_processed_time = 0
		self._debounce_interval = 0.1

		self._cached_provider_desc = {}
		self._cache_timeout = 0.4
		self._max_cache_size = 15

		self._foregroundTransition = False
		self._foreground_task = None
		self._last_foreground_time = 0
		self._last_sayFileExplorer_setting = None
		self._foregroundGeneration = 0

		self._speech_dict_task = None
		self._focusSnapshotTask = None
		self._lastItemFocusTime = 0.0
		self._landingSelectUntil = 0.0

		self._config_cache = None
		self._config_cache_time = 0.0

		self._update_speech_dict_for_title()

	def getConfig(self):
		now = time.time()
		if self._config_cache is not None and now - self._config_cache_time < 1.0:
			return self._config_cache
		self._config_cache = loadConfig()
		self._config_cache_time = now
		return self._config_cache

	def _invalidateConfigCache(self):
		self._config_cache = None
		self._config_cache_time = 0.0

	def _syncTempSpeechDictEntry(self, attrName, shouldSuppress, pattern, comment):
		currentEntry = getattr(self, attrName)
		if shouldSuppress and currentEntry is None:
			entry = SpeechDictEntry(
				pattern=pattern,
				replacement="",
				caseSensitive=True,
				type=0,
				comment=comment
			)
			speechDictHandler.dictionaries["temp"].append(entry)
			setattr(self, attrName, entry)
		elif not shouldSuppress and currentEntry is not None:
			try:
				speechDictHandler.dictionaries["temp"].remove(currentEntry)
			except ValueError:
				pass
			setattr(self, attrName, None)

	def _update_speech_dict_for_title(self):
		current_task = object()
		self._speech_dict_task = current_task

		def do_update():
			if self._speech_dict_task is not current_task:
				return
			self._speech_dict_task = None

			conf = self.getConfig()

			should_suppress = conf.get("sayFileExplorer", True)
			self._syncTempSpeechDictEntry(
				"_temp_entry", should_suppress,
				"- File Explorer", "xPlorer: suppress '- File Explorer'"
			)
			self._last_sayFileExplorer_setting = should_suppress

			# Restores the "Task Switching" suppression that xPlorer used to
			# provide as a side effect of a since-fixed event_foreground bug
			# (see xPlorerManager fix history). Implemented explicitly here,
			# via the same temp speech-dictionary mechanism as the line
			# above, rather than relying on that bug again.
			should_suppress_task_switching = conf.get("suppressTaskSwitchingAnnounce", True)
			self._syncTempSpeechDictEntry(
				"_taskSwitchingTempEntry", should_suppress_task_switching,
				"Task Switching", "xPlorer: suppress 'Task Switching' announcement"
			)

		core.callLater(100, do_update)

	def _should_process_event(self, obj):
		if not obj:
			return False
		current_time = time.time()
		try:
			obj_key = (obj.windowHandle, obj.role, id(obj))
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
			obj_key = id(obj)
		if self._last_processed_key == obj_key:
			if current_time - self._last_processed_time < self._debounce_interval:
				return False
		self._last_processed_key = obj_key
		self._last_processed_time = current_time
		return True

	def _is_explorer_list_cached(self, obj):
		if not obj or obj.role != Role.LIST:
			return False
		if not isinstance(obj, UIA):
			return False
		try:
			handle = obj.windowHandle
			current_time = time.time()
			if handle in self._cached_provider_desc:
				desc, timestamp = self._cached_provider_desc[handle]
				if current_time - timestamp < self._cache_timeout:
					return desc
			provider_desc = obj.UIAElement.CachedProviderDescription.lower()
			is_explorer = "explorerframe.dll" in provider_desc
			if len(self._cached_provider_desc) >= self._max_cache_size:
				oldest = min(self._cached_provider_desc.items(), key=lambda x: x[1][1])[0]
				del self._cached_provider_desc[oldest]
			self._cached_provider_desc[handle] = (is_explorer, current_time)
			return is_explorer
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
			return False

	def _isExplorerList(self, obj):
		return self._is_explorer_list_cached(obj)

	def _isFileItem(self, obj):
		if not obj or obj.role != Role.LISTITEM:
			return False
		parent = obj.parent
		if not parent:
			return False
		return self._isExplorerList(parent)

	def _isValidExplorerContext(self, obj):
		if not obj or not obj.appModule or obj.appModule.appName != "explorer":
			return False
		return (self._isExplorerList(obj) or self._isFileItem(obj))

	def _is_valid_uia_object(self, obj):
		if obj is None:
			return False
		try:
			if hasattr(obj, 'windowClassName') and obj.windowClassName == "DirectUIHWND":
				return False
			_ignore = obj.role
			return True
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
			return False

	def _validateHomeViewSelection(self, paneObj):
		# Previously this scheduled a core.callLater(150, ...) that, once
		# it fired, called setFocus() on a hardcoded
		# pane_ref.firstChild.children[1]. Both halves of that were the
		# root cause of focus "bouncing" back into the Home view: the
		# 150ms delay raced against the user's own next keypress (e.g.
		# pressing Enter then immediately downArrow landed the forced
		# focus call after the user had already moved into a subfolder),
		# and the hardcoded child index pointed at the wrong element the
		# moment Explorer's Home view layout shifted by even one item -
		# which Windows then resolves by throwing focus back to the
		# window's root. Explorer's own UIA events already put focus on
		# the correct element without any help; this is now a passive,
		# synchronous, same-call-stack check with no timer and no forced
		# setFocus(), used only to confirm - for logging/diagnostic
		# purposes - that the Home view already carries a real selection
		# rather than to alter it.
		try:
			homeListView = getattr(paneObj, "firstChild", None)
			if homeListView is None:
				return
			selectionPattern = getattr(homeListView, "UIASelectionPattern", None)
			if selectionPattern is None:
				return
			currentSelection = selectionPattern.GetCurrentSelection()
			if currentSelection is None or currentSelection.Length == 0:
				log.debug("xPlorer: Home view gained focus with no natural selection yet")
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError) as e:
			log.debug(f"xPlorer: Home view selection check failed: {e}")

	def _isForeignDialogOpen(self):
		for win in wx.GetTopLevelWindows():
			if win.IsShown() and isinstance(win, (wx.Dialog, wx.Frame)):
				if win is gui.mainFrame:
					continue
				if win.GetTitle() == "xPlorer - Create Multiple Folders":
					continue
				return True
		return False

	def terminate(self):
		self._speech_dict_task = None
		self._foreground_task = None
		self._explorer_focused = False
		if self._focusSnapshotTask:
			self._focusSnapshotTask.Stop()
			self._focusSnapshotTask = None

		self._syncTempSpeechDictEntry("_temp_entry", False, "- File Explorer", "")
		self._syncTempSpeechDictEntry("_taskSwitchingTempEntry", False, "Task Switching", "")
		self._cached_provider_desc.clear()
		self._landingSelectUntil = 0.0

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		if not obj or not obj.appModule:
			return
		conf = self.getConfig()
		if obj.appModule.appName == "explorer":
			if conf.get("suppressDirectUIAnnounce", True) and obj.role in (Role.LIST, Role.TOOLBAR):
				clsList.insert(0, LaconicFocusAncestor)
			elif obj.role == Role.STATICTEXT and obj.name in ("This folder is empty.", "Working on it..."):
				clsList.insert(0, EmptyFolderStaticText)
				log.debug(f"xPlorer TRACE: empty folder text overlay applied, name={obj.name!r}")
			if obj.role == Role.LISTITEM and isinstance(obj, UIA) and conf.get("announceSingleItem", True):
				clsList.insert(0, SingleItemArrowOverlay)
			if obj.role == Role.LISTITEM and isinstance(obj, UIA) and conf.get("autoSelectFirstItem", True):
				clsList.insert(0, FolderEntryOverlay)

	def _beginSizeContext(self, obj):
		try:
			if obj is None or obj.role != Role.LISTITEM or not isinstance(obj, UIA):
				return None
			if not loadConfig().get("showItemSize", False):
				return None
			fileOps = getattr(self.plugin, "fileOps", None)
			sizeAnnouncer = getattr(fileOps, "itemSizes", None)
			if sizeAnnouncer is None or not self._isFileItem(obj):
				return None
			sizeAnnouncer.beginFocus(obj.name, loadConfig().get("itemSizeScope", "all"))
			return sizeAnnouncer
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError) as e:
			log.debug(f"xPlorer: item size context skipped: {e}")
			return None

	def scheduleSoleItemAnnounce(self, item):
		if self.suppressAllAnnouncements or self._foregroundTransition or self.contextMenuActive:
			return
		pressedAt = time.time()

		def announceIfSole():
			# Explorer raises no focus event when an arrow key has nowhere to
			# go, which is always the case for a lone item. If a focus event
			# did arrive after the keypress, NVDA already spoke the item and
			# speaking it again here would only duplicate it.
			if self._lastItemFocusTime >= pressedAt:
				return
			try:
				if not self._isFileItem(item):
					return
				positionInfo = item.positionInfo
				if not positionInfo or positionInfo.get("similarItemsInGroup") != 1:
					return
				selectionPattern = getattr(item, "UIASelectionItemPattern", None)
				if selectionPattern is not None and not selectionPattern.CurrentIsSelected:
					selectionPattern.Select()
				speech.cancelSpeech()
				sizeAnnouncer = self._beginSizeContext(item)
				try:
					speech.speakObject(item, reason=OutputReason.FOCUS)
				finally:
					if sizeAnnouncer:
						sizeAnnouncer.endFocus()
			except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError) as e:
				log.debug(f"xPlorer: sole item announce skipped: {e}")

		core.callLater(120, announceIfSole)

	def armLandingSelect(self):
		# Enter on an item opens a folder inside the same list control, so
		# Explorer raises no focusEntered for it and only moves focus onto
		# the landing item without selecting it. The next list item that
		# receives focus within this window is the landing item.
		if not self.getConfig().get("autoSelectFirstItem", True):
			return
		self._landingSelectUntil = time.time() + 4.0

	def _selectLandingItem(self, obj):
		if not self._landingSelectUntil:
			return
		if time.time() > self._landingSelectUntil:
			self._landingSelectUntil = 0.0
			return
		if obj.role != Role.LISTITEM or not isinstance(obj, UIA):
			return
		self._landingSelectUntil = 0.0
		if not self.getConfig().get("autoSelectFirstItem", True):
			return
		try:
			selectionPattern = getattr(obj, "UIASelectionItemPattern", None)
			if selectionPattern is None or selectionPattern.CurrentIsSelected:
				return
			selectionPattern.Select()
			log.debug(f"xPlorer: selected landing item after folder entry, name={obj.name!r}")
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError) as e:
			log.debug(f"xPlorer: landing item select skipped: {e}")

	def _perform_auto_select(self, obj):
		conf = self.getConfig()
		if not conf.get("autoSelectFirstItem", True):
			return

		if self.suppressAllAnnouncements or self._foregroundTransition or self.contextMenuActive:
			return

		try:
			if obj.role == Role.LIST and isinstance(obj, UIA) and self._isExplorerList(obj):
				focus_item = obj.objectWithFocus()
				if focus_item is not None and focus_item.role == Role.LISTITEM:
					if hasattr(focus_item, 'UIASelectionItemPattern') and focus_item.UIASelectionItemPattern is not None:
						focus_item.UIASelectionItemPattern.Select()
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
			pass

	def event_gainFocus(self, obj, nextHandler):
		if not getattr(self, "_explorer_focused", False):
			return nextHandler()

		try:
			if obj is not None and obj.role == Role.LISTITEM:
				self._lastItemFocusTime = time.time()
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
			pass

		sizeAnnouncer = None
		if not (self._foregroundTransition or self.contextMenuActive or self.suppressAllAnnouncements):
			sizeAnnouncer = self._beginSizeContext(obj)
		try:
			self._dispatchGainFocus(obj, nextHandler)
		finally:
			if sizeAnnouncer:
				sizeAnnouncer.endFocus()

	def _dispatchGainFocus(self, obj, nextHandler):
		nextHandlerFired = False
		def callNextHandlerOnce():
			nonlocal nextHandlerFired
			if nextHandlerFired:
				return
			nextHandlerFired = True
			nextHandler()

		try:
			if self._foregroundTransition or self.contextMenuActive or self.suppressAllAnnouncements:
				return callNextHandlerOnce()
				
			if obj is None:
				return callNextHandlerOnce()

			targetHwnd = getattr(obj, "windowHandle", None)
			if targetHwnd and not _isExplorerWindowResponsive(targetHwnd):
				return callNextHandlerOnce()

			if eventHandler.isPendingEvents("gainFocus"):
				return callNextHandlerOnce()
				
			if not self._should_process_event(obj):
				return callNextHandlerOnce()
				
			if not self._is_valid_uia_object(obj):
				return callNextHandlerOnce()

			try:
				isHomeViewPane = (
					obj.role == Role.PANE and obj.firstChild
					and hasattr(obj.firstChild, "UIAAutomationId")
					and obj.firstChild.UIAAutomationId == "HomeListView"
				)
			except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
				isHomeViewPane = False

			if isHomeViewPane:
				self._validateHomeViewSelection(obj)

			if not self._isValidExplorerContext(obj):
				return callNextHandlerOnce()

			self._selectLandingItem(obj)
			callNextHandlerOnce()
			
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COMError suppressed in event_gainFocus: {e}")
			callNextHandlerOnce()
		except Exception as e:
			log.debug(f"event_gainFocus failed: {e}")
			callNextHandlerOnce()

	def event_focusEntered(self, obj, nextHandler):
		if not getattr(self, "_explorer_focused", False):
			try:
				return nextHandler()
			except (ComTypesCOMError, CtypesCOMError) as e:
				log.debug(f"xPlorer: nextHandler failed in event_focusEntered: {e}")
				return

		try:
			# Select the first/focused item synchronously, in the same event
			# instead of deferring with core.callLater. A deferred call left
			# a race window where Explorer's own follow-up gainFocus event
			# for that same list (the natural landing on its first item)
			# could arrive before the callback fired, tripping safety
			# guards and silently no-op'ing the whole feature. Acting
			# immediately, inline, removes that window entirely.
			if obj.role == Role.LIST and isinstance(obj, UIA) and self._isExplorerList(obj):
				if not self._isForeignDialogOpen():
					self._perform_auto_select(obj)
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
			pass

		try:
			nextHandler()
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COMError suppressed in event_focusEntered: {e}")
		except Exception as e:
			log.debug(f"Error in event_focusEntered: {e}")

	def event_foreground(self, obj, nextHandler):
		current_time = time.time()
		self._last_foreground_time = current_time
		# Any foreground switch invalidates deferred tasks scheduled for a
		# previous window - guards against a recycled HWND being reused by
		# a brand-new window inside the delay window of a pending callback.
		self._foregroundGeneration += 1
		self._landingSelectUntil = 0.0

		self._explorer_focused = False
		try:
			# Windows 11 hosts the Alt+Tab task-switching UI as a window
			# whose appModule also reports "explorer" (confirmed via
			# log.txt: NVDA's own foreground-resolution warning named hwnd
			# 198220 as windowClassName "XamlExplorerHostIslandWindow"
			# during a plain Alt+Tab between Explorer and a browser).
			# Without this exclusion, every Alt+Tab through the switcher
			# was treated as a real Explorer-focus transition, clearing
			# caches and scheduling a deferred task for a window that was
			# never an actual folder view - the root cause of the
			# constant, needless "Task Switching" processing and the
			# associated lag reported in log.txt.
			if (
				obj
				and getattr(obj, "appModule", None)
				and obj.appModule.appName == "explorer"
				and getattr(obj, "windowClassName", None) != "XamlExplorerHostIslandWindow"
			):
				self._explorer_focused = True
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
			pass

		if self._explorer_focused:
			log.debug(f"xPlorer TRACE: foreground explorer window hwnd={getattr(obj, 'windowHandle', None)}")

			if self._isForeignDialogOpen():
				log.debug("Foreign dialog detected, ignoring Explorer foreground event")
			else:
				if self._focusSnapshotTask:
					self._focusSnapshotTask.Stop()
				snapshotGeneration = self._foregroundGeneration
				self._focusSnapshotTask = core.callLater(
					800, self._checkFocusAfterForeground, snapshotGeneration
				)
				if not self._foregroundTransition:
					self._foregroundTransition = True
					self._cached_provider_desc.clear()
					log.debug("Foreground transition detected, delaying explorer operations")
					
					current_task = object()
					self._foreground_task = current_task
					
					def do_clear():
						if self._foreground_task is not current_task:
							return
						self._clearForegroundTransition()
						
					core.callLater(200, do_clear)
					
			self._update_speech_dict_for_title()
		else:
			self._update_speech_dict_for_title()

		if self.suppressAllAnnouncements:
			try:
				nextHandler()
			except (ComTypesCOMError, CtypesCOMError) as e:
				log.debug(f"xPlorer: nextHandler failed in event_foreground (suppressed): {e}")
			return

		try:
			nextHandler()
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COMError suppressed in event_foreground: {e}")
		except Exception as e:
			log.debug(f"Error in event_foreground: {e}")

	def _checkFocusAfterForeground(self, generation):
		self._focusSnapshotTask = None
		if generation != self._foregroundGeneration:
			return
		try:
			focusObj = api.getFocusObject()
			foregroundHwnd = ctypes.windll.user32.GetForegroundWindow()
			focusHwnd = getattr(focusObj, "windowHandle", None)
			focusClass = focusObj.windowClassName
			responsive = _isExplorerWindowResponsive(foregroundHwnd) if foregroundHwnd else None
			if log.isEnabledFor(logging.DEBUG):
				log.debug(
					f"xPlorer TRACE: focus snapshot foregroundHwnd={foregroundHwnd} focusHwnd={focusHwnd} "
					f"focusRole={focusObj.role} focusClass={focusClass} "
					f"windowResponsive={responsive} explorerFocused={self._explorer_focused}"
				)
			focusStuckOnFrame = bool(focusHwnd) and focusHwnd == foregroundHwnd and focusClass == "CabinetWClass"
			if not (focusStuckOnFrame and responsive and self._explorer_focused):
				return
			if self.contextMenuActive or self.suppressAllAnnouncements or self._isForeignDialogOpen():
				return
			if not loadConfig().get("recoverExplorerFocus", True):
				return
			self._recoverExplorerFocus(foregroundHwnd)
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError, OSError) as e:
			log.debug(f"xPlorer TRACE: focus check failed: {e}")

	def _recoverExplorerFocus(self, frameHwnd):
		itemsViewHwnd = _findItemsViewHwnd(frameHwnd)
		if not itemsViewHwnd:
			log.debug("xPlorer: focus stuck on Explorer frame, but no items view window was found")
			return
		uiaHandler = UIAHandler.handler
		if uiaHandler is None:
			return
		try:
			uiaHandler.clientObject.ElementFromHandle(itemsViewHwnd).SetFocus()
			log.debug(f"xPlorer: moved focus from Explorer frame {frameHwnd} to items view {itemsViewHwnd}")
		except (ComTypesCOMError, CtypesCOMError, AttributeError) as e:
			log.debug(f"xPlorer: could not move focus to items view {itemsViewHwnd}: {e}")

	def _clearForegroundTransition(self):
		self._foregroundTransition = False
		self._foreground_task = None
		if self.plugin:
			self.plugin._invalidatePathCache()
			self.plugin._recordRecentLocationDeferred()