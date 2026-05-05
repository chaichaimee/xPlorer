# folderInfo.py

import os
import threading
import wx
import ui
import addonHandler
import speech
import core
from logHandler import log

addonHandler.initTranslation()  # crucial for _()

class FolderInfoManager:
	def __init__(self, plugin):
		self.plugin = plugin

	def cleanup(self):
		pass

	def get_folder_info(self):
		speech.cancelSpeech()
		self.plugin.manager.suppressAllAnnouncements = True
		
		def delayed_retrieve():
			selected_items, _ = self.plugin._getSelectedItems()
			if not selected_items:
				wx.CallAfter(ui.message, _("No item selected"))
				wx.CallAfter(self._restoreSpeech)
				return
			
			if len(selected_items) > 1:
				wx.CallAfter(ui.message, _("Please select only one folder"))
				wx.CallAfter(self._restoreSpeech)
				return
			
			folder_path = selected_items[0][1]
			if not os.path.isdir(folder_path):
				wx.CallAfter(ui.message, _("Selected item is not a folder"))
				wx.CallAfter(self._restoreSpeech)
				return
			
			threading.Thread(target=self._calculate_folder_info, args=(folder_path,), daemon=True).start()
		
		core.callLater(500, delayed_retrieve)  # longer delay to avoid transition

	def _restoreSpeech(self):
		core.callLater(800, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))

	def _calculate_folder_info(self, folder_path):
		try:
			subfolder_count = 0
			file_count = 0
			for root, dirs, files in os.walk(folder_path):
				if not self.plugin.manager.suppressAllAnnouncements:  # optional check
					pass
				subfolder_count += len(dirs)
				file_count += len(files)
			
			message = _("{subfolders} subfolders and {files} files").format(
				subfolders=subfolder_count,
				files=file_count
			)
			wx.CallAfter(speech.cancelSpeech)
			wx.CallAfter(ui.message, message)
			wx.CallAfter(self._restoreSpeech)
		except Exception as e:
			log.error(f"Error calculating folder info: {e}")
			wx.CallAfter(ui.message, _("Error calculating folder info"))
			wx.CallAfter(self._restoreSpeech)