# contextMenu.py

import wx
import gui
import gui.guiHelper
import ui
import api
import os
import core
import tones
import threading
import time
import ctypes
import ctypes.wintypes
import datetime
import speech
from logHandler import log
import addonHandler
from comtypes import COMError

addonHandler.initTranslation()

def _restoreFocusAfterDialog(focusObj):
	# ContextMenuDialog/PropertiesDialog are parented to gui.mainFrame (NVDA's
	# own hidden window), not to the Explorer window itself, so Windows has
	# no natural focus-return path once the dialog closes - focus just stays
	# wherever gui.mainFrame left it, with no event ever telling NVDA
	# Explorer is focused again. That is a real, indefinite stall (not a
	# brief timing race), confirmed by watchdog-free logs where
	# api.getFocusObject() still wasn't Explorer over a second after the
	# dialog closed, with no further foreground event arriving until the
	# user manually pressed another key. Calling setFocus() immediately
	# here - synchronously, right after ShowModal() returns, using the
	# still-fresh NVDAObject captured moments earlier before the dialog was
	# even shown - is what actually closes that gap for Explorer.
	#
	# For a non-Explorer origin (the menu can now open anywhere), that alone
	# isn't enough: many apps' NVDAObject.setFocus() only repositions NVDA's
	# own internal navigator/virtual-buffer cursor and assumes the app's
	# window is already the real OS foreground window - it does not itself
	# call SetForegroundWindow. Since our dialog genuinely took real OS
	# foreground focus (wx.STAY_ON_TOP + Raise()), that assumption breaks
	# once the dialog closes, and Windows can hand foreground to whatever
	# is next in z-order instead of back to the original app. Forcing
	# SetForegroundWindow on the original window handle first removes that
	# dependency on any single app's setFocus() implementation.
	if not focusObj:
		return
	try:
		hwnd = getattr(focusObj, "windowHandle", None)
		if hwnd:
			ctypes.windll.user32.SetForegroundWindow(hwnd)
		focusObj.setFocus()
	except (COMError, RuntimeError, AttributeError, OSError) as e:
		log.debug(f"xPlorer: could not restore focus after dialog close: {e}")


