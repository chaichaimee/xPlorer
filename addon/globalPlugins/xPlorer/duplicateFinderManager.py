# duplicateFinderManager.py

import os
import hashlib
import datetime
import threading
import ctypes
import ctypes.wintypes
import wx
import gui
import gui.guiHelper
import ui
import tones
import addonHandler
import core
from logHandler import log

addonHandler.initTranslation()

# Only the first chunk of each same-size file is hashed - reading whole
# multi-gigabyte files just to prove two of them differ would defeat the
# purpose of a fast scan. Files with matching size AND matching first-chunk
# hash are treated as duplicates, which is the same trade-off most desktop
# duplicate finders make.
HASH_CHUNK_SIZE = 65536

FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004


class _SHFILEOPSTRUCTW(ctypes.Structure):
	_fields_ = [
		("hwnd", ctypes.wintypes.HWND),
		("wFunc", ctypes.wintypes.UINT),
		("pFrom", ctypes.wintypes.LPCWSTR),
		("pTo", ctypes.wintypes.LPCWSTR),
		("fFlags", ctypes.wintypes.WORD),
		("fAnyOperationsAborted", ctypes.wintypes.BOOL),
		("hNameMappings", ctypes.wintypes.LPVOID),
		("lpszProgressTitle", ctypes.wintypes.LPCWSTR),
	]


def _sendToRecycleBin(paths):
	"""Moves the given files to the Recycle Bin (undoable) instead of a
	permanent os.remove, using the same shell API Explorer itself uses for
	a normal Delete key press."""
	if not paths:
		return True
	# pFrom must be a double-null-terminated string of null-separated paths.
	joinedPaths = "\0".join(paths) + "\0\0"
	operation = _SHFILEOPSTRUCTW()
	operation.hwnd = None
	operation.wFunc = FO_DELETE
	operation.pFrom = joinedPaths
	operation.pTo = None
	operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
	operation.fAnyOperationsAborted = False
	operation.hNameMappings = None
	operation.lpszProgressTitle = None
	result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
	return result == 0 and not operation.fAnyOperationsAborted


