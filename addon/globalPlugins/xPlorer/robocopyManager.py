# robocopyManager.py

import ui
import api
import os
import wx
import gui
import gui.guiHelper
import subprocess
import threading
import time
import addonHandler
import core
import tones
import comtypes.client
from urllib.parse import unquote
from logHandler import log

addonHandler.initTranslation()

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

	def _run_transfer(self, sources, dest, is_move):
		dlg = None
		def create_dlg():
			nonlocal dlg
			dlg = ProgressDialog(gui.mainFrame, "xPloyer Robocopy")
			dlg.Show()
		wx.CallAfter(create_dlg)
		time.sleep(0.3)

		total_files = len(sources)
		for idx, source in enumerate(sources):
			if dlg and dlg.is_cancelled:
				break
			source_name = os.path.basename(source)
			is_dir = os.path.isdir(source)

			if is_dir:
				target_dest = os.path.join(dest, source_name)
				cmd = ["robocopy", source, target_dest, "/E", "/MT:8", "/R:5", "/W:5", "/V", "/NP", "/XJ"]
			else:
				source_dir = os.path.dirname(source)
				cmd = ["robocopy", source_dir, dest, source_name, "/MT:8", "/R:5", "/W:5", "/V", "/NP"]
			if is_move:
				cmd.append("/MOVE")

			try:
				startupinfo = subprocess.STARTUPINFO()
				startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
				self.active_process = subprocess.Popen(
					cmd,
					stdout=subprocess.PIPE,
					stderr=subprocess.STDOUT,
					universal_newlines=True,
					startupinfo=startupinfo,
					creationflags=subprocess.CREATE_NO_WINDOW
				)

				stdout_lines = []
				for line in self.active_process.stdout:
					stdout_lines.append(line)
					if dlg and dlg.is_cancelled:
						self.active_process.terminate()
						break
					wx.CallAfter(dlg.update_progress, int((idx + 1) / total_files * 100), f"Processing: {source_name}")

				self.active_process.wait()
				exit_code = self.active_process.returncode

				if exit_code is not None:
					if exit_code >= 8:
						error_msg = f"Robocopy error for {source_name} (exit code: {exit_code})"
						log.error(error_msg)
						core.callLater(0, ui.message, error_msg)
						def stop_and_notify():
							if dlg:
								dlg.Destroy()
							ui.message("Copy failed due to errors. Check NVDA log.")
						wx.CallAfter(stop_and_notify)
						return
					else:
						log.debug(f"Robocopy success for {source_name} (exit code: {exit_code})")
				else:
					log.warning(f"Robocopy for {source_name} finished but exit code is None")

				if not is_dir and not self._verify_file_copy(source, os.path.join(dest, source_name)):
					error_msg = f"Verification failed for {source_name}"
					log.error(error_msg)
					core.callLater(0, ui.message, error_msg)
					return

			except Exception as e:
				log.exception(f"Robocopy error for {source_name}: {e}")
				continue

		def cleanup_dlg():
			if dlg:
				dlg.Destroy()
		wx.CallAfter(cleanup_dlg)
		tones.beep(1760, 300)
		ui.message("Robocopy finished successfully")

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
		except Exception as e:
			log.error(f"Verification error: {e}")
			return False

	def cleanup(self):
		if self.active_process and self.active_process.poll() is None:
			try:
				self.active_process.terminate()
			except Exception:
				pass