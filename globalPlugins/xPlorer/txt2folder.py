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

addonHandler.initTranslation()

class TxtToFolder:
    """Class to handle TXT and RTF to Folder conversion"""
    
    def __init__(self, plugin):
        self.plugin = plugin
        self._striprtf_available = None
    
    def _get_striprtf_module(self):
        """Lazy import striprtf module"""
        if self._striprtf_available is None:
            try:
                # Try to get striprtf module from plugin
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
        """Convert selected text file (TXT or RTF) to folder structure"""
        focus = api.getFocusObject()
        if not focus or focus.appModule.appName != "explorer":
            ui.message(_("Not in File Explorer"))
            return
        
        items, _ = self.plugin._getSelectedItems()
        if not items or len(items) > 1:
            ui.message(_("Please select only one text file"))
            return
        
        file_path = items[0][1]
        
        # Check if it's a supported file
        if not (file_path.lower().endswith('.txt') or file_path.lower().endswith('.rtf')):
            ui.message(_("Please select a .txt or .rtf file"))
            return
        
        # Check if file exists
        if not os.path.exists(file_path):
            ui.message(_("Selected file does not exist"))
            return
        
        try:
            # Read the file based on extension
            lines = []
            if file_path.lower().endswith('.rtf'):
                rtf_to_text = self._get_striprtf_module()
                if not rtf_to_text:
                    ui.message(_("Cannot process RTF file: striprtf module not available"))
                    return
                
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        rtf_content = f.read()
                    text_content = rtf_to_text(rtf_content)
                    # Split into lines
                    lines = text_content.split('\n')
                except Exception as e:
                    log.error(f"Error processing RTF file: {e}")
                    ui.message(_("Error reading RTF file"))
                    return
            else:
                # Read TXT file
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            
            # Remove empty lines and strip whitespace
            folder_names = [line.strip() for line in lines if line.strip()]
            
            if not folder_names:
                ui.message(_("No valid folder names found in the file"))
                return
            
            # Create base folder name (without extension)
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            base_folder = os.path.join(os.path.dirname(file_path), base_name)
            
            # Check if base folder already exists
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
            
            # Create base folder
            try:
                os.makedirs(base_folder)
            except Exception as e:
                log.error(f"Error creating base folder: {e}")
                ui.message(_("Error creating base folder"))
                return
            
            # Create subfolders using robocopy for better reliability
            created_count = 0
            for folder_name in folder_names:
                # Create valid folder name (remove invalid characters)
                valid_name = self._make_valid_folder_name(folder_name)
                if valid_name:
                    folder_path = os.path.join(base_folder, valid_name)
                    try:
                        # Use robocopy to create empty directory
                        cmd = ['robocopy', base_folder, folder_path, '/CREATE']
                        subprocess.run(
                            cmd,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False
                        )
                        # Also create the directory using os.makedirs as backup
                        os.makedirs(folder_path, exist_ok=True)
                        created_count += 1
                    except Exception as e:
                        log.error(f"Error creating folder {folder_path}: {e}")
                        # Try alternative method
                        try:
                            os.makedirs(folder_path, exist_ok=True)
                            created_count += 1
                        except:
                            pass
            
            # Announce result
            if created_count > 0:
                ui.message(_("Successfully created {} folders in '{}'").format(
                    created_count, os.path.basename(base_folder)
                ))
                tones.beep(1000, 200)
            else:
                ui.message(_("No folders were created"))
            
        except UnicodeDecodeError:
            # Try with different encoding for TXT files
            if file_path.lower().endswith('.txt'):
                try:
                    with open(file_path, 'r', encoding='cp874') as f:
                        lines = f.readlines()
                    
                    folder_names = [line.strip() for line in lines if line.strip()]
                    
                    if not folder_names:
                        ui.message(_("No valid folder names found in the file"))
                        return
                    
                    # Create base folder name
                    base_name = os.path.splitext(os.path.basename(file_path))[0]
                    base_folder = os.path.join(os.path.dirname(file_path), base_name)
                    
                    # Check if base folder already exists
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
                    
                    # Create base folder
                    os.makedirs(base_folder)
                    
                    # Create subfolders
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
                        ui.message(_("Successfully created {} folders in '{}'").format(
                            created_count, os.path.basename(base_folder)
                        ))
                        tones.beep(1000, 200)
                    else:
                        ui.message(_("No folders were created"))
                    
                except Exception as e:
                    log.error(f"Error processing text file: {e}")
                    ui.message(_("Error processing text file: {}").format(str(e)))
            else:
                log.error(f"Unicode decode error for RTF file: {file_path}")
                ui.message(_("Error reading file encoding"))
        
        except Exception as e:
            log.error(f"Error converting file to folder: {e}")
            ui.message(_("Error: {}").format(str(e)))
    
    def _make_valid_folder_name(self, name):
        """Convert a string to a valid folder name"""
        if not name or not isinstance(name, str):
            return None
            
        # Remove invalid characters for Windows folder names
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '')
        
        # Remove leading/trailing dots and spaces
        name = name.strip('. ')
        
        # Replace multiple spaces with single space
        while '  ' in name:
            name = name.replace('  ', ' ')
        
        # If name is empty after cleaning, return None
        if not name:
            return None
        
        # Windows doesn't allow certain reserved names
        reserved_names = ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 
                         'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 
                         'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']
        if name.upper() in reserved_names:
            name = name + '_folder'
        
        # Limit length to 255 characters
        if len(name) > 255:
            name = name[:255]
        
        return name


