# batchRenameManager.py

import wx
import os
import re
import json
import datetime
import threading
import gui
import gui.guiHelper
import ui
import tones
import addonHandler
import core
from logHandler import log
from .folderTools import CONFIG_DIR

addonHandler.initTranslation()

UNDO_RENAME_FILE = os.path.join(CONFIG_DIR, "batch_rename_undo.json")


def _collectFilesRecursively(rootPath):
	"""Walk rootPath and return every regular file found within it, including
	files inside any subfolders. Pure filesystem logic with no NVDA API
	calls, kept separate from the dialog/manager classes so it can be
	exercised directly with pytest outside NVDA."""
	collectedFiles = []
	for currentDir, subDirNames, fileNames in os.walk(rootPath):
		subDirNames.sort()
		for fileName in sorted(fileNames):
			collectedFiles.append(os.path.join(currentDir, fileName))
	return collectedFiles


class BatchRenameDialog(wx.Dialog):
	"""Accessible multi-rename dialog. The preview list updates live as the
	user edits the pattern, and every list is a plain wx.ListBox so NVDA
	reads the current item normally on focus and on each arrow press."""

	def __init__(self, parent, selected_files, renameManager=None):
		super().__init__(parent, title=_("Multi-Rename Tool"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.selected_files = list(selected_files)
		self.new_names = list(selected_files)
		self.renameManager = renameManager
		self._init_ui()
		self.Bind(wx.EVT_CLOSE, self._on_close)

	def _init_ui(self):
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		mode_label = wx.StaticText(self, label=_("Rename mode:"))
		s_helper.addItem(mode_label)
		self.mode_combo = wx.ComboBox(
			self,
			choices=[
				_("Find and replace"),
				_("Tag pattern ([C] counter, [D] date, [N] name, [E] extension)"),
			],
			style=wx.CB_READONLY,
		)
		self.mode_combo.SetSelection(0)
		s_helper.addItem(self.mode_combo)

		find_label = wx.StaticText(self, label=_("Text to find:"))
		s_helper.addItem(find_label)
		self.find_text = wx.TextCtrl(self)
		s_helper.addItem(self.find_text)

		replace_label = wx.StaticText(self, label=_("Replace with:"))
		s_helper.addItem(replace_label)
		self.replace_text = wx.TextCtrl(self)
		s_helper.addItem(self.replace_text)

		self.regex_checkbox = wx.CheckBox(self, label=_("Use regular expressions (regex)"))
		s_helper.addItem(self.regex_checkbox)

		pattern_label = wx.StaticText(self, label=_("Tag pattern (e.g. [N]_[C].[E]):"))
		s_helper.addItem(pattern_label)
		self.pattern_text = wx.TextCtrl(self, value="[N]_[C].[E]")
		s_helper.addItem(self.pattern_text)

		counter_label = wx.StaticText(self, label=_("Counter start value:"))
		s_helper.addItem(counter_label)
		self.counter_start = wx.SpinCtrl(self, min=0, max=999999, initial=1)
		s_helper.addItem(self.counter_start)

		preview_label = wx.StaticText(self, label=_("Preview of new file names:"))
		s_helper.addItem(preview_label)
		self.preview_list = wx.ListBox(self, size=(500, 200))
		s_helper.addItem(self.preview_list, flag=wx.EXPAND, proportion=1)

		btn_sizer = wx.StdDialogButtonSizer()
		self.apply_btn = wx.Button(self, wx.ID_OK, label=_("Apply"))
		btn_sizer.AddButton(self.apply_btn)
		self.cancel_btn = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))
		btn_sizer.AddButton(self.cancel_btn)
		btn_sizer.Realize()
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)

		self.undo_btn = wx.Button(self, label=_("Undo Last Rename"))
		self.undo_btn.Enable(bool(self.renameManager and self.renameManager.hasUndoAvailable()))
		s_helper.addItem(self.undo_btn, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()

		self.mode_combo.Bind(wx.EVT_COMBOBOX, self._on_mode_change)
		self.find_text.Bind(wx.EVT_TEXT, self._on_text_change)
		self.replace_text.Bind(wx.EVT_TEXT, self._on_text_change)
		self.regex_checkbox.Bind(wx.EVT_CHECKBOX, self._on_text_change)
		self.pattern_text.Bind(wx.EVT_TEXT, self._on_text_change)
		self.counter_start.Bind(wx.EVT_SPINCTRL, self._on_text_change)
		self.apply_btn.Bind(wx.EVT_BUTTON, self._on_apply)
		self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
		self.undo_btn.Bind(wx.EVT_BUTTON, self._on_undo)

		self._on_mode_change(None)
		self._update_preview()
		self.find_text.SetFocus()

	def _on_undo(self, event):
		if self.renameManager:
			self.renameManager.undoLastRename()
		self.EndModal(wx.ID_CANCEL)

	def _on_mode_change(self, event):
		usePattern = self.mode_combo.GetSelection() == 1
		self.find_text.Enable(not usePattern)
		self.replace_text.Enable(not usePattern)
		self.regex_checkbox.Enable(not usePattern)
		self.pattern_text.Enable(usePattern)
		self.counter_start.Enable(usePattern)
		self._update_preview()
		if event:
			event.Skip()

	def _applyFindReplace(self, oldName):
		findValue = self.find_text.GetValue()
		replaceValue = self.replace_text.GetValue()
		if not findValue:
			return oldName
		if self.regex_checkbox.GetValue():
			try:
				return re.sub(findValue, replaceValue, oldName)
			except re.error as e:
				log.debug(f"xPlorer: batch rename regex error: {e}")
				return oldName
		return oldName.replace(findValue, replaceValue)

	def _applyTagPattern(self, filePath, index):
		pattern = self.pattern_text.GetValue()
		baseName = os.path.basename(filePath)
		name, ext = os.path.splitext(baseName)
		extNoDot = ext[1:] if ext.startswith(".") else ext
		counterValue = self.counter_start.GetValue() + index
		try:
			modTime = os.path.getmtime(filePath)
			dateText = datetime.datetime.fromtimestamp(modTime).strftime("%Y-%m-%d")
		except OSError as e:
			log.debug(f"xPlorer: batch rename could not read mtime for {filePath}: {e}")
			dateText = ""

		result = pattern
		result = result.replace("[C]", str(counterValue))
		result = result.replace("[D]", dateText)
		result = result.replace("[N]", name)
		result = result.replace("[E]", extNoDot)
		return result

	def _update_preview(self):
		self.preview_list.Clear()
		usePattern = self.mode_combo.GetSelection() == 1
		newNames = []

		for index, filePath in enumerate(self.selected_files):
			oldName = os.path.basename(filePath)
			if usePattern:
				candidate = self._applyTagPattern(filePath, index)
				if not os.path.splitext(candidate)[1]:
					_ignoredName, ext = os.path.splitext(oldName)
					candidate += ext
			else:
				name, ext = os.path.splitext(oldName)
				candidate = self._applyFindReplace(name) + ext

			candidate = candidate.strip()
			if not candidate:
				candidate = f"file_{index + 1}{os.path.splitext(oldName)[1]}"
			newNames.append(candidate)

		seen = set()
		for index, candidateName in enumerate(newNames):
			base, ext = os.path.splitext(candidateName)
			counter = 1
			finalName = candidateName
			while finalName in seen:
				finalName = f"{base}_{counter}{ext}"
				counter += 1
			seen.add(finalName)
			newNames[index] = finalName

		self.new_names = newNames
		self.preview_list.Set(newNames)

	def _on_text_change(self, event):
		self._update_preview()
		if event:
			event.Skip()

	def _on_apply(self, event):
		hasChanges = any(
			os.path.basename(filePath) != newName
			for filePath, newName in zip(self.selected_files, self.new_names)
		)
		if not hasChanges:
			ui.message(_("No changes to apply"))
			self.EndModal(wx.ID_CANCEL)
			return

		successCount = 0
		errorMessages = []
		appliedMapping = []
		for filePath, newName in zip(self.selected_files, self.new_names):
			oldName = os.path.basename(filePath)
			if oldName == newName:
				continue
			dirPath = os.path.dirname(filePath)
			newPath = os.path.join(dirPath, newName)
			try:
				if os.path.exists(newPath) and newPath != filePath:
					errorMessages.append(_("File already exists: {0}").format(newName))
					continue
				os.rename(filePath, newPath)
				appliedMapping.append({"original": filePath, "renamed": newPath})
				successCount += 1
			except OSError as e:
				errorMessages.append(_("Error renaming {0} to {1}: {2}").format(oldName, newName, str(e)))

		if successCount > 0:
			tones.beep(1000, 300)
			ui.message(_("Successfully renamed {0} files").format(successCount))
			if self.renameManager:
				self.renameManager.saveUndoMapping(appliedMapping)
				self.renameManager.logOperation(_("Renamed {0} files").format(successCount))
		if errorMessages:
			shown = errorMessages[:3]
			for msg in shown:
				ui.message(msg)
			if len(errorMessages) > 3:
				ui.message(_("...and {0} more errors").format(len(errorMessages) - 3))

		self.EndModal(wx.ID_OK)

	def _on_cancel(self, event):
		self.EndModal(wx.ID_CANCEL)

	def _on_close(self, event):
		self.EndModal(wx.ID_CANCEL)


class BatchRenameManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self.dialog = None
		self._isActive = True

	def cleanup(self):
		self._isActive = False
		if self.dialog:
			try:
				self.dialog.Destroy()
			except RuntimeError:
				pass
			self.dialog = None

	def show_dialog(self, retryCount=0):
		def handleSelection(selected_items, _hwnd):
			selectedFolders = [path for _name, path in selected_items if os.path.isdir(path)] if selected_items else []
			selectedFiles = [path for _name, path in selected_items if os.path.isfile(path)] if selected_items else []

			if selectedFolders:
				# A folder is part of the selection: scan it (and any
				# subfolders within it) for files, in addition to any
				# individually selected files.
				self._collectFromFoldersInBackground(selectedFolders, selectedFiles, retryCount)
				return

			if selectedFiles:
				self._finalizeShowDialog(selectedFiles, retryCount)
				return

			def afterPath(currentPath):
				if not currentPath or not os.path.isdir(currentPath):
					self._finalizeShowDialog([], retryCount)
					return
				# Nothing usable was selected: fall back to everything in
				# the folder currently open in Explorer, scanning its
				# subfolders too rather than only the top level.
				self._collectFromFoldersInBackground([currentPath], [], retryCount)

			self.plugin._getCurrentPathFromExplorerAsync(afterPath)

		self.plugin._getSelectedItemsAsync(handleSelection)

	def _collectFromFoldersInBackground(self, folderPaths, extraFiles, retryCount):
		# A recursive folder scan can be slow on a large tree or a network
		# share, so it must never run synchronously on the main thread
		# (NVDABuilderSkill 5.1). The scan itself touches only the
		# filesystem, never NVDA/COM APIs, so it's safe on a plain
		# background thread; the result is marshaled back via wx.CallAfter.
		def worker():
			collectedPaths = list(extraFiles)
			for folderPath in folderPaths:
				try:
					collectedPaths.extend(_collectFilesRecursively(folderPath))
				except OSError as e:
					log.error(f"Error scanning folder for batch rename: {e}")
			if self._isActive:
				wx.CallAfter(self._finalizeShowDialog, collectedPaths, retryCount)

		threading.Thread(target=worker, daemon=True).start()

	def _finalizeShowDialog(self, paths, retryCount):
		if not paths:
			if retryCount < 5:
				core.callLater(100, lambda: self.show_dialog(retryCount + 1))
				return
			ui.message(_("No files selected or found in the current folder"))
			return

		def do_show():
			self.dialog = BatchRenameDialog(gui.mainFrame, paths, renameManager=self)
			gui.mainFrame.prePopup()
			try:
				self.dialog.ShowModal()
			finally:
				gui.mainFrame.postPopup()
				try:
					self.dialog.Destroy()
				except RuntimeError:
					pass
				self.dialog = None

		wx.CallAfter(do_show)

	def logOperation(self, description):
		operationHistory = getattr(self.plugin, "operationHistory", None)
		if operationHistory:
			operationHistory.addEntry(description)

	def saveUndoMapping(self, appliedMapping):
		if not appliedMapping:
			return
		try:
			if not os.path.exists(CONFIG_DIR):
				os.makedirs(CONFIG_DIR)
			payload = {
				"timestamp": datetime.datetime.now().isoformat(),
				"mapping": appliedMapping,
			}
			with open(UNDO_RENAME_FILE, "w", encoding="utf-8") as f:
				json.dump(payload, f, indent=2, ensure_ascii=False)
		except OSError as e:
			log.error(f"Error saving batch rename undo mapping: {e}")

	def hasUndoAvailable(self):
		return os.path.exists(UNDO_RENAME_FILE)

	def undoLastRename(self):
		if not os.path.exists(UNDO_RENAME_FILE):
			ui.message(_("No rename operation to undo"))
			return

		try:
			with open(UNDO_RENAME_FILE, "r", encoding="utf-8") as f:
				payload = json.load(f)
		except (OSError, ValueError) as e:
			log.error(f"Error reading batch rename undo mapping: {e}")
			ui.message(_("Unable to read the last rename operation"))
			return

		mapping = payload.get("mapping", [])
		if not mapping:
			ui.message(_("No rename operation to undo"))
			return

		revertedCount = 0
		errorMessages = []
		for entry in reversed(mapping):
			originalPath = entry.get("original")
			renamedPath = entry.get("renamed")
			if not originalPath or not renamedPath:
				continue
			try:
				if not os.path.exists(renamedPath):
					errorMessages.append(_("Missing file, cannot undo: {0}").format(os.path.basename(renamedPath)))
					continue
				if os.path.exists(originalPath) and originalPath != renamedPath:
					errorMessages.append(_("Original name is taken, cannot undo: {0}").format(os.path.basename(originalPath)))
					continue
				os.rename(renamedPath, originalPath)
				revertedCount += 1
			except OSError as e:
				errorMessages.append(_("Error undoing rename for {0}: {1}").format(os.path.basename(renamedPath), str(e)))

		if revertedCount > 0:
			tones.beep(600, 300)
			ui.message(_("Reverted {0} file names").format(revertedCount))
			self.logOperation(_("Undid rename of {0} files").format(revertedCount))
		if errorMessages:
			shown = errorMessages[:3]
			for msg in shown:
				ui.message(msg)
			if len(errorMessages) > 3:
				ui.message(_("...and {0} more errors").format(len(errorMessages) - 3))

		if revertedCount == len(mapping):
			try:
				os.remove(UNDO_RENAME_FILE)
			except OSError as e:
				log.debug(f"xPlorer: could not remove undo mapping file after full undo: {e}")
