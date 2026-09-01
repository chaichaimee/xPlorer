# compressionManager.py

import ui
import api
import os
import wx
import gui
import subprocess
import zipfile
from threading import Thread
import tones
from logHandler import log
import addonHandler
import winUser
import time
import core
from .folderTools import loadConfig

addonHandler.initTranslation()

ARCHIVE_EXTENSIONS = (
	".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
	".tgz", ".iso", ".cab", ".wim", ".nvda-addon"
)

class CompressionManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self.progressDialog = None
		self.compressThread = None
		self.unzipThread = None
		self.cancelled = False

	def cleanup(self):
		if self.progressDialog:
			try:
				self.progressDialog.Destroy()
			except (RuntimeError, AttributeError):
				pass
		if self.compressThread and self.compressThread.is_alive():
			self.compressThread.join(timeout=1.0)
		if self.unzipThread and self.unzipThread.is_alive():
			self.unzipThread.join(timeout=1.0)

	def _updateProgress(self, percent, message):
		if self.progressDialog:
			def do_update():
				if self.progressDialog:
					cont, _ignore = self.progressDialog.Update(percent, message)
					if percent % 10 == 0:
						tones.beep(800 + percent * 2, 50)
					if not cont:
						self.cancelled = True
			wx.CallAfter(do_update)

	def _compressInBackground(self, sevenZipPath, selectedItems, callback):
		self.cancelled = False
		try:
			if len(selectedItems) == 1:
				sourcePath = selectedItems[0]
				if os.path.isfile(sourcePath):
					baseName = os.path.splitext(os.path.basename(sourcePath))[0]
				else:
					baseName = os.path.basename(sourcePath)
				zipPath = os.path.join(os.path.dirname(sourcePath), baseName + ".zip")
			else:
				folderPath = os.path.dirname(selectedItems[0])
				folderName = os.path.basename(folderPath)
				zipPath = os.path.join(folderPath, folderName + ".zip")

			counter = 1
			originalZipPath = zipPath
			while os.path.exists(zipPath):
				name, ext = os.path.splitext(originalZipPath)
				zipPath = f"{name} ({counter}){ext}"
				counter += 1

			cmd = [sevenZipPath, "a", "-tzip", zipPath]
			cmd.extend(selectedItems)

			process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, creationflags=subprocess.CREATE_NO_WINDOW)

			last_percent = 0
			msg = _("Compressing...")
			start_time = time.time()

			while True:
				if self.cancelled:
					process.terminate()
					break
				if time.time() - start_time > 30:
					try:
						process.terminate()
						log.warning("Compression timeout after 30 seconds")
						callback(False, _("Compression timed out"))
						return
					except (OSError, AttributeError):
						pass
				try:
					line = process.stdout.readline()
					if not line:
						break
					if '%' in line:
						try:
							percent_str = line.split('%')[0].strip()
							percent = int(percent_str)
							if percent > last_percent:
								last_percent = percent
								self._updateProgress(percent, f"{msg} {percent}%")
						except ValueError:
							pass
				except Exception as e:
					log.error(f"Error reading stdout: {e}")
					break

			return_code = process.poll()

			if self.cancelled:
				callback(False, _("Compression cancelled"))
			elif return_code == 0:
				callback(True, _("Compression completed {name}").format(name=os.path.basename(zipPath)))
			else:
				callback(False, _("compression failed"))
		except Exception as e:
			log.error(f"Error in background compression: {e}")
			callback(False, _("Error in compression process: {error}").format(error=str(e)))

	def _onCompressionComplete(self, success, message):
		if success:
			tones.beep(1000, 300)
			operationHistory = getattr(self.plugin, "operationHistory", None)
			if operationHistory:
				operationHistory.addEntry(message)
		else:
			tones.beep(500, 300)

		if hasattr(self.plugin, 'lastExplorerHwnd') and self.plugin.lastExplorerHwnd and winUser.isWindow(self.plugin.lastExplorerHwnd):
			try:
				winUser.setForegroundWindow(self.plugin.lastExplorerHwnd)
			except Exception as e:
				log.error(f"Error setting foreground window: {e}")

		def destroy_dialog():
			if self.progressDialog:
				try:
					self.progressDialog.Destroy()
				except (RuntimeError, AttributeError):
					pass
				self.progressDialog = None
		wx.CallAfter(destroy_dialog)

	def compressZip(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			return

		def handleSelection(selectedItems, _hwnd):
			try:
				if not selectedItems:
					ui.message(_("No items selected"))
					return

				paths = [path for name, path in selectedItems]
				self.plugin.lastExplorerHwnd = api.getForegroundObject().windowHandle

				sevenZipPath = self._find7zip()
				style = wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME | wx.STAY_ON_TOP

				def show_and_start():
					try:
						self.progressDialog = wx.ProgressDialog(
							_("Compressing files"),
							_("Starting..."),
							maximum=100,
							parent=gui.mainFrame,
							style=style
						)
						self.progressDialog.Raise()
						wx.CallAfter(self.progressDialog.SetFocus)
						wx.CallAfter(ui.message, _("Compressing files"))

						if sevenZipPath:
							if self.compressThread and self.compressThread.is_alive():
								self.compressThread.join(timeout=0.5)
							self.compressThread = Thread(
								target=self._compressInBackground,
								args=(sevenZipPath, paths, self._onCompressionComplete)
							)
							self.compressThread.daemon = True
							self.compressThread.start()
						else:
							self.compressThread = Thread(
								target=self._compressWithBuiltIn,
								args=(paths, self._onCompressionComplete)
							)
							self.compressThread.daemon = True
							self.compressThread.start()
					except Exception as e:
						log.error(f"Compression start failed: {e}")
						ui.message(_("Failed to start compression"))
						if self.progressDialog:
							self.progressDialog.Destroy()
							self.progressDialog = None

				wx.CallAfter(show_and_start)
			except Exception as e:
				log.error(f"Error in compressZip: {e}")
				ui.message(_("Error compressing files"))

		self.plugin._getSelectedItemsAsync(handleSelection)

	def _find7zip(self):
		paths = [
			os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "7-Zip", "7z.exe"),
			os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "7-Zip", "7z.exe"),
			os.path.join(os.environ.get("ProgramW6432", "C:\\Program Files"), "7-Zip", "7z.exe"),
		]
		for path in paths:
			if os.path.exists(path):
				return path
		return None

	def _getTotalSize(self, selectedItems):
		total = 0
		for path in selectedItems:
			if os.path.isfile(path):
				try:
					total += os.path.getsize(path)
				except (OSError, ValueError):
					pass
			elif os.path.isdir(path):
				for root, _, files in os.walk(path):
					for f in files:
						fp = os.path.join(root, f)
						try:
							total += os.path.getsize(fp)
						except (OSError, ValueError):
							pass
		return total

	def _compressWithBuiltIn(self, selectedItems, callback):
		self.cancelled = False
		try:
			if len(selectedItems) == 1:
				sourcePath = selectedItems[0]
				if os.path.isfile(sourcePath):
					baseName = os.path.splitext(os.path.basename(sourcePath))[0]
				else:
					baseName = os.path.basename(sourcePath)
				zipPath = os.path.join(os.path.dirname(sourcePath), baseName + ".zip")
			else:
				folderPath = os.path.dirname(selectedItems[0])
				folderName = os.path.basename(folderPath)
				zipPath = os.path.join(folderPath, folderName + ".zip")

			counter = 1
			originalZipPath = zipPath
			while os.path.exists(zipPath):
				name, ext = os.path.splitext(originalZipPath)
				zipPath = f"{name} ({counter}){ext}"
				counter += 1

			total_size = self._getTotalSize(selectedItems)
			current_size = 0

			with zipfile.ZipFile(zipPath, 'w', zipfile.ZIP_DEFLATED) as zipf:
				for item in selectedItems:
					if self.cancelled:
						break
					arcname = os.path.basename(item)
					if os.path.isfile(item):
						size = os.path.getsize(item)
						zipf.write(item, arcname)
						current_size += size
						percent = int(current_size * 100 / total_size) if total_size > 0 else 0
						self._updateProgress(percent, _("Compressing: {percent}%").format(percent=percent))
					elif os.path.isdir(item):
						for root, _, files in os.walk(item):
							if self.cancelled:
								break
							for file in files:
								if self.cancelled:
									break
								file_path = os.path.join(root, file)
								relative_path = os.path.relpath(file_path, os.path.dirname(item))
								size = os.path.getsize(file_path)
								zipf.write(file_path, os.path.join(arcname, relative_path))
								current_size += size
								percent = int(current_size * 100 / total_size) if total_size > 0 else 0
								self._updateProgress(percent, _("Compressing: {percent}%").format(percent=percent))

			if self.cancelled:
				if os.path.exists(zipPath):
					os.remove(zipPath)
				callback(False, _("Compression cancelled"))
			else:
				self._updateProgress(100, _("Completed"))
				callback(True, _("Compression completed {name}").format(name=os.path.basename(zipPath)))
		except Exception as e:
			log.error(f"Built-in compression failed: {e}")
			callback(False, _("Built-in compression failed: {error}").format(error=str(e)))

	def _isArchiveFile(self, path):
		return os.path.splitext(path)[1].lower() in ARCHIVE_EXTENSIONS

	def unzipSelected(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			return
		def handleSelection(selectedItems, _hwnd):
			try:
				self._handleUnzipSelection(selectedItems)
			except Exception as e:
				log.error(f"Error in unzipSelected: {e}")
				ui.message(_("Error uncompressing file"))

		self.plugin._getSelectedItemsAsync(handleSelection)

	def _handleUnzipSelection(self, selectedItems):
		if not selectedItems:
			ui.message(_("No items selected"))
			return
		archive_paths = [path for _name, path in selectedItems
						  if os.path.isfile(path) and self._isArchiveFile(path)]
		if not archive_paths:
			ui.message(_("Please select a compressed file"))
			return
		if len(archive_paths) > 1:
			ui.message(_("Please select only one compressed file"))
			return

		archive_path = archive_paths[0]

		conf = loadConfig()
		if not conf.get("showUncompressDialog", True):
			base_name = os.path.splitext(os.path.basename(archive_path))[0]
			parent_dir = os.path.dirname(archive_path)
			extract_to_folder = os.path.join(parent_dir, base_name + "\\")
			defaultAction = conf.get("uncompressDefaultAction", "extract_to")
			target_dir = extract_to_folder if defaultAction == "extract_to" else parent_dir
			self._extractArchiveInBackground(archive_path, target_dir)
			return

		def show_extraction_choice():
			base_name = os.path.splitext(os.path.basename(archive_path))[0]
			parent_dir = os.path.dirname(archive_path)
			extract_to_folder = os.path.join(parent_dir, base_name + "\\")

			choices = [
				_('Extract to "{folder}\\"').format(folder=base_name),
				_("Extract Here")
			]
			dialog = wx.SingleChoiceDialog(
				gui.mainFrame,
				_("Choose extraction method:"),
				_("Extract {name}").format(name=os.path.basename(archive_path)),
				choices
			)
			dialog.SetSelection(0)
			if dialog.ShowModal() != wx.ID_OK:
				dialog.Destroy()
				return
			choice = dialog.GetSelection()
			dialog.Destroy()

			target_dir = extract_to_folder if choice == 0 else parent_dir
			self._extractArchiveInBackground(archive_path, target_dir)

		wx.CallAfter(show_extraction_choice)

	def _extractArchiveInBackground(self, archive_path, target_dir):
		def worker():
			try:
				os.makedirs(target_dir, exist_ok=True)
				extension = os.path.splitext(archive_path)[1].lower()
				sevenZipPath = self._find7zip()
				if sevenZipPath:
					cmd = [sevenZipPath, "x", archive_path, f"-o{target_dir}", "-y"]
					if extension == ".nvda-addon":
						cmd.insert(2, "-tzip")
					try:
						process = subprocess.Popen(
							cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
							stderr=subprocess.STDOUT, universal_newlines=True,
							creationflags=subprocess.CREATE_NO_WINDOW
						)
						process.communicate(timeout=120)
					except subprocess.TimeoutExpired:
						process.kill()
						process.communicate()
						wx.CallAfter(ui.message, _("Extraction timed out"))
						return
					if process.returncode != 0:
						wx.CallAfter(ui.message, _("Extraction failed"))
						return
				elif extension in (".zip", ".nvda-addon"):
					with zipfile.ZipFile(archive_path, 'r') as zf:
						zf.extractall(target_dir)
				else:
					wx.CallAfter(ui.message, _("7-Zip is required to extract this file type"))
					return
				wx.CallAfter(ui.message, _("Extraction completed to {path}").format(path=target_dir))
				tones.beep(1000, 200)
				operationHistory = getattr(self.plugin, "operationHistory", None)
				if operationHistory:
					operationHistory.addEntry(_("Extracted {name} to {path}").format(
							name=os.path.basename(archive_path), path=target_dir))
			except Exception as e:
				log.error(f"Extraction failed: {e}")
				wx.CallAfter(ui.message, _("Extraction failed: {error}").format(error=str(e)))
		self.unzipThread = Thread(target=worker, daemon=True)
		self.unzipThread.start()
		ui.message(_("Extracting..."))

