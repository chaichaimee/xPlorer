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

	def _recalc_size(self, i_result, i_total_size=0):
		f_result = float(i_result)
		if i_total_size > 0:
			i_total_size = float(i_total_size)
			f_result = i_total_size - f_result    
		i = 0
		while f_result >= 1024:
			f_result = f_result / 1024
			i = i + 1
		s_recalc_size = ' {:.2f}'.format(f_result)
		s_result = (s_recalc_size, i)
		return s_result

	def _get_folder_size_windows_api(self, folder_path):
		try:
			import ctypes
			from ctypes import wintypes, windll, c_longlong, c_ulonglong, POINTER, Structure, c_int, c_uint, c_void_p
			
			class LARGE_INTEGER(Structure):
				_fields_ = [("QuadPart", c_longlong)]
				
			GetFileSizeEx = windll.kernel32.GetFileSizeEx
			GetFileSizeEx.argtypes = [wintypes.HANDLE, POINTER(LARGE_INTEGER)]
			GetFileSizeEx.restype = wintypes.BOOL
			
			FindFirstFile = windll.kernel32.FindFirstFileW
			FindFirstFile.argtypes = [wintypes.LPCWSTR, POINTER(wintypes.WIN32_FIND_DATAW)]
			FindFirstFile.restype = wintypes.HANDLE
			
			FindNextFile = windll.kernel32.FindNextFileW
			FindNextFile.argtypes = [wintypes.HANDLE, POINTER(wintypes.WIN32_FIND_DATAW)]
			FindNextFile.restype = wintypes.BOOL
			
			FindClose = windll.kernel32.FindClose
			FindClose.argtypes = [wintypes.HANDLE]
			FindClose.restype = wintypes.BOOL
			
			def get_folder_size_iterative(start_path):
				total = 0
				stack = [start_path]
				while stack:
					current_path = stack.pop()
					find_data = wintypes.WIN32_FIND_DATAW()
					handle = FindFirstFile(os.path.join(current_path, "*"), ctypes.byref(find_data))
					if handle == wintypes.HANDLE(-1):
						continue
					try:
						while True:
							name = find_data.cFileName
							if name not in ('.', '..'):
								full_path = os.path.join(current_path, name)
								if find_data.dwFileAttributes & 16:
									stack.append(full_path)
							if not FindNextFile(handle, ctypes.byref(find_data)):
								break
					finally:
						FindClose(handle)
				stack = [start_path]
				while stack:
					current_path = stack.pop()
					find_data = wintypes.WIN32_FIND_DATAW()
					handle = FindFirstFile(os.path.join(current_path, "*"), ctypes.byref(find_data))
					if handle == wintypes.HANDLE(-1):
						continue
					try:
						while True:
							name = find_data.cFileName
							if name not in ('.', '..'):
								full_path = os.path.join(current_path, name)
								if not (find_data.dwFileAttributes & 16):
									size_high = find_data.nFileSizeHigh
									size_low = find_data.nFileSizeLow
									file_size = (c_ulonglong(size_high).value << 32) + size_low
									total += file_size
							if not FindNextFile(handle, ctypes.byref(find_data)):
								break
					finally:
						FindClose(handle)
				return total
			
			return get_folder_size_iterative(folder_path)
		except Exception as e:
			log.error(f"Error in Windows API folder size calculation: {e}")
			return None

	def _calculate_folder_size_fast(self, folder_path):
		api_size = self._get_folder_size_windows_api(folder_path)
		if api_size is not None:
			return api_size
		return None

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
			
		selectedItems, _ignore = self.plugin._getSelectedItems()
		if not selectedItems:
			ui.message(_("No items selected"))
			return
		
		inaccessible_items = []
		for name, path in selectedItems:
			if not self._check_access_permission(path):
				inaccessible_items.append(name)
		
		if inaccessible_items and len(inaccessible_items) == len(selectedItems):
			ui.message(_("No access to size data"))
			return
		
		self._stop_calculation()
		self._calculation_active = True
		self._start_beeping()
		
		def calculate_size():
			try:
				total_size = 0
				is_drive = False
				accessible_item_count = 0
				
				for name, path in selectedItems:
					if not self._calculation_active:
						break
					if name in inaccessible_items:
						continue
					accessible_item_count += 1
					if self.plugin.objFSO.FileExists(path):
						try:
							file_size = self.plugin.objFSO.GetFile(path).Size
							total_size += file_size
						except Exception as e:
							log.error(f"Error getting file size for {name}: {e}")
					elif self.plugin.objFSO.DriveExists(path):
						is_drive = True
						try:
							drive = self.plugin.objFSO.GetDrive(path)
							used_size = drive.TotalSize - drive.FreeSpace
							total_size += used_size
						except Exception as e:
							log.error(f"Error getting drive size for {name}: {e}")
					elif self.plugin.objFSO.FolderExists(path):
						folder_size = self._calculate_folder_size_fast(path)
						if folder_size is not None and folder_size > 0:
							total_size += folder_size
						else:
							folder_size = 0
							count = 0
							max_files_to_check = 1000
							for root, _, files in os.walk(path):
								for f in files:
									if count >= max_files_to_check or not self._calculation_active:
										break
									fp = os.path.join(root, f)
									try:
										folder_size += os.path.getsize(fp)
										count += 1
									except (OSError, WindowsError):
										pass
								if count >= max_files_to_check or not self._calculation_active:
									break
								time.sleep(0.01)
							if count > 0:
								avg_size = folder_size / count
								estimated_total_files = count * 10
								folder_size = avg_size * estimated_total_files
							total_size += folder_size
				
				self._stop_beeping()
				self._calculation_active = False
				core.callLater(0, self._display_size_result, total_size, is_drive, accessible_item_count)
			except Exception as e:
				log.error(f"Error in size calculation thread: {e}")
				self._stop_beeping()
				self._calculation_active = False
				core.callLater(0, ui.message, _("Error calculating size"))
		
		self._size_thread = threading.Thread(target=calculate_size, daemon=True)
		self._size_thread.start()

	def _display_size_result(self, total_size, is_drive, item_count):
		if total_size == 0 and not is_drive:
			ui.message(_("No access to size data"))
			return
		col_recalc = self._recalc_size(total_size)
		s_dimension = [" bytes", " KB", " MB", " GB", " TB"][col_recalc[1]]
		s_recalc_size = col_recalc[0]
		s_info = s_recalc_size + s_dimension
		if item_count > 1:
			s_info = _("{count} items {size}").format(count=item_count, size=s_info)
		ui.message(s_info)

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