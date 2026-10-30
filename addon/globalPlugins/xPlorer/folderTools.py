# folderTools.py

import os
import json
import fnmatch
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
import comtypes.client
from comtypes import COMError
import globalVars
import struct
from speech.extensions import filter_speechSequence

addonHandler.initTranslation()

# ---- from config.py ----

# globalVars.appArgs.configPath is NVDA's own currently-active userConfig
# root - it already resolves correctly for portable vs installed copies and
# for the -c/--config-path override, unlike a hardcoded
# os.path.expanduser("~") guess (which pointed at the real Windows user
# profile's roaming folder even when NVDA itself was running as a portable
# copy elsewhere, so nothing this add-on saved was ever where NVDA - or the
# user - was actually looking for it).
CONFIG_DIR = os.path.join(globalVars.appArgs.configPath, "ChaiChaimee", "xPlorer")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")

DEFAULT_CONFIG = {
	"autoSelectFirstItem": True,
	"openExplorerMaximized": True,
	"hookAltEnterProperties": True,
	"announceEmptyFolder": True,
	"suppressDirectUIAnnounce": True,
	"sayFileExplorer": True,
	"autoPasteClipboardToRename": True,
	"forbiddenCharReplacement": "-",
	"showUncompressDialog": True,
	"uncompressDefaultAction": "extract_to",
	"searchLastMode": "normal",
	"searchIncludeSubfolders": False,
	"searchLastTerm": "",
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
		self._folderInfoGeneration = 0

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
		# Ask any still-running walk from a previous invocation (e.g. a
		# slow recursive walk left over from another tab/window) to stop,
		# and bump the generation so that even if it doesn't stop in time,
		# its eventual result gets discarded instead of overwriting what
		# the user asked for just now.
		self._stop_walk = True
		self._folderInfoGeneration += 1
		myGeneration = self._folderInfoGeneration

		def delayed_retrieve():
			def handleSelection(selected_items, _hwnd):
				if not selected_items:
					wx.CallAfter(ui.message, _("No item selected"))
					self._restore_speech()
					return

				folder_paths = [path for _name, path in selected_items if os.path.isdir(path)]
				if not folder_paths:
					wx.CallAfter(ui.message, _("Selected item is not a folder"))
					self._restore_speech()
					return

				self._stop_walk = False
				threading.Thread(target=self._calculate_folder_info_streaming, args=(folder_paths, myGeneration), daemon=True).start()

			self.plugin._getSelectedItemsAsync(handleSelection)

		core.callLater(500, delayed_retrieve)

	def _restore_speech(self):
		core.callLater(800, lambda: setattr(self.plugin.manager, 'suppressAllAnnouncements', False))

	def _calculate_folder_info_streaming(self, folder_paths, myGeneration):
		try:
			subfolder_count = 0
			file_count = 0
			for folder_path in folder_paths:
				for root, dirs, files in os.walk(folder_path):
					if self._stop_walk or myGeneration != self._folderInfoGeneration:
						break
					subfolder_count += len(dirs)
					file_count += len(files)
				if self._stop_walk or myGeneration != self._folderInfoGeneration:
					break

			if myGeneration != self._folderInfoGeneration:
				# Superseded by a newer folder-info request - discard
				# silently instead of speaking counts for whatever folder
				# used to be selected.
				return

			message = _("{subfolders} subfolders and {files} files").format(
				subfolders=subfolder_count,
				files=file_count
			)
			wx.CallAfter(speech.cancelSpeech)
			wx.CallAfter(ui.message, message)
			wx.CallAfter(self._restore_speech)
		except Exception as e:
			log.error(f"Error calculating folder info: {e}")
			if myGeneration == self._folderInfoGeneration:
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

def clean_clipboard_text(text, replacementChar="-"):
	if not text:
		return ""
	invalid_chars = '<>:"/\\|?*'
	cleaned_text = text
	for char in invalid_chars:
		cleaned_text = cleaned_text.replace(char, replacementChar)
	cleaned_text = ''.join(char for char in cleaned_text if ord(char) >= 32 or char in ['\n', '\r', '\t'])
	cleaned_text = cleaned_text.strip('. ')
	if replacementChar:
		cleaned_text = re.sub(re.escape(replacementChar) + r'+', replacementChar, cleaned_text)
	else:
		# "none" mode removes forbidden characters outright, which can
		# leave behind a run of spaces where the character used to sit
		# (e.g. "box : black" -> "box  black") - collapse those down to
		# a single space so the result reads as "box black".
		cleaned_text = re.sub(r' {2,}', ' ', cleaned_text)
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

_autoPasteGate = {"active": False, "text": "", "spoken": False, "pasted": False, "timer": None, "registered": False}


def _autoPasteSpeechFilter(speechSequence):
	if not _autoPasteGate["active"]:
		return speechSequence
	if not _autoPasteGate["spoken"]:
		allowedText = _autoPasteGate["text"].strip().casefold()
		for item in speechSequence:
			if isinstance(item, str) and item.strip().casefold() == allowedText:
				_autoPasteGate["spoken"] = True
				return speechSequence
	return []


def disarm_auto_paste_speech_gate():
	timer = _autoPasteGate["timer"]
	_autoPasteGate["timer"] = None
	_autoPasteGate["active"] = False
	if timer:
		try:
			timer.Stop()
		except (RuntimeError, AttributeError):
			pass
	if _autoPasteGate["registered"]:
		filter_speechSequence.unregister(_autoPasteSpeechFilter)
		_autoPasteGate["registered"] = False


def _expireAutoPasteGate():
	mustSpeak = _autoPasteGate["pasted"] and not _autoPasteGate["spoken"]
	text = _autoPasteGate["text"]
	disarm_auto_paste_speech_gate()
	if mustSpeak and text:
		ui.message(text)


def arm_auto_paste_speech_gate(pastedText, durationMs):
	disarm_auto_paste_speech_gate()
	_autoPasteGate.update(active=True, text=pastedText, spoken=False, pasted=False)
	filter_speechSequence.register(_autoPasteSpeechFilter)
	_autoPasteGate["registered"] = True
	_autoPasteGate["timer"] = core.callLater(durationMs, _expireAutoPasteGate)


def _speakPastedText():
	if not _autoPasteGate["active"] or _autoPasteGate["spoken"]:
		return
	if _autoPasteGate["text"]:
		ui.message(_autoPasteGate["text"])


def _markAutoPasted():
	_autoPasteGate["pasted"] = True
	core.callLater(120, _speakPastedText)


def get_auto_paste_text():
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
		return None

	replacementSetting = loadConfig().get("forbiddenCharReplacement", "-")
	replacementChar = "" if replacementSetting == "none" else replacementSetting

	cleaned_text = clean_clipboard_text(clipboard_text, replacementChar) if clipboard_text else None
	if not cleaned_text or not is_suitable_clipboard_text(cleaned_text):
		return None
	return cleaned_text


def type_clipboard_into_rename_if_suitable(preparedText=None):
	cleaned_text = preparedText or get_auto_paste_text()
	if not cleaned_text:
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
			_markAutoPasted()
			log.debug("Auto-paste via EM_REPLACESEL succeeded")
			return

		except Exception as e:
			log.debug(f"EM_REPLACESEL failed: {e}")

		try:
			backup = None
			try:
				backup = api.getClipData()
			except (OSError, RuntimeError):
				pass

			api.copyToClip(cleaned_text)

			VK_CONTROL = 0x11
			VK_V = 0x56
			KEYEVENTF_KEYUP = 0x0002

			def _releaseKeys():
				ctypes.windll.user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
				ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

			def _pressV():
				try:
					ctypes.windll.user32.keybd_event(VK_V, 0, 0, 0)
					core.callLater(40, _releaseKeys)
				except Exception as e:
					_releaseKeys()
					log.debug(f"keybd_event paste step failed: {e}")

			ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
			core.callLater(20, _pressV)

			if backup is not None:
				core.callLater(300, lambda: api.copyToClip(backup))
			_markAutoPasted()
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
			_markAutoPasted()
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

		def handleSelection(items, _hwnd):
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
			threading.Thread(target=self._processConversion, args=(file_path,), daemon=True).start()

		self.plugin._getSelectedItemsAsync(handleSelection)

	def _processConversion(self, file_path):
		try:
			lines = []
			if file_path.lower().endswith('.rtf'):
				rtf_to_text = self._get_striprtf_module()
				if not rtf_to_text:
					core.callLater(0, ui.message, _("Cannot process RTF file: striprtf module not available"))
					core.callLater(0, tones.beep, 200, 150)
					return

				try:
					with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
						rtf_content = f.read()
					text_content = rtf_to_text(rtf_content)
					lines = text_content.split('\n')
				except Exception as e:
					log.error(f"Error processing RTF file: {e}")
					core.callLater(0, ui.message, _("Error reading RTF file"))
					core.callLater(0, tones.beep, 200, 150)
					return
			else:
				with open(file_path, 'r', encoding='utf-8') as f:
					lines = f.readlines()

			folder_names = [line.strip() for line in lines if line.strip()]

			if not folder_names:
				core.callLater(0, ui.message, _("No valid folder names found in the file"))
				core.callLater(0, tones.beep, 200, 150)
				return

			base_name = os.path.splitext(os.path.basename(file_path))[0]
			base_folder = os.path.join(os.path.dirname(file_path), base_name)

			counter = 1
			original_base_folder = base_folder
			while os.path.exists(base_folder):
				base_folder = os.path.join(os.path.dirname(file_path), f"{base_name}_{counter}")
				counter += 1

			if base_folder != original_base_folder:
				core.callLater(0, ui.message, _("Folder '{}' already exists, creating '{}' instead").format(
					os.path.basename(original_base_folder),
					os.path.basename(base_folder)
				))

			try:
				os.makedirs(base_folder)
			except Exception as e:
				log.error(f"Error creating base folder: {e}")
				core.callLater(0, ui.message, _("Error creating base folder"))
				core.callLater(0, tones.beep, 200, 150)
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
						except (OSError,):
							pass

			if created_count > 0:
				core.callLater(0, tones.beep, 1760, 300)
				core.callLater(100, ui.message, _("Successfully created {} folders in '{}'").format(
					created_count, os.path.basename(base_folder)
				))
			else:
				core.callLater(0, ui.message, _("No folders were created"))
				core.callLater(0, tones.beep, 200, 150)

		except UnicodeDecodeError:
			if file_path.lower().endswith('.txt'):
				try:
					with open(file_path, 'r', encoding='cp874') as f:
						lines = f.readlines()

					folder_names = [line.strip() for line in lines if line.strip()]

					if not folder_names:
						core.callLater(0, ui.message, _("No valid folder names found in the file"))
						core.callLater(0, tones.beep, 200, 150)
						return

					base_name = os.path.splitext(os.path.basename(file_path))[0]
					base_folder = os.path.join(os.path.dirname(file_path), base_name)

					counter = 1
					original_base_folder = base_folder
					while os.path.exists(base_folder):
						base_folder = os.path.join(os.path.dirname(file_path), f"{base_name}_{counter}")
						counter += 1

					if base_folder != original_base_folder:
						core.callLater(0, ui.message, _("Folder '{}' already exists, creating '{}' instead").format(
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
						core.callLater(0, tones.beep, 1760, 300)
						core.callLater(100, ui.message, _("Successfully created {} folders in '{}'").format(
							created_count, os.path.basename(base_folder)
						))
					else:
						core.callLater(0, ui.message, _("No folders were created"))
						core.callLater(0, tones.beep, 200, 150)

				except Exception as e:
					log.error(f"Error processing text file: {e}")
					core.callLater(0, ui.message, _("Error processing text file: {}").format(str(e)))
					core.callLater(0, tones.beep, 200, 150)
			else:
				log.error(f"Unicode decode error for RTF file: {file_path}")
				core.callLater(0, ui.message, _("Error reading file encoding"))
				core.callLater(0, tones.beep, 200, 150)

		except Exception as e:
			log.error(f"Error converting file to folder: {e}")
			core.callLater(0, ui.message, _("Error: {}").format(str(e)))
			core.callLater(0, tones.beep, 200, 150)
	
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

_CFSTR_PREFERREDDROPEFFECT = "Preferred DropEffect"
_DROPEFFECT_COPY = 1
_DROPEFFECT_MOVE = 2

_FO_DELETE = 0x0003
_FOF_ALLOWUNDO = 0x0040
_FOF_NOCONFIRMATION = 0x0010
_FOF_SILENT = 0x0004


class _SHFILEOPSTRUCTW(ctypes.Structure):
	_fields_ = [
		("hwnd", ctypes.wintypes.HWND),
		("wFunc", ctypes.wintypes.UINT),
		("pFrom", ctypes.wintypes.LPCWSTR),
		("pTo", ctypes.wintypes.LPCWSTR),
		("fFlags", ctypes.wintypes.WORD),
		("fAnyOperationsAborted", ctypes.wintypes.BOOL),
		("hNameMappings", ctypes.wintypes.LPVOID),
		("lpszProgressTitle", ctypes.wintypes.LPCWSTR),
	]


def _sendToRecycleBin(paths):
	"""Moves the given files to the Recycle Bin (undoable) instead of a
	permanent os.remove, using the same shell API Explorer itself uses for
	a normal Delete key press."""
	if not paths:
		return True
	# pFrom must be a double-null-terminated string of null-separated paths.
	joinedPaths = "\0".join(paths) + "\0\0"
	operation = _SHFILEOPSTRUCTW()
	operation.hwnd = None
	operation.wFunc = _FO_DELETE
	operation.pFrom = joinedPaths
	operation.pTo = None
	operation.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT
	operation.fAnyOperationsAborted = False
	operation.hNameMappings = None
	operation.lpszProgressTitle = None
	result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
	return result == 0 and not operation.fAnyOperationsAborted


def _setFileClipboard(filePaths, isCut):
	"""Puts real files on the Windows clipboard as Explorer itself would
	for Ctrl+C/Ctrl+X, so pasting into any destination - not just back into
	xPlorer - works normally. wx.FileDataObject supplies the standard
	CF_HDROP file-list format; the separate "Preferred DropEffect" format
	is what tells Explorer's paste whether to copy or move, matching the
	real convention Explorer itself uses to distinguish Ctrl+C from
	Ctrl+X."""
	if not filePaths:
		return False
	fileDataObject = wx.FileDataObject()
	for filePath in filePaths:
		fileDataObject.AddFile(filePath)

	dropEffectData = wx.CustomDataObject(wx.DataFormat(_CFSTR_PREFERREDDROPEFFECT))
	effectValue = _DROPEFFECT_MOVE if isCut else _DROPEFFECT_COPY
	dropEffectData.SetData(struct.pack("<I", effectValue))

	composite = wx.DataObjectComposite()
	composite.Add(fileDataObject)
	composite.Add(dropEffectData)

	if not wx.TheClipboard.Open():
		return False
	try:
		wx.TheClipboard.SetData(composite)
		return True
	finally:
		wx.TheClipboard.Close()


SEARCH_MODE_NORMAL = "normal"
SEARCH_MODE_REGEX = "regex"
SEARCH_MODE_WILDCARD = "wildcard"


def _parseWildcardPatterns(rawText):
	# Multiple patterns may be given separated by commas and/or whitespace,
	# e.g. "*.txt, *.docx" or "*.txt *.docx" - an item matching any one of
	# them counts as a match. Only wildcard mode supports more than one
	# pattern this way; normal and regex mode each use the whole field as a
	# single term, since commas/spaces are frequently meaningful characters
	# in a plain search phrase or a regex.
	tokens = re.split(r'[,\s]+', rawText.strip())
	return [token for token in tokens if token]


def _matchesAnyWildcardPattern(name, patterns):
	lowerName = name.lower()
	return any(fnmatch.fnmatch(lowerName, pattern.lower()) for pattern in patterns)


def _matchesSearchTerm(name, mode, rawTerm):
	if mode == SEARCH_MODE_REGEX:
		try:
			return re.search(rawTerm, name, re.IGNORECASE) is not None
		except re.error:
			return False
	if mode == SEARCH_MODE_WILDCARD:
		patterns = _parseWildcardPatterns(rawTerm)
		return _matchesAnyWildcardPattern(name, patterns) if patterns else False
	# Normal mode: plain substring, case-insensitive - same semantics as
	# Flat View's own filter field, for a consistent feel across xPlorer.
	return rawTerm.lower() in name.lower()


class SelectionManager:
	"""Invert/extension/search selection all touch Shell.Application COM
	objects and can enumerate thousands of Items() entries - previously that
	entire enumeration ran synchronously on NVDA's main thread before any
	chunking kicked in, which is exactly the kind of heavy COM querying that
	trips NVDA's Watchdog on large folders. Every entry point below now only
	captures the target window handle on the calling thread and hands the
	rest off to a background daemon thread, which creates its own local
	Shell.Application COM object (its own apartment) rather than reusing one
	created on the main thread - COM objects are never passed across
	threads. Only plain data (counts, formatted strings) crosses back to the
	main thread, via wx.CallAfter."""

	def __init__(self, plugin):
		self.plugin = plugin
		self._selectionWorkerLock = threading.Lock()
		self._search_dialog = None

	def cleanup(self):
		if self._search_dialog:
			try:
				self._search_dialog.Destroy()
			except RuntimeError:
				pass
			self._search_dialog = None

	def _getTopLevelExplorerHwnd(self, hwnd):
		# Same reasoning as xPlorer_engine.py's module-level helper of the
		# same name (duplicated locally to avoid a circular import, since
		# xPlorer_engine imports this module): Windows 11's XAML-hosted
		# Explorer window exposes an inner XamlExplorerHostIslandWindow that
		# NVDA sometimes reports as focused, while Shell.Application only
		# knows the outer CabinetWClass top-level window.
		try:
			rootHwnd = ctypes.windll.user32.GetAncestor(hwnd, 2)
			if rootHwnd:
				return rootHwnd
		except (AttributeError, OSError) as e:
			log.debug(f"xPlorer: GetAncestor failed, using original hwnd: {e}")
		return hwnd

	def _findShellWindowByHwnd(self, localShell, target_hwnd, focusedItemNameHint=None):
		# A multi-tab Explorer window has several Windows() entries that all
		# share the same top-level hwnd - matching on hwnd alone (the old
		# behavior here) just grabs whichever entry happens to come first in
		# COM's enumeration order, regardless of which tab is actually
		# active. This mirrors the fix already proven for say-size in
		# xPlorer_engine.py's _getSelectedItemsAsync: disambiguate multiple
		# same-hwnd candidates by checking which one's SelectedItems()
		# actually contains the item NVDA reports as focused.
		comMatchHwnd = self._getTopLevelExplorerHwnd(target_hwnd)
		candidates = []
		for window in localShell.Windows():
			try:
				if window and window.hwnd == comMatchHwnd and hasattr(window, "Document") and window.Document:
					candidates.append(window)
			except (COMError, AttributeError):
				continue

		if len(candidates) == 1:
			return candidates[0]
		if len(candidates) > 1 and focusedItemNameHint:
			for candidate in candidates:
				try:
					document = getattr(candidate, "document", None)
					if not document or not hasattr(document, "SelectedItems"):
						continue
					items = document.SelectedItems()
					for i in range(items.Count):
						if items.Item(i).Name == focusedItemNameHint:
							return candidate
				except (COMError, AttributeError):
					continue
			log.debug("xPlorer: multiple tabs share this window and none matched the focused item name hint, using the first candidate")
		return candidates[0] if candidates else None

	def invertSelection(self):
		fg = api.getForegroundObject()
		if not fg or not fg.appModule or fg.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			return
		target_hwnd = fg.windowHandle
		focusedItemNameHint = None
		try:
			focusObj = api.getFocusObject()
			if focusObj:
				focusedItemNameHint = getattr(focusObj, "name", None)
		except Exception as e:
			log.debug(f"xPlorer: could not resolve focused item name hint for invertSelection: {e}")
		threading.Thread(target=self._invertSelectionWorker, args=(target_hwnd, focusedItemNameHint), daemon=True).start()

	def _invertSelectionWorker(self, target_hwnd, focusedItemNameHint=None):
		if not self._selectionWorkerLock.acquire(blocking=False):
			wx.CallAfter(ui.message, _("A selection operation is already in progress"))
			return
		try:
			try:
				comtypes.CoInitialize()
			except OSError:
				pass
			try:
				localShell = comtypes.client.CreateObject("Shell.Application")
				shellWindow = self._findShellWindowByHwnd(localShell, target_hwnd, focusedItemNameHint)
				if not shellWindow:
					wx.CallAfter(ui.message, _("No active File Explorer window found"))
					return

				document = shellWindow.Document
				if not hasattr(document, "Folder"):
					wx.CallAfter(ui.message, _("Unable to get folder view"))
					return

				folder = document.Folder
				items = folder.Items()
				total_count = items.Count
				if total_count == 0:
					wx.CallAfter(ui.message, _("No items in folder"))
					return

				selected_paths = set()
				sel_items = document.SelectedItems()
				for i in range(sel_items.Count):
					selected_paths.add(sel_items.Item(i).Path)

				if total_count > 300:
					wx.CallAfter(ui.message, _("Processing {count} items in background...").format(count=total_count))

				for i in range(total_count):
					item = items.Item(i)
					if item.Path in selected_paths:
						document.SelectItem(item, 0)
					else:
						document.SelectItem(item, 1)

				try:
					new_selected = document.SelectedItems()
					count = new_selected.Count
					wx.CallAfter(ui.message, _("Selected {count} items").format(count=count))
				except (COMError, AttributeError) as e:
					log.debug(f"xPlorer: failed to get selected count after invert: {e}")
					wx.CallAfter(ui.message, _("Selection inverted"))
			except COMError as e:
				log.debug(f"xPlorer: invertSelection background COM error: {e}")
				wx.CallAfter(ui.message, _("Error inverting selection"))
			except Exception as e:
				log.error(f"Error in invertSelection background worker: {e}")
				wx.CallAfter(ui.message, _("Error inverting selection"))
			finally:
				try:
					comtypes.CoUninitialize()
				except OSError:
					pass
		finally:
			self._selectionWorkerLock.release()

	def selectByExtension(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			return

		def handleSelection(selected_items, _hwnd):
			try:
				focusedPath = selected_items[0][1] if selected_items else None
				if not focusedPath or not os.path.isfile(focusedPath):
					ui.message(_("Focus a single file first to select others with the same extension"))
					return

				targetExt = os.path.splitext(focusedPath)[1].lower()
				if not targetExt:
					ui.message(_("The focused item has no file extension"))
					return

				predicate = lambda itemPath, _ext=targetExt: os.path.splitext(itemPath)[1].lower() == _ext
				self._startBatchSelect(predicate, _("Selected {count} items {ext}").format(count="{count}", ext=targetExt))
			except Exception as e:
				log.error(f"Error in selectByExtension: {e}")
				ui.message(_("Error selecting by extension"))

		self.plugin._getSelectedItemsAsync(handleSelection)

	def showSearchSelectionDialog(self):
		# The search term is entered through a modal dialog, so unlike
		# invertSelection/selectByExtension above, the target Explorer window
		# is no longer guaranteed to be foreground by the time the user
		# presses OK - focus takes a moment to return to Explorer after the
		# dialog closes. Capture the hwnd here, while Explorer is definitely
		# still foreground, and carry it through to selectBySearch instead
		# of re-detecting the foreground window after the dialog has closed.
		fg = api.getForegroundObject()
		if not fg or not fg.appModule or fg.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			return
		targetHwnd = fg.windowHandle
		focusedItemNameHint = None
		try:
			focusObj = api.getFocusObject()
			if focusObj:
				focusedItemNameHint = getattr(focusObj, "name", None)
		except Exception as e:
			log.debug(f"xPlorer: could not resolve focused item name hint for search dialog: {e}")

		def handleRootPath(rootPath):
			def do_show():
				self._search_dialog = SearchSelectionDialog(gui.mainFrame, self, targetHwnd, focusedItemNameHint, rootPath)
				gui.mainFrame.prePopup()
				try:
					self._search_dialog.ShowModal()
				finally:
					gui.mainFrame.postPopup()
					if self._search_dialog:
						self._search_dialog.Destroy()
					self._search_dialog = None

			wx.CallAfter(do_show)

		# Needed only for the "include subfolders" option below, which walks
		# the filesystem directly rather than through Explorer's COM view -
		# the dialog still opens normally even if this comes back empty.
		self.plugin._getCurrentPathFromExplorerAsync(handleRootPath)

	def selectBySearch(self, rawTerm, mode, targetHwnd=None, focusedItemNameHint=None, recursive=False, rootPath=None):
		if not rawTerm:
			ui.message(_("Enter a search term or pattern first"))
			return
		try:
			if recursive and rootPath:
				# Explorer can only ever select items visible in its current
				# single-level view, so "recursive select" means: a
				# top-level item counts as a match if it matches directly,
				# or is a folder containing a match at any depth below it.
				threading.Thread(
					target=self._selectBySearchRecursiveWorker,
					args=(targetHwnd, focusedItemNameHint, rootPath, mode, rawTerm),
					daemon=True
				).start()
				return
			predicate = lambda itemPath, _mode=mode, _term=rawTerm: _matchesSearchTerm(os.path.basename(itemPath), _mode, _term)
			self._startBatchSelect(
				predicate,
				_("Selected {count} items matching {term}").format(count="{count}", term=rawTerm),
				targetHwnd=targetHwnd,
				focusedItemNameHint=focusedItemNameHint,
			)
		except Exception as e:
			log.error(f"Error in selectBySearch: {e}")
			ui.message(_("Error selecting by search"))

	def _selectBySearchRecursiveWorker(self, targetHwnd, focusedItemNameHint, rootPath, mode, rawTerm):
		qualifyingNames = self._computeRecursiveTopLevelMatches(rootPath, mode, rawTerm)
		if not qualifyingNames:
			wx.CallAfter(ui.message, _("No matches found for {term}").format(term=rawTerm))
			return
		predicate = lambda itemPath, _names=qualifyingNames: os.path.basename(itemPath.rstrip("\\/")) in _names
		resultMessageTemplate = _("Selected {count} top-level items containing matches for {term}").format(count="{count}", term=rawTerm)
		self._startBatchSelect(predicate, resultMessageTemplate, targetHwnd=targetHwnd, focusedItemNameHint=focusedItemNameHint)

	def _computeRecursiveTopLevelMatches(self, rootPath, mode, rawTerm):
		# Walks the filesystem directly (like Flat View does) rather than
		# through Explorer's COM view, since subfolder contents aren't part
		# of that view at all. Once a top-level folder has one match found
		# anywhere inside it, that whole branch stops being walked further -
		# it already qualifies and finding more matches under it wouldn't
		# change the result.
		qualifyingNames = set()
		try:
			for currentDir, dirNames, fileNames in os.walk(rootPath, topdown=True):
				relativeToRoot = os.path.relpath(currentDir, rootPath)
				if relativeToRoot == ".":
					for name in dirNames + fileNames:
						if _matchesSearchTerm(name, mode, rawTerm):
							qualifyingNames.add(name)
					continue
				topLevelAncestor = relativeToRoot.split(os.sep)[0]
				if topLevelAncestor in qualifyingNames:
					dirNames[:] = []
					continue
				for name in dirNames + fileNames:
					if _matchesSearchTerm(name, mode, rawTerm):
						qualifyingNames.add(topLevelAncestor)
						dirNames[:] = []
						break
		except OSError as e:
			log.debug(f"xPlorer: recursive search scan failed: {e}")
		return qualifyingNames

	def previewSearchMatchesRecursive(self, rawTerm, mode, callback, generation, rootPath):
		if not rawTerm or not rootPath:
			wx.CallAfter(callback, generation, [])
			return
		threading.Thread(
			target=self._previewSearchRecursiveWorker,
			args=(rootPath, mode, rawTerm, callback, generation),
			daemon=True
		).start()

	def _previewSearchRecursiveWorker(self, rootPath, mode, rawTerm, callback, generation):
		matches = []
		try:
			for currentDir, dirNames, fileNames in os.walk(rootPath):
				relativeToRoot = os.path.relpath(currentDir, rootPath)
				for name in dirNames + fileNames:
					if _matchesSearchTerm(name, mode, rawTerm):
						displayPath = name if relativeToRoot == "." else os.path.join(relativeToRoot, name)
						matches.append(displayPath)
						if len(matches) >= 2000:
							wx.CallAfter(callback, generation, matches)
							return
		except OSError as e:
			log.debug(f"xPlorer: recursive search preview failed: {e}")
		wx.CallAfter(callback, generation, matches)

	def previewSearchMatches(self, rawTerm, mode, callback, generation, targetHwnd=None, focusedItemNameHint=None):
		# Read-only lookup used while the Search dialog's edit field is
		# still being typed into - lists which items currently match
		# without touching Explorer's actual selection. "generation" lets
		# the dialog discard a slow, now-stale result if the user kept
		# typing and a newer query already started.
		if not rawTerm:
			wx.CallAfter(callback, generation, [])
			return
		if targetHwnd is None:
			fg = api.getForegroundObject()
			if not fg or not fg.appModule or fg.appModule.appName != "explorer":
				wx.CallAfter(callback, generation, [])
				return
			targetHwnd = fg.windowHandle
		threading.Thread(
			target=self._previewSearchWorker,
			args=(targetHwnd, mode, rawTerm, callback, generation, focusedItemNameHint),
			daemon=True
		).start()

	def _previewSearchWorker(self, target_hwnd, mode, rawTerm, callback, generation, focusedItemNameHint=None):
		try:
			comtypes.CoInitialize()
		except OSError:
			pass
		try:
			localShell = comtypes.client.CreateObject("Shell.Application")
			shellWindow = self._findShellWindowByHwnd(localShell, target_hwnd, focusedItemNameHint)
			if not shellWindow:
				wx.CallAfter(callback, generation, [])
				return
			document = shellWindow.Document
			if not hasattr(document, "Folder"):
				wx.CallAfter(callback, generation, [])
				return
			folder = document.Folder
			items = folder.Items()
			matchedNames = []
			for i in range(items.Count):
				item = items.Item(i)
				try:
					itemName = os.path.basename(item.Path)
				except (OSError, AttributeError, TypeError):
					continue
				if _matchesSearchTerm(itemName, mode, rawTerm):
					matchedNames.append(itemName)
			wx.CallAfter(callback, generation, matchedNames)
		except COMError as e:
			log.debug(f"xPlorer: search preview background COM error: {e}")
			wx.CallAfter(callback, generation, [])
		except Exception as e:
			log.error(f"Error in search preview background worker: {e}")
			wx.CallAfter(callback, generation, [])
		finally:
			try:
				comtypes.CoUninitialize()
			except OSError:
				pass

	def clearSelection(self, targetHwnd=None, focusedItemNameHint=None):
		# Used when entering the Multi-select layer: the layer is meant to
		# start from a clean slate, as if the user had just started holding
		# Ctrl with nothing picked yet, regardless of whatever was already
		# highlighted from earlier plain browsing.
		if targetHwnd is None:
			fg = api.getForegroundObject()
			if not fg or not fg.appModule or fg.appModule.appName != "explorer":
				return
			targetHwnd = fg.windowHandle
		threading.Thread(
			target=self._clearSelectionWorker,
			args=(targetHwnd, focusedItemNameHint),
			daemon=True
		).start()

	def _clearSelectionWorker(self, target_hwnd, focusedItemNameHint=None):
		if not self._selectionWorkerLock.acquire(blocking=False):
			return
		try:
			try:
				comtypes.CoInitialize()
			except OSError:
				pass
			try:
				localShell = comtypes.client.CreateObject("Shell.Application")
				shellWindow = self._findShellWindowByHwnd(localShell, target_hwnd, focusedItemNameHint)
				if not shellWindow:
					return
				document = shellWindow.Document
				if not hasattr(document, "Folder"):
					return
				folder = document.Folder
				items = folder.Items()
				for i in range(items.Count):
					item = items.Item(i)
					try:
						document.SelectItem(item, 0)
					except (OSError, AttributeError, TypeError) as e:
						log.debug(f"xPlorer: could not deselect an item while clearing selection: {e}")
			except COMError as e:
				log.debug(f"xPlorer: clear selection background COM error: {e}")
			except Exception as e:
				log.error(f"Error in clear selection background worker: {e}")
			finally:
				try:
					comtypes.CoUninitialize()
				except OSError:
					pass
		finally:
			self._selectionWorkerLock.release()

	def _startBatchSelect(self, predicate, resultMessageTemplate, targetHwnd=None, focusedItemNameHint=None):
		if targetHwnd is None:
			fg = api.getForegroundObject()
			if not fg or not fg.appModule or fg.appModule.appName != "explorer":
				ui.message(_("Not in File Explorer"))
				return
			targetHwnd = fg.windowHandle
			try:
				focusObj = api.getFocusObject()
				if focusObj:
					focusedItemNameHint = getattr(focusObj, "name", None)
			except Exception as e:
				log.debug(f"xPlorer: could not resolve focused item name hint for batch select: {e}")
		threading.Thread(
			target=self._batchSelectWorker,
			args=(targetHwnd, predicate, resultMessageTemplate, focusedItemNameHint),
			daemon=True
		).start()

	def _batchSelectWorker(self, target_hwnd, predicate, resultMessageTemplate, focusedItemNameHint=None):
		if not self._selectionWorkerLock.acquire(blocking=False):
			wx.CallAfter(ui.message, _("A selection operation is already in progress"))
			return
		try:
			try:
				comtypes.CoInitialize()
			except OSError:
				pass
			try:
				localShell = comtypes.client.CreateObject("Shell.Application")
				shellWindow = self._findShellWindowByHwnd(localShell, target_hwnd, focusedItemNameHint)
				if not shellWindow:
					wx.CallAfter(ui.message, _("No active File Explorer window found"))
					return

				document = shellWindow.Document
				if not hasattr(document, "Folder"):
					wx.CallAfter(ui.message, _("Unable to get folder view"))
					return

				folder = document.Folder
				items = folder.Items()
				total_count = items.Count
				if total_count == 0:
					wx.CallAfter(ui.message, _("No items in folder"))
					return

				if total_count > 300:
					wx.CallAfter(ui.message, _("Processing {count} items in background...").format(count=total_count))

				match_count = 0
				for i in range(total_count):
					item = items.Item(i)
					try:
						matches = predicate(item.Path)
					except (OSError, AttributeError, TypeError) as e:
						log.debug(f"xPlorer: select predicate failed for an item: {e}")
						matches = False
					if matches:
						document.SelectItem(item, 1)
						match_count += 1

				wx.CallAfter(ui.message, resultMessageTemplate.format(count=match_count))
			except COMError as e:
				log.debug(f"xPlorer: batch select background COM error: {e}")
				wx.CallAfter(ui.message, _("Error selecting items"))
			except Exception as e:
				log.error(f"Error in batch select background worker: {e}")
				wx.CallAfter(ui.message, _("Error selecting items"))
			finally:
				try:
					comtypes.CoUninitialize()
				except OSError:
					pass
		finally:
			self._selectionWorkerLock.release()


class SearchSelectionDialog(wx.Dialog):
	"""Accessible dialog for selecting items in the active Explorer folder
	by normal (substring) search, regular expression, or wildcard pattern
	(e.g. *.txt, report_*.docx - comma or space separated for more than
	one, wildcard mode only). A live, debounced results list shows what
	currently matches as the term is typed, without requiring the dialog
	to be closed and reopened to check or correct it."""

	PREVIEW_DEBOUNCE_MS = 500
	_MODE_CHOICES = (
		(SEARCH_MODE_NORMAL, "normal"),
		(SEARCH_MODE_REGEX, "regex"),
		(SEARCH_MODE_WILDCARD, "wildcard"),
	)

	def __init__(self, parent, selectionManager, targetHwnd=None, focusedItemNameHint=None, rootPath=None):
		super().__init__(parent, title=_("Select by Search"))
		self.selectionManager = selectionManager
		self.targetHwnd = targetHwnd
		self.focusedItemNameHint = focusedItemNameHint
		self.rootPath = rootPath
		self.pattern = None
		self._previewTimer = None
		self._previewGeneration = 0
		self._init_ui()
		self.Bind(wx.EVT_CLOSE, self._on_close)

	def _init_ui(self):
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		savedConfig = loadConfig()

		self.recursive_check = wx.CheckBox(self, label=_("Include subfolders (search all levels, like Flat View)"))
		self.recursive_check.SetValue(bool(savedConfig.get("searchIncludeSubfolders", False)) and bool(self.rootPath))
		if not self.rootPath:
			self.recursive_check.Enable(False)
		s_helper.addItem(self.recursive_check)

		mode_label = wx.StaticText(self, label=_("Search mode:"))
		s_helper.addItem(mode_label)
		modeDisplayLabels = [_("Normal search"), _("Regex"), _("Wildcard")]
		self.mode_combo = wx.ComboBox(self, style=wx.CB_READONLY, choices=modeDisplayLabels)
		savedMode = savedConfig.get("searchLastMode", SEARCH_MODE_NORMAL)
		savedModeIndex = next((i for i, (modeKey, _label) in enumerate(self._MODE_CHOICES) if modeKey == savedMode), 0)
		self.mode_combo.SetSelection(savedModeIndex)
		s_helper.addItem(self.mode_combo)

		label = wx.StaticText(self, label=_("Pattern / search text (meaning depends on the mode above):"))
		s_helper.addItem(label)
		self.pattern_ctrl = s_helper.addItem(wx.TextCtrl(self, value=savedConfig.get("searchLastTerm", "")))
		self.pattern_ctrl.SelectAll()

		results_label = wx.StaticText(self, label=_("Matching items (Enter opens, Ctrl+C/Ctrl+X copy/cut, Ctrl+Space toggles a pick, right-click or Menu key for more):"))
		s_helper.addItem(results_label)
		self.results_list = wx.ListBox(self, choices=[], size=(420, 150), style=wx.LB_MULTIPLE)
		s_helper.addItem(self.results_list, flag=wx.EXPAND, proportion=1)

		btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()
		self.pattern_ctrl.SetFocus()

		self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
		self.Bind(wx.EVT_TEXT_ENTER, self._on_ok)
		self.pattern_ctrl.Bind(wx.EVT_TEXT, self._on_pattern_text_changed)
		self.recursive_check.Bind(wx.EVT_CHECKBOX, self._on_recursive_toggle)
		self.mode_combo.Bind(wx.EVT_COMBOBOX, self._on_mode_changed)
		self.results_list.Bind(wx.EVT_CONTEXT_MENU, self._on_results_context_menu)
		self.results_list.Bind(wx.EVT_KEY_DOWN, self._on_results_key_down)
		self._schedulePreview()

	def _getSelectedMode(self):
		index = self.mode_combo.GetSelection()
		if 0 <= index < len(self._MODE_CHOICES):
			return self._MODE_CHOICES[index][0]
		return SEARCH_MODE_NORMAL

	def _on_mode_changed(self, event):
		self._schedulePreview()
		event.Skip()

	def _on_recursive_toggle(self, event):
		self._schedulePreview()
		event.Skip()

	def _on_pattern_text_changed(self, event):
		self._schedulePreview()
		event.Skip()

	def _schedulePreview(self):
		# Debounced on purpose: querying Explorer on every single keystroke
		# would make typing feel laggy, so the actual lookup only runs once
		# typing has paused for a moment.
		self._cancelPreviewTimer()
		self._previewTimer = core.callLater(self.PREVIEW_DEBOUNCE_MS, self._runPreview)

	def _cancelPreviewTimer(self):
		if self._previewTimer:
			self._previewTimer.Stop()
			self._previewTimer = None

	def _runPreview(self):
		rawTerm = self.pattern_ctrl.Value.strip()
		self._previewGeneration += 1
		generation = self._previewGeneration
		if not rawTerm:
			self.results_list.Set([])
			return
		mode = self._getSelectedMode()
		if mode == SEARCH_MODE_REGEX:
			try:
				re.compile(rawTerm)
			except re.error as e:
				self.results_list.Set([_("Invalid regular expression: {0}").format(e)])
				return
		if self.recursive_check.GetValue() and self.rootPath:
			self.selectionManager.previewSearchMatchesRecursive(rawTerm, mode, self._onPreviewReady, generation, self.rootPath)
		else:
			self.selectionManager.previewSearchMatches(
				rawTerm, mode, self._onPreviewReady, generation,
				targetHwnd=self.targetHwnd, focusedItemNameHint=self.focusedItemNameHint,
			)

	def _onPreviewReady(self, generation, matchedNames):
		if generation != self._previewGeneration:
			# A newer keystroke already started a fresher query - this
			# result is stale and would otherwise flash outdated matches.
			return
		try:
			self.results_list.Set(matchedNames)
		except RuntimeError:
			return
		ui.message(_("{count} matches").format(count=len(matchedNames)))

	def _saveLastSettings(self):
		conf = loadConfig()
		conf["searchLastMode"] = self._getSelectedMode()
		conf["searchIncludeSubfolders"] = self.recursive_check.GetValue()
		conf["searchLastTerm"] = self.pattern_ctrl.Value
		saveConfig(conf)

	def _getSelectedResultPaths(self):
		# Every row shown in the results list is either a direct child name
		# (single-level mode) or a path relative to rootPath (recursive
		# mode) - os.path.join resolves both correctly since rootPath is
		# always the folder these results were found under.
		if not self.rootPath:
			return []
		paths = []
		for index in self.results_list.GetSelections():
			displayLabel = self.results_list.GetString(index)
			candidatePath = os.path.join(self.rootPath, displayLabel)
			if os.path.exists(candidatePath):
				paths.append(candidatePath)
		return paths

	# Native listbox messages used below for reliable non-contiguous
	# selection independent of wx's own keyboard handling. The list is
	# created with wx.LB_MULTIPLE (LBS_MULTIPLESEL) rather than
	# wx.LB_EXTENDED (LBS_EXTENDEDSEL) specifically so LB_SETSEL below
	# behaves as documented - LB_SETSEL is intended for multiple-selection
	# listboxes, and sending it to an extended-selection one was silently
	# losing earlier toggles (each new Ctrl+Space looked like it worked -
	# "select"/"not select" announced correctly - but only the most recent
	# one actually stuck, so Ctrl+C only ever copied the last item picked).
	_LB_SETCARETINDEX = 0x019E
	_LB_GETCARETINDEX = 0x019F
	_LB_SETSEL = 0x0185

	def _getResultCaretIndex(self):
		hwnd = self.results_list.GetHandle()
		result = ctypes.windll.user32.SendMessageW(hwnd, self._LB_GETCARETINDEX, 0, 0)
		return result if result >= 0 else wx.NOT_FOUND

	def _moveResultCaret(self, delta):
		count = self.results_list.GetCount()
		if count == 0:
			return
		caretIndex = self._getResultCaretIndex()
		if caretIndex == wx.NOT_FOUND:
			caretIndex = 0
		newIndex = max(0, min(count - 1, caretIndex + delta))
		hwnd = self.results_list.GetHandle()
		ctypes.windll.user32.SendMessageW(hwnd, self._LB_SETCARETINDEX, newIndex, 0)
		ui.message(self.results_list.GetString(newIndex))

	def _toggleCurrentResultSelection(self):
		caretIndex = self._getResultCaretIndex()
		if caretIndex == wx.NOT_FOUND:
			return
		isSelected = self.results_list.IsSelected(caretIndex)
		hwnd = self.results_list.GetHandle()
		ctypes.windll.user32.SendMessageW(hwnd, self._LB_SETSEL, 0 if isSelected else 1, caretIndex)
		label = self.results_list.GetString(caretIndex)
		ui.message(_("not select {name}").format(name=label) if isSelected else _("select {name}").format(name=label))

	def _openFocusedResult(self):
		caretIndex = self._getResultCaretIndex()
		if caretIndex == wx.NOT_FOUND or not self.rootPath:
			ui.message(_("No result selected"))
			return
		displayLabel = self.results_list.GetString(caretIndex)
		targetPath = os.path.join(self.rootPath, displayLabel)
		if not os.path.exists(targetPath):
			ui.message(_("File not found"))
			return
		try:
			os.startfile(targetPath)
		except OSError as e:
			log.error(f"xPlorer: could not open {targetPath} from search results: {e}")
			ui.message(_("Could not open the file"))

	def _on_results_key_down(self, event):
		keyCode = event.GetKeyCode()
		controlDown = event.ControlDown()
		if controlDown and keyCode == wx.WXK_SPACE:
			self._toggleCurrentResultSelection()
			return
		if controlDown and keyCode in (wx.WXK_DOWN, wx.WXK_UP):
			self._moveResultCaret(1 if keyCode == wx.WXK_DOWN else -1)
			return
		if controlDown and keyCode == ord('C'):
			self._onResultsCopy(self._getSelectedResultPaths())
			return
		if controlDown and keyCode == ord('X'):
			self._onResultsCut(self._getSelectedResultPaths())
			return
		if keyCode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
			self._openFocusedResult()
			return
		event.Skip()

	def _on_results_context_menu(self, event):
		paths = self._getSelectedResultPaths()
		if not paths:
			ui.message(_("No result selected"))
			return
		menu = wx.Menu()
		copyItem = menu.Append(wx.ID_ANY, _("Copy"))
		cutItem = menu.Append(wx.ID_ANY, _("Cut"))
		openPathItem = menu.Append(wx.ID_ANY, _("Open to path"))
		menu.AppendSeparator()
		deleteItem = menu.Append(wx.ID_ANY, _("Delete"))
		self.Bind(wx.EVT_MENU, lambda evt: self._onResultsCopy(paths), copyItem)
		self.Bind(wx.EVT_MENU, lambda evt: self._onResultsCut(paths), cutItem)
		self.Bind(wx.EVT_MENU, lambda evt: self._onResultsOpenToPath(paths), openPathItem)
		self.Bind(wx.EVT_MENU, lambda evt: self._onResultsDelete(paths), deleteItem)
		self.PopupMenu(menu)
		menu.Destroy()

	def _clearAllResultSelections(self):
		hwnd = self.results_list.GetHandle()
		ctypes.windll.user32.SendMessageW(hwnd, self._LB_SETSEL, 0, -1)

	def _onResultsCopy(self, paths):
		if not paths:
			ui.message(_("No result selected"))
			return
		if _setFileClipboard(paths, isCut=False):
			ui.message(_("Copied {count} items").format(count=len(paths)))
			# Cleared right after so a leftover pick from this copy can't
			# silently get bundled into whatever gets selected next -
			# each Ctrl+C/Ctrl+X starts the next selection from a clean
			# slate, same as re-entering the Multi-select layer does.
			self._clearAllResultSelections()
		else:
			ui.message(_("Could not open clipboard"))

	def _onResultsCut(self, paths):
		if not paths:
			ui.message(_("No result selected"))
			return
		if _setFileClipboard(paths, isCut=True):
			ui.message(_("Cut {count} items").format(count=len(paths)))
			self._clearAllResultSelections()
		else:
			ui.message(_("Could not open clipboard"))

	def _onResultsOpenToPath(self, paths):
		# Only reveals the first selected item - "open to path" is about
		# jumping to a location, and a multi-selection spanning several
		# different subfolders has no single location to jump to.
		if not paths:
			ui.message(_("No result selected"))
			return
		from .explorerWindow import launchExplorer
		try:
			launchExplorer(["/select,", paths[0]])
		except OSError as e:
			log.error(f"xPlorer: could not open containing folder for {paths[0]}: {e}")
			ui.message(_("Could not open the folder"))

	def _onResultsDelete(self, paths):
		if not paths:
			ui.message(_("No result selected"))
			return
		confirm = wx.MessageBox(
			_("Move {count} item(s) to the Recycle Bin?").format(count=len(paths)),
			_("Delete"), wx.YES_NO | wx.ICON_WARNING, self
		)
		if confirm != wx.YES:
			return
		removedOk = _sendToRecycleBin(paths)
		if removedOk:
			ui.message(_("Moved {count} item(s) to the Recycle Bin").format(count=len(paths)))
			self._runPreview()
		else:
			ui.message(_("Could not delete one or more items"))

	def _on_ok(self, event):
		rawTerm = self.pattern_ctrl.Value.strip()
		if not rawTerm:
			ui.message(_("Enter a search term or pattern first"))
			return
		mode = self._getSelectedMode()
		if mode == SEARCH_MODE_REGEX:
			try:
				re.compile(rawTerm)
			except re.error as e:
				ui.message(_("Invalid regular expression: {0}").format(e))
				return
		self._cancelPreviewTimer()
		self._saveLastSettings()
		self.pattern = rawTerm
		recursive = self.recursive_check.GetValue()
		self.EndModal(wx.ID_OK)
		self.selectionManager.selectBySearch(
			rawTerm, mode, self.targetHwnd, self.focusedItemNameHint,
			recursive=recursive, rootPath=self.rootPath,
		)

	def _on_cancel(self, event):
		self._cancelPreviewTimer()
		self._saveLastSettings()
		self.EndModal(wx.ID_CANCEL)

	def _on_close(self, event):
		self._cancelPreviewTimer()
		self._saveLastSettings()
		self.EndModal(wx.ID_CANCEL)


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





