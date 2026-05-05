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
import urllib.parse

# COM imports
import comtypes.client
from comtypes import COMError as ComTypesCOMError
from _ctypes import COMError as CtypesCOMError

addonHandler.initTranslation()
log.debug("xPlorer: Initializing add-on")

# Import submodules
try:
	from .xPlorerManager import xPlorerSettingsPanel, ExplorerManager
	log.debug("xPlorer: xPlorerManager imported")
except Exception as e:
	log.exception("Failed to import xPlorerManager")
	raise

try:
	from .fileOperations import FileOperations
	log.debug("xPlorer: fileOperations imported")
except Exception as e:
	log.exception("Failed to import fileOperations")
	raise

try:
	from .compressionManager import CompressionManager
	log.debug("xPlorer: compressionManager imported")
except Exception as e:
	log.exception("Failed to import compressionManager")
	raise

try:
	from .clipboardManager import ClipboardManager
	log.debug("xPlorer: clipboardManager imported")
except Exception as e:
	log.exception("Failed to import clipboardManager")
	raise

try:
	from .selectionManager import SelectionManager
	log.debug("xPlorer: selectionManager imported")
except Exception as e:
	log.exception("Failed to import selectionManager")
	raise

try:
	from .robocopyManager import RobocopyManager
	log.debug("xPlorer: robocopyManager imported")
except Exception as e:
	log.exception("Failed to import robocopyManager")
	raise

try:
	from .txt2folder import TxtToFolder
	log.debug("xPlorer: txt2folder imported")
except Exception as e:
	log.exception("Failed to import txt2folder")
	raise

try:
	from .createFile import CreateFileManager
	log.debug("xPlorer: createFile imported")
except Exception as e:
	log.exception("Failed to import createFile")
	raise

try:
	from .contextMenu import ContextMenuManager
	log.debug("xPlorer: contextMenu imported")
except Exception as e:
	log.exception("Failed to import contextMenu")
	raise

try:
	from .folderInfo import FolderInfoManager
	log.debug("xPlorer: folderInfo imported")
except Exception as e:
	log.exception("Failed to import folderInfo")
	raise

try:
	from .case import CaseConverter
	log.debug("xPlorer: case imported")
except Exception as e:
	log.exception("Failed to import case")
	raise

try:
	from .folder_creation_dialog import FolderCreationDialog
	log.debug("xPlorer: folder_creation_dialog imported")
except Exception as e:
	log.exception("Failed to import folder_creation_dialog")
	raise

try:
	from .folder_creator import type_clipboard_into_rename_if_suitable
	log.debug("xPlorer: folder_creator imported")
except Exception as e:
	log.exception("Failed to import folder_creator")
	raise

log.debug("xPlorer: All modules imported successfully")

# Global tap counters
_last_tap_time_compress = 0
_tap_count_compress = 0
_compress_timer = None

_last_tap_time_copy = 0
_tap_count_copy = 0
_copy_timer = None

_last_tap_time_invert = 0
_tap_count_invert = 0
_invert_timer = None

