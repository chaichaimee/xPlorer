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
		self._stop_walk = False

	def cleanup(self):
		self._stop_walk = True

	def get_folder_info(self):
		speech.cancelSpeech()
		self.plugin.manager.suppressAllAnnouncements = True
		self._stop_walk = False
		
		def delayed_retrieve():
			selected_items, _ignore = self.plugin._getSelectedItems()
			if not selected_items:
				wx.CallAfter(ui.message, _("No item selected"))
				self._restore_speech()
				return
			
			if len(selected_items) > 1:
				wx.CallAfter(ui.message, _("Please select only one folder"))
				self._restore_speech()
				return
			
			folder_path = selected_items[0][1]
			if not os.path.isdir(folder_path):
				wx.CallAfter(ui.message, _("Selected item is not a folder"))
				self._restore_speech()
				return
			
			threading.Thread(target=self._calculate_folder_info_streaming, args=(folder_path,), daemon=True).start()
		
		core.callLater(500, delayed_retrieve)

	def _restore_speech(self):
		core.callLater(800, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))

	def _calculate_folder_info_streaming(self, folder_path):
		try:
			subfolder_count = 0
			file_count = 0
			for root, dirs, files in os.walk(folder_path):
				if self._stop_walk:
					break
				subfolder_count += len(dirs)
				file_count += len(files)
			
			message = _("{subfolders} subfolders and {files} files").format(
				subfolders=subfolder_count,
				files=file_count
			)
			wx.CallAfter(speech.cancelSpeech)
			wx.CallAfter(ui.message, message)
			wx.CallAfter(self._restore_speech)
		except Exception as e:
			log.error(f"Error calculating folder info: {e}")
			wx.CallAfter(ui.message, _("Error calculating folder info"))
			wx.CallAfter(self._restore_speech)