# case.py

import ui
import os
import tempfile
import shutil
import re
import addonHandler
from logHandler import log

addonHandler.initTranslation()

class CaseConverter:
	def __init__(self):
		self.text_extensions = [
			'.txt', '.md', '.markdown', '.mdown', '.mkd', '.rst', '.rtf', '.log',
			'.py', '.pyw', '.js', '.jsx', '.ts', '.tsx', '.java', '.kt', '.scala',
			'.cpp', '.c', '.h', '.hpp', '.cc', '.cxx', '.cs', '.vb', '.go', '.rs',
			'.php', '.php3', '.php4', '.php5', '.phtml', '.rb', '.rhtml', '.erb',
			'.pl', '.pm', '.sh', '.bash', '.zsh', '.fish', '.ps1', '.psm1', '.bat',
			'.cmd', '.vbs', '.lua', '.coffee', '.dart', '.groovy', '.clj', '.cljs',
			'.html', '.htm', '.xhtml', '.shtml', '.css', '.scss', '.sass', '.less',
			'.xml', '.xsl', '.xslt', '.svg', '.json', '.json5', '.jsonc', '.yaml',
			'.yml', '.toml', '.ini', '.conf', '.cfg', '.properties',
			'.po', '.pot', '.mo', '.xliff', '.xlf', '.resx', '.ts',
			'.sql', '.graphql', '.gql', '.vue', '.svelte', '.astro', '.ejs',
			'.twig', '.hbs', '.handlebars', '.jade', '.pug', '.haml',
			'.cmake', '.gradle', '.dockerfile', 'dockerfile', '.env', '.gitignore',
			'.gitattributes', '.editorconfig', 'makefile', 'Makefile', '.make',
			'.ini.t2t'
		]
		
		self._minor_words = set([
			"a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet",
			"at", "by", "for", "from", "in", "into", "of", "off", "on", "onto",
			"out", "over", "to", "up", "with", "as", "if", "than", "that",
			"till", "when", "via"
		])

	def is_text_file(self, filepath):
		ext = os.path.splitext(filepath)[1].lower()
		return ext in self.text_extensions

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

	def _collect_folders_only(self, paths):
		folders = []
		for path in paths:
			if os.path.isdir(path):
				folders.append(path)
				for root, dirs, _ in os.walk(path):
					for d in dirs:
						folders.append(os.path.join(root, d))
		folders = list(set(folders))
		folders.sort(key=lambda x: x.count(os.sep), reverse=True)
		return folders

	def _rename_folder_only(self, old_path, convert_func):
		try:
			if not os.path.isdir(old_path):
				return False
			dir_name, folder_name = os.path.split(old_path)
			new_folder_name = convert_func(folder_name)
			new_path = os.path.join(dir_name, new_folder_name)
			if old_path == new_path:
				return True
			if os.path.exists(new_path):
				if os.path.normcase(old_path) == os.path.normcase(new_path):
					pass
				else:
					log.warning(f"Cannot rename folder {old_path} to {new_path}, target already exists")
					return False
			os.rename(old_path, new_path)
			log.info(f"Renamed folder {old_path} to {new_path}")
			return True
		except Exception as e:
			log.error(f"Error renaming folder {old_path}: {e}")
			return False

	def convert_folder_to_uppercase(self, paths):
		folders = self._collect_folders_only(paths)
		if not folders:
			ui.message(_("No folders found"))
			return
		success = 0
		for folder in folders:
			if self._rename_folder_only(folder, str.upper):
				success += 1
		if success > 0:
			ui.message(_("Successfully converted {count} folders to uppercase").format(count=success))
		else:
			ui.message(_("Failed to rename any folders"))

	def convert_folder_to_lowercase(self, paths):
		folders = self._collect_folders_only(paths)
		if not folders:
			ui.message(_("No folders found"))
			return
		success = 0
		for folder in folders:
			if self._rename_folder_only(folder, str.lower):
				success += 1
		if success > 0:
			ui.message(_("Successfully converted {count} folders to lowercase").format(count=success))
		else:
			ui.message(_("Failed to rename any folders"))

	def convert_folder_to_titlecase(self, paths):
		def to_title_case(text):
			words = text.split()
			title_words = []
			for word in words:
				if word:
					title_words.append(word.capitalize())
			return ' '.join(title_words)
		folders = self._collect_folders_only(paths)
		if not folders:
			ui.message(_("No folders found"))
			return
		success = 0
		for folder in folders:
			if self._rename_folder_only(folder, to_title_case):
				success += 1
		if success > 0:
			ui.message(_("Successfully converted {count} folders to title case").format(count=success))
		else:
			ui.message(_("Failed to rename any folders"))

	def convert_folder_to_headlinecase(self, paths):
		folders = self._collect_folders_only(paths)
		if not folders:
			ui.message(_("No folders found"))
			return
		success = 0
		for folder in folders:
			if self._rename_folder_only(folder, self._to_headline_case):
				success += 1
		if success > 0:
			ui.message(_("Successfully converted {count} folders to headline case").format(count=success))
		else:
			ui.message(_("Failed to rename any folders"))