class ContextMenuDialog(wx.Dialog):
	def __init__(self, parent, menu_data, recentLocationsController=None):
		super().__init__(
			parent, title="",
			style=wx.BORDER_SIMPLE | wx.STAY_ON_TOP | wx.FRAME_FLOAT_ON_PARENT
		)
		self.menu_stack = []
		self.current_menu = menu_data
		self._first_item_label = ''
		self._recentLocationsController = recentLocationsController
		self.InitUI()
		self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)
		self.Bind(wx.EVT_SHOW, self._onShow)
		self.listbox.Bind(wx.EVT_CONTEXT_MENU, self._onListContextMenu)
		self.listbox.SetFocus()
		self.Raise()

	def InitUI(self):
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.listbox = wx.ListBox(panel, choices=[], style=wx.LB_SINGLE)
		sizer.Add(self.listbox, 1, wx.EXPAND | wx.ALL, 5)
		panel.SetSizer(sizer)
		self._populate_list()
		self.Fit()
		self.CentreOnScreen()

	def _populate_list(self):
		self.listbox.Clear()
		for item in self.current_menu:
			label = item['label']
			if not item.get('enabled', True):
				label += f" ({_('unavailable')})"
			self.listbox.Append(label)
		if self.listbox.GetCount() > 0:
			self.listbox.SetSelection(0)
			self._first_item_label = self.current_menu[0]['label']

	def refresh_visible_labels(self, menu_ref):
		if self.current_menu is not menu_ref:
			return
		try:
			selection = self.listbox.GetSelection()
			for index, item in enumerate(self.current_menu):
				label = item['label']
				if not item.get('enabled', True):
					label += f" ({_('unavailable')})"
				self.listbox.SetString(index, label)
			if selection != wx.NOT_FOUND:
				self.listbox.SetSelection(selection)
		except RuntimeError:
			pass

	def _onShow(self, event):
		if event.IsShown():
			previous_mode = speech.getState()
			speech.setSpeechMode(speech.SpeechMode.off)
			core.callLater(150, self._restoreSpeechAndAnnounceFirst, previous_mode)
		event.Skip()

	def _restoreSpeechAndAnnounceFirst(self, previous_mode):
		speech.setSpeechMode(previous_mode)
		if self._first_item_label:
			ui.message(self._first_item_label)

	def onCharHook(self, event):
		key = event.GetKeyCode()
		if key == wx.WXK_RETURN:
			self.onActivate()
		elif key == wx.WXK_ESCAPE:
			if self.menu_stack:
				self.go_back()
			else:
				self.EndModal(wx.ID_CANCEL)
		elif key == wx.WXK_UP:
			self._moveSelection(-1)
		elif key == wx.WXK_DOWN:
			self._moveSelection(1)
		elif key == wx.WXK_HOME and (self._isRecentLocationsCurrentMenu() or self._isPropertyMenu()):
			self._jumpToEdge(0)
		elif key == wx.WXK_END and (self._isRecentLocationsCurrentMenu() or self._isPropertyMenu()):
			self._jumpToEdge(-1)
		elif key == wx.WXK_RIGHT:
			self._openSubmenu()
		elif key == wx.WXK_LEFT:
			if self.menu_stack:
				self.go_back()
		else:
			event.Skip()

	def _isRecentLocationsCurrentMenu(self):
		if not self.current_menu:
			return False
		first = self.current_menu[0]
		return bool(first.get('isRecentLocation', False))

	def _isPropertyMenu(self):
		return bool(self.current_menu) and self.current_menu[0].get('isPropertyItem', False)

	def _jumpToEdge(self, index):
		count = self.listbox.GetCount()
		if count == 0:
			return
		target = 0 if index == 0 else count - 1
		self.listbox.SetSelection(target)

	def _moveSelection(self, delta):
		count = self.listbox.GetCount()
		if count == 0:
			return
		sel = self.listbox.GetSelection()
		if sel == wx.NOT_FOUND:
			sel = 0
		elif self._isRecentLocationsCurrentMenu() or self._isPropertyMenu():
			newSel = sel + delta
			if newSel < 0 or newSel >= count:
				return
			sel = newSel
		else:
			sel = (sel + delta) % count
		self.listbox.SetSelection(sel)

	def _openSubmenu(self):
		sel = self.listbox.GetSelection()
		if sel == wx.NOT_FOUND:
			return
		item = self.current_menu[sel]
		if item.get('submenu'):
			self.menu_stack.append((self.current_menu, sel))
			self.current_menu = item['submenu']
			self._populate_list()

	def go_back(self):
		if self.menu_stack:
			prev_menu, prev_sel = self.menu_stack.pop()
			self.current_menu = prev_menu
			self._populate_list()
			self.listbox.SetSelection(prev_sel)

	def onActivate(self):
		sel = self.listbox.GetSelection()
		if sel == wx.NOT_FOUND:
			return
		item = self.current_menu[sel]
		if not item.get('enabled', True):
			return
		if item.get('submenu'):
			self._openSubmenu()
		elif item.get('action'):
			wx.CallAfter(self.EndModal, wx.ID_OK)
			wx.CallAfter(item['action'])

	def _onListContextMenu(self, event):
		if not self._recentLocationsController:
			event.Skip()
			return
		sel = self.listbox.GetSelection()
		if sel == wx.NOT_FOUND or sel >= len(self.current_menu):
			return
		item = self.current_menu[sel]
		path = item.get('path')
		if not item.get('isRecentLocation') or not path:
			return
		self._showRecentLocationOptionsMenu(path)

	def _showRecentLocationOptionsMenu(self, path):
		recentLocations = self._recentLocationsController.plugin.recentLocations
		isPinned = recentLocations.isPinned(path)
		isReversed = recentLocations.getReverseDisplay()

		menu = wx.Menu()
		pinItem = menu.Append(wx.ID_ANY, _("Unpin") if isPinned else _("Pin"))
		clearAllItem = menu.Append(wx.ID_ANY, _("Clear all (except pinned)"))
		menu.AppendSeparator()
		normalItem = menu.AppendRadioItem(wx.ID_ANY, _("Normal display"))
		reversedItem = menu.AppendRadioItem(wx.ID_ANY, _("Reversed display"))
		normalItem.Check(not isReversed)
		reversedItem.Check(isReversed)

		self.Bind(wx.EVT_MENU, lambda evt: self._onTogglePin(path), pinItem)
		self.Bind(wx.EVT_MENU, lambda evt: self._onClearAllUnpinned(), clearAllItem)
		self.Bind(wx.EVT_MENU, lambda evt: self._onSetReverseDisplay(False), normalItem)
		self.Bind(wx.EVT_MENU, lambda evt: self._onSetReverseDisplay(True), reversedItem)

		self.PopupMenu(menu)
		menu.Destroy()

	def _refreshRecentLocationsMenu(self, announcement):
		controller = self._recentLocationsController
		if not controller:
			return
		newSubmenu = controller._buildRecentLocationsSubmenu()
		self.current_menu = newSubmenu
		self._populate_list()
		if announcement:
			ui.message(announcement)

	def _onTogglePin(self, path):
		recentLocations = self._recentLocationsController.plugin.recentLocations
		nowPinned = recentLocations.togglePin(path)
		self._refreshRecentLocationsMenu(_("Pinned") if nowPinned else _("Unpinned"))

	def _onClearAllUnpinned(self):
		recentLocations = self._recentLocationsController.plugin.recentLocations
		recentLocations.clearAllUnpinned()
		self._refreshRecentLocationsMenu(_("Cleared recent locations"))

	def _onSetReverseDisplay(self, value):
		recentLocations = self._recentLocationsController.plugin.recentLocations
		recentLocations.setReverseDisplay(value)
		self._refreshRecentLocationsMenu(_("Reversed display") if value else _("Normal display"))


