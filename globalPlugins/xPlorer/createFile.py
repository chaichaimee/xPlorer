# createFile.py

import os
import wx
import gui
import gui.guiHelper
import ui
import api
from logHandler import log
import addonHandler

addonHandler.initTranslation()

class CreateFileDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Create File"))
        self.file_data = []  # List of tuples (name, extension)
        self.files_created = False
        self.file_inputs = []  # Store references to all file input controls
        self.InitUI()
        
    def InitUI(self):
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
        
        # File count field using SpinCtrl for better control
        sHelper.addItem(wx.StaticText(self, label=_("Number of files to create:")))
        self.countCtrl = wx.SpinCtrl(self, min=1, max=10, initial=1)
        sHelper.addItem(self.countCtrl)
        
        # Create a scrolled panel for file fields
        self.scrolledPanel = wx.ScrolledWindow(self)
        self.scrolledPanel.SetScrollRate(0, 20)
        sHelper.addItem(self.scrolledPanel, proportion=1, flag=wx.EXPAND)
        
        # Create main sizer for scrolled panel
        self.fieldsSizer = wx.BoxSizer(wx.VERTICAL)
        self.scrolledPanel.SetSizer(self.fieldsSizer)
        
        # Create initial file field
        self._create_file_field(1, is_first=True)
        
        # Set scrolled panel size
        self.scrolledPanel.SetMinSize((400, 200))
        
        # Bind count change event
        self.countCtrl.Bind(wx.EVT_SPINCTRL, self.onCountChanged)
        
        # Create button sizer
        btnSizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sHelper.addItem(btnSizer, flag=wx.ALIGN_CENTER)
        
        self.SetSizer(mainSizer)
        mainSizer.Fit(self)
        
        self.CentreOnScreen()
        
        # Set focus to first file name field
        self.firstNameCtrl.SetFocus()
        
        # Bind events
        self.Bind(wx.EVT_BUTTON, self.OnOk, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.OnCancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_TEXT_ENTER, self.OnOk)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        
    def _create_file_field(self, index, is_first=False):
        """Create a file field set for the given index"""
        fieldPanel = wx.Panel(self.scrolledPanel)
        fieldSizer = wx.BoxSizer(wx.HORIZONTAL)
        fieldPanel.SetSizer(fieldSizer)
        
        # File name field
        if is_first:
            nameLabel = wx.StaticText(fieldPanel, label=_("File name:"))
        else:
            nameLabel = wx.StaticText(fieldPanel, label=_("File name {index}:").format(index=index))
        fieldSizer.Add(nameLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        
        nameCtrl = wx.TextCtrl(fieldPanel)
        fieldSizer.Add(nameCtrl, 1, wx.EXPAND | wx.RIGHT, 10)
        
        # Extension field
        extLabel = wx.StaticText(fieldPanel, label=_("Extension:"))
        fieldSizer.Add(extLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        
        extCtrl = wx.TextCtrl(fieldPanel, value="txt")
        fieldSizer.Add(extCtrl, 0, wx.EXPAND)
        
        self.fieldsSizer.Add(fieldPanel, 0, wx.EXPAND | wx.TOP, 5)
        
        # Store references
        if index == 1:
            self.firstNameCtrl = nameCtrl
            fieldPanel.Show()
        else:
            fieldPanel.Hide()
            
        self.file_inputs.append({
            'panel': fieldPanel,
            'nameCtrl': nameCtrl,
            'extCtrl': extCtrl,
            'index': index,
            'is_first': is_first
        })
        
    def _update_file_fields(self, count):
        """Update file fields based on count"""
        try:
            # Ensure count is within limits
            if count < 1:
                count = 1
            if count > 10:
                count = 10
            
            # Create additional fields if needed
            current_count = len(self.file_inputs)
            if count > current_count:
                for i in range(current_count + 1, count + 1):
                    is_first = (i == 1)
                    self._create_file_field(i, is_first)
            
            # Show/hide fields based on count
            for i, file_input in enumerate(self.file_inputs):
                if i < count:
                    file_input['panel'].Show()
                    # Update label for second and subsequent files
                    if i >= 1 and not file_input['is_first']:
                        # Find and update the label
                        for child in file_input['panel'].GetChildren():
                            if isinstance(child, wx.StaticText) and child.GetLabel().startswith(_("File name")):
                                child.SetLabel(_("File name {index}:").format(index=i+1))
                else:
                    file_input['panel'].Hide()
            
            # Update layout
            self.fieldsSizer.Layout()
            self.scrolledPanel.Layout()
            self.Layout()
            
            # Adjust scrollable area
            self.scrolledPanel.FitInside()
            
        except Exception as e:
            log.error(f"Error updating file fields: {e}")
        
    def onCountChanged(self, event):
        """Handle change in file count"""
        try:
            count = self.countCtrl.GetValue()
            self._update_file_fields(count)
        except Exception as e:
            log.error(f"Error in onCountChanged: {e}")
        
    def OnOk(self, event):
        # Get file count
        count = self.countCtrl.GetValue()
        
        if count < 1:
            ui.message(_("File count must be at least 1"))
            return
        if count > 10:
            ui.message(_("File count cannot exceed 10"))
            return
            
        # Collect file data
        self.file_data = []
        has_empty_name = False
        
        for i in range(count):
            if i < len(self.file_inputs):
                file_input = self.file_inputs[i]
                nameCtrl = file_input['nameCtrl']
                extCtrl = file_input['extCtrl']
                
                name = nameCtrl.GetValue().strip()
                ext = extCtrl.GetValue().strip()
                
                # Validate file name
                if not name:
                    has_empty_name = True
                    if i == 0:
                        name = _("new_file")
                    else:
                        name = _("new_file_{index}").format(index=i+1)
                    
                # Process extension
                if ext:
                    # Remove leading dot if present
                    if ext.startswith('.'):
                        ext = ext[1:]
                    ext = "." + ext
                else:
                    ext = ".txt"
                    
                self.file_data.append((name, ext))
            
        if has_empty_name:
            ui.message(_("Some files will use default names"))
            
        self.files_created = True
        self.EndModal(wx.ID_OK)
        
    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)
        
    def OnClose(self, event):
        self.EndModal(wx.ID_CANCEL)


class CreateFileManager:
    def __init__(self, plugin):
        self.plugin = plugin
        self.create_file_dialog = None
        
    def cleanup(self):
        if self.create_file_dialog:
            try:
                self.create_file_dialog.Destroy()
            except:
                pass
                
    def create_file(self):
        """Create new file(s) in the current directory"""
        focus = api.getFocusObject()
        if not focus or focus.appModule.appName != "explorer":
            ui.message(_("Not in File Explorer"))
            return
            
        # Get current directory path
        current_path = self.plugin._getCurrentPath()
        if not current_path:
            ui.message(_("Unable to get current directory"))
            return
            
        if not os.path.isdir(current_path):
            ui.message(_("Current path is not a directory"))
            return
            
        # Show create file dialog
        wx.CallAfter(self._show_create_file_dialog, current_path)
        
    def _show_create_file_dialog(self, current_path):
        try:
            if self.create_file_dialog and self.create_file_dialog.IsShown():
                self.create_file_dialog.Destroy()
                
            self.create_file_dialog = CreateFileDialog(gui.mainFrame)
            
            self.create_file_dialog.Raise()
            
            result = self.create_file_dialog.ShowModal()
            
            if result == wx.ID_OK and self.create_file_dialog.files_created:
                self._create_files(current_path, self.create_file_dialog.file_data)
                
            self.create_file_dialog.Destroy()
            self.create_file_dialog = None
            
        except Exception as e:
            log.error(f"Error showing create file dialog: {e}")
            ui.message(_("Error opening create file dialog"))
            if self.create_file_dialog:
                try:
                    self.create_file_dialog.Destroy()
                except:
                    pass
                self.create_file_dialog = None
                
    def _create_files(self, directory, file_data):
        """Create the actual files"""
        try:
            created_count = 0
            
            # Define templates for different file types
            templates = {
                'py': '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\n"""\nCreated with xPlorer\n"""\n\ndef main():\n    pass\n\nif __name__ == "__main__":\n    main()\n',
                'js': '// Created with xPlorer\n\nfunction main() {\n    // Your code here\n}\n\nmain();\n',
                'html': '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>New Document</title>\n</head>\n<body>\n    <!-- Created with xPlorer -->\n</body>\n</html>\n',
                'css': '/* Created with xPlorer */\n\nbody {\n    margin: 0;\n    padding: 0;\n}\n',
                'xml': '<?xml version="1.0" encoding="UTF-8"?>\n<!-- Created with xPlorer -->\n<root>\n</root>\n',
                'json': '{\n    "created_with": "xPlorer"\n}\n',
                'md': '# New Document\n\nCreated with xPlorer\n',
                'ini': '; Created with xPlorer\n[Settings]\n',
                'conf': '# Created with xPlorer\n\n# Configuration settings\n',
                'cfg': '# Created with xPlorer\n\n# Configuration settings\n',
                'java': '// Created with xPlorer\n\npublic class Main {\n    public static void main(String[] args) {\n        // Your code here\n    }\n}\n',
                'cpp': '// Created with xPlorer\n\n#include <iostream>\n\nint main() {\n    std::cout << "Hello World!" << std::endl;\n    return 0;\n}\n',
                'c': '// Created with xPlorer\n\n#include <stdio.h>\n\nint main() {\n    printf("Hello World!\\n");\n    return 0;\n}\n',
                'h': '// Created with xPlorer\n\n#ifndef HEADER_H\n#define HEADER_H\n\n// Your declarations here\n\n#endif // HEADER_H\n',
                'php': '<?php\n// Created with xPlorer\n\n// Your code here\n?>\n',
                'rb': '# Created with xPlorer\n\n# Your code here\n',
                'pl': '# Created with xPlorer\n\n# Your code here\n',
                'sh': '#!/bin/bash\n# Created with xPlorer\n\n# Your script here\n',
                'bat': '@echo off\nREM Created with xPlorer\n\nREM Your batch commands here\n',
                'ps1': '# Created with xPlorer\n\n# Your PowerShell script here\n',
                'rtf': '{\\rtf1\\ansi\\ansicpg1252\\deff0\\nouicompat\\deflang1033{\\fonttbl{\\f0\\fnil\\fcharset0 Calibri;}}\n{\\*\\generator Riched20 10.0.19041}\\viewkind4\\uc1 \n\\pard\\sa200\\sl276\\slmult1\\f0\\fs22\\lang9 Created with xPlorer\\par\n}\n'
            }
            
            # Common text extensions for empty files
            text_extensions = ['txt', 'csv', 'log', 'yml', 'yaml', 'toml', 'env', 'gitignore', 'dockerignore']
            
            for i, (name, ext) in enumerate(file_data, 1):
                # Create file name with extension
                file_name = f"{name}{ext}"
                file_path = os.path.join(directory, file_name)
                
                # Check if file already exists
                if os.path.exists(file_path):
                    # Try to find a unique name
                    counter = 1
                    base_name = name
                    while os.path.exists(file_path):
                        file_name = f"{base_name}_{counter}{ext}"
                        file_path = os.path.join(directory, file_name)
                        counter += 1
                        if counter > 100:
                            ui.message(_("Cannot find unique name for: {name}").format(name=name))
                            break
                
                # Create file with appropriate content
                try:
                    # Get extension without dot
                    ext_clean = ext[1:].lower() if ext.startswith('.') else ext.lower()
                    
                    if ext_clean in templates:
                        # Use template for supported file types
                        content = templates[ext_clean]
                        encoding = 'utf-8'
                    elif ext_clean in text_extensions:
                        # Create empty text file
                        content = ""
                        encoding = 'utf-8'
                    else:
                        # For other extensions, create empty file
                        content = ""
                        encoding = 'utf-8'
                        
                    # Write file
                    with open(file_path, 'w', encoding=encoding) as f:
                        f.write(content)
                        
                    created_count += 1
                    
                except Exception as e:
                    log.error(f"Error creating file {file_path}: {e}")
                    # Try creating empty file as fallback
                    try:
                        open(file_path, 'w').close()
                        created_count += 1
                    except:
                        pass
                        
            # Report results
            if created_count == 0:
                ui.message(_("No files were created"))
            elif created_count == 1:
                ui.message(_("1 file created"))
            else:
                ui.message(_("{count} files created").format(count=created_count))
                
        except Exception as e:
            log.error(f"Error in create_files: {e}")
            ui.message(_("Error creating files"))