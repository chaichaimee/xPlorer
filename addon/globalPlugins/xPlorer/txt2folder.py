# txt2folder.py

import ui
import api
import os
import wx
import gui
import addonHandler
from logHandler import log
import subprocess
import tones
import core

addonHandler.initTranslation()

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