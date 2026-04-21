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
import speech

addonHandler.initTranslation()

log.debug("xPlorerManager module loaded")

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

	def onSave(self):
		conf = {
			"autoSelectFirstItem": self.autoSelectFirstItem.GetValue(),
			"announceEmptyFolder": self.announceEmptyFolder.GetValue(),
			"suppressDirectUIAnnounce": self.suppressDirectUIAnnounce.GetValue(),
			"sayFileExplorer": self.sayFileExplorer.GetValue(),
		}
		saveConfig(conf)

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

	def getConfig(self):
		return loadConfig()

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

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		conf = self.getConfig()
		if obj.appModule.appName == "explorer":
			if conf.get("suppressDirectUIAnnounce", True) and obj.role in (Role.LIST, Role.TOOLBAR):
				clsList.insert(0, LaconicFocusAncestor)
			elif obj.role == Role.STATICTEXT and obj.name == "This folder is empty.":
				clsList.insert(0, EmptyFolderStaticText)

	def event_gainFocus(self, obj, nextHandler):
		if not self._should_process_event(obj):
			nextHandler()
			return
		
		appName = obj.appModule.appName if obj and obj.appModule else ""
		conf = self.getConfig()
		should_suppress = conf.get("sayFileExplorer", True)
		
		if appName == "explorer":
			if not self._explorer_focused:
				self._explorer_focused = True
				if should_suppress:
					self._add_temp_entry()
				else:
					self._remove_temp_entry()
			else:
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
		
		# Do NOT speak here. Let NVDA handle default speech for list items.
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
		if not self._should_process_event(obj):
			nextHandler()
			return
		
		if self.suppressAnnouncements or self.contextMenuActive or self.suppressAllAnnouncements:
			nextHandler()
			return
		
		if not self._isValidExplorerContext(obj):
			nextHandler()
			return
		
		conf = self.getConfig()
		
		if self._isExplorerList(obj):
			self.currentFolderPath = self._getFolderPath(obj)
			
			if conf.get("autoSelectFirstItem", True) and obj.childCount > 0:
				focus = obj.objectWithFocus()
				if focus is not None and focus.role == Role.LISTITEM and hasattr(focus, 'UIASelectionItemPattern'):
					try:
						focus.UIASelectionItemPattern.Select()
						api.setNavigatorObject(focus)
						# NVDA will speak automatically when focus moves, so no extra ui.message here.
					except:
						pass
				else:
					firstChild = obj.firstChild
					if firstChild and hasattr(firstChild, 'UIASelectionItemPattern'):
						try:
							firstChild.UIASelectionItemPattern.Select()
							api.setNavigatorObject(firstChild)
						except:
							pass
		
		nextHandler()

	def event_foreground(self, obj, nextHandler):
		if obj and obj.appModule and obj.appModule.appName != "explorer":
			if self._explorer_focused:
				self._explorer_focused = False
				self._remove_temp_entry()
		
		if self.suppressAllAnnouncements:
			nextHandler()
			return
		
		nextHandler()

	def event_UIA_elementSelected(self, obj, nextHandler):
		if self.suppressAllAnnouncements:
			nextHandler()
			return
		
		nextHandler()