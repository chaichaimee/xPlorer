# folderInfo.py
import os
import threading
import wx
import ui
import addonHandler
import speech
import core
from logHandler import log

addonHandler.initTranslation()

class FolderInfoManager:
	def __init__(self, plugin):
		self.plugin = plugin

	def cleanup(self):
		pass

	def get_folder_info(self):
		# Cancel any pending speech immediately
		speech.cancelSpeech()
		
		# Suppress all Explorer announcements (including focus changes)
		self.plugin.manager.suppressAllAnnouncements = True
		
		selected_items, shell_window = self.plugin._getSelectedItems()
		if not selected_items:
			ui.message(_("No item selected"))
			self._restoreSpeech()
			return
		
		if len(selected_items) > 1:
			ui.message(_("Please select only one folder"))
			self._restoreSpeech()
			return
		
		folder_path = selected_items[0][1]
		if not os.path.isdir(folder_path):
			ui.message(_("Selected item is not a folder"))
			self._restoreSpeech()
			return
		
		# Start background calculation
		calculation_thread = threading.Thread(
			target=self._calculate_folder_info,
			args=(folder_path,)
		)
		calculation_thread.daemon = True
		calculation_thread.start()
	
	def _restoreSpeech(self):
		# Restore speech after a longer delay to ensure all focus events are processed
		core.callLater(800, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))
	
	def _calculate_folder_info(self, folder_path):
		try:
			subfolder_count = 0
			file_count = 0
			
			for root, dirs, files in os.walk(folder_path):
				subfolder_count += len(dirs)
				file_count += len(files)
			
			message = _("{subfolders} subfolders and {files} files").format(
				subfolders=subfolder_count,
				files=file_count
			)
			
			# Cancel any speech that might have been triggered (like window title)
			wx.CallAfter(speech.cancelSpeech)
			wx.CallAfter(ui.message, message)
			wx.CallAfter(self._restoreSpeech)
			
		except Exception as e:
			log.error(f"Error calculating folder info: {e}")
			wx.CallAfter(ui.message, _("Error calculating folder info"))
			wx.CallAfter(self._restoreSpeech)