# clipboardManager.py

import ui
import api
import os
import threading
import wx
from logHandler import log
import addonHandler
from .documentReaders import DocumentReadError, isDocumentFile, readDocumentText, rtfBytesToText

addonHandler.initTranslation()

class ClipboardManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self._striprtf_available = None

	def _getStriprtfModule(self):
		return self.plugin._getStriprtfModule()

	def copySelectedNames(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			return

		def handleSelection(selectedItems, _hwnd):
			try:
				if not selectedItems:
					ui.message(_("No items selected"))
					return
				folders = []
				files = []
				for name, path in selectedItems:
					if os.path.isdir(path):
						folders.append(name)
					else:
						files.append(name)
				folders.sort()
				files.sort()
				sortedNames = folders + files
				namesText = "\n".join(sortedNames)
				if wx.TheClipboard.Open():
					try:
						wx.TheClipboard.SetData(wx.TextDataObject(namesText))
						if len(selectedItems) == 1:
							ui.message(_("Copied 1 item name to clipboard"))
						else:
							ui.message(_("Copied {count} item names to clipboard").format(count=len(selectedItems)))
					finally:
						wx.TheClipboard.Close()
				else:
					ui.message(_("Could not open clipboard"))
			except Exception as e:
				log.error(f"Error in copySelectedNames: {e}")
				ui.message(_("Error copying names to clipboard"))

		self.plugin._getSelectedItemsAsync(handleSelection)

	def copyFileContent(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			return

		def handleSelection(selectedItems, _hwnd):
			try:
				if not selectedItems:
					ui.message(_("No items selected"))
					return
				for name, path in selectedItems:
					if os.path.isdir(path):
						ui.message(_("Cannot copy content of folders, please select files only"))
						return
				textExtensions = ['.txt', '.py', '.js', '.html', '.css', '.xml', '.json',
								'.csv', '.md', '.ini', '.conf', '.cfg', '.java', '.cpp',
								'.c', '.h', '.php', '.rb', '.pl', '.sh', '.bat', '.ps1', '.rtf']
				textFiles = []
				for name, path in selectedItems:
					fileExt = os.path.splitext(path)[1].lower()
					isReadableDocument = isDocumentFile(path) and not os.path.basename(path).startswith("~$")
					if fileExt in textExtensions or isReadableDocument:
						textFiles.append(path)
					else:
						log.debug(f"Skipping non-text file: {name}")
				if not textFiles:
					ui.message(_("No text files selected"))
					return
				totalSize = 0
				for filePath in textFiles:
					try:
						totalSize += os.path.getsize(filePath)
					except (OSError, ValueError):
						pass
				if totalSize > 15 * 1024 * 1024:
					ui.message(_("Total file size is too large to copy content"))
					return
				threading.Thread(target=self._readAndCopyFileContent, args=(textFiles,), daemon=True).start()
			except Exception as e:
				log.error(f"Error in copyFileContent: {e}")
				ui.message(_("Error copying file content"))

		self.plugin._getSelectedItemsAsync(handleSelection)

	def _readSingleFile(self, filePath):
		fileExt = os.path.splitext(filePath)[1].lower()
		try:
			if fileExt == '.rtf':
				with open(filePath, 'rb') as f:
					return rtfBytesToText(f.read())
			if isDocumentFile(filePath):
				return readDocumentText(filePath)
			try:
				with open(filePath, 'r', encoding='utf-8') as f:
					return f.read()
			except UnicodeDecodeError:
				with open(filePath, 'r', encoding='latin-1') as f:
					return f.read()
		except DocumentReadError as e:
			log.warning(f"Could not convert {filePath}: {e}")
		except (OSError, UnicodeError) as e:
			log.error(f"Failed to read file {filePath}: {e}")
		return None

	def _readAndCopyFileContent(self, textFiles):
		try:
			combinedContent = ""
			filesProcessed = 0
			failedCount = 0
			for filePath in textFiles:
				content = self._readSingleFile(filePath)
				if content is None:
					failedCount += 1
					continue
				if filesProcessed > 0:
					combinedContent += "\n\n"
				combinedContent += content
				filesProcessed += 1

			def finish():
				if failedCount:
					ui.message(_("{count} files could not be read").format(count=failedCount))
				if not combinedContent.strip():
					ui.message(_("No content could be read from selected files"))
					return
				if wx.TheClipboard.Open():
					try:
						wx.TheClipboard.SetData(wx.TextDataObject(combinedContent))
						lineCount = len(combinedContent.splitlines())
						ui.message(_("Copy {lines} Lines from {files} files").format(lines=lineCount, files=filesProcessed))
					finally:
						wx.TheClipboard.Close()
				else:
					ui.message(_("Could not open clipboard"))

			wx.CallAfter(finish)
		except Exception as e:
			log.error(f"Error in copyFileContent: {e}")
			wx.CallAfter(ui.message, _("Error copying file content"))