class DuplicateFinderDialog(wx.Dialog):
	"""Accessible two-pane view: a list of duplicate groups (by size and
	hash) on the left, and the individual files within the selected group
	on the right, each labelled with its folder and modified date so the
	user can tell them apart before choosing what to keep."""

	def __init__(self, parent, manager, duplicateGroups):
		super().__init__(parent, title=_("Duplicate Finder"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.manager = manager
		self.duplicateGroups = duplicateGroups
		self._init_ui()
		self.Bind(wx.EVT_CLOSE, self._on_close)

	def _init_ui(self):
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		summary_label = wx.StaticText(
			self,
			label=_("Found {0} duplicate groups").format(len(self.duplicateGroups))
			if self.duplicateGroups else _("No duplicate files found")
		)
		s_helper.addItem(summary_label)

		groups_label = wx.StaticText(self, label=_("Duplicate groups:"))
		s_helper.addItem(groups_label)
		groupChoices = [self._formatGroupLabel(group) for group in self.duplicateGroups]
		self.groups_list = wx.ListBox(self, choices=groupChoices, size=(500, 150))
		s_helper.addItem(self.groups_list, flag=wx.EXPAND, proportion=1)

		files_label = wx.StaticText(self, label=_("Files in this group:"))
		s_helper.addItem(files_label)
		self.files_list = wx.ListBox(self, choices=[], size=(500, 150))
		s_helper.addItem(self.files_list, flag=wx.EXPAND, proportion=1)

		action_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self.keep_newest_btn = wx.Button(self, label=_("Keep Newest"))
		action_sizer.Add(self.keep_newest_btn, 0, wx.ALL, 5)
		self.keep_oldest_btn = wx.Button(self, label=_("Keep Oldest"))
		action_sizer.Add(self.keep_oldest_btn, 0, wx.ALL, 5)
		self.keep_here_btn = wx.Button(self, label=_("Keep File in This Folder"))
		action_sizer.Add(self.keep_here_btn, 0, wx.ALL, 5)
		s_helper.addItem(action_sizer, flag=wx.ALIGN_CENTER)

		self.close_btn = wx.Button(self, wx.ID_CANCEL, label=_("Close"))
		s_helper.addItem(self.close_btn, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()

		self.groups_list.Bind(wx.EVT_LISTBOX, self._on_group_selected)
		self.keep_newest_btn.Bind(wx.EVT_BUTTON, lambda e: self._resolveGroup("newest"))
		self.keep_oldest_btn.Bind(wx.EVT_BUTTON, lambda e: self._resolveGroup("oldest"))
		self.keep_here_btn.Bind(wx.EVT_BUTTON, lambda e: self._resolveGroup("here"))
		self.close_btn.Bind(wx.EVT_BUTTON, self._on_close_button)

		if self.duplicateGroups:
			self.groups_list.SetSelection(0)
			self._refreshFilesList()
		self.groups_list.SetFocus()

	def _formatGroupLabel(self, group):
		fileCount = len(group["files"])
		return _("{0} copies, {1} each").format(fileCount, self.manager.formatSize(group["size"]))

	def _formatFileLabel(self, filePath):
		try:
			modTime = os.path.getmtime(filePath)
			dateText = datetime.datetime.fromtimestamp(modTime).strftime("%Y-%m-%d %H:%M")
		except OSError:
			dateText = _("unknown date")
		return f"{filePath} ({dateText})"

	def _refreshFilesList(self):
		selectionIndex = self.groups_list.GetSelection()
		if selectionIndex == wx.NOT_FOUND or selectionIndex >= len(self.duplicateGroups):
			self.files_list.Set([])
			return
		group = self.duplicateGroups[selectionIndex]
		self.files_list.Set([self._formatFileLabel(p) for p in group["files"]])

	def _on_group_selected(self, event):
		self._refreshFilesList()

	def _currentGroupIndex(self):
		selectionIndex = self.groups_list.GetSelection()
		if selectionIndex == wx.NOT_FOUND or not self.duplicateGroups:
			ui.message(_("No duplicate group selected"))
			return None
		return selectionIndex

	def _resolveGroup(self, strategy):
		groupIndex = self._currentGroupIndex()
		if groupIndex is None:
			return
		group = self.duplicateGroups[groupIndex]
		files = group["files"]
		if len(files) < 2:
			ui.message(_("Nothing to remove in this group"))
			return

		if strategy == "newest":
			keepPath = max(files, key=lambda p: self._safeMtime(p))
		elif strategy == "oldest":
			keepPath = min(files, key=lambda p: self._safeMtime(p))
		else:
			referenceFolder = self.manager.scanRootFolder
			matches = [p for p in files if os.path.dirname(p) == referenceFolder]
			if not matches:
				ui.message(_("None of the copies are directly in the scanned folder"))
				return
			keepPath = matches[0]

		toRemove = [p for p in files if p != keepPath]
		removedOk = _sendToRecycleBin(toRemove)
		if removedOk:
			tones.beep(700, 200)
			ui.message(_("Kept {0}, moved {1} duplicates to the Recycle Bin").format(os.path.basename(keepPath), len(toRemove)))
			self.manager.logOperation(_("Removed {0} duplicate copies of {1}").format(len(toRemove), os.path.basename(keepPath)))
			del self.duplicateGroups[groupIndex]
			self.groups_list.Delete(groupIndex)
			if self.groups_list.GetCount() > 0:
				newIndex = min(groupIndex, self.groups_list.GetCount() - 1)
				self.groups_list.SetSelection(newIndex)
			self._refreshFilesList()
		else:
			ui.message(_("Some duplicates could not be removed"))

	def _safeMtime(self, filePath):
		try:
			return os.path.getmtime(filePath)
		except OSError:
			return 0

	def _on_close_button(self, event):
		self.EndModal(wx.ID_CANCEL)

	def _on_close(self, event):
		self.EndModal(wx.ID_CANCEL)


class DuplicateFinderManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self.dialog = None
		self.scanRootFolder = None
		self._scanLock = threading.Lock()

	def cleanup(self):
		if self.dialog:
			try:
				self.dialog.Destroy()
			except RuntimeError:
				pass
			self.dialog = None

	def formatSize(self, sizeInBytes):
		fileOps = getattr(self.plugin, "fileOps", None)
		if fileOps:
			return fileOps._format_size(sizeInBytes)
		return f"{sizeInBytes} bytes"

	def logOperation(self, description):
		operationHistory = getattr(self.plugin, "operationHistory", None)
		if operationHistory:
			operationHistory.addEntry(description)

	def scanForDuplicates(self, retryCount=0):
		def handleSelection(selected_items, _hwnd):
			scopeFolder = None
			if selected_items:
				folderPaths = [path for _name, path in selected_items if os.path.isdir(path)]
				if folderPaths:
					scopeFolder = folderPaths[0]

			if scopeFolder:
				self._continueScan(scopeFolder, retryCount)
				return

			self.plugin._getCurrentPathFromExplorerAsync(lambda currentPath: self._continueScan(currentPath, retryCount))

		self.plugin._getSelectedItemsAsync(handleSelection)

	def _continueScan(self, scopeFolder, retryCount):
		if not scopeFolder or not os.path.isdir(scopeFolder):
			# Retries unconditionally rather than only while
			# _foregroundTransition is set - path resolution can come up
			# empty on its own (breadcrumb/shell-window lookups occasionally
			# need another pass), not just during that transition window.
			if retryCount < 5:
				core.callLater(100, lambda: self.scanForDuplicates(retryCount + 1))
				return
			ui.message(_("Select a folder, or open one in Explorer, to scan for duplicates"))
			return

		if not self._scanLock.acquire(blocking=False):
			ui.message(_("A duplicate scan is already running"))
			return

		self.scanRootFolder = scopeFolder
		ui.message(_("Scanning {0} for duplicates...").format(scopeFolder))
		threading.Thread(target=self._scanWorker, args=(scopeFolder,), daemon=True).start()

	def _scanWorker(self, scopeFolder):
		try:
			bySize = {}
			for root, _dirs, files in os.walk(scopeFolder):
				for fileName in files:
					filePath = os.path.join(root, fileName)
					try:
						fileSize = os.path.getsize(filePath)
					except OSError:
						continue
					if fileSize == 0:
						continue
					bySize.setdefault(fileSize, []).append(filePath)

			duplicateGroups = []
			for fileSize, pathsOfSize in bySize.items():
				if len(pathsOfSize) < 2:
					continue
				byHash = {}
				for filePath in pathsOfSize:
					fileHash = self._hashFirstChunk(filePath)
					if fileHash is None:
						continue
					byHash.setdefault(fileHash, []).append(filePath)
				for fileHash, pathsOfHash in byHash.items():
					if len(pathsOfHash) >= 2:
						duplicateGroups.append({"size": fileSize, "files": pathsOfHash})

			duplicateGroups.sort(key=lambda g: g["size"] * len(g["files"]), reverse=True)

			wx.CallAfter(self._showResults, duplicateGroups)
		except Exception as e:
			log.error(f"Error scanning for duplicates: {e}")
			wx.CallAfter(ui.message, _("Error scanning for duplicates"))
		finally:
			self._scanLock.release()

	def _hashFirstChunk(self, filePath):
		try:
			hasher = hashlib.sha1()
			with open(filePath, "rb") as f:
				chunk = f.read(HASH_CHUNK_SIZE)
				hasher.update(chunk)
			return hasher.hexdigest()
		except OSError as e:
			log.debug(f"xPlorer: could not hash {filePath}: {e}")
			return None

	def _showResults(self, duplicateGroups):
		if not duplicateGroups:
			ui.message(_("No duplicate files found"))
			return

		totalDuplicateFiles = sum(len(group["files"]) - 1 for group in duplicateGroups)
		ui.message(_("Found {0} duplicate groups, {1} redundant files").format(len(duplicateGroups), totalDuplicateFiles))

		def do_show():
			self.dialog = DuplicateFinderDialog(gui.mainFrame, self, duplicateGroups)
			gui.mainFrame.prePopup()
			try:
				self.dialog.ShowModal()
			finally:
				gui.mainFrame.postPopup()
				self.dialog.Destroy()
				self.dialog = None

		wx.CallAfter(do_show)

