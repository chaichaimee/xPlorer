# folderTools.py

import os
import json
from logHandler import log
import threading
import wx
import ui
import addonHandler
import speech
import core
import tones
import time
import winUser
import ctypes
import ctypes.wintypes
import re
import api
from keyboardHandler import KeyboardInputGesture
import gui
import subprocess
from ctypes import wintypes

addonHandler.initTranslation()

# ---- from config.py ----

CONFIG_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "nvda", "ChaiChaimee")
CONFIG_FILE = os.path.join(CONFIG_DIR, "xplorer.json")

DEFAULT_CONFIG = {
	"autoSelectFirstItem": True,
	"announceEmptyFolder": True,
	"suppressDirectUIAnnounce": True,
	"sayFileExplorer": True,
	"autoPasteClipboardToRename": True,
}

def loadConfig():
	if not os.path.exists(CONFIG_FILE):
		return DEFAULT_CONFIG.copy()
	try:
		with open(CONFIG_FILE, "r", encoding="utf-8") as f:
			conf = json.load(f)
		for key, value in DEFAULT_CONFIG.items():
			if key not in conf:
				conf[key] = value
		return conf
	except Exception as e:
		log.error(f"Error loading config: {e}")
		return DEFAULT_CONFIG.copy()

def saveConfig(conf):
	try:
		if not os.path.exists(CONFIG_DIR):
			os.makedirs(CONFIG_DIR)
		with open(CONFIG_FILE, "w", encoding="utf-8") as f:
			json.dump(conf, f, indent=2, ensure_ascii=False)
	except Exception as e:
		log.error(f"Error saving config: {e}")


# ---- from folderInfo.py ----

class FolderInfoManager:
	FAST_INFO_ENTRY_CAP = 9000

	def __init__(self, plugin):
		self.plugin = plugin
		self._stop_walk = False

	def cleanup(self):
		self._stop_walk = True

	def _computeBoundedFolderCounts(self, folder_paths, maxEntries=None):
		"""Try to get exact recursive subfolder/file counts, bailing out
		(returning None) as soon as the total entries scanned exceeds
		maxEntries. The previous top-level-only scan reported '0 files' for
		any folder whose files were all nested inside subfolders rather than
		sitting directly in it - correct for "top level only" but not what
		was expected. A bounded recursive walk fixes that while staying
		instant for anything reasonably sized, matching the same file-count
		cap FileOperations uses for the Say size label."""
		if maxEntries is None:
			maxEntries = self.FAST_INFO_ENTRY_CAP
		subfolder_count = 0
		file_count = 0
		pendingDirs = list(folder_paths)
		while pendingDirs:
			current_dir = pendingDirs.pop()
			try:
				with os.scandir(current_dir) as entries:
					for entry in entries:
						try:
							if entry.is_dir(follow_symlinks=False):
								subfolder_count += 1
								pendingDirs.append(entry.path)
							else:
								file_count += 1
							if subfolder_count + file_count > maxEntries:
								return None
						except OSError:
							continue
			except OSError:
				continue
		return subfolder_count, file_count

	def get_folder_info(self):
		speech.cancelSpeech()
		self.plugin.manager.suppressAllAnnouncements = True
		self._stop_walk = False
		
		def delayed_retrieve():
			selected_items, _ignore = self.plugin._getSelectedItems()
			if not selected_items:
				wx.CallAfter(ui.message, _("No item selected"))
				self._restore_speech()
				return

			folder_paths = [path for _name, path in selected_items if os.path.isdir(path)]
			if not folder_paths:
				wx.CallAfter(ui.message, _("Selected item is not a folder"))
				self._restore_speech()
				return

			threading.Thread(target=self._calculate_folder_info_streaming, args=(folder_paths,), daemon=True).start()

		core.callLater(500, delayed_retrieve)

	def _restore_speech(self):
		core.callLater(800, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))

	def _calculate_folder_info_streaming(self, folder_paths):
		try:
			subfolder_count = 0
			file_count = 0
			for folder_path in folder_paths:
				for root, dirs, files in os.walk(folder_path):
					if self._stop_walk:
						break
					subfolder_count += len(dirs)
					file_count += len(files)
				if self._stop_walk:
					break

			message = _("{subfolders} subfolders and {files} files").format(
				subfolders=subfolder_count,
				files=file_count
			)
			wx.CallAfter(speech.cancelSpeech)
			wx.CallAfter(ui.message, message)
			wx.CallAfter(self._restore_speech)
		except Exception as e:
			log.error(f"Error calculating folder info: {e}")
			wx.CallAfter(ui.message, _("Error calculating folder info"))
			wx.CallAfter(self._restore_speech)


