# robocopyManager.py

import ui
import api
import os
import wx
import gui
import gui.guiHelper
import subprocess
import threading
import queue
import time
import re
import ctypes
import addonHandler
import core
import tones
import comtypes.client
from urllib.parse import unquote
from logHandler import log

addonHandler.initTranslation()

DRIVE_REMOVABLE = 2
STALL_HEARTBEAT_SECONDS = 8
QUEUE_POLL_TIMEOUT = 0.3
UI_UPDATE_MIN_INTERVAL = 0.15
ROBOCOPY_FILES_SUMMARY_RE = re.compile(r"^\s*Files\s*:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", re.MULTILINE)


class ProgressDialog(wx.Dialog):
	def __init__(self, parent, title):
		super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP)
		self.is_cancelled = False
		self._gauge = None
		self._label = None
		self._cancel_btn = None
		self._init_ui()
		self.CentreOnScreen()

	def _init_ui(self):
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self._label = wx.StaticText(self, label="Initializing Robocopy...")
		s_helper.addItem(self._label)
		self._gauge = wx.Gauge(self, range=100)
		s_helper.addItem(self._gauge, proportion=0, flag=wx.EXPAND)
		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self._cancel_btn = wx.Button(self, label="Cancel")
		btn_sizer.Add(self._cancel_btn, 1, wx.ALL, 5)
		main_sizer.Add(s_helper.sizer, 1, wx.EXPAND | wx.ALL, 10)
		main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
		self.SetSizer(main_sizer)
		main_sizer.Fit(self)
		self._cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

	def _on_cancel(self, evt):
		self.is_cancelled = True
		self.EndModal(wx.ID_CANCEL)

	def update_progress(self, percentage, status_text=""):
		def _update():
			if not self or not self._gauge:
				return
			self._gauge.SetValue(int(percentage))
			if status_text:
				self._label.SetLabel(status_text)
		wx.CallAfter(_update)


class RobocopyManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self.source_items = []
		self.operation_type = "copy"
		self.active_process = None

	def _get_explorer_data_via_com(self, get_selection=True):
		paths = []
		current_folder = None
		try:
			shell = comtypes.client.CreateObject("Shell.Application")
			fg_hwnd = api.getForegroundObject().windowHandle
			for window in shell.Windows():
				try:
					if window.hwnd == fg_hwnd:
						if get_selection:
							selection = window.Document.SelectedItems()
							for i in range(selection.Count):
								paths.append(selection.Item(i).Path)
						try:
							current_folder = window.Document.Folder.Self.Path
						except Exception:
							url = window.LocationURL
							if url.startswith("file:///"):
								current_folder = unquote(url[8:].replace("/", "\\"))
						break
				except Exception:
					continue
		except Exception as e:
			log.debug(f"Robocopy COM Error: {e}")
		return paths if get_selection else current_folder

	def copy(self):
		paths = self._get_explorer_data_via_com(get_selection=True)
		if not paths:
			tones.beep(200, 150)
			ui.message("No items selected")
			return
		self.source_items = paths
		self.operation_type = "copy"
		tones.beep(440, 150)
		ui.message(f"Robocopy: {len(paths)} items ready")

	def move(self):
		paths = self._get_explorer_data_via_com(get_selection=True)
		if not paths:
			tones.beep(200, 150)
			ui.message("No items selected")
			return
		self.source_items = paths
		self.operation_type = "move"
		tones.beep(440, 150)
		ui.message(f"Robocopy: {len(paths)} items ready to move")

	def paste(self):
		if not self.source_items:
			tones.beep(200, 150)
			ui.message("Nothing to paste")
			return
		dest_path = self._get_explorer_data_via_com(get_selection=False)
		if not dest_path:
			dest_path = getattr(self.plugin.manager, "lastExplorerPath", None)
		if not dest_path:
			dest_path = self.plugin._getCurrentPath()
		if not dest_path or not os.path.exists(dest_path):
			tones.beep(200, 150)
			ui.message("Destination not found")
			return
		tones.beep(880, 200)
		thread = threading.Thread(
			target=self._run_transfer,
			args=(list(self.source_items), dest_path, self.operation_type == "move")
		)
		thread.daemon = True
		thread.start()
		self.source_items = []

	def _isRemovableDrive(self, path):
		# Old USB 2/3 flash drives choke on robocopy's multithreaded mode (/MT),
		# which issues many parallel I/O requests their controllers cannot keep up with.
		try:
			driveRoot = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
			driveType = ctypes.windll.kernel32.GetDriveTypeW(driveRoot)
			return driveType == DRIVE_REMOVABLE
		except (OSError, ValueError, AttributeError) as e:
			log.debug(f"Robocopy: drive type check failed: {e}")
			return False

	def _buildRobocopyCommand(self, source, dest, isDir, isMove, useMultiThread):
		if isDir:
			sourceName = os.path.basename(source)
			targetDest = os.path.join(dest, sourceName)
			cmd = ["robocopy", source, targetDest, "/E"]
		else:
			sourceDir = os.path.dirname(source)
			sourceName = os.path.basename(source)
			cmd = ["robocopy", sourceDir, dest, sourceName]
		# /J: unbuffered I/O, avoids cache-related stalls and corruption on slow removable media
		cmd += ["/R:5", "/W:5", "/J", "/V", "/NP"]
		if isDir:
			cmd.append("/XJ")
		if useMultiThread:
			cmd.append("/MT:8")
		if isMove:
			cmd.append("/MOVE")
		return cmd

	def _startStdoutReader(self, process):
		# Reading stdout line-by-line in the main transfer loop blocks whenever robocopy
		# goes quiet (e.g. one large file trickling over USB 2.0), which freezes cancel
		# responsiveness and progress updates. A dedicated reader thread plus a queue lets
		# the transfer loop poll with a short timeout instead of blocking indefinitely.
		outputQueue = queue.Queue()

		def _readerLoop():
			try:
				for rawLine in iter(process.stdout.readline, b""):
					try:
						line = rawLine.decode("utf-8", errors="replace")
					except (UnicodeDecodeError, LookupError):
						line = ""
					outputQueue.put(line)
			except (OSError, ValueError):
				pass
			finally:
				outputQueue.put(None)

		readerThread = threading.Thread(target=_readerLoop, daemon=True)
		readerThread.start()
		return outputQueue, readerThread

	def _parseFailedCount(self, lines):
		joined = "".join(lines)
		match = ROBOCOPY_FILES_SUMMARY_RE.search(joined)
		if not match:
			return 0
		# Total, Copied, Skipped, Mismatch, FAILED, Extras
		return int(match.group(5))

	def _run_transfer(self, sources, dest, is_move):
		dlg = None

		def create_dlg():
			nonlocal dlg
			dlg = ProgressDialog(gui.mainFrame, "xPloyer Robocopy")
			dlg.Show()
		wx.CallAfter(create_dlg)
		time.sleep(0.3)

		useMultiThread = not self._isRemovableDrive(dest)
		totalFiles = len(sources)
		failedItems = []
		succeededCount = 0
		wasCancelled = False

		for idx, source in enumerate(sources):
			if dlg and dlg.is_cancelled:
				wasCancelled = True
				break
			source_name = os.path.basename(source)
			is_dir = os.path.isdir(source)
			target_dest = os.path.join(dest, source_name)
			cmd = self._buildRobocopyCommand(source, dest, is_dir, is_move, useMultiThread)

			try:
				startupinfo = subprocess.STARTUPINFO()
				startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
				self.active_process = subprocess.Popen(
					cmd,
					stdout=subprocess.PIPE,
					stderr=subprocess.STDOUT,
					startupinfo=startupinfo,
					creationflags=subprocess.CREATE_NO_WINDOW
				)

				outputQueue, readerThread = self._startStdoutReader(self.active_process)
				summaryLines = []
				lastActivityTime = time.monotonic()
				lastUiUpdateTime = 0.0

				while True:
					if dlg and dlg.is_cancelled:
						wasCancelled = True
						self.active_process.terminate()
						break
					try:
						line = outputQueue.get(timeout=QUEUE_POLL_TIMEOUT)
					except queue.Empty:
						if self.active_process.poll() is not None:
							break
						if time.monotonic() - lastActivityTime >= STALL_HEARTBEAT_SECONDS:
							lastActivityTime = time.monotonic()
							wx.CallAfter(dlg.update_progress, int((idx / totalFiles) * 100), f"Still copying: {source_name}")
						continue
					if line is None:
						break
					lastActivityTime = time.monotonic()
					summaryLines.append(line)
					now = time.monotonic()
					if now - lastUiUpdateTime >= UI_UPDATE_MIN_INTERVAL:
						lastUiUpdateTime = now
						wx.CallAfter(dlg.update_progress, int((idx + 1) / totalFiles * 100), f"Copying: {source_name}")

				readerThread.join(timeout=2)
				try:
					self.active_process.wait(timeout=10)
				except subprocess.TimeoutExpired:
					self.active_process.kill()
					self.active_process.wait(timeout=5)
				exit_code = self.active_process.returncode

				if wasCancelled:
					break

				if exit_code is not None and exit_code >= 8:
					log.error(f"Robocopy error for {source_name} (exit code: {exit_code})")
					failedItems.append(source_name)
					continue

				if exit_code is None:
					log.warning(f"Robocopy for {source_name} finished but exit code is None")

				failedInSummary = self._parseFailedCount(summaryLines)
				if failedInSummary > 0:
					log.error(f"Robocopy reported {failedInSummary} failed file(s) for {source_name}")
					failedItems.append(source_name)
					continue

				if not is_dir and not self._verify_file_copy(source, target_dest):
					log.error(f"Verification failed for {source_name}")
					failedItems.append(source_name)
					continue

				log.debug(f"Robocopy success for {source_name} (exit code: {exit_code})")
				succeededCount += 1

			except (OSError, subprocess.SubprocessError) as e:
				log.exception(f"Robocopy error for {source_name}: {e}")
				failedItems.append(source_name)
				continue

		def cleanup_dlg():
			if dlg:
				dlg.Destroy()
		wx.CallAfter(cleanup_dlg)

		if wasCancelled:
			tones.beep(200, 150)
			core.callLater(0, ui.message, "Robocopy cancelled")
			return

		if failedItems:
			tones.beep(200, 300)
			shownItems = ", ".join(failedItems[:5])
			if len(failedItems) > 5:
				shownItems += f" and {len(failedItems) - 5} more"
			core.callLater(0, ui.message, f"Robocopy finished. {succeededCount} succeeded, {len(failedItems)} failed: {shownItems}")
		else:
			tones.beep(1760, 300)
			core.callLater(0, ui.message, f"Robocopy finished successfully. {succeededCount} item(s) copied")

	def _verify_file_copy(self, source_path, dest_path):
		try:
			if not os.path.exists(dest_path):
				return False
			src_size = os.path.getsize(source_path)
			dst_size = os.path.getsize(dest_path)
			if src_size != dst_size:
				log.warning(f"Size mismatch: {source_path} ({src_size}) vs {dest_path} ({dst_size})")
				return False
			return True
		except OSError as e:
			log.error(f"Verification error: {e}")
			return False

	def cleanup(self):
		if self.active_process and self.active_process.poll() is None:
			try:
				self.active_process.terminate()
			except OSError:
				pass
