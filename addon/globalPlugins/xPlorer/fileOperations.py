# fileOperations.py

import ui
import api
import os
import wx
import gui
import gui.guiHelper
import subprocess
import time
import threading
from logHandler import log
import addonHandler
import tones
import core

addonHandler.initTranslation()

class RenameDialog(wx.Dialog):
	def __init__(self, parent, file_name):
		super().__init__(parent, title="")
		self.file_name = file_name
		self.new_name = None
		self.name_ctrl = None
		self.ext_ctrl = None
		self._init_ui()
		
	def _init_ui(self):
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		
		name, ext = os.path.splitext(self.file_name)
		
		self.name_ctrl = s_helper.addItem(wx.TextCtrl(self, value=name))
		self.name_ctrl.SelectAll()
		
		if ext and ext.startswith('.'):
			ext = ext[1:]
		self.ext_ctrl = s_helper.addItem(wx.TextCtrl(self, value=ext))
		
		btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)
		
		self.SetSizer(main_sizer)
		main_sizer.Fit(self)
		self.CentreOnScreen()
		self.name_ctrl.SetFocus()
		
		self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
		self.Bind(wx.EVT_TEXT_ENTER, self._on_ok)
		self.Bind(wx.EVT_CLOSE, self._on_close)
		
	def _on_ok(self, event):
		name = self.name_ctrl.Value.strip()
		ext = self.ext_ctrl.Value.strip()
		
		if not name:
			ui.message(_("File name cannot be empty"))
			return
			
		if ext:
			ext = "." + ext
		self.new_name = name + ext
		self.EndModal(wx.ID_OK)
		
	def _on_cancel(self, event):
		self.EndModal(wx.ID_CANCEL)
		
	def _on_close(self, event):
		self.EndModal(wx.ID_CANCEL)

