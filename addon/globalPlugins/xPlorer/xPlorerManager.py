# xPlorerManager.py

import ui
import api
from NVDAObjects import NVDAObject
from NVDAObjects.UIA import UIA
from controlTypes import Role
import addonHandler
from logHandler import log
import gui
import wx
import gui.guiHelper
from gui.settingsDialogs import SettingsPanel
from .config import loadConfig, saveConfig
import core
import speechDictHandler
from speechDictHandler import SpeechDictEntry
import time
from comtypes import COMError as ComTypesCOMError
from _ctypes import COMError as CtypesCOMError

addonHandler.initTranslation()

log.debug("xPlorerManager module loaded")

_global_plugin_instance = None

def set_global_plugin(plugin):
	global _global_plugin_instance
	_global_plugin_instance = plugin

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
	def _get_name(self):
		conf = loadConfig()
		if conf.get("announceEmptyFolder", True):
			return _("Empty Folder")
		return super().name

class xPlorerSettingsPanel(SettingsPanel):
	title = _("xPlorer")

	def makeSettings(self, settingsSizer):
		conf = loadConfig()
		sHelper = gui.guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		
		self.autoSelectFirstItem = sHelper.addItem(
			wx.CheckBox(self, label=_("Automatically select the first item"))
		)
		self.autoSelectFirstItem.SetValue(conf["autoSelectFirstItem"])
		
		self.announceEmptyFolder = sHelper.addItem(
			wx.CheckBox(self, label=_("Announce 'Empty Folder' when entering an empty folder"))
		)
		self.announceEmptyFolder.SetValue(conf["announceEmptyFolder"])
		
		self.suppressDirectUIAnnounce = sHelper.addItem(
			wx.CheckBox(self, label=_("Suppress announcement of DirectUIHWND class"))
		)
		self.suppressDirectUIAnnounce.SetValue(conf["suppressDirectUIAnnounce"])
		
		self.sayFileExplorer = sHelper.addItem(
			wx.CheckBox(self, label=_("Suppress announcement of '- File Explorer' in window titles"))
		)
		self.sayFileExplorer.SetValue(conf["sayFileExplorer"])
		
		self.autoPasteClipboardToRename = sHelper.addItem(
			wx.CheckBox(self, label=_("Automatically paste clipboard content into rename field"))
		)
		self.autoPasteClipboardToRename.SetValue(conf.get("autoPasteClipboardToRename", True))

	def onSave(self):
		conf = {
			"autoSelectFirstItem": self.autoSelectFirstItem.GetValue(),
			"announceEmptyFolder": self.announceEmptyFolder.GetValue(),
			"suppressDirectUIAnnounce": self.suppressDirectUIAnnounce.GetValue(),
			"sayFileExplorer": self.sayFileExplorer.GetValue(),
			"autoPasteClipboardToRename": self.autoPasteClipboardToRename.GetValue(),
		}
		saveConfig(conf)
		if _global_plugin_instance and hasattr(_global_plugin_instance, 'manager'):
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
		self._explorer_focused = False
		
		self._last_processed_obj = None
		self._last_processed_time = 0
		self._debounce_interval = 0.05
		
		self._cached_provider_desc = {}
		self._cache_timeout = 0.5
		self._max_cache_size = 20
		
		self._foregroundTransition = False
		self._foregroundTransitionTimer = None
		self._last_foreground_time = 0
		self._last_sayFileExplorer_setting = None
		
		self._update_speech_dict_for_title()

	def getConfig(self):
		return loadConfig()

	def _update_speech_dict_for_title(self):
		conf = self.getConfig()
		should_suppress = conf.get("sayFileExplorer", True)
		
		if should_suppress and self._temp_entry is None:
			entry = SpeechDictEntry(
				pattern="- File Explorer",
				replacement="",
				caseSensitive=True,
				type=0,
				comment="xPlorer: suppress '- File Explorer'"
			)
			speechDictHandler.dictionaries["temp"].append(entry)
			self._temp_entry = entry
			log.debug("Added speech dict entry to suppress '- File Explorer'")
		elif not should_suppress and self._temp_entry is not None:
			try:
				speechDictHandler.dictionaries["temp"].remove(self._temp_entry)
			except ValueError:
				pass
			self._temp_entry = None
			log.debug("Removed speech dict entry for '- File Explorer'")
		
		self._last_sayFileExplorer_setting = should_suppress

	def _should_process_event(self, obj):
		if not obj:
			return False
		current_time = time.time()
		try:
			obj_id = (obj.windowHandle, obj.role, id(obj))
		except:
			obj_id = id(obj)
		if obj_id == self._last_processed_obj:
			if current_time - self._last_processed_time < self._debounce_interval:
				return False
		self._last_processed_obj = obj_id
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
		except:
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

	def _add_temp_entry(self):
		if self._temp_entry is None:
			entry = SpeechDictEntry(
				pattern="- File Explorer",
				replacement="",
				caseSensitive=True,
				type=0,
				comment="xPlorer: suppress '- File Explorer'"
			)
			speechDictHandler.dictionaries["temp"].append(entry)
			self._temp_entry = entry

	def _remove_temp_entry(self):
		if self._temp_entry is not None:
			try:
				speechDictHandler.dictionaries["temp"].remove(self._temp_entry)
			except ValueError:
				pass
			self._temp_entry = None

	def terminate(self):
		self._remove_temp_entry()
		self._cached_provider_desc.clear()
		if self._foregroundTransitionTimer:
			self._foregroundTransitionTimer.cancel()
			self._foregroundTransitionTimer = None

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		if not obj or not obj.appModule:
			return
		conf = self.getConfig()
		if obj.appModule.appName == "explorer":
			if conf.get("suppressDirectUIAnnounce", True) and obj.role in (Role.LIST, Role.TOOLBAR):
				clsList.insert(0, LaconicFocusAncestor)
			elif obj.role == Role.STATICTEXT and obj.name == "This folder is empty.":
				clsList.insert(0, EmptyFolderStaticText)

	def event_gainFocus(self, obj, nextHandler):
		try:
			if self._foregroundTransition:
				nextHandler()
				return
			if obj is None or obj.appModule is None:
				nextHandler()
				return
			if not self._should_process_event(obj):
				nextHandler()
				return
			if not self._is_valid_uia_object(obj):
				nextHandler()
				return
			
			appName = obj.appModule.appName
			conf = self.getConfig()
			should_suppress = conf.get("sayFileExplorer", True)
			if should_suppress != self._last_sayFileExplorer_setting:
				self._update_speech_dict_for_title()
			
			if appName == "explorer":
				if not self._explorer_focused:
					self._explorer_focused = True
					if should_suppress and self._temp_entry is None:
						self._add_temp_entry()
					elif not should_suppress and self._temp_entry is not None:
						self._remove_temp_entry()
			else:
				if self._explorer_focused:
					self._explorer_focused = False
					self._remove_temp_entry()
			
			if self.suppressAnnouncements or self.contextMenuActive or self.suppressAllAnnouncements:
				nextHandler()
				return
			
			if not self._isValidExplorerContext(obj):
				nextHandler()
				return
			
			if obj.role == Role.PANE and obj.firstChild and hasattr(obj.firstChild, "UIAAutomationId"):
				if obj.firstChild.UIAAutomationId == "HomeListView":
					def set_focus():
						try:
							if obj.firstChild and obj.firstChild.children and len(obj.firstChild.children) > 1:
								obj.firstChild.children[1].setFocus()
						except:
							pass
					core.callLater(200, set_focus)
			nextHandler()
		except Exception as e:
			log.error(f"event_gainFocus failed: {e}")
			nextHandler()

	def _getFolderPath(self, listObj):
		try:
			parent = listObj
			while parent and parent.role != Role.WINDOW:
				parent = parent.parent
			if parent and parent.role == Role.WINDOW:
				return parent.name
		except:
			pass
		return None

	def event_focusEntered(self, obj, nextHandler):
		if not self._foregroundTransition:
			conf = self.getConfig()
			if conf.get("autoSelectFirstItem", True):
				if self._isExplorerList(obj):
					focus = obj.objectWithFocus()
					if focus is not None and focus.role == Role.LISTITEM:
						try:
							if hasattr(focus, 'UIASelectionItemPattern') and focus.UIASelectionItemPattern is not None:
								focus.UIASelectionItemPattern.Select()
								api.setNavigatorObject(focus)
						except Exception as e:
							log.debug(f"Auto-select failed: {e}")
		nextHandler()

	def event_foreground(self, obj, nextHandler):
		current_time = time.time()
		self._last_foreground_time = current_time
		if obj and obj.appModule and obj.appModule.appName == "explorer":
			if not self._foregroundTransition:
				self._foregroundTransition = True
				self._cached_provider_desc.clear()
				log.debug("Foreground transition detected, delaying explorer operations")
				if self._foregroundTransitionTimer:
					self._foregroundTransitionTimer.cancel()
				self._foregroundTransitionTimer = core.callLater(250, self._clearForegroundTransition)
			conf = self.getConfig()
			should_suppress = conf.get("sayFileExplorer", True)
			if should_suppress != self._last_sayFileExplorer_setting:
				core.callLater(100, self._update_speech_dict_for_title)
			elif should_suppress and self._temp_entry is None:
				core.callLater(100, self._add_temp_entry)
		else:
			if self._explorer_focused:
				self._explorer_focused = False
				self._remove_temp_entry()
		if self.suppressAllAnnouncements:
			nextHandler()
			return
		nextHandler()
	
	def _clearForegroundTransition(self):
		self._foregroundTransition = False
		self._foregroundTransitionTimer = None
		log.debug("Foreground transition cleared, explorer operations resumed")

	def event_UIA_elementSelected(self, obj, nextHandler):
		nextHandler()

	def event_selection(self, obj, nextHandler):
		nextHandler()