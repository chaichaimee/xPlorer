# xPlorerManager.py
# Copyright (C) 2026 Chai Chaimee
# Licensed under GNU General Public License. See COPYING.txt for details.

import ui
import api
from NVDAObjects import NVDAObject
from NVDAObjects.UIA import UIA
from controlTypes import Role, State
import addonHandler
from logHandler import log
import gui
import wx
import gui.guiHelper
from gui.settingsDialogs import SettingsPanel
from .folderTools import loadConfig, saveConfig
import core
import speechDictHandler
from speechDictHandler import SpeechDictEntry
import time
import eventHandler
from comtypes import COMError as ComTypesCOMError
from _ctypes import COMError as CtypesCOMError

addonHandler.initTranslation()
log.debug("xPlorerManager module loaded")

_global_plugin_instance = None

def set_global_plugin(plugin):
	global _global_plugin_instance
	_global_plugin_instance = plugin

# ----------------------------------------------------------------------
# Overlay classes
# ----------------------------------------------------------------------
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
			return "Empty Folder"
		return super().name

# ----------------------------------------------------------------------
# Settings panel
# ----------------------------------------------------------------------
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
		self.sayFileExplorer = sHelper.addItem(wx.CheckBox(self, label="Suppress announcement of '- File Explorer' in window titles"))
		self.sayFileExplorer.SetValue(conf["sayFileExplorer"])
		self.autoPasteClipboardToRename = sHelper.addItem(wx.CheckBox(self, label="Automatically paste clipboard content into rename field"))
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
			_global_plugin_instance.manager._invalidateConfigCache()
			_global_plugin_instance.manager._update_speech_dict_for_title()

