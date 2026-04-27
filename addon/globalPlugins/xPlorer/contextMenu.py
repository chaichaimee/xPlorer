# contextMenu.py

import wx
import gui
import gui.guiHelper
import ui
import api
import core
import tones
from logHandler import log
import addonHandler

addonHandler.initTranslation()

class ContextMenuManager:
	def __init__(self, plugin):
		self.plugin = plugin
		
	def createContextMenu(self):
		menu = wx.Menu()
		
		settings_item = menu.Append(wx.ID_ANY, _("xPlorer Settings"))
		menu.AppendSeparator()
		
		compress_item = menu.Append(wx.ID_ANY, _("Compress zip"))
		invert_selection_item = menu.Append(wx.ID_ANY, _("Invert selection"))
		copy_address_item = menu.Append(wx.ID_ANY, _("Copy address bar"))
		copy_content_item = menu.Append(wx.ID_ANY, _("Copy content"))
		copy_names_item = menu.Append(wx.ID_ANY, _("Copy selected file and folder names"))
		create_file_item = menu.Append(wx.ID_ANY, _("Create File"))
		rename_item = menu.Append(wx.ID_ANY, _("Rename selected file"))
		say_size_item = menu.Append(wx.ID_ANY, _("Say size"))
		
		robocopy_menu = wx.Menu()
		robocopy_item = menu.AppendSubMenu(robocopy_menu, _("Robocopy"))
		copy_item = robocopy_menu.Append(wx.ID_ANY, _("copy"))
		move_item = robocopy_menu.Append(wx.ID_ANY, _("move"))
		paste_item = robocopy_menu.Append(wx.ID_ANY, _("paste"))
		robocopy_menu.AppendSeparator()
		mirror_item = robocopy_menu.Append(wx.ID_ANY, _("mirror Backup"))
		
		txt_to_folder_item = menu.Append(wx.ID_ANY, _("TXT to Folder"))
		create_multiple_folders_item = menu.Append(wx.ID_ANY, _("Create Multiple Folders..."))
		
		case_menu = wx.Menu()
		case_item = menu.AppendSubMenu(case_menu, _("Case Converter for Folders"))
		uppercase_item = case_menu.Append(wx.ID_ANY, _("Uppercase"))
		lowercase_item = case_menu.Append(wx.ID_ANY, _("Lowercase"))
		titlecase_item = case_menu.Append(wx.ID_ANY, _("Title Case"))
		headlinecase_item = case_menu.Append(wx.ID_ANY, _("Headline Case"))
		
		folder_info_item = menu.Append(wx.ID_ANY, _("Folder info"))
		
		robocopy_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.robocopy.copy), copy_item)
		robocopy_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.robocopy.move), move_item)
		robocopy_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.robocopy.paste), paste_item)
		robocopy_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin.robocopy.showMirrorBackupDialog), mirror_item)
		
		case_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("uppercase")), uppercase_item)
		case_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("lowercase")), lowercase_item)
		case_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("titlecase")), titlecase_item)
		case_menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, lambda: self.plugin._convertFolderNames("headlinecase")), headlinecase_item)
		
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._openSettings), settings_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.compression.compressZip), compress_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.selection.invertSelection), invert_selection_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin._copyAddressBar), copy_address_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.clipboard.copyFileContent), copy_content_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.clipboard.copySelectedNames), copy_names_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.createFileManager.create_file), create_file_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileOps.renameFile), rename_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.fileOps.saySize), say_size_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.txt2folder.convert_txt_to_folder), txt_to_folder_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin._createMultipleFolders), create_multiple_folders_item)
		menu.Bind(wx.EVT_MENU, lambda evt: core.callLater(0, self.plugin._executeWithSilence, self.plugin.folderInfo.get_folder_info), folder_info_item)
		
		return menu
	
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
				
				menu = self.createContextMenu()
				
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