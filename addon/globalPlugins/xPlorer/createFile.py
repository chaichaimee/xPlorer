# createFile.py

import os
import wx
import gui
import gui.guiHelper
import ui
import api
from logHandler import log
import addonHandler
import core

addonHandler.initTranslation()

class CreateFileDialog(wx.Dialog):
	def __init__(self, parent):
		super().__init__(parent, title=_("Create File"))
		self.file_data = []
		self.files_created = False
		self.file_inputs = []
		self.first_name_ctrl = None
		self._init_ui()
		
	def _init_ui(self):
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		
		s_helper.addItem(wx.StaticText(self, label=_("Number of files to create:")))
		self.count_ctrl = wx.SpinCtrl(self, min=1, max=10, initial=1)
		s_helper.addItem(self.count_ctrl)
		
		self.scrolled_panel = wx.ScrolledWindow(self)
		self.scrolled_panel.SetScrollRate(0, 20)
		s_helper.addItem(self.scrolled_panel, proportion=1, flag=wx.EXPAND)
		
		self.fields_sizer = wx.BoxSizer(wx.VERTICAL)
		self.scrolled_panel.SetSizer(self.fields_sizer)
		
		self._create_file_field(1, is_first=True)
		self.scrolled_panel.SetMinSize((400, 200))
		
		self.count_ctrl.Bind(wx.EVT_SPINCTRL, self._on_count_changed)
		
		btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)
		
		self.SetSizer(main_sizer)
		main_sizer.Fit(self)
		self.CentreOnScreen()
		
		self.first_name_ctrl.SetFocus()
		
		self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
		self.Bind(wx.EVT_TEXT_ENTER, self._on_ok)
		self.Bind(wx.EVT_CLOSE, self._on_close)
		
	def _create_file_field(self, index, is_first=False):
		field_panel = wx.Panel(self.scrolled_panel)
		field_sizer = wx.BoxSizer(wx.HORIZONTAL)
		field_panel.SetSizer(field_sizer)
		
		if is_first:
			name_label = wx.StaticText(field_panel, label=_("File name:"))
		else:
			name_label = wx.StaticText(field_panel, label=_("File name {index}:").format(index=index))
		field_sizer.Add(name_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
		
		name_ctrl = wx.TextCtrl(field_panel)
		field_sizer.Add(name_ctrl, 1, wx.EXPAND | wx.RIGHT, 10)
		
		ext_label = wx.StaticText(field_panel, label=_("Extension:"))
		field_sizer.Add(ext_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
		
		ext_ctrl = wx.TextCtrl(field_panel, value="txt")
		field_sizer.Add(ext_ctrl, 0, wx.EXPAND)
		
		self.fields_sizer.Add(field_panel, 0, wx.EXPAND | wx.TOP, 5)
		
		if index == 1:
			self.first_name_ctrl = name_ctrl
			field_panel.Show()
		else:
			field_panel.Hide()
			
		self.file_inputs.append({
			'panel': field_panel,
			'name_ctrl': name_ctrl,
			'ext_ctrl': ext_ctrl,
			'index': index,
			'is_first': is_first
		})
		
	def _update_file_fields(self, count):
		try:
			if count < 1:
				count = 1
			if count > 10:
				count = 10
			
			current_count = len(self.file_inputs)
			if count > current_count:
				for i in range(current_count + 1, count + 1):
					is_first = (i == 1)
					self._create_file_field(i, is_first)
			
			for i, file_input in enumerate(self.file_inputs):
				if i < count:
					file_input['panel'].Show()
					if i >= 1 and not file_input['is_first']:
						for child in file_input['panel'].GetChildren():
							if isinstance(child, wx.StaticText) and child.GetLabel().startswith(_("File name")):
								child.SetLabel(_("File name {index}:").format(index=i+1))
				else:
					file_input['panel'].Hide()
			
			self.fields_sizer.Layout()
			self.scrolled_panel.Layout()
			self.Layout()
			self.scrolled_panel.FitInside()
		except Exception as e:
			log.error(f"Error updating file fields: {e}")
		
	def _on_count_changed(self, event):
		try:
			count = self.count_ctrl.GetValue()
			self._update_file_fields(count)
		except Exception as e:
			log.error(f"Error in onCountChanged: {e}")
		
	def _on_ok(self, event):
		count = self.count_ctrl.GetValue()
		
		if count < 1:
			ui.message(_("File count must be at least 1"))
			return
		if count > 10:
			ui.message(_("File count cannot exceed 10"))
			return
			
		self.file_data = []
		has_empty_name = False
		
		for i in range(count):
			if i < len(self.file_inputs):
				file_input = self.file_inputs[i]
				name_ctrl = file_input['name_ctrl']
				ext_ctrl = file_input['ext_ctrl']
				
				name = name_ctrl.GetValue().strip()
				ext = ext_ctrl.GetValue().strip()
				
				if not name:
					has_empty_name = True
					if i == 0:
						name = _("new_file")
					else:
						name = _("new_file_{index}").format(index=i+1)
					
				if ext:
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
		
	def _on_cancel(self, event):
		self.EndModal(wx.ID_CANCEL)
		
	def _on_close(self, event):
		self.EndModal(wx.ID_CANCEL)


class CreateFileManager:
	def __init__(self, plugin):
		self.plugin = plugin
		self.create_file_dialog = None
		self._retry_attempts = 0
		
	def cleanup(self):
		if self.create_file_dialog:
			try:
				self.create_file_dialog.Destroy()
			except:
				pass
				
	def create_file(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			log.debug("create_file: Not in Explorer")
			return
		
		current_path = self.plugin._getCurrentPath()
		log.debug(f"create_file: initial path = {current_path}")
		if current_path and os.path.isdir(current_path):
			wx.CallAfter(self._show_create_file_dialog, current_path)
		else:
			self._retry_attempts = 0
			core.callLater(300, self._retry_get_path)
		
	def _retry_get_path(self):
		self._retry_attempts += 1
		if self._retry_attempts > 3:
			ui.message(_("Unable to get current directory after multiple attempts"))
			log.debug("create_file: path retry exhausted")
			return
		
		current_path = self.plugin._getCurrentPath()
		log.debug(f"create_file: retry {self._retry_attempts}, path = {current_path}")
		if current_path and os.path.isdir(current_path):
			wx.CallAfter(self._show_create_file_dialog, current_path)
		else:
			core.callLater(300, self._retry_get_path)
		
	def _show_create_file_dialog(self, current_path):
		try:
			log.debug(f"Showing create file dialog for path: {current_path}")
			if gui.mainFrame:
				gui.mainFrame.prePopup()
			
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
		finally:
			if gui.mainFrame:
				gui.mainFrame.postPopup()
				
	def _create_files(self, directory, file_data):
		try:
			created_count = 0
			for name, ext in file_data:
				file_name = f"{name}{ext}"
				file_path = os.path.join(directory, file_name)
				
				if os.path.exists(file_path):
					counter = 1
					base_name = name
					while os.path.exists(file_path):
						file_name = f"{base_name}_{counter}{ext}"
						file_path = os.path.join(directory, file_name)
						counter += 1
						if counter > 100:
							ui.message(_("Cannot find unique name for: {name}").format(name=name))
							break
				
				try:
					with open(file_path, 'w'):
						pass
					created_count += 1
				except Exception as e:
					log.error(f"Error creating file {file_path}: {e}")
					
			if created_count == 0:
				ui.message(_("No files were created"))
			elif created_count == 1:
				ui.message(_("1 file created"))
			else:
				ui.message(_("{count} files created").format(count=created_count))
		except Exception as e:
			log.error(f"Error in create_files: {e}")
			ui.message(_("Error creating files"))