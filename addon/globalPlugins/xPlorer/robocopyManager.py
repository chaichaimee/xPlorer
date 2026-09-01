# robocopyManager.py

import ui
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
from logHandler import log

addonHandler.initTranslation()

DRIVE_REMOVABLE = 2
QUEUE_POLL_TIMEOUT = 0.3
# How often the (relatively expensive) destination-size walk is refreshed.
# Kept coarse on purpose: re-measuring a growing destination tree too often
# adds real I/O load on exactly the slow drives this is meant to help.
PROGRESS_MEASURE_INTERVAL_SECONDS = 1.0
# How often the progress dialog itself is allowed to repaint/re-announce.
PROGRESS_UI_MIN_INTERVAL_SECONDS = 1.0
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
		# self.active_process is written from the copy worker thread and
		# read/terminated from cleanup(), which can run on a different
		# thread (e.g. plugin.terminate() during an add-on reload while a
		# copy is still in flight). Without this lock, cleanup() could
		# terminate a stale Popen reference or race the worker thread's
		# own reassignment of it between subprocess attempts.
		self._processLock = threading.Lock()

	def _setActiveProcess(self, process):
		with self._processLock:
			self.active_process = process

	def _getActiveProcess(self):
		with self._processLock:
			return self.active_process

	def _get_explorer_data_via_com_async(self, get_selection, callback):
		# Reuse the plugin's tab-aware resolution instead of spinning up a
		# separate Shell.Application and re-doing an unvalidated hwnd match:
		# that duplicate logic could not tell tabs apart on a Windows 11
		# tabbed Explorer window and would silently return whichever tab's
		# COM entry it happened to enumerate first.
		def afterPath(current_folder):
			if not get_selection:
				callback(current_folder, [])
				return

			def afterSelection(selectedItems, _hwnd):
				paths = [path for _name, path in selectedItems] if selectedItems else []
				callback(current_folder, paths)

			self.plugin._getSelectedItemsAsync(afterSelection)

		self.plugin._getCurrentPathFromExplorerAsync(afterPath)

	def copy(self):
		def handle(_current_folder, paths):
			if not paths:
				tones.beep(200, 150)
				ui.message("No items selected")
				return
			self.source_items = paths
			self.operation_type = "copy"
			tones.beep(440, 150)
			ui.message(f"Robocopy: {len(paths)} items ready")
		self._get_explorer_data_via_com_async(True, handle)

	def move(self):
		def handle(_current_folder, paths):
			if not paths:
				tones.beep(200, 150)
				ui.message("No items selected")
				return
			self.source_items = paths
			self.operation_type = "move"
			tones.beep(440, 150)
			ui.message(f"Robocopy: {len(paths)} items ready to move")
		self._get_explorer_data_via_com_async(True, handle)

	def paste(self):
		if not self.source_items:
			tones.beep(200, 150)
			ui.message("Nothing to paste")
			return

		def handle(current_folder, _paths):
			dest_path = current_folder
			if not dest_path:
				dest_path = getattr(self.plugin.manager, "lastExplorerPath", None)
			if not dest_path:
				self.plugin._getCurrentPathFromExplorerAsync(self._finishPaste)
				return
			self._finishPaste(dest_path)

		self._get_explorer_data_via_com_async(False, handle)

	def _finishPaste(self, dest_path):
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

	def _buildRobocopyCommand(self, source, dest, isDir, isMove, useMultiThread, isSlowDrive):
		if isDir:
			sourceName = os.path.basename(source)
			targetDest = os.path.join(dest, sourceName)
			cmd = ["robocopy", source, targetDest, "/E"]
		else:
			sourceDir = os.path.dirname(source)
			sourceName = os.path.basename(source)
			cmd = ["robocopy", sourceDir, dest, sourceName]
		# /J: unbuffered I/O, avoids cache-related stalls and corruption on slow removable media.
		# Old/slow drives get many SHORT retries (/R high, /W low) instead of the default few
		# long waits: their failures are usually brief controller hiccups rather than the kind
		# of outage a long wait helps with. This is what previously let large multi-file
		# transfers on old USB sticks give up (or take far longer than needed) before finishing.
		if isSlowDrive:
			cmd += ["/R:10", "/W:2", "/J", "/V", "/NP"]
		else:
			cmd += ["/R:5", "/W:5", "/J", "/V", "/NP"]
		if isDir:
			cmd.append("/XJ")
		if useMultiThread:
			cmd.append("/MT:8")
		if isMove:
			cmd.append("/MOVE")
		return cmd

	def _computeTransferSizes(self, sources):
		"""Metadata-only pass (file sizes only, no content read) to get a real
		total byte count up front, per source. Progress is then reported as
		bytes-copied/bytes-total instead of one tick per top-level selected
		item, which previously meant a single large folder or file sat at 0%
		for the entire copy and only jumped once it finished."""
		perSourceBytes = []
		totalBytes = 0
		for source in sources:
			sourceBytes = 0
			try:
				if os.path.isdir(source):
					for root, dirs, files in os.walk(source):
						for fileName in files:
							try:
								sourceBytes += os.path.getsize(os.path.join(root, fileName))
							except OSError:
								continue
				else:
					sourceBytes = os.path.getsize(source)
			except OSError:
				pass
			perSourceBytes.append(sourceBytes)
			totalBytes += sourceBytes
		return perSourceBytes, totalBytes

	def _measurePathBytes(self, path):
		"""Bounded size check of what has been written to a single
		destination so far - called on a throttle (PROGRESS_MEASURE_INTERVAL)
		so repeatedly walking a growing destination tree doesn't itself add
		meaningful I/O load on the slow drive we're trying to protect."""
		total = 0
		try:
			if os.path.isdir(path):
				for root, dirs, files in os.walk(path):
					for fileName in files:
						try:
							total += os.path.getsize(os.path.join(root, fileName))
						except OSError:
							continue
			elif os.path.isfile(path):
				total = os.path.getsize(path)
		except OSError:
			pass
		return total

	@staticmethod
	def _formatETA(seconds):
		if seconds is None or seconds == float("inf") or seconds <= 0:
			return _("estimating time remaining")
		seconds = int(seconds)
		hours, rem = divmod(seconds, 3600)
		minutes, secs = divmod(rem, 60)
		if hours:
			return _("{h}h {m}m remaining").format(h=hours, m=minutes)
		if minutes:
			return _("{m}m {s}s remaining").format(m=minutes, s=secs)
		return _("{s}s remaining").format(s=secs)

	@staticmethod
	def _formatSpeed(bytesPerSecond):
		if bytesPerSecond <= 0:
			return ""
		value = bytesPerSecond
		for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
			if value < 1024:
				return f"{value:.1f} {unit}"
			value /= 1024
		return f"{value:.1f} TB/s"

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

	def _reportProgress(self, dlg, target_dest, bytesCompletedBeforeCurrent, totalBytes,
			startTime, itemIndex, totalItems, source_name, measureCache):
		now = time.monotonic()
		if now - measureCache["time"] >= PROGRESS_MEASURE_INTERVAL_SECONDS:
			measureCache["bytes"] = self._measurePathBytes(target_dest)
			measureCache["time"] = now
		copiedSoFar = bytesCompletedBeforeCurrent + measureCache["bytes"]
		percentage = int((copiedSoFar / totalBytes) * 100) if totalBytes else 0
		# Never claim 100% until the item has actually finished - the exact
		# final byte count on disk can lag the reported percentage slightly.
		percentage = max(0, min(percentage, 99))
		elapsed = now - startTime
		speed = copiedSoFar / elapsed if elapsed > 0 else 0
		remainingBytes = max(totalBytes - copiedSoFar, 0)
		eta = remainingBytes / speed if speed > 0 else None
		speedText = self._formatSpeed(speed)
		statusText = _("{pct}% - item {idx}/{total}: {name}").format(
			pct=percentage, idx=itemIndex, total=totalItems, name=source_name
		)
		if speedText:
			statusText += f" - {speedText}"
		statusText += f" - {self._formatETA(eta)}"
		wx.CallAfter(dlg.update_progress, percentage, statusText)

	def _run_transfer(self, sources, dest, is_move):
		dlg = None

		def create_dlg():
			nonlocal dlg
			dlg = ProgressDialog(gui.mainFrame, "xPloyer Robocopy")
			dlg.Show()
		wx.CallAfter(create_dlg)
		time.sleep(0.3)

		if dlg:
			wx.CallAfter(dlg.update_progress, 0, _("Calculating total size..."))
		perSourceBytes, totalBytes = self._computeTransferSizes(sources)

		isSlowDrive = self._isRemovableDrive(dest)
		useMultiThread = not isSlowDrive
		totalItems = len(sources)
		failedItems = []
		succeededCount = 0
		wasCancelled = False
		startTime = time.monotonic()
		bytesCompletedBeforeCurrent = 0

		for idx, source in enumerate(sources):
			if dlg and dlg.is_cancelled:
				wasCancelled = True
				break
			source_name = os.path.basename(source)
			is_dir = os.path.isdir(source)
			target_dest = os.path.join(dest, source_name)

			# Try once with the drive's normal threading mode; if that attempt
			# fails outright, retry the SAME source single-threaded with the
			# more patient slow-drive retry timing before giving up entirely.
			# This also protects against drives Windows misreports as fixed
			# (e.g. through a generic USB card-reader enclosure) but which are
			# actually old and slow: robocopy's own /MT overload is what most
			# often caused an otherwise-good copy to fail partway through.
			attemptPlan = [(useMultiThread, isSlowDrive)]
			if useMultiThread:
				attemptPlan.append((False, True))

			succeededThisSource = False
			measureCache = {"bytes": 0, "time": 0.0}

			for attemptMultiThread, attemptSlowTuning in attemptPlan:
				if succeededThisSource or wasCancelled:
					break
				cmd = self._buildRobocopyCommand(source, dest, is_dir, is_move, attemptMultiThread, attemptSlowTuning)

				try:
					startupinfo = subprocess.STARTUPINFO()
					startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
					process = subprocess.Popen(
						cmd,
						stdout=subprocess.PIPE,
						stderr=subprocess.STDOUT,
						startupinfo=startupinfo,
						creationflags=subprocess.CREATE_NO_WINDOW
					)
					self._setActiveProcess(process)

					outputQueue, readerThread = self._startStdoutReader(process)
					summaryLines = []
					lastUiUpdateTime = 0.0

					while True:
						if dlg and dlg.is_cancelled:
							wasCancelled = True
							process.terminate()
							break
						try:
							line = outputQueue.get(timeout=QUEUE_POLL_TIMEOUT)
						except queue.Empty:
							if process.poll() is not None:
								break
							now = time.monotonic()
							if dlg and now - lastUiUpdateTime >= PROGRESS_UI_MIN_INTERVAL_SECONDS:
								lastUiUpdateTime = now
								self._reportProgress(dlg, target_dest, bytesCompletedBeforeCurrent,
										totalBytes, startTime, idx + 1, totalItems, source_name, measureCache)
							continue
						if line is None:
							break
						summaryLines.append(line)
						now = time.monotonic()
						if dlg and now - lastUiUpdateTime >= PROGRESS_UI_MIN_INTERVAL_SECONDS:
							lastUiUpdateTime = now
							self._reportProgress(dlg, target_dest, bytesCompletedBeforeCurrent,
									totalBytes, startTime, idx + 1, totalItems, source_name, measureCache)

					readerThread.join(timeout=2)
					try:
						process.wait(timeout=10)
					except subprocess.TimeoutExpired:
						process.kill()
						process.wait(timeout=5)
					exit_code = process.returncode

					if wasCancelled:
						break

					if exit_code is not None and exit_code >= 8:
						log.error(f"Robocopy error for {source_name} (exit code: {exit_code})")
						continue

					if exit_code is None:
						log.warning(f"Robocopy for {source_name} finished but exit code is None")

					failedInSummary = self._parseFailedCount(summaryLines)
					if failedInSummary > 0:
						log.error(f"Robocopy reported {failedInSummary} failed file(s) for {source_name}")
						continue

					if not is_dir and not self._verify_file_copy(source, target_dest):
						log.error(f"Verification failed for {source_name}")
						continue

					log.debug(f"Robocopy success for {source_name} (exit code: {exit_code})")
					succeededThisSource = True

				except (OSError, subprocess.SubprocessError) as e:
					log.exception(f"Robocopy error for {source_name}: {e}")
					continue

			if wasCancelled:
				break

			if succeededThisSource:
				succeededCount += 1
			else:
				failedItems.append(source_name)

			bytesCompletedBeforeCurrent += perSourceBytes[idx]
			if dlg:
				overallPercentage = int((bytesCompletedBeforeCurrent / totalBytes) * 100) if totalBytes else 0
				wx.CallAfter(dlg.update_progress, min(overallPercentage, 100),
						_("Finished {n} of {total}: {name}").format(n=idx + 1, total=totalItems, name=source_name))

		def cleanup_dlg():
			if dlg:
				dlg.Destroy()
		wx.CallAfter(cleanup_dlg)

		if wasCancelled:
			tones.beep(200, 150)
			core.callLater(0, ui.message, _("Robocopy cancelled"))
			return

		operationHistory = getattr(self.plugin, "operationHistory", None)
		actionWord = _("Moved") if is_move else _("Copied")

		if failedItems:
			tones.beep(200, 300)
			shownItems = ", ".join(failedItems[:5])
			if len(failedItems) > 5:
				shownItems += _(" and {n} more").format(n=len(failedItems) - 5)
			core.callLater(0, ui.message, _("Robocopy finished. {ok} succeeded, {failed} failed: {items}").format(
					ok=succeededCount, failed=len(failedItems), items=shownItems))
			if operationHistory and succeededCount:
				operationHistory.addEntry(_("{action} {n} item(s) to {dest} ({failed} failed)").format(
						action=actionWord, n=succeededCount, dest=dest, failed=len(failedItems)))
		else:
			tones.beep(1760, 300)
			core.callLater(0, ui.message, _("Robocopy finished successfully. {n} item(s) copied").format(n=succeededCount))
			if operationHistory and succeededCount:
				operationHistory.addEntry(_("{action} {n} item(s) to {dest}").format(
						action=actionWord, n=succeededCount, dest=dest))

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
		process = self._getActiveProcess()
		if process and process.poll() is None:
			try:
				process.terminate()
			except OSError:
				pass