# ----------------------------------------------------------------------
# ExplorerManager
# ----------------------------------------------------------------------
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

		self._last_processed_key = None
		self._last_processed_time = 0
		self._debounce_interval = 0.05

		self._cached_provider_desc = {}
		self._cache_timeout = 0.5
		self._max_cache_size = 20

		self._foregroundTransition = False
		self._foreground_task = None
		self._last_foreground_time = 0
		self._last_sayFileExplorer_setting = None

		self._speech_dict_task = None
		self._homeview_focus_task = None   # store handle of scheduled set_focus

		# getConfig() runs on essentially every object that gains focus in
		# Explorer (chooseNVDAObjectOverlayClasses, _perform_auto_select),
		# but loadConfig() is a disk read - on a slow/portable/removable
		# drive that adds up fast. A short TTL cache avoids re-reading the
		# same unchanged file dozens of times a second during normal
		# navigation, without noticeably delaying a real settings change.
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

	def _update_speech_dict_for_title(self):
		current_task = object()
		self._speech_dict_task = current_task

		def do_update():
			if self._speech_dict_task is not current_task:
				return
			self._speech_dict_task = None

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

		core.callLater(100, do_update)

	def _should_process_event(self, obj):
		if not obj:
			return False
		current_time = time.time()
		try:
			obj_key = (obj.windowHandle, obj.role, id(obj))
		except Exception:
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

	def _cancelHomeViewFocusTask(self):
		if self._homeview_focus_task:
			self._homeview_focus_task.Stop()
			self._homeview_focus_task = None

	def _scheduleHomeViewFocus(self, paneObj):
		"""Explorer's Home view sometimes needs a nudge into its second child
		shortly after gaining focus. The correction is scheduled 200ms out,
		so it must re-validate everything at fire time rather than trusting
		what was true when it was scheduled."""
		self._cancelHomeViewFocusTask()
		expected_hwnd = getattr(paneObj, "windowHandle", None)
		pane_ref = paneObj

		def set_focus():
			if self._isForeignDialogOpen():
				return
			try:
				fg = api.getForegroundObject()
				if not fg or not fg.appModule or fg.appModule.appName != "explorer":
					return
				if expected_hwnd is not None and getattr(fg, "windowHandle", None) != expected_hwnd:
					return
				# hwnd alone is not enough proof: on a tabbed Explorer window
				# the hwnd stays identical across tabs, so a tab switch away
				# from Home in the last 200ms would otherwise slip past the
				# check above undetected. Re-check the LIVE focus target.
				liveFocus = api.getFocusObject()
				if not liveFocus or liveFocus.appModule is None or liveFocus.appModule.appName != "explorer":
					return
				stillOnHomeView = False
				probe = liveFocus
				for _ in range(4):
					if probe is None:
						break
					if getattr(probe, "UIAAutomationId", None) == "HomeListView":
						stillOnHomeView = True
						break
					probe = getattr(probe, "parent", None)
				if not stillOnHomeView:
					return
				if pane_ref.firstChild and pane_ref.firstChild.children and len(pane_ref.firstChild.children) > 1:
					pane_ref.firstChild.children[1].setFocus()
			except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
				pass

		self._homeview_focus_task = core.callLater(200, set_focus)

	# ------------------------------------------------------------------
	# Detect if any foreign dialog or frame is currently open.
	# Excludes NVDA's main window and xPlorer's own folder creation dialog.
	# ------------------------------------------------------------------
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
		self._cancelHomeViewFocusTask()

		if self._temp_entry is not None:
			try:
				speechDictHandler.dictionaries["temp"].remove(self._temp_entry)
			except ValueError:
				pass
			self._temp_entry = None
		self._cached_provider_desc.clear()

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		if not obj or not obj.appModule:
			return
		conf = self.getConfig()
		if obj.appModule.appName == "explorer":
			if conf.get("suppressDirectUIAnnounce", True) and obj.role in (Role.LIST, Role.TOOLBAR):
				clsList.insert(0, LaconicFocusAncestor)
			elif obj.role == Role.STATICTEXT and obj.name == "This folder is empty.":
				clsList.insert(0, EmptyFolderStaticText)

	def _perform_auto_select(self, obj):
		conf = self.getConfig()
		if not conf.get("autoSelectFirstItem", True):
			return

		if self.suppressAllAnnouncements or self._foregroundTransition or self.contextMenuActive:
			return

		try:
			if not obj or not obj.appModule or obj.appModule.appName != "explorer":
				return
			
			if obj.role == Role.LIST and isinstance(obj, UIA) and self._isExplorerList(obj):
				focus_item = obj.objectWithFocus()
				if focus_item is not None and focus_item.role == Role.LISTITEM:
					if hasattr(focus_item, 'UIASelectionItemPattern') and focus_item.UIASelectionItemPattern is not None:
						focus_item.UIASelectionItemPattern.Select()
						
			elif obj.role == Role.LISTITEM and isinstance(obj, UIA):
				parent = obj.parent
				if parent and parent.role == Role.LIST and self._isExplorerList(parent):
					if hasattr(obj, 'UIASelectionItemPattern') and obj.UIASelectionItemPattern is not None:
						obj.UIASelectionItemPattern.Select()
						
		except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
			pass

	def event_gainFocus(self, obj, nextHandler):
		# No longer block the whole event; let other add-ons process normally
		try:
			if self._foregroundTransition or self.contextMenuActive or self.suppressAllAnnouncements:
				nextHandler()
				return
			if obj is None or obj.appModule is None:
				nextHandler()
				return
			if eventHandler.isPendingEvents("gainFocus"):
				nextHandler()
				return
			if not self._should_process_event(obj):
				nextHandler()
				return
			if not self._is_valid_uia_object(obj):
				nextHandler()
				return

			appName = obj.appModule.appName
			if appName == "explorer":
				if not self._explorer_focused:
					self._explorer_focused = True
					self._update_speech_dict_for_title()
			else:
				if self._explorer_focused:
					self._explorer_focused = False
					self._update_speech_dict_for_title()

			# NOTE: this check must run BEFORE _isValidExplorerContext below.
			# The Home view's outer container reports Role.PANE, which
			# _isValidExplorerContext (LIST/LISTITEM only) always rejects -
			# previously this whole block sat after that check and could
			# never execute at all.
			if appName == "explorer":
				try:
					if (obj.role == Role.PANE and obj.firstChild
							and hasattr(obj.firstChild, "UIAAutomationId")):
						if obj.firstChild.UIAAutomationId == "HomeListView":
							self._scheduleHomeViewFocus(obj)
						else:
							self._cancelHomeViewFocusTask()
				except (ComTypesCOMError, CtypesCOMError, AttributeError, RuntimeError):
					pass

			if not self._isValidExplorerContext(obj):
				nextHandler()
				return

			# A real file/list focus event (e.g. focus landing directly on a
			# LIST/LISTITEM in a different tab, with no intervening PANE
			# gainFocus) also means any pending Home-view correction from a
			# moment ago is stale and must not fire later.
			self._cancelHomeViewFocusTask()

			nextHandler()
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COMError suppressed in event_gainFocus: {e}")
		except Exception as e:
			log.debug(f"event_gainFocus failed: {e}")

	def event_focusEntered(self, obj, nextHandler):
		# Protect only auto-select; do not block the entire event
		if obj.role == Role.LIST and isinstance(obj, UIA) and self._isExplorerList(obj):
			if not self._isForeignDialogOpen():
				self._perform_auto_select(obj)
		try:
			nextHandler()
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COMError suppressed in event_focusEntered: {e}")
		except Exception as e:
			log.debug(f"Error in event_focusEntered: {e}")

	def event_foreground(self, obj, nextHandler):
		current_time = time.time()
		self._last_foreground_time = current_time

		if obj and obj.appModule and obj.appModule.appName == "explorer":
			# If a foreign dialog is open, immediately cancel any pending set_focus task
			if self._isForeignDialogOpen():
				self._cancelHomeViewFocusTask()
				log.debug("Foreign dialog detected, ignoring Explorer foreground event")
				return

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
					
				core.callLater(250, do_clear)
				
			self._update_speech_dict_for_title()
		else:
			if self._explorer_focused:
				self._explorer_focused = False
				self._update_speech_dict_for_title()

		if self.suppressAllAnnouncements:
			try:
				nextHandler()
			except Exception:
				pass
			return

		try:
			nextHandler()
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COMError suppressed in event_foreground: {e}")
		except Exception as e:
			log.debug(f"Error in event_foreground: {e}")

	def _clearForegroundTransition(self):
		self._foregroundTransition = False
		self._foreground_task = None
		if self.plugin:
			self.plugin._invalidatePathCache()
		log.debug("Foreground transition cleared, explorer operations resumed")

	def event_UIA_elementSelected(self, obj, nextHandler):
		try:
			nextHandler()
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COMError suppressed in event_UIA_elementSelected: {e}")
		except Exception as e:
			log.debug(f"Error in event_UIA_elementSelected: {e}")

	def event_selection(self, obj, nextHandler):
		try:
			nextHandler()
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COMError suppressed in event_selection: {e}")
		except Exception as e:
			log.debug(f"Error in event_selection: {e}")