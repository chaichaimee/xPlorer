# case.py

import ui
import os
import threading
import wx
import ctypes
from ctypes import wintypes
from logHandler import log
import addonHandler
import core
import time

addonHandler.initTranslation()

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