class ContextMenuManager:
	def __init__(self, plugin):
		self.plugin = plugin

	def _buildRecentLocationsSubmenu(self):
		entries = self.plugin.recentLocations.getRecentLocations()
		if not entries:
			return [{'label': _("No recent locations yet"), 'enabled': False, 'action': None, 'isRecentLocation': True}]

		reverseDisplay = self.plugin.recentLocations.getReverseDisplay()
		submenu = []
		for path, pinned in entries:
			displayPath = self.plugin.recentLocations.formatDisplayPath(path, reverseDisplay)
			label = _("{0} (pinned)").format(displayPath) if pinned else displayPath
			submenu.append({
				'label': label,
				'enabled': True,
				'path': path,
				'isRecentLocation': True,
				'action': lambda p=path: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin.recentLocations.openLocation(p)),
			})
		return submenu

	def showRecentLocationsMenu(self):
		last_focus = api.getFocusObject()
		def show_menu():
			try:
				if not last_focus or last_focus.appModule.appName != "explorer":
					log.debug("xPlorer: showRecentLocationsMenu aborted - focus left Explorer before the deferred wx.CallAfter ran")
					return
				speech.cancelSpeech()
				self.plugin.manager.contextMenuActive = True
				self.plugin.manager.suppressAllAnnouncements = True
				menu_data = self._buildRecentLocationsSubmenu()
				try:
					dlg = ContextMenuDialog(gui.mainFrame, menu_data, recentLocationsController=self)
					dlg.ShowModal()
				except Exception as e:
					log.error(f"Error displaying recent locations dialog: {e}")
				finally:
					try:
						dlg.Destroy()
					except (RuntimeError, AttributeError, UnboundLocalError):
						pass
					_restoreFocusAfterDialog(last_focus)
					core.callLater(1000, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))
					core.callLater(100, lambda: setattr(self.plugin.manager, 'contextMenuActive', False))
			except Exception as e:
				log.error(f"Error in showRecentLocationsMenu: {e}")
				self.plugin.manager.contextMenuActive = False
				self.plugin.manager.suppressAllAnnouncements = False
		wx.CallAfter(show_menu)

	def _buildWorkspaceSubmenu(self):
		# "Edit Workspace" was removed from here - it's now reached via
		# NVDA+shift+m triple tap instead, which also exposes pin/reorder
		# and doesn't need a menu round-trip just to rename or delete one.
		submenu = []
		for workspaceName in self.plugin.workspaceManager.getOrderedWorkspaceNames():
			submenu.append({
				'label': workspaceName,
				'enabled': True,
				'action': lambda n=workspaceName: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin.workspaceManager.loadWorkspace(n)),
			})
		submenu.append({'label': _("Save Current as Workspace..."), 'enabled': True,
			'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.workspaceManager.showSaveDialog)})
		return submenu

	def showWorkspaceMenu(self):
		last_focus = api.getFocusObject()
		def show_menu():
			try:
				if not last_focus:
					log.debug("xPlorer: showWorkspaceMenu aborted - no focus object captured before the deferred wx.CallAfter ran")
					return
				speech.cancelSpeech()
				self.plugin.manager.contextMenuActive = True
				self.plugin.manager.suppressAllAnnouncements = True
				menu_data = self._buildWorkspaceSubmenu()
				try:
					dlg = ContextMenuDialog(gui.mainFrame, menu_data)
					dlg.ShowModal()
				except Exception as e:
					log.error(f"Error displaying workspace menu dialog: {e}")
				finally:
					try:
						dlg.Destroy()
					except (RuntimeError, AttributeError, UnboundLocalError):
						pass
					_restoreFocusAfterDialog(last_focus)
					core.callLater(1000, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))
					core.callLater(100, lambda: setattr(self.plugin.manager, 'contextMenuActive', False))
			except Exception as e:
				log.error(f"Error in showWorkspaceMenu: {e}")
				self.plugin.manager.contextMenuActive = False
				self.plugin.manager.suppressAllAnnouncements = False
		wx.CallAfter(show_menu)

	def _create_context_menu_data(self, selected_items, currentPath, inExplorer=True):
		menu_data = []

		# Create File
		if inExplorer:
			menu_data.append({'label': _("Create File"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.createFileManager.create_file)})

		# File Basket - selecting this from the menu both adds whatever is
		# currently selected and opens the basket in one step, since there's
		# no multi-tap gesture available from a menu click the way
		# NVDA+shift+n has single/double/open separately.
		if inExplorer:
			menu_data.append({'label': _("File Basket"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileBasket.addSelectedAndShowBasket)})
		else:
			menu_data.append({'label': _("File Basket"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileBasket.showBasketDialog)})

		# Batch Rename Tool
		if inExplorer:
			menu_data.append({'label': _("Batch Rename Tool"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.batchRename.show_dialog)})

		# Undo Last Rename - operates on a saved undo mapping of file paths,
		# not on the current Explorer selection, so it works anywhere.
		menu_data.append({'label': _("Undo Last Rename"), 'enabled': True,
			'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.batchRename.undoLastRename)})

		# Folder Sync & Compare
		if inExplorer:
			sync_compare_submenu = [
				{'label': _("Mark Left Folder (Sync Compare)"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.syncCompare.markLeftFolder)},
				{'label': _("Run Compare (Sync Compare)"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.syncCompare.compareWithCurrentFolder)},
			]
			menu_data.append({'label': _("Folder Sync & Compare"), 'enabled': True, 'submenu': sync_compare_submenu})

		# Duplicate Finder
		if inExplorer:
			menu_data.append({'label': _("Duplicate Finder"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.duplicateFinder.scanForDuplicates)})

		# Case Converter for Folders
		if inExplorer:
			case_submenu = [
				{'label': _("Uppercase"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("uppercase"))},
				{'label': _("Lowercase"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("lowercase"))},
				{'label': _("Title Case"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("titlecase"))},
				{'label': _("Headline Case"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("headlinecase"))},
			]
			menu_data.append({'label': _("Case Converter for Folders"), 'enabled': True, 'submenu': case_submenu})

		# TXT to Folder
		if inExplorer:
			menu_data.append({'label': _("TXT to Folder"), 'enabled': True,
				'action': lambda: core.callLater(800, self.plugin._executeWithSilence, self.plugin.txt2folder.convert_txt_to_folder)})

		# Flat View
		if inExplorer:
			menu_data.append({'label': _("Flat View"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.flatView.show_dialog)})

		# Folder to ISO
		if inExplorer:
			menu_data.append({'label': _("Folder to ISO"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileOps.convertFolderToIso)})

		# Create Multiple Folders...
		if inExplorer:
			menu_data.append({'label': _("Create Multiple Folders..."), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin._createMultipleFolders)})

		# Compress
		if inExplorer:
			compress_submenu = [
				{'label': _("Compress zip"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.compression.compressZip)},
				{'label': _("unCompress zip"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.compression.unzipSelected)},
			]
			menu_data.append({'label': _("Compress"), 'enabled': True, 'submenu': compress_submenu})

		# Selection
		if inExplorer:
			selection_submenu = [
				{'label': _("Select by Extension"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.selection.selectByExtension)},
				{'label': _("Invert selection"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.selection.invertSelection)},
				{'label': _("Multi-select"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin._enterMultiSelectLayer)},
				{'label': _("Select by Search"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.selection.showSearchSelectionDialog)},
			]
			menu_data.append({'label': _("Selection"), 'enabled': True, 'submenu': selection_submenu})

		# Clipboard Operations
		if inExplorer:
			clipboard_submenu = [
				{'label': _("Copy address bar"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin._copyAddressBar)},
				{'label': _("Copy content"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.clipboard.copyFileContent)},
				{'label': _("Copy selected file and folder names"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.clipboard.copySelectedNames)},
			]
			menu_data.append({'label': _("Clipboard Operations"), 'enabled': True, 'submenu': clipboard_submenu})

		# Rename selected file
		if inExplorer:
			menu_data.append({'label': _("Rename selected file"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileOps.renameFile)})

		# Robocopy
		if inExplorer:
			robocopy_submenu = [
				{'label': _("copy"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.robocopy.copy)},
				{'label': _("move"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.robocopy.move)},
				{'label': _("paste"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.robocopy.paste)},
			]
			menu_data.append({'label': _("Robocopy"), 'enabled': True, 'submenu': robocopy_submenu})

		# Workspace Manager - opens/saves lists of saved paths, doesn't need
		# a live Explorer selection.
		workspace_submenu = self._buildWorkspaceSubmenu()
		menu_data.append({'label': _("Workspace Manager"), 'enabled': True, 'submenu': workspace_submenu})

		# Size list of the folder open in Explorer - needs a live Explorer window.
		if inExplorer:
			menu_data.append({'label': _("Current folder size list"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileOps.showFolderSizeList)})

		# Recent Locations - browsing/navigating to saved paths, doesn't
		# need a live Explorer selection.
		recent_locations_submenu = self._buildRecentLocationsSubmenu()
		menu_data.append({'label': _("Recent Locations"), 'enabled': True, 'submenu': recent_locations_submenu})

		# Operation History - a plain log viewer, no Explorer needed.
		menu_data.append({'label': _("Operation History"), 'enabled': True,
			'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.operationHistory.show_dialog)})

		# xPlorer Settings - a plain settings dialog, no Explorer needed.
		menu_data.append({'label': _("xPlorer Settings"), 'enabled': True,
			'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin._openSettings)})

		target_name = None
		target_path = None
		if selected_items:
			target_name, target_path = selected_items[0]
		elif currentPath:
			trimmed = currentPath.rstrip("\\")
			target_name = os.path.basename(trimmed) or currentPath
			target_path = currentPath

		def invokePropertiesMenu():
			self.plugin.propertiesMenuManager.show_properties_menu(target_name, target_path)

		# Properties, say size, folder info - all need a live selection or
		# current Explorer folder.
		if inExplorer:
			menu_data.append({'label': _("Properties"), 'enabled': True,
				'action': lambda: core.callLater(0, invokePropertiesMenu)})

			say_size_entry = {'label': _("Say size"), 'enabled': True,
				'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileOps.saySize)}
			menu_data.append(say_size_entry)

			hasFolderSelected = any(os.path.isdir(path) for _name, path in selected_items) if selected_items else False
			if hasFolderSelected:
				folder_info_entry = {'label': _("Folder info"), 'enabled': True,
					'action': lambda: core.callLater(0, self.plugin._executeWithSilence, self.plugin.folderInfo.get_folder_info)}
				menu_data.append(folder_info_entry)
			else:
				folder_info_entry = None
		else:
			say_size_entry = None
			folder_info_entry = None

		return menu_data, say_size_entry, folder_info_entry, selected_items

	def _scheduleLiveLabelUpdate(self, saySizeEntry, folderInfoEntry, selected_items, topMenuData, dialogRef):
		if saySizeEntry is None and folderInfoEntry is None:
			return

		def computeAndApply():
			sizeLabel = None
			if saySizeEntry is not None:
				try:
					sizeLabel = self._resolveSaySizeLabel(selected_items)
				except Exception as e:
					log.debug(f"xPlorer: say-size label computation failed: {e}")
			infoLabel = None
			if folderInfoEntry is not None:
				try:
					infoLabel = self._resolveFolderInfoLabel(selected_items)
				except Exception as e:
					log.debug(f"xPlorer: folder-info label computation failed: {e}")

			def apply():
				if sizeLabel and saySizeEntry is not None:
					saySizeEntry['label'] = sizeLabel
				if infoLabel and folderInfoEntry is not None:
					folderInfoEntry['label'] = infoLabel
				dlg = dialogRef.get('dialog')
				if dlg:
					dlg.refresh_visible_labels(topMenuData)

			wx.CallAfter(apply)

		threading.Thread(target=computeAndApply, daemon=True).start()

	def _resolveSaySizeLabel(self, selected_items):
		if not selected_items:
			return _("Say size")

		total_size = 0
		folder_paths = []
		for _name, path in selected_items:
			if os.path.isdir(path):
				drive_letter = os.path.splitdrive(path)[0]
				if drive_letter and len(drive_letter) == 2 and drive_letter[1] == ":" and path == drive_letter + "\\":
					return _("Say size")
				folder_paths.append(path)
			else:
				try:
					total_size += os.path.getsize(path)
				except OSError:
					return _("Say size")

		if folder_paths:
			boundedFolderSize = self.plugin.fileOps._computeBoundedFolderSize(folder_paths)
			if boundedFolderSize is None:
				return _("Say size")
			total_size += boundedFolderSize

		return self.plugin.fileOps._format_size(total_size)

	def _resolveFolderInfoLabel(self, selected_items):
		if not selected_items:
			return _("Folder info")
		folder_paths = [path for _name, path in selected_items if os.path.isdir(path)]
		if not folder_paths:
			return _("Folder info")
		counts = self.plugin.folderInfo._computeBoundedFolderCounts(folder_paths)
		if counts is None:
			return _("Folder info")
		subfolder_count, file_count = counts
		return _("{subfolders} subfolders, {files} files").format(
			subfolders=subfolder_count, files=file_count
		)

	def showContextMenu(self):
		last_focus = api.getFocusObject()
		inExplorer = bool(last_focus and last_focus.appModule and last_focus.appModule.appName == "explorer")

		def buildAndShow(selected_items, currentPath):
			try:
				menu_data, say_size_entry, folder_info_entry, resolved_items = self._create_context_menu_data(selected_items, currentPath, inExplorer)
				dialogRef = {'dialog': None}
				self._scheduleLiveLabelUpdate(say_size_entry, folder_info_entry, resolved_items, menu_data, dialogRef)
				try:
					dlg = ContextMenuDialog(gui.mainFrame, menu_data, recentLocationsController=self)
					dialogRef['dialog'] = dlg
					dlg.ShowModal()
				except Exception as e:
					log.error(f"Error displaying context menu dialog: {e}")
				finally:
					dialogRef['dialog'] = None
					try:
						dlg.Destroy()
					except (RuntimeError, AttributeError, UnboundLocalError):
						pass
					_restoreFocusAfterDialog(last_focus)
					core.callLater(1000, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))
					core.callLater(100, lambda: setattr(self.plugin.manager, 'contextMenuActive', False))
			except Exception as e:
				log.error(f"Error in showContextMenu: {e}")
				self.plugin.manager.contextMenuActive = False
				self.plugin.manager.suppressAllAnnouncements = False

		def afterSelection(selected_items, _hwnd):
			try:
				if not last_focus or last_focus.appModule.appName != "explorer":
					log.debug("xPlorer: showContextMenu aborted - focus left Explorer before selection resolved")
					return
				if selected_items:
					buildAndShow(selected_items, None)
				else:
					self.plugin._getCurrentPathFromExplorerAsync(lambda currentPath: buildAndShow(selected_items, currentPath))
			except Exception as e:
				log.error(f"Error in showContextMenu: {e}")
				self.plugin.manager.contextMenuActive = False
				self.plugin.manager.suppressAllAnnouncements = False

		def show_menu():
			try:
				speech.cancelSpeech()
				self.plugin.manager.contextMenuActive = True
				self.plugin.manager.suppressAllAnnouncements = True
				if inExplorer:
					self.plugin._getSelectedItemsAsync(afterSelection)
				else:
					# Outside Explorer there is nothing to select or
					# resolve a current path from - go straight to building
					# the menu with only the Explorer-independent entries.
					buildAndShow(None, None)
			except Exception as e:
				log.error(f"Error in showContextMenu: {e}")
				self.plugin.manager.contextMenuActive = False
				self.plugin.manager.suppressAllAnnouncements = False
		wx.CallAfter(show_menu)


class PropertiesDialog(wx.Dialog):
	"""Read-only, accessible view of item properties. A single multi-line
	text control lets NVDA read every property with normal review commands,
	instead of treating each property as a selectable menu action."""

	def __init__(self, parent, title, lines):
		super().__init__(
			parent, title=title,
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP | wx.FRAME_FLOAT_ON_PARENT
		)
		self.lines = list(lines)
		self._init_ui()

	def _init_ui(self):
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self.text_ctrl = wx.TextCtrl(
			self,
			value="\n".join(self.lines),
			style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE,
			size=(500, 300),
		)
		s_helper.addItem(self.text_ctrl, flag=wx.EXPAND, proportion=1)

		btn_sizer = wx.StdDialogButtonSizer()
		close_btn = wx.Button(self, wx.ID_CANCEL, label=_("Close"))
		btn_sizer.AddButton(close_btn)
		btn_sizer.Realize()
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()
		self.Raise()
		self.text_ctrl.SetFocus()

	def update_line(self, index, text):
		try:
			self.lines[index] = text
			insertionPoint = self.text_ctrl.GetInsertionPoint()
			self.text_ctrl.SetValue("\n".join(self.lines))
			self.text_ctrl.SetInsertionPoint(insertionPoint)
		except (RuntimeError, IndexError):
			pass


class PropertiesMenuManager:
	FOLDER_STATS_CAP = 20000

	def __init__(self, plugin):
		self.plugin = plugin

	def _resolveTargetAsync(self, callback):
		def afterSelection(selected_items, _hwnd):
			if selected_items:
				name, path = selected_items[0]
				callback(name, path)
				return

			def afterPath(currentPath):
				if currentPath:
					trimmed = currentPath.rstrip("\\")
					callback(os.path.basename(trimmed) or currentPath, currentPath)
				else:
					callback(None, None)

			self.plugin._getCurrentPathFromExplorerAsync(afterPath)

		self.plugin._getSelectedItemsAsync(afterSelection)

	def _formatBytes(self, numBytes):
		units = (_("bytes"), _("KB"), _("MB"), _("GB"), _("TB"))
		size = float(numBytes)
		unitIndex = 0
		while size >= 1024 and unitIndex < len(units) - 1:
			size /= 1024
			unitIndex += 1
		return f"{size:.2f} {units[unitIndex]}"

	def _formatDate(self, epochSeconds):
		try:
			dt = datetime.datetime.fromtimestamp(epochSeconds)
		except (OverflowError, OSError, ValueError):
			return None

		now = datetime.datetime.now()
		today = now.date()
		dtDate = dt.date()

		if dtDate == today:
			dayLabel = _("Today")
		elif dtDate == today - datetime.timedelta(days=1):
			dayLabel = _("Yesterday")
		else:
			dayLabel = dt.strftime("%A")

		if dtDate == today:
			elapsedSeconds = max(0, (now - dt).total_seconds())
			if elapsedSeconds < 60:
				relativeText = _("less than a minute ago")
			elif elapsedSeconds < 3600:
				minutes = int(elapsedSeconds // 60)
				relativeText = (
					_("{0} minute ago").format(minutes) if minutes == 1
					else _("{0} minutes ago").format(minutes)
				)
			else:
				hours = int(elapsedSeconds // 3600)
				relativeText = (
					_("{0} hour ago").format(hours) if hours == 1
					else _("{0} hours ago").format(hours)
				)
			return "{0}, {1} {2}, {3}, {4}".format(dayLabel, dt.strftime("%B"), dt.day, dt.year, relativeText)

		timeText = dt.strftime("%#I:%M:%S %p")
		return "{0}, {1} {2}, {3}, {4}".format(dayLabel, dt.strftime("%B"), dt.day, dt.year, timeText)

	def _getVolumeInfo(self, driveRoot):
		volumeNameBuffer = ctypes.create_unicode_buffer(261)
		fsNameBuffer = ctypes.create_unicode_buffer(261)
		try:
			ok = ctypes.windll.kernel32.GetVolumeInformationW(
				ctypes.c_wchar_p(driveRoot), volumeNameBuffer, ctypes.sizeof(volumeNameBuffer),
				None, None, None, fsNameBuffer, ctypes.sizeof(fsNameBuffer)
			)
		except OSError as e:
			log.debug(f"xPlorer: GetVolumeInformationW failed: {e}")
			return None, None
		if not ok:
			return None, None
		return volumeNameBuffer.value, fsNameBuffer.value

	def show_properties_menu(self, pre_name=None, pre_path=None):
		def resolve_and_show(retryCount=0):
			if pre_path:
				self._show_menu_for(pre_name, pre_path)
				return

			def afterTarget(name, path):
				if not path:
					if retryCount < 5:
						core.callLater(100, lambda: resolve_and_show(retryCount + 1))
						return
					ui.message(_("No item to show properties for"))
					return
				self._show_menu_for(name, path)

			self._resolveTargetAsync(afterTarget)
		wx.CallAfter(lambda: resolve_and_show(0))

	def _show_menu_for(self, name, path, retryCount=0):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			if retryCount < 10:
				core.callLater(100, lambda: self._show_menu_for(name, path, retryCount + 1))
				return
			log.debug("xPlorer: showPropertiesMenu aborted - focus left Explorer before it ran")
			return
		try:
			speech.cancelSpeech()
			self.plugin.manager.contextMenuActive = True
			self.plugin.manager.suppressAllAnnouncements = True

			menu_data, size_index, count_index = self._create_properties_data(name, path)
			lines = [item['label'] for item in menu_data]
			dialogRef = {'dialog': None}

			if size_index != -1 and count_index != -1:
				self._scheduleFolderStats(path, size_index, count_index, dialogRef)

			try:
				dlg = PropertiesDialog(gui.mainFrame, _("Properties"), lines)
				dialogRef['dialog'] = dlg
				dlg.ShowModal()
			except Exception as e:
				log.error(f"Error displaying properties menu: {e}")
			finally:
				dialogRef['dialog'] = None
				try:
					dlg.Destroy()
				except Exception:
					pass
				_restoreFocusAfterDialog(focus)
				core.callLater(1000, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))
				core.callLater(100, lambda: setattr(self.plugin.manager, 'contextMenuActive', False))
		except Exception as e:
			log.error(f"Error in showPropertiesMenu: {e}")
			self.plugin.manager.contextMenuActive = False
			self.plugin.manager.suppressAllAnnouncements = False

	def _create_properties_data(self, name, path):
		menu_data = []
		driveRoot = os.path.splitdrive(path)[0] + "\\"
		isDrive = os.path.normcase(path.rstrip("\\") + "\\") == os.path.normcase(driveRoot)

		size_index = -1
		count_index = -1

		if isDrive:
			self._populateDriveItems(menu_data, driveRoot)
		else:
			size_index, count_index = self._populateItemItems(menu_data, name, path)

		return menu_data, size_index, count_index

	def _populateDriveItems(self, menu_data, driveRoot):
		menu_data.append({'label': _("Drive: {0}").format(driveRoot), 'enabled': True, 'isPropertyItem': True})

		volumeLabel, fsName = self._getVolumeInfo(driveRoot)
		if volumeLabel is not None:
			menu_data.append({'label': _("Network name: {0}").format(volumeLabel or _("Local")), 'enabled': True, 'isPropertyItem': True})
		if fsName:
			menu_data.append({'label': _("File system: {0}").format(fsName), 'enabled': True, 'isPropertyItem': True})

		try:
			free_bytes = ctypes.c_ulonglong(0)
			total_bytes = ctypes.c_ulonglong(0)
			ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
				ctypes.c_wchar_p(driveRoot), None,
				ctypes.byref(total_bytes), ctypes.byref(free_bytes)
			)
			if not ok:
				raise OSError("GetDiskFreeSpaceExW failed")
			free = free_bytes.value
			total = total_bytes.value
			used = total - free
			menu_data.append({'label': _("Free space: {0}").format(self._formatBytes(free)), 'enabled': True, 'isPropertyItem': True})
			menu_data.append({'label': _("Used space: {0}").format(self._formatBytes(used)), 'enabled': True, 'isPropertyItem': True})
			menu_data.append({'label': _("Total capacity: {0}").format(self._formatBytes(total)), 'enabled': True, 'isPropertyItem': True})
		except OSError as e:
			log.debug(f"xPlorer: drive space lookup failed: {e}")

	def _populateItemItems(self, menu_data, name, path):
		menu_data.append({'label': _("Name: {0}").format(name), 'enabled': True, 'isPropertyItem': True})
		menu_data.append({'label': _("Location: {0}").format(os.path.dirname(path) or path), 'enabled': True, 'isPropertyItem': True})

		isFolder = os.path.isdir(path)
		try:
			st = os.stat(path)
		except OSError as e:
			log.debug(f"xPlorer: stat failed for properties menu: {e}")
			return -1, -1

		size_index = -1
		count_index = -1

		if isFolder:
			size_index = len(menu_data)
			menu_data.append({'label': _("Size: calculating..."), 'enabled': True, 'isPropertyItem': True})
		else:
			menu_data.append({'label': _("Size: {0}").format(self._formatBytes(st.st_size)), 'enabled': True, 'isPropertyItem': True})

		createdText = self._formatDate(st.st_ctime)
		if createdText:
			menu_data.append({'label': _("Created: {0}").format(createdText), 'enabled': True, 'isPropertyItem': True})
		modifiedText = self._formatDate(st.st_mtime)
		if modifiedText:
			menu_data.append({'label': _("Modified: {0}").format(modifiedText), 'enabled': True, 'isPropertyItem': True})
		accessedText = self._formatDate(st.st_atime)
		if accessedText:
			menu_data.append({'label': _("Accessed: {0}").format(accessedText), 'enabled': True, 'isPropertyItem': True})

		if isFolder:
			count_index = len(menu_data)
			menu_data.append({'label': _("Contents: calculating..."), 'enabled': True, 'isPropertyItem': True})

		return size_index, count_index

	def _scheduleFolderStats(self, path, size_index, count_index, dialogRef):
		def compute():
			totalSize = 0
			fileCount = 0
			folderCount = 0
			entriesScanned = 0
			pendingDirs = [path]
			capped = False
			try:
				while pendingDirs and not capped:
					current_dir = pendingDirs.pop()
					try:
						with os.scandir(current_dir) as entries:
							for entry in entries:
								try:
									if entry.is_dir(follow_symlinks=False):
										folderCount += 1
										pendingDirs.append(entry.path)
									else:
										fileCount += 1
										totalSize += entry.stat().st_size
								except OSError:
									continue
								entriesScanned += 1
								if entriesScanned > self.FOLDER_STATS_CAP:
									capped = True
									break
					except OSError:
						continue
			except Exception as e:
				log.debug(f"xPlorer: folder stats computation failed: {e}")

			def apply():
				dlg = dialogRef.get('dialog')
				if not dlg:
					return
				try:
					sizeSuffix = _(" (partial)") if capped else ""
					dlg.update_line(size_index, _("Size: {0}{1}").format(self._formatBytes(totalSize), sizeSuffix))
					dlg.update_line(count_index, _("Contents: {0} files, {1} folders{2}").format(fileCount, folderCount, sizeSuffix))
				except (RuntimeError, IndexError):
					pass

			wx.CallAfter(apply)

		threading.Thread(target=compute, daemon=True).start()



# createFile.py
