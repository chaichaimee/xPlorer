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
	"""Copy cleaned clipboard text into rename edit control (multiple fallback methods)"""
	clipboard_text = None
	try:
		if wx.TheClipboard.Open():
			data = wx.TextDataObject()
			if wx.TheClipboard.GetData(data):
				clipboard_text = data.GetText().strip()
			wx.TheClipboard.Close()
	except Exception:
		return

	cleaned_text = clean_clipboard_text(clipboard_text) if clipboard_text else None
	if not cleaned_text or not is_suitable_clipboard_text(cleaned_text):
		return

	try:
		time.sleep(0.3)

		focused_hwnd = winUser.GetFocus()
		if not focused_hwnd:
			focused_hwnd = winUser.getForegroundWindow()

		# Method 1: direct EM_REPLACESEL + WM_SETTEXT
		EM_SETSEL = 0x00B1
		EM_REPLACESEL = 0x00C2
		WM_SETTEXT = 0x000C

		ctypes.windll.user32.SendMessageW(focused_hwnd, EM_SETSEL, 0, -1)
		time.sleep(0.05)
		ctypes.windll.user32.SendMessageW(focused_hwnd, EM_REPLACESEL, 0, cleaned_text)
		time.sleep(0.1)
		ctypes.windll.user32.SendMessageW(focused_hwnd, WM_SETTEXT, 0, cleaned_text)
		return

	except Exception:
		# Method 2: use clipboard replacement + Ctrl+V
		try:
			backup = None
			try:
				backup = api.getClipData()
			except:
				pass

			api.copyToClip(cleaned_text)
			time.sleep(0.05)
			api.processPendingEvents(False)

			KeyboardInputGesture.fromName("control+v").send()
			time.sleep(0.1)

			if backup is not None:
				def restore():
					try:
						api.copyToClip(backup)
					except:
						pass
				core.callLater(300, restore)
			return

		except Exception:
			# Method 3: direct keyboard simulation
			try:
				time.sleep(0.1)
				INPUT_KEYBOARD = 1
				KEYEVENTF_KEYUP = 0x0002

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

				def send_key(vk_code, flags=0):
					inp = INPUT()
					inp.type = INPUT_KEYBOARD
					inp.u.ki.wVk = vk_code
					inp.u.ki.wScan = 0
					inp.u.ki.dwFlags = flags
					inp.u.ki.time = 0
					inp.u.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
					ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

				send_key(winUser.VK_CONTROL)
				time.sleep(0.05)
				send_key(ord('A'))
				time.sleep(0.05)
				send_key(ord('A'), KEYEVENTF_KEYUP)
				send_key(winUser.VK_CONTROL, KEYEVENTF_KEYUP)
				time.sleep(0.15)

				for char in cleaned_text:
					vk = winUser.VkKeyScanW(ord(char))
					if vk == -1:
						continue
					vk_code = vk & 0xFF
					shift = (vk & 0x100) != 0
					if shift:
						send_key(winUser.VK_SHIFT)
					send_key(vk_code)
					time.sleep(0.03)
					send_key(vk_code, KEYEVENTF_KEYUP)
					if shift:
						send_key(winUser.VK_SHIFT, KEYEVENTF_KEYUP)
					time.sleep(0.03)
			except Exception as e:
				log.debug(f"Auto paste fallback failed: {e}")