class FileOperations:
	def __init__(self, plugin):
		self.plugin = plugin
		self.rename_dialog = None
		self._beep_timer = None
		self._calculation_active = False
		self._stop_beep_event = threading.Event()
		self._size_thread = None

	def cleanup(self):
		self._stop_calculation()
		if self.rename_dialog:
			try:
				self.rename_dialog.Destroy()
			except:
				pass

	def _stop_calculation(self):
		self._calculation_active = False
		self._stop_beeping()
		if self._size_thread and self._size_thread.is_alive():
			self._size_thread.join(timeout=1.0)

	def _start_beeping(self):
		self._stop_beep_event.clear()
		self._beep_timer = threading.Timer(2.0, self._beep_interval)
		self._beep_timer.daemon = True
		self._beep_timer.start()

	def _stop_beeping(self):
		self._stop_beep_event.set()
		if self._beep_timer:
			self._beep_timer.cancel()
			self._beep_timer = None

	def _beep_interval(self):
		if not self._stop_beep_event.is_set():
			core.callLater(0, tones.beep, 440, 100)
			self._beep_timer = threading.Timer(2.0, self._beep_interval)
			self._beep_timer.daemon = True
			self._beep_timer.start()

	def _format_size(self, size_in_bytes):
		if size_in_bytes < 1024:
			return f"{size_in_bytes} bytes"
		elif size_in_bytes < 1024 * 1024:
			return f"{size_in_bytes / 1024:.2f} KB"
		elif size_in_bytes < 1024 * 1024 * 1024:
			return f"{size_in_bytes / (1024 * 1024):.2f} MB"
		else:
			return f"{size_in_bytes / (1024 * 1024 * 1024):.2f} GB"

	FAST_SIZE_FILE_CAP = 9000

	def _computeBoundedFolderSize(self, folder_paths, maxFiles=None):
		"""Try to get an exact recursive size for the given folders, bailing
		out (returning None) as soon as the file count exceeds maxFiles.
		Byte size is irrelevant to how long this takes - stat() costs the
		same for a 1KB file as a 1GB one - only the number of entries
		scanned matters, so the cap is on file count."""
		if maxFiles is None:
			maxFiles = self.FAST_SIZE_FILE_CAP
		total_size = 0
		file_count = 0
		pendingDirs = list(folder_paths)
		while pendingDirs:
			current_dir = pendingDirs.pop()
			try:
				with os.scandir(current_dir) as entries:
					for entry in entries:
						try:
							if entry.is_dir(follow_symlinks=False):
								pendingDirs.append(entry.path)
							else:
								total_size += entry.stat(follow_symlinks=False).st_size
								file_count += 1
								if file_count > maxFiles:
									return None
						except OSError:
							continue
			except OSError:
				continue
		return total_size

	def _get_folder_size_accurate(self, folder_path):
		total_size = 0
		try:
			pendingDirs = [folder_path]
			while pendingDirs:
				if not self._calculation_active:
					return 0
				current_dir = pendingDirs.pop()
				try:
					with os.scandir(current_dir) as entries:
						for entry in entries:
							if not self._calculation_active:
								return 0
							try:
								if entry.is_dir(follow_symlinks=False):
									pendingDirs.append(entry.path)
								else:
									# DirEntry.stat() reuses the stat info the OS already
									# returned while listing this directory, instead of a
									# second syscall via os.path.getsize() per file - a real
									# speedup on large trees and slow/network drives.
									total_size += entry.stat(follow_symlinks=False).st_size
							except OSError:
								continue
				except OSError:
					continue
			return total_size
		except Exception as e:
			log.error(f"Error calculating folder size for {folder_path}: {e}")
			return 0

	def _check_access_permission(self, path):
		try:
			if os.path.isdir(path):
				next(os.scandir(path), None)
				return True
			elif os.path.isfile(path):
				with open(path, 'rb') as f:
					f.read(1)
				return True
			return False
		except (PermissionError, OSError, WindowsError):
			return False
		except Exception:
			return True

	def saySize(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			return
			
		selected_items, _ignore = self.plugin._getSelectedItems()
		if not selected_items:
			ui.message(_("No items selected"))
			return
		
		inaccessible_items = []
		for name, path in selected_items:
			if not self._check_access_permission(path):
				inaccessible_items.append(name)
		
		if inaccessible_items and len(inaccessible_items) == len(selected_items):
			ui.message(_("No access to size data"))
			return
		
		self._stop_calculation()
		self._calculation_active = True
		self._start_beeping()
		
		def calculate_size():
			try:
				total_size = 0
				accessible_item_count = 0
				is_drive = False
				
				for name, path in selected_items:
					if not self._calculation_active:
						break
					if name in inaccessible_items:
						continue
						
					accessible_item_count += 1
					
					if os.path.isfile(path):
						try:
							file_size = os.path.getsize(path)
							total_size += file_size
						except Exception as e:
							log.error(f"Error getting file size for {name}: {e}")
							
					elif os.path.isdir(path):
						try:
							drive_letter = os.path.splitdrive(path)[0]
							if drive_letter and len(drive_letter) == 2 and drive_letter[1] == ':':
								if path == drive_letter + "\\":
									is_drive = True
									import ctypes
									free_bytes = ctypes.c_ulonglong(0)
									total_bytes = ctypes.c_ulonglong(0)
									if ctypes.windll.kernel32.GetDiskFreeSpaceExW(
										ctypes.c_wchar_p(path), None,
										ctypes.byref(total_bytes),
										ctypes.byref(free_bytes)
									):
										used_size = total_bytes.value - free_bytes.value
										total_size += used_size
									continue
							
							folder_size = self._get_folder_size_accurate(path)
							total_size += folder_size
						except Exception as e:
							log.error(f"Error getting folder size for {name}: {e}")
				
				self._stop_beeping()
				self._calculation_active = False
				
				formatted_size = self._format_size(total_size)
				
				if accessible_item_count == 0:
					display_message = _("No access to size data")
				elif accessible_item_count == 1:
					if is_drive:
						display_message = formatted_size
					else:
						display_message = formatted_size
				else:
					display_message = _("{count} items {size}").format(
						count=accessible_item_count, 
						size=formatted_size
					)
				
				core.callLater(0, ui.message, display_message)
				
			except Exception as e:
				log.error(f"Error in size calculation thread: {e}")
				self._stop_beeping()
				self._calculation_active = False
				core.callLater(0, ui.message, _("Error calculating size"))
		
		self._size_thread = threading.Thread(target=calculate_size, daemon=True)
		self._size_thread.start()

	def renameFile(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			return
		try:
			selectedItems, _ignore = self.plugin._getSelectedItems()
			if not selectedItems:
				ui.message(_("No items selected"))
				return
			if len(selectedItems) > 1:
				ui.message(_("Please select only one file"))
				return
			file_path = selectedItems[0][1]
			if not os.path.isfile(file_path):
				ui.message(_("Please select a file, not a folder"))
				return
			file_name = os.path.basename(file_path)
			dir_name = os.path.dirname(file_path)
			wx.CallAfter(self._show_rename_dialog, file_name, dir_name, file_path)
		except Exception as e:
			log.error(f"Error in renameFile: {e}")
			ui.message(_("Error renaming file"))

	def _show_rename_dialog(self, file_name, dir_name, file_path):
		dialog = None
		try:
			if gui.mainFrame:
				gui.mainFrame.prePopup()
			
			dialog = RenameDialog(gui.mainFrame, file_name)
			dialog.CentreOnScreen()
			dialog.Raise()
			
			result = dialog.ShowModal()
			
			if result == wx.ID_OK and dialog.new_name:
				new_path = os.path.join(dir_name, dialog.new_name)
				if new_path == file_path:
					ui.message(_("File name not changed"))
					return
				if os.path.exists(new_path):
					ui.message(_("A file with this name already exists"))
					return
				try:
					os.rename(file_path, new_path)
					ui.message(_("File renamed to {name}").format(name=dialog.new_name))
				except Exception as e:
					log.error(f"Error renaming file: {e}")
					ui.message(_("Error renaming file"))
		except Exception as e:
			log.error(f"Error showing rename dialog: {e}")
			ui.message(_("Error opening rename dialog"))
		finally:
			if dialog:
				dialog.Destroy()
			if gui.mainFrame:
				gui.mainFrame.postPopup()

