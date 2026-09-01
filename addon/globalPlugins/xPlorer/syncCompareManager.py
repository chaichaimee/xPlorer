# syncCompareManager.py

import wx
import os
import threading
import shutil
import gui
import gui.guiHelper
import ui
import core
import tones
import addonHandler
from logHandler import log

addonHandler.initTranslation()

_LEFT_ONLY = _("Only in left")
_RIGHT_ONLY = _("Only in right")
_DIFFERENT = _("Different (size/date)")
_IDENTICAL = _("Identical")


class SyncCompareDialog(wx.Dialog):
	"""Compares two folder trees by relative path and reports, per file,
	whether it exists only on one side or differs on both. This is a
	read-only report - nothing is copied or deleted automatically, since
	silently reconciling two folders is exactly the kind of surprise
	behaviour that should never happen without the user reviewing and
	choosing an action first."""

	def __init__(self, parent, leftPath, rightPath):
		super().__init__(parent, title=_("Compare Folders"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.leftPath = leftPath
		self.rightPath = rightPath
		self.results = []
		self._compareThread = None
		self._compareCancelled = threading.Event()
		self._init_ui()
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self._start_compare()

	def _init_ui(self):
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		summary_label = wx.StaticText(self, label=_("Left: {0}   Right: {1}").format(self.leftPath, self.rightPath))
		s_helper.addItem(summary_label)

		self.status_label = wx.StaticText(self, label=_("Comparing..."))
		s_helper.addItem(self.status_label)

		self.list_ctrl = wx.ListCtrl(self, size=(650, 350), style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
		self.list_ctrl.InsertColumn(0, _("Relative Path"), width=320)
		self.list_ctrl.InsertColumn(1, _("Status"), width=180)
		s_helper.addItem(self.list_ctrl, flag=wx.EXPAND, proportion=1)

		btn_sizer = wx.StdDialogButtonSizer()
		self.copy_btn = wx.Button(self, wx.ID_OK, label=_("Copy Selected to Right"))
		btn_sizer.AddButton(self.copy_btn)
		self.close_btn = wx.Button(self, wx.ID_CANCEL, label=_("Close"))
		btn_sizer.AddButton(self.close_btn)
		btn_sizer.Realize()
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()

		self.copy_btn.Bind(wx.EVT_BUTTON, self._on_copy_selected)
		self.close_btn.Bind(wx.EVT_BUTTON, self._on_close_button)
		self.list_ctrl.SetFocus()

	def _start_compare(self):
		self._compareThread = threading.Thread(target=self._compare_worker, daemon=True)
		self._compareThread.start()

	def _buildRelativeFileMap(self, rootPath):
		fileMap = {}
		for currentDir, _dirNames, fileNames in os.walk(rootPath):
			if self._compareCancelled.is_set():
				return fileMap
			for fileName in fileNames:
				fullPath = os.path.join(currentDir, fileName)
				relativePath = os.path.relpath(fullPath, rootPath)
				try:
					stat = os.stat(fullPath)
					fileMap[relativePath] = (stat.st_size, int(stat.st_mtime))
				except OSError as e:
					log.debug(f"xPlorer: sync compare could not stat {fullPath}: {e}")
		return fileMap

	def _compare_worker(self):
		try:
			leftMap = self._buildRelativeFileMap(self.leftPath)
			if self._compareCancelled.is_set():
				return
			rightMap = self._buildRelativeFileMap(self.rightPath)
			if self._compareCancelled.is_set():
				return

			results = []
			allRelativePaths = set(leftMap.keys()) | set(rightMap.keys())
			for relativePath in sorted(allRelativePaths):
				inLeft = relativePath in leftMap
				inRight = relativePath in rightMap
				if inLeft and not inRight:
					results.append((relativePath, _LEFT_ONLY))
				elif inRight and not inLeft:
					results.append((relativePath, _RIGHT_ONLY))
				elif leftMap[relativePath] != rightMap[relativePath]:
					results.append((relativePath, _DIFFERENT))
			wx.CallAfter(self._on_compare_done, results)
		except OSError as e:
			log.debug(f"xPlorer: sync compare failed: {e}")
			wx.CallAfter(self._on_compare_done, [])

	def _on_compare_done(self, results):
		self.results = results
		self.status_label.SetLabel(_("{0} differences found").format(len(results)))
		self.list_ctrl.DeleteAllItems()
		for relativePath, status in results:
			index = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), relativePath)
			self.list_ctrl.SetItem(index, 1, status)

	def _on_copy_selected(self, event):
		selectedIndex = self.list_ctrl.GetFirstSelected()
		if selectedIndex == -1:
			ui.message(_("No item selected"))
			return
		if selectedIndex >= len(self.results):
			return
		relativePath, status = self.results[selectedIndex]
		if status == _RIGHT_ONLY:
			ui.message(_("This file only exists on the right side"))
			return

		sourcePath = os.path.join(self.leftPath, relativePath)
		destPath = os.path.join(self.rightPath, relativePath)
		try:
			os.makedirs(os.path.dirname(destPath), exist_ok=True)
			shutil.copy2(sourcePath, destPath)
			tones.beep(1000, 200)
			ui.message(_("Copied {0}").format(relativePath))
			self.list_ctrl.DeleteItem(selectedIndex)
			del self.results[selectedIndex]
		except OSError as e:
			log.debug(f"xPlorer: sync compare copy failed: {e}")
			ui.message(_("Error copying {0}").format(relativePath))

	def _on_close_button(self, event):
		self.EndModal(wx.ID_CANCEL)

	def _on_close(self, event):
		self._compareCancelled.set()
		self.EndModal(wx.ID_CANCEL)


class SyncCompareManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self.dialog = None
		self._pendingLeftPath = None

	def cleanup(self):
		if self.dialog:
			try:
				self.dialog._compareCancelled.set()
				self.dialog.Destroy()
			except RuntimeError:
				pass
			self.dialog = None

	def markLeftFolder(self):
		def handlePath(currentPath):
			if not currentPath or not os.path.isdir(currentPath):
				ui.message(_("No Explorer folder detected"))
				return
			self._pendingLeftPath = currentPath
			ui.message(_("Marked as left folder: {0}. Navigate to the right folder and run compare again").format(currentPath))

		self.plugin._getCurrentPathFromExplorerAsync(handlePath)

	def compareWithCurrentFolder(self):
		if not self._pendingLeftPath:
			self.markLeftFolder()
			return

		def handlePath(rightPath):
			if not rightPath or not os.path.isdir(rightPath):
				ui.message(_("No Explorer folder detected"))
				return

			leftPath = self._pendingLeftPath
			self._pendingLeftPath = None

			if os.path.normcase(leftPath) == os.path.normcase(rightPath):
				ui.message(_("Left and right folders are the same"))
				return

			def do_show():
				self.dialog = SyncCompareDialog(gui.mainFrame, leftPath, rightPath)
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

