# fileBasketManager.py

import os
import json
import shutil
import zipfile
import threading
import wx
import gui
import gui.guiHelper
import ui
import tones
import core
import addonHandler
from logHandler import log
from .folderTools import CONFIG_DIR

addonHandler.initTranslation()

BASKET_FILE = os.path.join(CONFIG_DIR, "file_basket.json")


class FileBasketDialog(wx.Dialog):
	"""Accessible view of the virtual file basket. Nothing here is copied
	or moved on disk until the user runs a bulk operation - the basket only
	tracks paths gathered from various locations."""

	def __init__(self, parent, basketManager):
		super().__init__(parent, title=_("File Basket Collection"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.basketManager = basketManager
		self._init_ui()
		self.Bind(wx.EVT_CLOSE, self._on_close)

	def _init_ui(self):
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		label = wx.StaticText(self, label=_("Items in the basket:"))
		s_helper.addItem(label)

		choices = self.basketManager.getPaths()
		self.pathListBox = wx.ListBox(self, choices=choices if choices else [_("Basket is empty")], size=(500, 250))
		s_helper.addItem(self.pathListBox, flag=wx.EXPAND, proportion=1)
		self.pathListBox.Bind(wx.EVT_KEY_DOWN, self._onListKeyDown)

		actionSizer = wx.BoxSizer(wx.HORIZONTAL)
		actionLabel = wx.StaticText(self, label=_("Action:"))
		actionSizer.Add(actionLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.actionCombo = wx.ComboBox(
			self, choices=[_("Copy"), _("Move"), _("Zip"), _("Mirror Copy")], style=wx.CB_READONLY
		)
		self.actionCombo.SetSelection(0)
		actionSizer.Add(self.actionCombo, 1, wx.EXPAND | wx.ALL, 5)
		s_helper.addItem(actionSizer, flag=wx.EXPAND)

		destSizer = wx.BoxSizer(wx.HORIZONTAL)
		destLabel = wx.StaticText(self, label=_("Destination:"))
		destSizer.Add(destLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
		self.destText = wx.TextCtrl(self)
		destSizer.Add(self.destText, 1, wx.EXPAND | wx.ALL, 5)
		self.browseBtn = wx.Button(self, label=_("Browse"))
		destSizer.Add(self.browseBtn, 0, wx.ALL, 5)
		s_helper.addItem(destSizer, flag=wx.EXPAND)

		executeSizer = wx.BoxSizer(wx.HORIZONTAL)
		self.executeBtn = wx.Button(self, label=_("Execute"))
		executeSizer.Add(self.executeBtn, 0, wx.ALL, 5)
		s_helper.addItem(executeSizer, flag=wx.ALIGN_CENTER)

		manageButtonSizer = wx.BoxSizer(wx.HORIZONTAL)
		self.removeBtn = wx.Button(self, label=_("Remove Selected"))
		manageButtonSizer.Add(self.removeBtn, 0, wx.ALL, 5)
		self.clearBtn = wx.Button(self, label=_("Clear Basket"))
		manageButtonSizer.Add(self.clearBtn, 0, wx.ALL, 5)
		self.closeBtn = wx.Button(self, id=wx.ID_CANCEL, label=_("Close"))
		manageButtonSizer.Add(self.closeBtn, 0, wx.ALL, 5)
		s_helper.addItem(manageButtonSizer, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()

		self.removeBtn.Bind(wx.EVT_BUTTON, self.onRemoveSelected)
		self.clearBtn.Bind(wx.EVT_BUTTON, self.onClearBasket)
		self.browseBtn.Bind(wx.EVT_BUTTON, self.onBrowseDestination)
		self.executeBtn.Bind(wx.EVT_BUTTON, self.onExecute)
		self.pathListBox.SetFocus()

	def _onListKeyDown(self, event):
		if event.GetKeyCode() == wx.WXK_DELETE:
			self.onRemoveSelected(event)
			return
		event.Skip()

	def _refreshList(self, focusIndex=None):
		choices = self.basketManager.getPaths()
		self.pathListBox.Set(choices if choices else [_("Basket is empty")])
		if choices and focusIndex is not None:
			newIndex = min(focusIndex, len(choices) - 1)
			self.pathListBox.SetSelection(newIndex)
		self.pathListBox.SetFocus()

	def onRemoveSelected(self, event):
		selectionIndex = self.pathListBox.GetSelection()
		if selectionIndex == wx.NOT_FOUND:
			ui.message(_("No item selected"))
			return

		selectedPath = self.pathListBox.GetString(selectionIndex)
		if not self.basketManager.removePath(selectedPath):
			return
		ui.message(_("Item removed"))
		self._refreshList(focusIndex=selectionIndex)

	def onClearBasket(self, event):
		self.basketManager.clearBasketWithAnnouncement()
		self._refreshList()

	def onBrowseDestination(self, event):
		dirDialog = wx.DirDialog(self, _("Select Destination Directory"), style=wx.DD_DEFAULT_STYLE)
		try:
			if dirDialog.ShowModal() == wx.ID_OK:
				self.destText.SetValue(dirDialog.GetPath())
		finally:
			dirDialog.Destroy()
		self.destText.SetFocus()

	def onExecute(self, event):
		currentPaths = self.basketManager.getPaths()
		if not currentPaths:
			ui.message(_("Basket is empty"))
			return

		actionText = self.actionCombo.GetStringSelection()
		targetDirectory = self.destText.GetValue().strip()

		if actionText == _("Zip"):
			fileDialog = wx.FileDialog(
				self, _("Save Zip File As"), wildcard="Zip files (*.zip)|*.zip",
				style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
			)
			try:
				if fileDialog.ShowModal() != wx.ID_OK:
					return
				zipPath = fileDialog.GetPath()
			finally:
				fileDialog.Destroy()
			if not zipPath.lower().endswith(".zip"):
				zipPath += ".zip"
			threading.Thread(target=self.basketManager.executeBulkZip, args=(currentPaths, zipPath), daemon=True).start()
			self.Close()
			return

		if not targetDirectory or not os.path.isdir(targetDirectory):
			ui.message(_("Please choose a valid destination folder"))
			return

		if actionText == _("Copy"):
			threading.Thread(target=self.basketManager.executeBulkCopy, args=(currentPaths, targetDirectory), daemon=True).start()
		elif actionText == _("Move"):
			threading.Thread(target=self.basketManager.executeBulkMove, args=(currentPaths, targetDirectory), daemon=True).start()
		elif actionText == _("Mirror Copy"):
			threading.Thread(target=self.basketManager.executeBulkMirrorCopy, args=(currentPaths, targetDirectory), daemon=True).start()
		self.Close()

	def _on_close(self, event):
		self.EndModal(wx.ID_CANCEL)


class FileBasketManager:
	"""A virtual staging area for files gathered from multiple locations -
	nothing physically moves until the user runs a bulk Copy/Move/Zip/Mirror
	on the whole basket, and all of that runs on a background thread so a
	large basket never blocks NVDA. The collection itself persists across
	NVDA restarts (saved to file_basket.json) until explicitly cleared."""

	def __init__(self, plugin):
		self.plugin = plugin
		self.collectedPaths = set()
		self.dialog = None
		self._writeLock = threading.Lock()
		self._loadBasket()

	def cleanup(self):
		if self.dialog:
			try:
				self.dialog.Destroy()
			except RuntimeError:
				pass
			self.dialog = None

	def logOperation(self, description):
		operationHistory = getattr(self.plugin, "operationHistory", None)
		if operationHistory:
			operationHistory.addEntry(description)

	def _loadBasket(self):
		if not os.path.exists(BASKET_FILE):
			return
		try:
			with open(BASKET_FILE, "r", encoding="utf-8") as f:
				data = json.load(f)
			paths = data.get("paths", [])
			self.collectedPaths = {p for p in paths if os.path.exists(p)}
		except (OSError, ValueError) as e:
			log.error(f"Error loading file basket: {e}")

	def _saveBasket(self):
		with self._writeLock:
			try:
				if not os.path.exists(CONFIG_DIR):
					os.makedirs(CONFIG_DIR)
				with open(BASKET_FILE, "w", encoding="utf-8") as f:
					json.dump({"paths": sorted(self.collectedPaths)}, f, indent=2, ensure_ascii=False)
			except OSError as e:
				log.error(f"Error saving file basket: {e}")

	def addSelectedToBasket(self, retryCount=0):
		def handleSelection(selected_items, _hwnd):
			if not selected_items:
				if retryCount < 10:
					core.callLater(100, lambda: self.addSelectedToBasket(retryCount + 1))
					return
				ui.message(_("No items selected"))
				return
			self._addItems(selected_items)

		self.plugin._getSelectedItemsAsync(handleSelection)

	def addSelectedAndShowBasket(self, retryCount=0):
		"""Used from the context menu (no multi-tap gesture available there):
		adds whatever is currently selected, then opens the basket GUI in
		the same action, per the requested single combined menu entry."""
		def handleSelection(selected_items, _hwnd):
			if selected_items:
				self._addItems(selected_items, announce=False)
			elif retryCount < 5:
				core.callLater(100, lambda: self.addSelectedAndShowBasket(retryCount + 1))
				return
			self.showBasketDialog()

		self.plugin._getSelectedItemsAsync(handleSelection)

	def _addItems(self, selected_items, announce=True):
		addedFolders = 0
		addedFiles = 0
		for _name, path in selected_items:
			if path in self.collectedPaths or not os.path.exists(path):
				continue
			self.collectedPaths.add(path)
			if os.path.isdir(path):
				addedFolders += 1
			else:
				addedFiles += 1

		if addedFolders or addedFiles:
			self._saveBasket()
			if announce:
				parts = []
				if addedFolders:
					parts.append(_("{0} folders").format(addedFolders))
				if addedFiles:
					parts.append(_("{0} files").format(addedFiles))
				ui.message(_("Added {0}").format(" ".join(parts)))
		elif announce:
			ui.message(_("Selected items are already in the basket"))

	def addPath(self, targetPath, announce=True):
		if not os.path.exists(targetPath):
			if announce:
				ui.message(_("Path not found: {0}").format(targetPath))
			return False

		if targetPath in self.collectedPaths:
			if announce:
				ui.message(_("Already in basket"))
			return False

		self.collectedPaths.add(targetPath)
		self._saveBasket()
		if announce:
			ui.message(_("Added to basket. Total items: {0}").format(len(self.collectedPaths)))
		return True

	def removePath(self, targetPath):
		if targetPath not in self.collectedPaths:
			return False
		self.collectedPaths.remove(targetPath)
		self._saveBasket()
		return True

	def clearBasket(self):
		self.collectedPaths.clear()
		self._saveBasket()
		ui.message(_("Basket cleared"))

	def clearBasketWithAnnouncement(self):
		folderCount = sum(1 for p in self.collectedPaths if os.path.isdir(p))
		fileCount = sum(1 for p in self.collectedPaths if os.path.isfile(p))
		self.collectedPaths.clear()
		self._saveBasket()
		if folderCount or fileCount:
			parts = []
			if folderCount:
				parts.append(_("{0} folders").format(folderCount))
			if fileCount:
				parts.append(_("{0} files").format(fileCount))
			ui.message(_("Cleared {0} from basket").format(" ".join(parts)))
		else:
			ui.message(_("Basket is already empty"))

	def getPaths(self):
		return sorted(self.collectedPaths)

	def showBasketDialog(self):
		def do_show():
			self.dialog = FileBasketDialog(gui.mainFrame, self)
			gui.mainFrame.prePopup()
			try:
				self.dialog.ShowModal()
			finally:
				gui.mainFrame.postPopup()
				self.dialog.Destroy()
				self.dialog = None

		wx.CallAfter(do_show)

	def executeBulkCopy(self, sourcePaths, targetDirectory):
		successCount = 0
		errorCount = 0

		for sourcePath in sourcePaths:
			try:
				if os.path.isfile(sourcePath):
					shutil.copy2(sourcePath, targetDirectory)
				elif os.path.isdir(sourcePath):
					folderName = os.path.basename(sourcePath.rstrip(os.sep))
					destinationPath = os.path.join(targetDirectory, folderName)
					shutil.copytree(sourcePath, destinationPath, dirs_exist_ok=True)
				successCount += 1
			except OSError as e:
				log.error(f"Failed to copy {sourcePath}: {e}")
				errorCount += 1

		wx.CallAfter(self._reportBulkResult, _("copied"), successCount, errorCount)
		if successCount:
			self.logOperation(_("Copied {0} items from the basket").format(successCount))

	def executeBulkMove(self, sourcePaths, targetDirectory):
		successCount = 0
		errorCount = 0

		for sourcePath in sourcePaths:
			try:
				shutil.move(sourcePath, targetDirectory)
				self.collectedPaths.discard(sourcePath)
				successCount += 1
			except OSError as e:
				log.error(f"Failed to move {sourcePath}: {e}")
				errorCount += 1

		self._saveBasket()
		wx.CallAfter(self._reportBulkResult, _("moved"), successCount, errorCount)
		if successCount:
			self.logOperation(_("Moved {0} items from the basket").format(successCount))

	def executeBulkMirrorCopy(self, sourcePaths, targetDirectory):
		successCount = 0
		errorCount = 0

		for sourcePath in sourcePaths:
			try:
				if os.path.isfile(sourcePath):
					destinationPath = os.path.join(targetDirectory, os.path.basename(sourcePath))
					if os.path.exists(destinationPath):
						os.remove(destinationPath)
					shutil.copy2(sourcePath, destinationPath)
				elif os.path.isdir(sourcePath):
					folderName = os.path.basename(sourcePath.rstrip(os.sep))
					destinationPath = os.path.join(targetDirectory, folderName)
					if os.path.exists(destinationPath):
						shutil.rmtree(destinationPath)
					shutil.copytree(sourcePath, destinationPath)
				successCount += 1
			except OSError as e:
				log.error(f"Failed to mirror copy {sourcePath}: {e}")
				errorCount += 1

		wx.CallAfter(self._reportBulkResult, _("mirror copied"), successCount, errorCount)
		if successCount:
			self.logOperation(_("Mirror copied {0} items from the basket").format(successCount))

	def executeBulkZip(self, sourcePaths, zipPath):
		successCount = 0
		errorCount = 0

		try:
			with zipfile.ZipFile(zipPath, "w", zipfile.ZIP_DEFLATED) as zipHandle:
				for sourcePath in sourcePaths:
					try:
						if os.path.isfile(sourcePath):
							zipHandle.write(sourcePath, os.path.basename(sourcePath))
						elif os.path.isdir(sourcePath):
							baseFolderName = os.path.basename(sourcePath.rstrip(os.sep))
							for root, _dirs, files in os.walk(sourcePath):
								for fileName in files:
									filePath = os.path.join(root, fileName)
									relativePath = os.path.join(baseFolderName, os.path.relpath(filePath, sourcePath))
									zipHandle.write(filePath, relativePath)
						successCount += 1
					except OSError as e:
						log.error(f"Failed to zip {sourcePath}: {e}")
						errorCount += 1
		except OSError as e:
			log.error(f"Failed to create zip file {zipPath}: {e}")
			wx.CallAfter(ui.message, _("Error creating zip file"))
			return

		wx.CallAfter(self._reportBulkResult, _("zipped"), successCount, errorCount)
		if successCount:
			self.logOperation(_("Zipped {0} items from the basket").format(successCount))

	def _reportBulkResult(self, verb, successCount, errorCount):
		tones.beep(1000, 200)
		if errorCount > 0:
			ui.message(_("{0} complete. {1} successful, {2} failed. Check NVDA log.").format(verb.capitalize(), successCount, errorCount))
		else:
			ui.message(_("Successfully {0} {1} items.").format(verb, successCount))

