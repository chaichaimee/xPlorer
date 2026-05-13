# selectionManager.py

import ui
import api
import core
from logHandler import log
import addonHandler

addonHandler.initTranslation()

class SelectionManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self._invert_batch_index = 0
		self._invert_items = []
		self._invert_selected_set = set()
		self._invert_document = None
		self._invert_total = 0

	def cleanup(self):
		self._invert_items = []
		self._invert_selected_set.clear()
		self._invert_document = None

	def invertSelection(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			return
			
		try:
			shellWindow = self.plugin._getActiveExplorerWindow()
			if not shellWindow:
				ui.message(_("No active File Explorer window found"))
				return
				
			document = shellWindow.document
			if not hasattr(document, 'Folder'):
				ui.message(_("Unable to get folder view"))
				return
				
			folder = document.Folder
			items = folder.Items()
			total_count = items.Count
			
			if total_count == 0:
				ui.message(_("No items in folder"))
				return
				
			selected_paths = set()
			sel_items = document.SelectedItems()
			for i in range(sel_items.Count):
				selected_paths.add(sel_items.Item(i).Path)
			
			if total_count > 300:
				ui.message(_("Processing {count} items in background...").format(count=total_count))
			
			self._invert_items = []
			for i in range(total_count):
				self._invert_items.append(items.Item(i))
			self._invert_selected_set = selected_paths
			self._invert_document = document
			self._invert_batch_index = 0
			self._invert_total = total_count
			self._invert_batch_process()
				
		except Exception as e:
			log.error(f"Error in invertSelection: {e}")
			ui.message(_("Error inverting selection"))

	def _invert_batch_process(self):
		BATCH_SIZE = 80
		start = self._invert_batch_index
		end = min(start + BATCH_SIZE, len(self._invert_items))
		
		for i in range(start, end):
			item = self._invert_items[i]
			if item.Path in self._invert_selected_set:
				self._invert_document.SelectItem(item, 0)
			else:
				self._invert_document.SelectItem(item, 1)
		
		self._invert_batch_index = end
		
		if self._invert_batch_index < len(self._invert_items):
			core.callLater(15, self._invert_batch_process)
		else:
			ui.message(_("Inverted selection completed"))
			self._invert_items = []
			self._invert_selected_set.clear()
			self._invert_document = None