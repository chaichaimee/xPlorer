# folder_creator.py

import addonHandler
import wx
import winUser
import time
import ctypes
import ctypes.wintypes
import re
import api
import core
from keyboardHandler import KeyboardInputGesture
from logHandler import log

addonHandler.initTranslation()

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