# ---- from folder_creation_dialog.py ----

class FolderCreationDialog(wx.Dialog):
	def __init__(self, parent, current_path):
		super().__init__(parent, title=_("Create Multiple Folders"), style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
		self.current_path = current_path
		self.folder_edit_controls = []
		self.last_update_time = 0
		self.update_timer = None
		self._creation_thread = None
		self._init_ui()
		self.CentreOnScreen()
		self.Raise()
		
	def _init_ui(self):
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		
		title_sizer = wx.BoxSizer(wx.HORIZONTAL)
		title_label = wx.StaticText(self, label=_("Folder title:"))
		self.title_text = wx.TextCtrl(self)
		self.title_text.SetValue("")
		title_sizer.Add(title_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		title_sizer.Add(self.title_text, 1, wx.ALL | wx.EXPAND, 5)
		main_sizer.Add(title_sizer, 0, wx.EXPAND)
		
		number_sizer = wx.BoxSizer(wx.HORIZONTAL)
		number_label = wx.StaticText(self, label=_("Number of folders:"))
		self.number_text = wx.TextCtrl(self)
		self.number_text.SetValue("10")
		number_sizer.Add(number_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		number_sizer.Add(self.number_text, 1, wx.ALL | wx.EXPAND, 5)
		main_sizer.Add(number_sizer, 0, wx.EXPAND)
		
		self.subfolder_checkbox = wx.CheckBox(self, label=_("Create main folder and then subfolders"))
		self.subfolder_checkbox.SetValue(False)
		main_sizer.Add(self.subfolder_checkbox, 0, wx.ALL | wx.EXPAND, 5)
		
		self.edit_names_checkbox = wx.CheckBox(self, label=_("Edit individual folder names"))
		self.edit_names_checkbox.SetValue(False)
		self.edit_names_checkbox.Bind(wx.EVT_CHECKBOX, self._on_edit_names_changed)
		main_sizer.Add(self.edit_names_checkbox, 0, wx.ALL | wx.EXPAND, 5)
		
		self.scrolled_window = wx.ScrolledWindow(self)
		self.scrolled_window.SetScrollRate(10, 10)
		self.preview_sizer = wx.BoxSizer(wx.VERTICAL)
		self.scrolled_window.SetSizer(self.preview_sizer)
		self.scrolled_window.Hide()
		main_sizer.Add(self.scrolled_window, 1, wx.ALL | wx.EXPAND, 5)
		
		button_sizer = wx.BoxSizer(wx.HORIZONTAL)
		apply_button = wx.Button(self, wx.ID_OK, label=_("&Apply"))
		cancel_button = wx.Button(self, wx.ID_CANCEL, label=_("&Cancel"))
		button_sizer.Add(apply_button, 0, wx.ALL, 5)
		button_sizer.Add(cancel_button, 0, wx.ALL, 5)
		main_sizer.Add(button_sizer, 0, wx.ALIGN_CENTER)
		
		self.SetSizer(main_sizer)
		self.SetSize((500, 400))
		
		self.title_text.Bind(wx.EVT_TEXT, self._on_title_changed)
		self.number_text.Bind(wx.EVT_TEXT, self._on_number_changed)
		self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
		
		core.callLater(100, self._update_preview)

	def _on_char_hook(self, event):
		if event.GetKeyCode() == wx.WXK_ESCAPE:
			self.EndModal(wx.ID_CANCEL)
		event.Skip()
	
	def _on_title_changed(self, event):
		self._schedule_update()
		event.Skip()
	
	def _on_number_changed(self, event):
		self._schedule_update()
		event.Skip()
	
	def _schedule_update(self):
		current_time = time.time()
		self.last_update_time = current_time
		if self.update_timer:
			self.update_timer.Stop()
		self.update_timer = core.callLater(300, self._update_preview)
	
	def _on_edit_names_changed(self, event):
		if self.edit_names_checkbox.GetValue():
			self.scrolled_window.Show()
			self._update_preview()
		else:
			self.scrolled_window.Hide()
		self.Layout()
		event.Skip()
	
	def _update_preview(self):
		if not self.edit_names_checkbox.GetValue():
			if self.scrolled_window.IsShown():
				self.scrolled_window.Hide()
				self.Layout()
			return
		
		title = self.title_text.GetValue().strip()
		if not title:
			title = _("Folder")
		
		try:
			num_folders = int(self.number_text.GetValue().strip())
			if num_folders < 1:
				num_folders = 1
			if num_folders > 100:
				num_folders = 100
				self.number_text.SetValue("100")
		except ValueError:
			num_folders = 1
			self.number_text.SetValue("1")
		
		current_count = len(self.folder_edit_controls)
		
		if current_count != num_folders:
			current_values = [ctrl.GetValue() for ctrl in self.folder_edit_controls]
			for control in self.folder_edit_controls:
				control.Destroy()
			self.folder_edit_controls.clear()
			
			for i in range(1, num_folders + 1):
				folder_sizer = wx.BoxSizer(wx.HORIZONTAL)
				number_label = wx.StaticText(self.scrolled_window, label=f"{i:02d}")
				folder_sizer.Add(number_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
				folder_edit = wx.TextCtrl(self.scrolled_window)
				if i <= len(current_values):
					folder_edit.SetValue(current_values[i-1])
				folder_sizer.Add(folder_edit, 1, wx.ALL | wx.EXPAND, 5)
				self.preview_sizer.Add(folder_sizer, 0, wx.EXPAND)
				self.folder_edit_controls.append(folder_edit)
			
			self.scrolled_window.SetSizer(self.preview_sizer)
			self.scrolled_window.Layout()
			self.scrolled_window.FitInside()
			self.scrolled_window.Refresh()
	
	def process_input(self):
		title = self.title_text.GetValue().strip()
		if not title:
			title = _("Folder")
		
		try:
			num_folders = int(self.number_text.GetValue().strip())
			if num_folders < 1:
				ui.message(_("Number of folders must be at least 1"))
				return
			if num_folders > 100:
				ui.message(_("Maximum 100 folders allowed"))
				return
		except ValueError:
			ui.message(_("Invalid number for folders"))
			return
		
		create_subfolders = self.subfolder_checkbox.GetValue()
		edit_names = self.edit_names_checkbox.GetValue()
		
		folder_names = []
		if edit_names:
			for i in range(1, num_folders + 1):
				if i <= len(self.folder_edit_controls):
					folder_name = self.folder_edit_controls[i-1].GetValue().strip()
					if folder_name:
						folder_names.append(folder_name)
		else:
			for i in range(1, num_folders + 1):
				folder_names.append(f"{title}{i}")
		
		if not folder_names:
			ui.message(_("No valid folder names provided"))
			return
		
		if create_subfolders:
			success, main_folder_name = self._create_folder(title, self.current_path)
			if not success:
				ui.message(_("Error creating main folder"))
				return
			main_folder_path = os.path.join(self.current_path, main_folder_name)
			tones.beep(1000, 100)
			self._start_background_creation(folder_names, main_folder_path, True)
		else:
			self._start_background_creation(folder_names, self.current_path, False)
	
	def _start_background_creation(self, folder_names, base_path, is_subfolder_mode):
		ui.message(_("Creating folders in background..."))
		
		def worker():
			created = 0
			total = len(folder_names)
			for idx, folder_name in enumerate(folder_names):
				cleaned = self._clean_folder_name(folder_name)
				if not cleaned:
					continue
				success, _ = self._create_folder(cleaned, base_path)
				if success:
					created += 1
				if idx % 10 == 0 and idx > 0:
					wx.CallAfter(ui.message, _("Created {count} of {total} folders...").format(count=idx, total=total))
				time.sleep(0.002)
			wx.CallAfter(self._on_creation_done, created, total, is_subfolder_mode)
		
		self._creation_thread = threading.Thread(target=worker, daemon=True)
		self._creation_thread.start()
	
	def _on_creation_done(self, created, total, is_subfolder_mode):
		if created > 0:
			tones.beep(1200, 100)
			if created == 1 and is_subfolder_mode:
				ui.message(_("Successfully created main folder only"))
			elif created == 1 and not is_subfolder_mode:
				ui.message(_("Successfully created 1 folder"))
			else:
				ui.message(_("Successfully created {count} of {total} folders").format(count=created, total=total))
		else:
			ui.message(_("No folders were created"))
	
	def _clean_folder_name(self, name):
		invalid_chars = '<>:"/\\|?*'
		cleaned_name = name
		for char in invalid_chars:
			cleaned_name = cleaned_name.replace(char, '_')
		cleaned_name = cleaned_name.strip('. ')
		return cleaned_name if cleaned_name else ""
	
	def _create_folder(self, base_name, base_path):
		if not base_path or not os.path.exists(base_path):
			return False, None
		cleaned_name = self._clean_folder_name(base_name)
		if not cleaned_name:
			return False, None
		original_name = cleaned_name
		counter = 1
		folder_path = os.path.join(base_path, original_name)
		while os.path.exists(folder_path):
			original_name = f"{cleaned_name} ({counter})"
			folder_path = os.path.join(base_path, original_name)
			counter += 1
			if counter > 100:
				return False, None
		try:
			os.mkdir(folder_path)
			return True, original_name
		except Exception:
			return False, None


# ---- from folder_creator.py ----

def clean_clipboard_text(text):
	if not text:
		return ""
	invalid_chars = '<>:"/\\|?*'
	cleaned_text = text
	for char in invalid_chars:
		cleaned_text = cleaned_text.replace(char, '_')
	cleaned_text = ''.join(char for char in cleaned_text if ord(char) >= 32 or char in ['\n', '\r', '\t'])
	cleaned_text = cleaned_text.strip('. ')
	cleaned_text = re.sub(r'_+', '_', cleaned_text)
	return cleaned_text

def is_suitable_clipboard_text(text):
	if not text:
		return False
	if '\n' in text or '\r' in text:
		return False
	if len(text) > 200:
		return False
	invalid_chars = '<>:"/\\|?*'
	if any(c in text for c in invalid_chars):
		return False
	if any(ord(c) < 32 for c in text):
		return False
	return True

def type_clipboard_into_rename_if_suitable():
	clipboard_text = None
	try:
		if wx.TheClipboard.Open():
			try:
				data = wx.TextDataObject()
				if wx.TheClipboard.GetData(data):
					clipboard_text = data.GetText().strip()
			finally:
				wx.TheClipboard.Close()
	except Exception:
		return

	cleaned_text = clean_clipboard_text(clipboard_text) if clipboard_text else None
	if not cleaned_text or not is_suitable_clipboard_text(cleaned_text):
		log.debug("Clipboard text not suitable for auto-paste")
		return

	def paste_after_delay():
		try:
			focused_hwnd = winUser.GetFocus()
			if not focused_hwnd:
				focused_hwnd = winUser.getForegroundWindow()
			if not focused_hwnd:
				log.debug("No focused window for auto-paste")
				return

			EM_SETSEL = 0x00B1
			EM_REPLACESEL = 0x00C2
			WM_SETTEXT = 0x000C

			ctypes.windll.user32.SendMessageW(focused_hwnd, EM_SETSEL, 0, -1)
			core.callLater(30, lambda: ctypes.windll.user32.SendMessageW(focused_hwnd, EM_REPLACESEL, 0, cleaned_text))
			core.callLater(100, lambda: ctypes.windll.user32.SendMessageW(focused_hwnd, WM_SETTEXT, 0, cleaned_text))
			log.debug("Auto-paste via EM_REPLACESEL succeeded")
			return

		except Exception as e:
			log.debug(f"EM_REPLACESEL failed: {e}")

		try:
			backup = None
			try:
				backup = api.getClipData()
			except:
				pass

			api.copyToClip(cleaned_text)

			VK_CONTROL = 0x11
			VK_V = 0x56
			KEYEVENTF_KEYUP = 0x0002

			ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
			time.sleep(0.02)
			ctypes.windll.user32.keybd_event(VK_V, 0, 0, 0)
			time.sleep(0.02)
			ctypes.windll.user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
			time.sleep(0.02)
			ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

			if backup is not None:
				core.callLater(300, lambda: api.copyToClip(backup))
			log.debug("Auto-paste via keybd_event succeeded")
			return

		except Exception as e:
			log.debug(f"keybd_event failed: {e}")

		try:
			INPUT_KEYBOARD = 1
			KEYEVENTF_KEYUP = 0x0002
			KEYEVENTF_UNICODE = 0x0004

			class KEYBDINPUT(ctypes.Structure):
				_fields_ = [("wVk", ctypes.wintypes.WORD),
							("wScan", ctypes.wintypes.WORD),
							("dwFlags", ctypes.wintypes.DWORD),
							("time", ctypes.wintypes.DWORD),
							("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

			class INPUT_UNION(ctypes.Union):
				_fields_ = [("ki", KEYBDINPUT)]

			class INPUT(ctypes.Structure):
				_fields_ = [("type", ctypes.wintypes.DWORD),
							("u", INPUT_UNION)]

			def send_unicode_char(char):
				inp = INPUT()
				inp.type = INPUT_KEYBOARD
				inp.u.ki.wVk = 0
				inp.u.ki.wScan = ord(char)
				inp.u.ki.dwFlags = KEYEVENTF_UNICODE
				inp.u.ki.time = 0
				inp.u.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
				ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
				inp.u.ki.dwFlags |= KEYEVENTF_KEYUP
				ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

			ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
			ctypes.windll.user32.keybd_event(ord('A'), 0, 0, 0)
			ctypes.windll.user32.keybd_event(ord('A'), 0, KEYEVENTF_KEYUP, 0)
			ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

			for i, ch in enumerate(cleaned_text):
				core.callLater(50 + i * 20, send_unicode_char, ch)
			log.debug("Auto-paste via SendInput Unicode succeeded")
		except Exception as e:
			log.debug(f"All auto-paste methods failed: {e}")

	core.callLater(300, paste_after_delay)


# ---- from txt2folder.py ----

class TxtToFolder:
	
	def __init__(self, plugin):
		self.plugin = plugin
		self._striprtf_available = None
	
	def _get_striprtf_module(self):
		if self._striprtf_available is None:
			try:
				rtf_to_text = self.plugin._getStriprtfModule()
				if rtf_to_text:
					self._striprtf_available = rtf_to_text
					log.info("striprtf module loaded successfully for TxtToFolder")
				else:
					self._striprtf_available = False
					log.warning("striprtf module not available for TxtToFolder")
			except Exception as e:
				log.error(f"Error loading striprtf in TxtToFolder: {e}")
				self._striprtf_available = False
		return self._striprtf_available
	
	def convert_txt_to_folder(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			tones.beep(200, 150)
			return
		
		items, _ignore = self.plugin._getSelectedItems()
		if not items or len(items) > 1:
			ui.message(_("Please select only one text file"))
			tones.beep(200, 150)
			return
		
		file_path = items[0][1]
		
		if not (file_path.lower().endswith('.txt') or file_path.lower().endswith('.rtf')):
			ui.message(_("Please select a .txt or .rtf file"))
			tones.beep(200, 150)
			return
		
		if not os.path.exists(file_path):
			ui.message(_("Selected file does not exist"))
			tones.beep(200, 150)
			return
		
		tones.beep(440, 150)
		
		try:
			lines = []
			if file_path.lower().endswith('.rtf'):
				rtf_to_text = self._get_striprtf_module()
				if not rtf_to_text:
					ui.message(_("Cannot process RTF file: striprtf module not available"))
					tones.beep(200, 150)
					return
				
				try:
					with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
						rtf_content = f.read()
					text_content = rtf_to_text(rtf_content)
					lines = text_content.split('\n')
				except Exception as e:
					log.error(f"Error processing RTF file: {e}")
					ui.message(_("Error reading RTF file"))
					tones.beep(200, 150)
					return
			else:
				with open(file_path, 'r', encoding='utf-8') as f:
					lines = f.readlines()
			
			folder_names = [line.strip() for line in lines if line.strip()]
			
			if not folder_names:
				ui.message(_("No valid folder names found in the file"))
				tones.beep(200, 150)
				return
			
			base_name = os.path.splitext(os.path.basename(file_path))[0]
			base_folder = os.path.join(os.path.dirname(file_path), base_name)
			
			counter = 1
			original_base_folder = base_folder
			while os.path.exists(base_folder):
				base_folder = os.path.join(os.path.dirname(file_path), f"{base_name}_{counter}")
				counter += 1
			
			if base_folder != original_base_folder:
				ui.message(_("Folder '{}' already exists, creating '{}' instead").format(
					os.path.basename(original_base_folder), 
					os.path.basename(base_folder)
				))
			
			try:
				os.makedirs(base_folder)
			except Exception as e:
				log.error(f"Error creating base folder: {e}")
				ui.message(_("Error creating base folder"))
				tones.beep(200, 150)
				return
			
			created_count = 0
			for folder_name in folder_names:
				valid_name = self._make_valid_folder_name(folder_name)
				if valid_name:
					folder_path = os.path.join(base_folder, valid_name)
					try:
						cmd = ['robocopy', base_folder, folder_path, '/CREATE']
						subprocess.run(
							cmd,
							creationflags=subprocess.CREATE_NO_WINDOW,
							stdout=subprocess.DEVNULL,
							stderr=subprocess.DEVNULL,
							check=False,
							timeout=5
						)
						os.makedirs(folder_path, exist_ok=True)
						created_count += 1
					except Exception as e:
						log.error(f"Error creating folder {folder_path}: {e}")
						try:
							os.makedirs(folder_path, exist_ok=True)
							created_count += 1
						except:
							pass
			
			if created_count > 0:
				tones.beep(1760, 300)
				core.callLater(100, ui.message, _("Successfully created {} folders in '{}'").format(
					created_count, os.path.basename(base_folder)
				))
			else:
				ui.message(_("No folders were created"))
				tones.beep(200, 150)
			
		except UnicodeDecodeError:
			if file_path.lower().endswith('.txt'):
				try:
					with open(file_path, 'r', encoding='cp874') as f:
						lines = f.readlines()
					
					folder_names = [line.strip() for line in lines if line.strip()]
					
					if not folder_names:
						ui.message(_("No valid folder names found in the file"))
						tones.beep(200, 150)
						return
					
					base_name = os.path.splitext(os.path.basename(file_path))[0]
					base_folder = os.path.join(os.path.dirname(file_path), base_name)
					
					counter = 1
					original_base_folder = base_folder
					while os.path.exists(base_folder):
						base_folder = os.path.join(os.path.dirname(file_path), f"{base_name}_{counter}")
						counter += 1
					
					if base_folder != original_base_folder:
						ui.message(_("Folder '{}' already exists, creating '{}' instead").format(
							os.path.basename(original_base_folder), 
							os.path.basename(base_folder)
						))
					
					os.makedirs(base_folder)
					
					created_count = 0
					for folder_name in folder_names:
						valid_name = self._make_valid_folder_name(folder_name)
						if valid_name:
							folder_path = os.path.join(base_folder, valid_name)
							try:
								os.makedirs(folder_path)
								created_count += 1
							except Exception as e:
								log.error(f"Error creating folder {folder_path}: {e}")
					
					if created_count > 0:
						tones.beep(1760, 300)
						core.callLater(100, ui.message, _("Successfully created {} folders in '{}'").format(
							created_count, os.path.basename(base_folder)
						))
					else:
						ui.message(_("No folders were created"))
						tones.beep(200, 150)
					
				except Exception as e:
					log.error(f"Error processing text file: {e}")
					ui.message(_("Error processing text file: {}").format(str(e)))
					tones.beep(200, 150)
			else:
				log.error(f"Unicode decode error for RTF file: {file_path}")
				ui.message(_("Error reading file encoding"))
				tones.beep(200, 150)
		
		except Exception as e:
			log.error(f"Error converting file to folder: {e}")
			ui.message(_("Error: {}").format(str(e)))
			tones.beep(200, 150)
	
	def _make_valid_folder_name(self, name):
		if not name or not isinstance(name, str):
			return None
			
		invalid_chars = '<>:"/\\|?*'
		for char in invalid_chars:
			name = name.replace(char, '')
		
		name = name.strip('. ')
		
		while '  ' in name:
			name = name.replace('  ', ' ')
		
		if not name:
			return None
		
		reserved_names = ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 
						 'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 
						 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']
		if name.upper() in reserved_names:
			name = name + '_folder'
		
		if len(name) > 255:
			name = name[:255]
		
		return name


# ---- from selectionManager.py ----

class SelectionManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self._invert_batch_index = 0
		self._invert_items = []
		self._invert_selected_set = set()
		self._invert_document = None
		self._invert_total = 0

	def cleanup(self):
		self._invert_items = []
		self._invert_selected_set.clear()
		self._invert_document = None

	def invertSelection(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			return

		try:
			shellWindow = self.plugin._getActiveExplorerWindow()
			if not shellWindow:
				ui.message(_("No active File Explorer window found"))
				return

			document = shellWindow.document
			if not hasattr(document, 'Folder'):
				ui.message(_("Unable to get folder view"))
				return

			folder = document.Folder
			items = folder.Items()
			total_count = items.Count

			if total_count == 0:
				ui.message(_("No items in folder"))
				return

			selected_paths = set()
			sel_items = document.SelectedItems()
			for i in range(sel_items.Count):
				selected_paths.add(sel_items.Item(i).Path)

			if total_count > 300:
				ui.message(_("Processing {count} items in background...").format(count=total_count))

			self._invert_items = []
			for i in range(total_count):
				self._invert_items.append(items.Item(i))
			self._invert_selected_set = selected_paths
			self._invert_document = document
			self._invert_batch_index = 0
			self._invert_total = total_count
			self._invert_batch_process()

		except Exception as e:
			log.error(f"Error in invertSelection: {e}")
			ui.message(_("Error inverting selection"))

	def _invert_batch_process(self):
		BATCH_SIZE = 80
		start = self._invert_batch_index
		end = min(start + BATCH_SIZE, len(self._invert_items))

		for i in range(start, end):
			item = self._invert_items[i]
			if item.Path in self._invert_selected_set:
				self._invert_document.SelectItem(item, 0)
			else:
				self._invert_document.SelectItem(item, 1)

		self._invert_batch_index = end

		if self._invert_batch_index < len(self._invert_items):
			core.callLater(15, self._invert_batch_process)
		else:
			try:
				new_selected = self._invert_document.SelectedItems()
				count = new_selected.Count
				ui.message(_("Selected {count} items").format(count=count))
			except Exception as e:
				log.debug(f"Failed to get selected count after invert: {e}")
				ui.message(_("Selection inverted"))

			self._invert_items = []
			self._invert_selected_set.clear()
			self._invert_document = None


# ---- from case.py ----

class CaseConverter:
	def __init__(self):
		self._minor_words = set([
			"a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet",
			"at", "by", "for", "from", "in", "into", "of", "off", "on", "onto",
			"out", "over", "to", "up", "with", "as", "if", "than", "that",
			"till", "when", "via"
		])
		self._active_thread = None
		self._should_stop = False

	def _capitalize_word(self, word):
		for i, ch in enumerate(word):
			if ch.isalpha():
				return word[:i] + ch.upper() + word[i+1:].lower()
		return word

	def _to_headline_case(self, text):
		words = text.split()
		if not words:
			return text
		result_words = []
		for i, word in enumerate(words):
			if not word:
				result_words.append(word)
				continue
			core_word = word.lower().strip(".,!?;:'\"()[]{}")
			if i == 0 or i == len(words) - 1:
				result_words.append(self._capitalize_word(word))
			else:
				if core_word in self._minor_words:
					result_words.append(word.lower())
				else:
					result_words.append(self._capitalize_word(word))
		return ' '.join(result_words)

	def _rename_folder_with_retry(self, old_path, new_path, max_retries=3, delay=0.2):
		for attempt in range(max_retries):
			try:
				if ctypes.windll.kernel32.MoveFileW(old_path, new_path):
					return True
				else:
					error_code = ctypes.GetLastError()
					if error_code == 5:
						log.debug(f"Access denied renaming {old_path} (attempt {attempt+1})")
						if attempt < max_retries - 1:
							time.sleep(delay)
							continue
			except Exception as e:
				log.debug(f"MoveFileW exception: {e}")
			try:
				os.rename(old_path, new_path)
				return True
			except OSError as e:
				if e.winerror == 5 and attempt < max_retries - 1:
					time.sleep(delay)
					continue
				log.error(f"Rename error {old_path}: {e}")
				return False
		return False

	def _rename_folder_only(self, old_path, convert_func):
		if not os.path.isdir(old_path):
			return False
		dir_name, folder_name = os.path.split(old_path)
		new_folder_name = convert_func(folder_name)
		new_path = os.path.join(dir_name, new_folder_name)
		if old_path == new_path:
			return True
		if os.path.exists(new_path) and os.path.normcase(old_path) != os.path.normcase(new_path):
			log.warning(f"Cannot rename {old_path} to {new_path}, target exists")
			return False
		success = self._rename_folder_with_retry(old_path, new_path)
		if success:
			log.info(f"Renamed {old_path} -> {new_path}")
		return success

	def _walk_and_rename(self, root_path, convert_func, progress_callback):
		processed = 0
		success = 0
		if self._rename_folder_only(root_path, convert_func):
			success += 1
		processed += 1
		for current_root, dirs, _ in os.walk(root_path):
			if self._should_stop:
				break
			for d in dirs[:]:
				if self._should_stop:
					break
				old_path = os.path.join(current_root, d)
				if self._rename_folder_only(old_path, convert_func):
					success += 1
				processed += 1
				if processed % 20 == 0:
					wx.CallAfter(progress_callback, processed)
		return success

	def _run_conversion_streaming(self, root_paths, convert_func, success_template):
		if self._active_thread and self._active_thread.is_alive():
			wx.CallAfter(ui.message, _("Conversion already in progress"))
			return

		def worker():
			self._should_stop = False
			total_success = 0
			total_processed = 0
			for folder in root_paths:
				if self._should_stop:
					break
				success = self._walk_and_rename(folder, convert_func, lambda p: None)
				total_success += success
			wx.CallAfter(self._on_conversion_finished, total_success, success_template.format(count=total_success) if total_success > 0 else _("Failed to rename any folders"))
			self._active_thread = None

		self._active_thread = threading.Thread(target=worker, daemon=True)
		self._active_thread.start()
		wx.CallAfter(ui.message, _("Converting"))

	def _on_conversion_finished(self, success, message):
		if success > 0:
			ui.message(message)
		else:
			ui.message(message)

	def convert_folder_to_uppercase(self, paths):
		if not paths:
			ui.message(_("No folders found"))
			return
		self._run_conversion_streaming(paths, str.upper, _("Successfully converted {count} folders to uppercase"))

	def convert_folder_to_lowercase(self, paths):
		if not paths:
			ui.message(_("No folders found"))
			return
		self._run_conversion_streaming(paths, str.lower, _("Successfully converted {count} folders to lowercase"))

	def convert_folder_to_titlecase(self, paths):
		def to_title(text):
			words = text.split()
			return ' '.join(w.capitalize() for w in words if w)
		if not paths:
			ui.message(_("No folders found"))
			return
		self._run_conversion_streaming(paths, to_title, _("Successfully converted {count} folders to title case"))

	def convert_folder_to_headlinecase(self, paths):
		if not paths:
			ui.message(_("No folders found"))
			return
		self._run_conversion_streaming(paths, self._to_headline_case, _("Successfully converted {count} folders to headline case"))

