# flatViewManager.py

import wx
import os
import threading
import subprocess
import gui
import gui.guiHelper
import ui
import core
import tones
import addonHandler
from logHandler import log

addonHandler.initTranslation()

_SCAN_CAP = 50000

class FlatViewDialog(wx.Dialog):
	def __init__(self, parent, rootPath):
		super().__init__(parent, title=_("Flat View: {0}").format(rootPath),
						 style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.rootPath = rootPath
		self.allEntries = []
		self.filteredEntries = []
		self._wasCapped = False
		self._scanThread = None
		self._scanCancelled = threading.Event()
		self._filterGeneration = 0
		self._init_ui()
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self._start_scan()

	def _init_ui(self):
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		filter_label = wx.StaticText(self, label=_("Filter (type to narrow the list):"))
		s_helper.addItem(filter_label)
		self.filter_ctrl = s_helper.addItem(wx.TextCtrl(self))

		self.status_label = wx.StaticText(self, label=_("Scanning..."))
		s_helper.addItem(self.status_label)

		self.list_ctrl = wx.ListCtrl(self, size=(600, 350), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
		self.list_ctrl.InsertColumn(0, _("Name"), width=220)
		self.list_ctrl.InsertColumn(1, _("Folder"), width=250)
		self.list_ctrl.InsertColumn(2, _("Size"), width=90)
		s_helper.addItem(self.list_ctrl, flag=wx.EXPAND, proportion=1)

		btn_sizer = wx.StdDialogButtonSizer()
		self.open_btn = wx.Button(self, wx.ID_OK, label=_("Open Containing Folder"))
		btn_sizer.AddButton(self.open_btn)
		self.close_btn = wx.Button(self, wx.ID_CANCEL, label=_("Close"))
		btn_sizer.AddButton(self.close_btn)
		btn_sizer.Realize()
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()

		self.filter_ctrl.Bind(wx.EVT_TEXT, self._on_filter_change)
		self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate_item)
		self.open_btn.Bind(wx.EVT_BUTTON, self._on_open_containing_folder)
		self.close_btn.Bind(wx.EVT_BUTTON, self._on_close_button)
		self.filter_ctrl.SetFocus()

	def _start_scan(self):
		self._scanThread = threading.Thread(target=self._scan_worker, daemon=True)
		self._scanThread.start()

	def _scan_worker(self):
		entries = []
		try:
			for currentDir, dirNames, fileNames in os.walk(self.rootPath):
				if self._scanCancelled.is_set():
					return
				for fileName in fileNames:
					fullPath = os.path.join(currentDir, fileName)
					try:
						sizeBytes = os.path.getsize(fullPath)
					except OSError:
						sizeBytes = 0
					relativeFolder = os.path.relpath(currentDir, self.rootPath)
					if relativeFolder == ".":
						relativeFolder = ""
					entries.append((fileName, relativeFolder, sizeBytes, fullPath))
					if len(entries) >= _SCAN_CAP:
						wx.CallAfter(self._on_scan_done, entries, True)
						return
		except OSError as e:
			log.debug(f"xPlorer: flat view scan failed: {e}")
		if not self._scanCancelled.is_set():
			wx.CallAfter(self._on_scan_done, entries, False)

	def _on_scan_done(self, entries, wasCapped):
		self.allEntries = entries
		self._wasCapped = wasCapped
		self._apply_filter("", announce_all_names=True)

	def _formatSize(self, sizeBytes):
		for unit in ("B", "KB", "MB", "GB"):
			if sizeBytes < 1024:
				return f"{sizeBytes:.0f} {unit}" if unit == "B" else f"{sizeBytes:.1f} {unit}"
			sizeBytes /= 1024
		return f"{sizeBytes:.1f} TB"

	def _apply_filter(self, filterText, announce_all_names=False, announce=True):
		filterText = filterText.lower()
		if filterText:
			self.filteredEntries = [e for e in self.allEntries if filterText in e[0].lower()]
		else:
			self.filteredEntries = self.allEntries

		self.list_ctrl.DeleteAllItems()
		for fileName, relativeFolder, sizeBytes, _fullPath in self.filteredEntries[:5000]:
			index = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), fileName)
			self.list_ctrl.SetItem(index, 1, relativeFolder or _("(root)"))
			self.list_ctrl.SetItem(index, 2, self._formatSize(sizeBytes))

		self._updateStatusLabel(filterText)
		if announce_all_names:
			self._announceAllFileNames()
		elif announce:
			ui.message(self._buildCountMessage(filterText))

	def _updateStatusLabel(self, filterText):
		count = len(self.filteredEntries)
		if filterText:
			statusText = _("{0} matches found").format(count)
		else:
			statusText = _("{0} files found").format(count)
			if self._wasCapped:
				statusText += " " + _("(list capped at {0} - refine your folder selection)").format(_SCAN_CAP)
		self.status_label.SetLabel(statusText)

	def _buildCountMessage(self, filterText):
		count = len(self.filteredEntries)
		if filterText:
			return _("{0} matches found").format(count)
		message = _("{0} files found").format(count)
		if self._wasCapped:
			message += " " + _("(list capped at {0} - refine your folder selection)").format(_SCAN_CAP)
		return message

	def _announceAllFileNames(self):
		if not self.filteredEntries:
			ui.message(_("No files found"))
			return
		names = [entry[0] for entry in self.filteredEntries]
		message = _("Files found: {names}").format(names=", ".join(names))
		ui.message(message)

	def _on_filter_change(self, event):
		# The list and status label still update on every keystroke, but the
		# spoken count is held off until typing pauses - announcing on each
		# character was what caused speech to lag behind while typing.
		self._filterGeneration += 1
		currentGeneration = self._filterGeneration
		currentText = self.filter_ctrl.GetValue()
		self._apply_filter(currentText, announce=False)
		core.callLater(500, self._announceFilterResultIfCurrent, currentGeneration, currentText)
		event.Skip()

	def _announceFilterResultIfCurrent(self, generation, filterText):
		if generation != self._filterGeneration:
			return
		try:
			ui.message(self._buildCountMessage(filterText))
		except RuntimeError:
			pass

	def _on_activate_item(self, event):
		selectedIndex = self.list_ctrl.GetFirstSelected()
		if selectedIndex == -1:
			ui.message(_("No item selected"))
			return
		if selectedIndex >= len(self.filteredEntries):
			return
		_name, _relFolder, _size, fullPath = self.filteredEntries[selectedIndex]
		try:
			os.startfile(fullPath)
		except OSError as e:
			log.debug(f"xPlorer: could not open file from flat view: {e}")
			ui.message(_("Could not open {0}").format(_name))

	def _on_open_containing_folder(self, event):
		selectedIndex = self.list_ctrl.GetFirstSelected()
		if selectedIndex == -1:
			ui.message(_("No item selected"))
			return
		if selectedIndex >= len(self.filteredEntries):
			return
		_name, _relFolder, _size, fullPath = self.filteredEntries[selectedIndex]
		try:
			subprocess.Popen(["explorer.exe", "/select,", fullPath])
		except OSError as e:
			log.debug(f"xPlorer: could not open containing folder: {e}")
			ui.message(_("Could not open the containing folder"))

	def _on_close_button(self, event):
		self.EndModal(wx.ID_CANCEL)

	def _on_close(self, event):
		self._scanCancelled.set()
		self.EndModal(wx.ID_CANCEL)

class FlatViewManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self.dialog = None

	def cleanup(self):
		if self.dialog:
			try:
				self.dialog._scanCancelled.set()
				self.dialog.Destroy()
			except RuntimeError:
				pass
			self.dialog = None

	def show_dialog(self):
		def handlePath(currentPath):
			if not currentPath or not os.path.isdir(currentPath):
				ui.message(_("No Explorer folder detected"))
				return

			def do_show():
				self.dialog = FlatViewDialog(gui.mainFrame, currentPath)
				gui.mainFrame.prePopup()
				try:
					self.dialog.ShowModal()
				finally:
					gui.mainFrame.postPopup()
					if self.dialog:
						self.dialog.Destroy()
					self.dialog = None

			wx.CallAfter(do_show)

		self.plugin._getCurrentPathFromExplorerAsync(handlePath)

