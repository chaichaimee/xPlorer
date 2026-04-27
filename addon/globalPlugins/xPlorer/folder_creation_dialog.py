# folder_creation_dialog.py

import addonHandler
import wx
import os
import ui
import tones
import time

addonHandler.initTranslation()

class FolderCreationDialog(wx.Dialog):
	def __init__(self, parent, current_path):
		super().__init__(parent, title=_("Create Multiple Folders"), style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
		self.current_path = current_path
		self.folder_edit_controls = []
		self.last_update_time = 0
		self.update_timer = None
		self.init_ui()
		self.CentreOnScreen()
		self.Raise()
		
	def init_ui(self):
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
		self.edit_names_checkbox.Bind(wx.EVT_CHECKBOX, self.on_edit_names_changed)
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
		
		self.title_text.Bind(wx.EVT_TEXT, self.on_title_changed)
		self.number_text.Bind(wx.EVT_TEXT, self.on_number_changed)
		self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
		
		wx.CallLater(100, self.update_preview)
		
	def on_char_hook(self, event):
		if event.GetKeyCode() == wx.WXK_ESCAPE:
			self.EndModal(wx.ID_CANCEL)
		event.Skip()
	
	def on_title_changed(self, event):
		self.schedule_update()
		event.Skip()
	
	def on_number_changed(self, event):
		self.schedule_update()
		event.Skip()
	
	def schedule_update(self):
		current_time = time.time()
		self.last_update_time = current_time
		if self.update_timer:
			self.update_timer.Stop()
		self.update_timer = wx.CallLater(300, self.update_preview)
	
	def on_edit_names_changed(self, event):
		if self.edit_names_checkbox.GetValue():
			self.scrolled_window.Show()
			self.update_preview()
		else:
			self.scrolled_window.Hide()
		self.Layout()
		event.Skip()
	
	def update_preview(self):
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
				else:
					folder_edit.SetValue("")
				
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
		created_count = 0
		
		if create_subfolders:
			success, main_folder_name = self.create_folder(title, self.current_path)
			if not success:
				ui.message(_("Error creating main folder"))
				return
			main_folder_path = os.path.join(self.current_path, main_folder_name)
			tones.beep(1000, 100)
			created_count += 1
			
			for i in range(1, num_folders + 1):
				if edit_names and i <= len(self.folder_edit_controls):
					folder_name = self.folder_edit_controls[i-1].GetValue().strip()
					if not folder_name:
						continue
				else:
					folder_name = f"{i:02d}{title}"
				
				folder_name = self.clean_folder_name(folder_name)
				if not folder_name:
					continue
					
				sub_success, sub_folder_name = self.create_folder(folder_name, main_folder_path)
				if sub_success:
					created_count += 1
				else:
					ui.message(_("Error creating subfolder: {number}").format(number=i))
		else:
			for i in range(1, num_folders + 1):
				if edit_names and i <= len(self.folder_edit_controls):
					folder_name = self.folder_edit_controls[i-1].GetValue().strip()
					if not folder_name:
						continue
				else:
					folder_name = f"{title}{i}"
				
				folder_name = self.clean_folder_name(folder_name)
				if not folder_name:
					continue
					
				success, folder_name = self.create_folder(folder_name, self.current_path)
				if success:
					created_count += 1
				else:
					ui.message(_("Error creating folder: {number}").format(number=i))
		
		if created_count > 0:
			tones.beep(1200, 100)
			if created_count == 1 and create_subfolders:
				ui.message(_("Successfully created main folder only"))
			elif created_count == 1 and not create_subfolders:
				ui.message(_("Successfully created 1 folder"))
			else:
				ui.message(_("Successfully created {count} folders").format(count=created_count))
		else:
			ui.message(_("No folders were created"))
	
	def clean_folder_name(self, name):
		invalid_chars = '<>:"/\\|?*'
		cleaned_name = name
		for char in invalid_chars:
			cleaned_name = cleaned_name.replace(char, '_')
		cleaned_name = cleaned_name.strip('. ')
		if not cleaned_name:
			return ""
		return cleaned_name
	
	def create_folder(self, base_name, base_path):
		if not base_path or not os.path.exists(base_path):
			return False, None
		cleaned_name = self.clean_folder_name(base_name)
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