_double_tap_threshold = 0.5

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = _("xPlorer")
	
	def __init__(self):
		log.debug("xPlorer GlobalPlugin.__init__ starting")
		try:
			super().__init__()
			# Create COM objects once
			self.objShellApp = comtypes.client.CreateObject("Shell.Application")
			self.objFSO = comtypes.client.CreateObject("scripting.FileSystemObject")
			
			# Register settings panel
			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(xPlorerSettingsPanel)
			
			# Initialize managers
			self.manager = ExplorerManager(self)
			self.fileOps = FileOperations(self)
			self.compression = CompressionManager(self)
			self.clipboard = ClipboardManager(self)
			self.selection = SelectionManager(self)
			self.robocopy = RobocopyManager(self)
			self.txt2folder = TxtToFolder(self)
			self.createFileManager = CreateFileManager(self)
			self.contextMenuManager = ContextMenuManager(self)
			self.folderInfo = FolderInfoManager(self)
			self.caseConverter = CaseConverter()
			
			# Caching for Explorer windows
			self._last_window = None
			self._last_window_hwnd = None
			self._last_window_time = 0
			self._last_path = None
			
			self._cached_explorer_hwnd = None
			self._cached_explorer_time = 0
			self._cache_valid_duration = 1.0
			
			self._striprtf_available = None
			tools_dir = os.path.join(os.path.dirname(__file__), "tools")
			if os.path.exists(tools_dir) and tools_dir not in sys.path:
				sys.path.insert(0, tools_dir)
			
			log.debug("xPlorer GlobalPlugin initialized successfully")
		except Exception as e:
			log.exception("Error in xPlorer GlobalPlugin.__init__")
			raise

	def terminate(self):
		log.debug("xPlorer GlobalPlugin.terminate starting")
		try:
			super().terminate()
			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(xPlorerSettingsPanel)
			self.fileOps.cleanup()
			self.compression.cleanup()
			self.selection.cleanup()
			self.robocopy.cleanup()
			self.createFileManager.cleanup()
			self.folderInfo.cleanup()
			self.manager.terminate()
			self._cancelAllTimers()
			log.debug("xPlorer GlobalPlugin terminated successfully")
		except Exception as e:
			log.exception("Error in xPlorer GlobalPlugin.terminate")

	def _cancelAllTimers(self):
		global _compress_timer, _copy_timer, _invert_timer
		
		if _compress_timer:
			_compress_timer.Stop()
			_compress_timer = None
		
		if _copy_timer:
			_copy_timer.Stop()
			_copy_timer = None
			
		if _invert_timer:
			_invert_timer.Stop()
			_invert_timer = None

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

	def _getCurrentPathDeferred(self, callback, delay=200):
		core.callLater(delay, lambda: callback(self._getCurrentPathFromExplorer()))

	def _getSelectedItemsDeferred(self, callback, delay=200):
		core.callLater(delay, lambda: callback(self._getSelectedItems()))

	def _getCurrentPathFromExplorer(self):
		if self.manager._foregroundTransition:
			log.debug("Foreground transition active, skipping path retrieval")
			return None
		try:
			fg = api.getForegroundObject()
			if not fg or not fg.appModule or fg.appModule.appName != "explorer":
				return None

			if hasattr(fg, 'windowClassName'):
				winClass = fg.windowClassName
				if winClass == "CabinetWClass" and self.manager._last_foreground_time > 0:
					if time.time() - self.manager._last_foreground_time < 0.5:
						log.debug("CabinetWClass detected during transition, deferring")
						return None

			target_hwnd = fg.windowHandle
			if not winUser.isWindow(target_hwnd):
				return None

			current_time = time.time()
			if (self._cached_explorer_hwnd == target_hwnd and 
				current_time - self._cached_explorer_time < self._cache_valid_duration):
				if self._last_window and winUser.isWindow(self._last_window_hwnd):
					try:
						if hasattr(self._last_window, "Document") and self._last_window.Document:
							folder = self._last_window.Document.Folder
							if folder and hasattr(folder, "Self"):
								path = folder.Self.Path
								if path and os.path.isdir(path):
									return os.path.normpath(path)
					except (ComTypesCOMError, CtypesCOMError, AttributeError):
						pass

			shell = self.objShellApp
			if not shell:
				return None

			path_result = [None]

			def enum_windows():
				try:
					for window in shell.Windows():
						try:
							if not window or window.hwnd != target_hwnd:
								continue

							if hasattr(window, "Document") and window.Document:
								folder = window.Document.Folder
								if folder and hasattr(folder, "Self"):
									path = folder.Self.Path
									if path and os.path.isdir(path):
										self._last_window = window
										self._last_window_hwnd = window.hwnd
										self._last_window_time = current_time
										self._cached_explorer_hwnd = target_hwnd
										self._cached_explorer_time = current_time
										path_result[0] = os.path.normpath(path)
										return

							if hasattr(window, "LocationURL") and window.LocationURL:
								url = window.LocationURL
								if url.startswith("file:///"):
									try:
										path = urllib.parse.unquote(url[8:])
									except Exception:
										path = url[8:]
									path = path.replace("/", "\\")
									if os.path.isdir(path):
										self._last_window = window
										self._last_window_hwnd = window.hwnd
										self._last_window_time = current_time
										self._cached_explorer_hwnd = target_hwnd
										self._cached_explorer_time = current_time
										path_result[0] = os.path.normpath(path)
										return

							if hasattr(window, "LocationName") and window.LocationName:
								possible_path = window.LocationName
								if os.path.isabs(possible_path) and os.path.isdir(possible_path):
									self._last_window = window
									self._last_window_hwnd = window.hwnd
									self._last_window_time = current_time
									self._cached_explorer_hwnd = target_hwnd
									self._cached_explorer_time = current_time
									path_result[0] = os.path.normpath(possible_path)
									return
						except (ComTypesCOMError, CtypesCOMError, AttributeError):
							continue
				except (ComTypesCOMError, CtypesCOMError):
					pass

				if path_result[0] is None:
					try:
						focus = api.getFocusObject()
						if focus and focus.appModule and focus.appModule.appName == "explorer":
							focus_hwnd = focus.windowHandle
							for window in shell.Windows():
								try:
									if not window or window.hwnd != focus_hwnd:
										continue
									if hasattr(window, "Document") and window.Document:
										folder = window.Document.Folder
										if folder and hasattr(folder, "Self"):
											path = folder.Self.Path
											if path and os.path.isdir(path):
												self._last_window = window
												self._last_window_hwnd = window.hwnd
												self._last_window_time = current_time
												self._cached_explorer_hwnd = focus_hwnd
												self._cached_explorer_time = current_time
												path_result[0] = os.path.normpath(path)
												return
								except (ComTypesCOMError, CtypesCOMError, AttributeError):
									continue
					except (ComTypesCOMError, CtypesCOMError):
						pass

			enum_windows()

			if path_result[0] is not None:
				return path_result[0]

			if (self._last_window and self._last_window_hwnd and 
				current_time - self._last_window_time < 2.0):
				if winUser.isWindow(self._last_window_hwnd):
					try:
						if hasattr(self._last_window, "Document") and self._last_window.Document:
							folder = self._last_window.Document.Folder
							if folder and hasattr(folder, "Self"):
								path = folder.Self.Path
								if path and os.path.isdir(path):
									return os.path.normpath(path)
					except (ComTypesCOMError, CtypesCOMError, AttributeError):
						pass

		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COM error in _getCurrentPathFromExplorer: {e}")
		except Exception as e:
			log.error(f"Error in _getCurrentPathFromExplorer: {e}")
		
		return None

	def _getActiveExplorerWindow(self):
		if self.manager._foregroundTransition:
			log.debug("Foreground transition active, skipping window retrieval")
			return None
		try:
			current_time = time.time()
			
			if (self._last_window and self._last_window_hwnd and 
				current_time - self._last_window_time < 1.0):
				if winUser.isWindow(self._last_window_hwnd):
					return self._last_window
			
			fg = api.getForegroundObject()
			if not fg or not fg.appModule or fg.appModule.appName != "explorer":
				return None

			if hasattr(fg, 'windowClassName'):
				winClass = fg.windowClassName
				if winClass == "CabinetWClass" and self.manager._last_foreground_time > 0:
					if time.time() - self.manager._last_foreground_time < 0.5:
						log.debug("CabinetWClass during transition, skipping window")
						return None

			target_hwnd = fg.windowHandle

			shell = self.objShellApp
			if not shell:
				return None

			for window in shell.Windows():
				try:
					if not window or window.hwnd != target_hwnd:
						continue

					if hasattr(window, "Document") and window.Document:
						self._last_window = window
						self._last_window_hwnd = window.hwnd
						self._last_window_time = current_time
						return window
				except (ComTypesCOMError, CtypesCOMError, AttributeError):
					continue

			focus = api.getFocusObject()
			if focus and focus.appModule and focus.appModule.appName == "explorer":
				focus_hwnd = focus.windowHandle
				for window in shell.Windows():
					try:
						if not window or window.hwnd != focus_hwnd:
							continue
						if hasattr(window, "Document") and window.Document:
							self._last_window = window
							self._last_window_hwnd = window.hwnd
							self._last_window_time = current_time
							return window
					except (ComTypesCOMError, CtypesCOMError, AttributeError):
						continue

			for window in shell.Windows():
				try:
					if window and window.Visible and window.Name == "File Explorer":
						if hasattr(window, "Document") and window.Document:
							self._last_window = window
							self._last_window_hwnd = window.hwnd
							self._last_window_time = current_time
							return window
				except (ComTypesCOMError, CtypesCOMError, AttributeError):
					continue

			return None
			
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COM error in _getActiveExplorerWindow: {e}")
			return None
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
					log.debug("Switched to new Explorer document/tab")
			except (ComTypesCOMError, CtypesCOMError, AttributeError):
				return None, None
				
			selectedItems = []
			try:
				if hasattr(document, 'SelectedItems'):
					selectedItemsCount = document.SelectedItems().Count
					for i in range(selectedItemsCount):
						item = document.SelectedItems().Item(i)
						selectedItems.append((item.Name, item.Path))
			except (ComTypesCOMError, CtypesCOMError, AttributeError):
				pass
				
			return selectedItems if selectedItems else None, shellWindow
			
		except (ComTypesCOMError, CtypesCOMError) as e:
			log.debug(f"COM error in _getSelectedItems: {e}")
			return None, None
		except Exception as e:
			log.debug(f"Error in _getSelectedItems: {e}")
			return None, None

	def _executeWithSilence(self, func):
		import speech
		speech.cancelSpeech()
		self.manager.suppressAllAnnouncements = True
		try:
			func()
		finally:
			core.callLater(1000, lambda: setattr(self.manager, 'suppressAllAnnouncements', False))

	def _copyAddressBar(self):
		def do_copy(path):
			if path:
				if wx.TheClipboard.Open():
					wx.TheClipboard.SetData(wx.TextDataObject(path))
					wx.TheClipboard.Close()
					ui.message(_("Copied: {path}").format(path=path))
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

	# -------------------------------------------------------------------------
	# Scripts with double-tap support (using wx.CallLater for timers)
	# -------------------------------------------------------------------------
	def script_copySelectedNamesOrAddressBar(self, gesture):
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
			_copy_timer = wx.CallLater(int(_double_tap_threshold * 1000), self._processCopyTap)
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
			_invert_timer = wx.CallLater(int(_double_tap_threshold * 1000), self._processInvertTap)
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
			_compress_timer = wx.CallLater(int(_double_tap_threshold * 1000), self._processCompressTap)
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

	def script_openXPlorerContextMenu(self, gesture):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return
		self._showContextMenu()

	script_openXPlorerContextMenu.__doc__ = _("Open xPlorer context menu")
	script_openXPlorerContextMenu.category = _("xPlorer")
	script_openXPlorerContextMenu.gestures = ["kb(desktop):NVDA+shift+x"]

	def _renameFile(self):
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
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			self._handleNonExplorerGesture(gesture)
			return

		gesture.send()

		from .config import loadConfig
		conf = loadConfig()
		if conf.get("autoPasteClipboardToRename", True):
			core.callLater(600, type_clipboard_into_rename_if_suitable)

	script_createFolderWithAutoPaste.__doc__ = _("Create new folder and paste clipboard content into rename field")
	script_createFolderWithAutoPaste.category = _("xPlorer")
	script_createFolderWithAutoPaste.gestures = ["kb(desktop):control+shift+n"]

	def _openSettings(self):
		try:
			wx.CallAfter(self._showSettingsDialog)
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
		self.contextMenuManager.showContextMenu()

	def _createMultipleFolders(self):
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
			wx.CallAfter(show_dialog)
		self._getCurrentPathDeferred(do_create, 200)

	def _convertFolderNames(self, conversion_type):
		def do_convert(selected_data):
			selected_items, shell_window = selected_data
			folders_to_convert = []
			if selected_items:
				for name, path in selected_items:
					if os.path.isdir(path):
						folders_to_convert.append(path)
			if not folders_to_convert:
				def get_path_callback(path):
					if path and os.path.isdir(path):
						folders_to_convert = [path]
					else:
						ui.message(_("No folders selected or current folder not available"))
						return
					self._perform_conversion(conversion_type, folders_to_convert)
				self._getCurrentPathDeferred(get_path_callback, 200)
				return
			self._perform_conversion(conversion_type, folders_to_convert)
		self._getSelectedItemsDeferred(do_convert, 200)

	def _perform_conversion(self, conversion_type, folders_to_convert):
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

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		self.manager.chooseNVDAObjectOverlayClasses(obj, clsList)

	def event_gainFocus(self, obj, nextHandler):
		if obj and obj.appModule and obj.appModule.appName == "explorer":
			if hasattr(obj, 'windowHandle'):
				if obj.windowHandle != self._last_window_hwnd:
					self._last_window = None
					self._last_window_hwnd = None
		self.manager.event_gainFocus(obj, nextHandler)

	def event_focusEntered(self, obj, nextHandler):
		self.manager.event_focusEntered(obj, nextHandler)

	def event_foreground(self, obj, nextHandler):
		self._last_window = None
		self._last_window_hwnd = None
		self.manager.event_foreground(obj, nextHandler)

	def event_UIA_elementSelected(self, obj, nextHandler):
		self.manager.event_UIA_elementSelected(obj, nextHandler)

	def event_selection(self, obj, nextHandler):
		self.manager.event_selection(obj, nextHandler)