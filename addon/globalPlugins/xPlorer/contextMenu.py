# contextMenu.py

import wx
import gui
import gui.guiHelper
import ui
import api
import os
import core
import tones
from logHandler import log
import addonHandler

addonHandler.initTranslation()

class ContextMenuManager:
	def __init__(self, plugin):
		self.plugin = plugin

	def _create_context_menu(self):
		menu = wx.Menu()

		create_file_item = menu.Append(wx.ID_ANY, _("Create File"))
		menu.AppendSeparator()

		compress_item = menu.Append(wx.ID_ANY, _("Compress zip"))
		invert_selection_item = menu.Append(wx.ID_ANY, _("Invert selection"))
		copy_address_item = menu.Append(wx.ID_ANY, _("Copy address bar"))
		copy_content_item = menu.Append(wx.ID_ANY, _("Copy content"))
		copy_names_item = menu.Append(wx.ID_ANY, _("Copy selected file and folder names"))
		rename_item = menu.Append(wx.ID_ANY, _("Rename selected file"))

		robocopy_menu = wx.Menu()
		robocopy_item = menu.AppendSubMenu(robocopy_menu, _("Robocopy"))
		copy_item = robocopy_menu.Append(wx.ID_ANY, _("copy"))
		move_item = robocopy_menu.Append(wx.ID_ANY, _("move"))
		paste_item = robocopy_menu.Append(wx.ID_ANY, _("paste"))

		txt_to_folder_item = menu.Append(wx.ID_ANY, _("TXT to Folder"))
		create_multiple_folders_item = menu.Append(wx.ID_ANY, _("Create Multiple Folders..."))

		case_menu = wx.Menu()
		case_item = menu.AppendSubMenu(case_menu, _("Case Converter for Folders"))
		uppercase_item = case_menu.Append(wx.ID_ANY, _("Uppercase"))
		lowercase_item = case_menu.Append(wx.ID_ANY, _("Lowercase"))
		titlecase_item = case_menu.Append(wx.ID_ANY, _("Title Case"))
		headlinecase_item = case_menu.Append(wx.ID_ANY, _("Headline Case"))

		settings_item = menu.Append(wx.ID_ANY, _("xPlorer Settings"))
		say_size_item = menu.Append(wx.ID_ANY, self._buildSaySizeLabel())
		folder_info_item = menu.Append(wx.ID_ANY, self._buildFolderInfoLabel())

		robocopy_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.robocopy.copy), copy_item)
		robocopy_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.robocopy.move), move_item)
		robocopy_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.robocopy.paste), paste_item)

		case_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("uppercase")), uppercase_item)
		case_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("lowercase")), lowercase_item)
		case_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("titlecase")), titlecase_item)
		case_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("headlinecase")), headlinecase_item)

		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.createFileManager.create_file), create_file_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.compression.compressZip), compress_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.selection.invertSelection), invert_selection_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin._copyAddressBar), copy_address_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.clipboard.copyFileContent), copy_content_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.clipboard.copySelectedNames), copy_names_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileOps.renameFile), rename_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileOps.saySize), say_size_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(800, self.plugin._executeWithSilence, self.plugin.txt2folder.convert_txt_to_folder), txt_to_folder_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin._createMultipleFolders), create_multiple_folders_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin._openSettings), settings_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.folderInfo.get_folder_info), folder_info_item)

		return menu

	def _buildSaySizeLabel(self):
		"""Mirrors _buildFolderInfoLabel. Files are always instant (a single
		stat call each, regardless of file size). Folders are also computed
		instantly as long as their total file count stays within
		FileOperations.FAST_SIZE_FILE_CAP - a stat() call costs the same for
		a 1KB file as a 1GB one, so it's the number of entries scanned that
		determines speed, not their size. A folder (or drive) whose count
		exceeds the cap falls back to the plain action name, same as before,
		and the real number is computed on activation."""
		try:
			selected_items, _ignore = self.plugin._getSelectedItems()
			if not selected_items:
				return _("Say size")

			total_size = 0
			folder_paths = []
			for _name, path in selected_items:
				if os.path.isdir(path):
					# A drive root's size is looked up (used space, not a
					# walk) rather than counted like a normal folder - keep
					# that case on the on-demand path, same as before.
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
		except Exception as e:
			log.debug(f"xPlorer: could not build live say-size label: {e}")
			return _("Say size")

	def _buildFolderInfoLabel(self):
		"""Compute an immediate folder/file count for the menu item's own
		label, so NVDA announces the counts the moment the item is reached
		while arrowing through the menu - no need to select it and wait.
		Uses a bounded recursive walk (same file-count cap as Say size) so
		it stays instant while still counting files nested inside
		subfolders, not just ones sitting directly in the selected folder.
		A full, uncapped recursive count is still available by selecting the
		item, via get_folder_info(). With one folder selected, or several,
		the counts are combined across all of them; with nothing folder-like
		selected, just "Folder info" is shown."""
		try:
			selected_items, _ignore = self.plugin._getSelectedItems()
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
		except Exception as e:
			log.debug(f"xPlorer: could not build live folder info label: {e}")
			return _("Folder info")

	def showContextMenu(self):
		def show_menu():
			try:
				focus = api.getFocusObject()
				if not focus or focus.appModule.appName != "explorer":
					return
				import speech
				speech.cancelSpeech()
				self.plugin.manager.contextMenuActive = True
				self.plugin.manager.suppressAllAnnouncements = True
				last_focus = api.getFocusObject()
				menu = self._create_context_menu()
				frame = wx.Frame(gui.mainFrame, -1, "", pos=(0, 0), size=(0, 0))
				try:
					frame.Show()
					frame.Raise()
					frame.PopupMenu(menu)
					if last_focus:
						last_focus.setFocus()
				except Exception as e:
					log.error(f"Error displaying popup menu: {e}")
				finally:
					try:
						menu.Destroy()
					except:
						pass
					try:
						frame.Destroy()
					except:
						pass
					core.callLater(1000, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))
					core.callLater(100, lambda: setattr(self.plugin.manager, 'contextMenuActive', False))
			except Exception as e:
				log.error(f"Error in showContextMenu: {e}")
				self.plugin.manager.contextMenuActive = False
				self.plugin.manager.suppressAllAnnouncements = False
		wx.CallAfter(show_menu)

