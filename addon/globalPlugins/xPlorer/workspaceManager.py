# workspaceManager.py

import os
import json
import threading
import ctypes
import comtypes.client
from comtypes import COMError
from urllib.parse import unquote, urlparse
import wx
import gui
import gui.guiHelper
import ui
import core
import addonHandler
from logHandler import log
from .folderTools import CONFIG_DIR
from .explorerWindow import launchExplorer

addonHandler.initTranslation()

WORKSPACES_FILE = os.path.join(CONFIG_DIR, "workspaces.json")


class WorkspaceEditDialog(wx.Dialog):
	"""Accessible dialog for naming a new workspace made up of the folder
	paths currently gathered for it (e.g. the current Explorer folder plus
	any the user adds by hand)."""

	def __init__(self, parent, initialPaths, workspaceManager=None):
		super().__init__(parent, title=_("Save Workspace"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.paths = list(initialPaths)
		self.workspaceName = None
		# Kept so the "Edit Workspace" button below can open the full
		# workspace list (rename/pin/reorder/delete) without this dialog
		# needing to know how that list is stored or persisted.
		self.workspaceManager = workspaceManager
		self._init_ui()
		self.Bind(wx.EVT_CLOSE, self._on_close)

	def _init_ui(self):
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		self.name_label = wx.StaticText(self, label=_("Workspace name:"))
		s_helper.addItem(self.name_label)
		self.name_text = wx.TextCtrl(self)
		s_helper.addItem(self.name_text)

		paths_label = wx.StaticText(self, label=_("Folders in this workspace:"))
		s_helper.addItem(paths_label)
		self.paths_list = wx.ListBox(self, choices=[], size=(500, 150))
		s_helper.addItem(self.paths_list, flag=wx.EXPAND, proportion=1)

		self.show_paths_check = wx.CheckBox(self, label=_("Show paths"))
		self.show_paths_check.SetValue(False)
		s_helper.addItem(self.show_paths_check)

		paste_label = wx.StaticText(self, label=_("Or paste/type folder paths here, one per line:"))
		s_helper.addItem(paste_label)
		self.paste_text = wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(500, 60))
		s_helper.addItem(self.paste_text, flag=wx.EXPAND)

		add_remove_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self.add_btn = wx.Button(self, label=_("Add Folder..."))
		add_remove_sizer.Add(self.add_btn, 0, wx.ALL, 5)
		self.remove_btn = wx.Button(self, label=_("Remove Selected"))
		add_remove_sizer.Add(self.remove_btn, 0, wx.ALL, 5)
		s_helper.addItem(add_remove_sizer)

		btn_sizer = wx.StdDialogButtonSizer()
		self.save_btn = wx.Button(self, wx.ID_OK, label=_("Save"))
		btn_sizer.AddButton(self.save_btn)
		self.cancel_btn = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))
		btn_sizer.AddButton(self.cancel_btn)
		btn_sizer.Realize()
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)

		self.editWorkspaces_btn = wx.Button(self, label=_("Edit Workspace"))
		s_helper.addItem(self.editWorkspaces_btn, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()

		self.add_btn.Bind(wx.EVT_BUTTON, self._on_add_folder_or_paths)
		self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove_folder)
		self.save_btn.Bind(wx.EVT_BUTTON, self._on_save)
		self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
		self.show_paths_check.Bind(wx.EVT_CHECKBOX, self._on_toggle_show_paths)
		self.paste_text.Bind(wx.EVT_TEXT, self._on_paste_text_changed)
		self.editWorkspaces_btn.Bind(wx.EVT_BUTTON, self._on_edit_workspaces)
		self._refreshPathsList()
		self.name_text.SetFocus()

	def _displayLabelFor(self, path):
		if self.show_paths_check.GetValue():
			return path
		trimmedPath = path.rstrip("\\/")
		return os.path.basename(trimmedPath) or path

	def _refreshPathsList(self):
		self.paths_list.Set([self._displayLabelFor(p) for p in self.paths])
		# Naming a workspace only makes sense once it actually has folders
		# in it, so the name field stays out of the tab order until the
		# first folder is added - matters most for the double-tap "add
		# folder" flow, which can pop this dialog up with zero folders in
		# it if triggered outside Explorer.
		hasPaths = bool(self.paths)
		self.name_label.Show(hasPaths)
		self.name_text.Show(hasPaths)
		self.Layout()
		self.Fit()

	def _on_add_folder_or_paths(self, event):
		pastedText = self.paste_text.GetValue().strip()
		if pastedText:
			candidatePaths = [line.strip().strip('"') for line in pastedText.splitlines() if line.strip()]
			addedCount = 0
			for candidatePath in candidatePaths:
				if os.path.isdir(candidatePath) and candidatePath not in self.paths:
					self.paths.append(candidatePath)
					addedCount += 1
			self.paste_text.SetValue("")
			self._refreshPathsList()
			if addedCount:
				ui.message(_("Added {count} folders").format(count=addedCount))
			else:
				ui.message(_("No valid folder paths found"))
			return
		dirDialog = wx.DirDialog(self, _("Select Folder to Add"), style=wx.DD_DEFAULT_STYLE)
		if dirDialog.ShowModal() == wx.ID_OK:
			selectedPath = dirDialog.GetPath()
			if selectedPath not in self.paths:
				self.paths.append(selectedPath)
				self._refreshPathsList()
		dirDialog.Destroy()

	def _on_paste_text_changed(self, event):
		hasText = bool(self.paste_text.GetValue().strip())
		self.add_btn.SetLabel(_("Add Path") if hasText else _("Add Folder..."))
		event.Skip()

	def _on_toggle_show_paths(self, event):
		self._refreshPathsList()

	def _on_edit_workspaces(self, event):
		if not self.workspaceManager:
			ui.message(_("Workspace manager not available"))
			return
		listDialog = WorkspaceListDialog(self, self.workspaceManager)
		try:
			listDialog.ShowModal()
		finally:
			listDialog.Destroy()

	def _on_remove_folder(self, event):
		selectionIndex = self.paths_list.GetSelection()
		if selectionIndex == wx.NOT_FOUND:
			ui.message(_("No folder selected"))
			return
		del self.paths[selectionIndex]
		self._refreshPathsList()

	def _on_save(self, event):
		name = self.name_text.GetValue().strip()
		if not name:
			ui.message(_("Enter a workspace name"))
			self.name_text.SetFocus()
			return
		if not self.paths:
			ui.message(_("Add at least one folder to this workspace"))
			return
		self.workspaceName = name
		self.EndModal(wx.ID_OK)

	def _on_cancel(self, event):
		self.EndModal(wx.ID_CANCEL)

	def _on_close(self, event):
		self.EndModal(wx.ID_CANCEL)


class WorkspaceListDialog(wx.Dialog):
	"""Accessible list of saved workspaces with Load/Delete actions."""

	def __init__(self, parent, workspaceManager):
		super().__init__(parent, title=_("Workspace Manager"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.workspaceManager = workspaceManager
		self._init_ui()
		self.Bind(wx.EVT_CLOSE, self._on_close)

	def _init_ui(self):
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		label = wx.StaticText(self, label=_("Saved workspaces (right-click or press the Menu key for pin/reorder/clear options):"))
		s_helper.addItem(label)

		self.workspaceNames = []
		self.workspace_list = wx.ListBox(self, choices=[], size=(420, 200))
		s_helper.addItem(self.workspace_list, flag=wx.EXPAND, proportion=1)

		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self.load_btn = wx.Button(self, label=_("Load Workspace"))
		btn_sizer.Add(self.load_btn, 0, wx.ALL, 5)
		self.edit_btn = wx.Button(self, label=_("Edit Workspace"))
		btn_sizer.Add(self.edit_btn, 0, wx.ALL, 5)
		self.delete_btn = wx.Button(self, label=_("Delete Workspace"))
		btn_sizer.Add(self.delete_btn, 0, wx.ALL, 5)
		self.close_btn = wx.Button(self, wx.ID_CANCEL, label=_("Close"))
		btn_sizer.Add(self.close_btn, 0, wx.ALL, 5)
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()

		self.load_btn.Bind(wx.EVT_BUTTON, self._on_load)
		self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
		self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
		self.close_btn.Bind(wx.EVT_BUTTON, self._on_close_button)
		self.workspace_list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
		self._refreshList()
		self.workspace_list.SetFocus()

	def _refreshList(self, selectName=None):
		self.workspaceNames = self.workspaceManager.getOrderedWorkspaceNames()
		if self.workspaceNames:
			labels = [
				_("{name} (pinned)").format(name=name) if self.workspaceManager.isPinned(name) else name
				for name in self.workspaceNames
			]
		else:
			labels = [_("No workspaces saved yet")]
		self.workspace_list.Set(labels)
		if selectName and selectName in self.workspaceNames:
			self.workspace_list.SetSelection(self.workspaceNames.index(selectName))
		elif self.workspaceNames:
			self.workspace_list.SetSelection(0)

	def _selectedName(self):
		if not self.workspaceNames:
			ui.message(_("No workspaces saved yet"))
			return None
		selectionIndex = self.workspace_list.GetSelection()
		if selectionIndex == wx.NOT_FOUND:
			ui.message(_("No workspace selected"))
			return None
		return self.workspaceNames[selectionIndex]

	def _on_context_menu(self, event):
		name = self._selectedName()
		if not name:
			return
		menu = wx.Menu()
		pinLabel = _("Unpin from Top") if self.workspaceManager.isPinned(name) else _("Pin to Top")
		pinItem = menu.Append(wx.ID_ANY, pinLabel)
		moveUpItem = menu.Append(wx.ID_ANY, _("Move Up"))
		moveDownItem = menu.Append(wx.ID_ANY, _("Move Down"))
		menu.AppendSeparator()
		deleteItem = menu.Append(wx.ID_ANY, _("Delete"))
		clearAllItem = menu.Append(wx.ID_ANY, _("Clear All Workspaces"))
		self.Bind(wx.EVT_MENU, lambda evt, n=name: self._on_toggle_pin(n), pinItem)
		self.Bind(wx.EVT_MENU, lambda evt, n=name: self._on_move(n, -1), moveUpItem)
		self.Bind(wx.EVT_MENU, lambda evt, n=name: self._on_move(n, 1), moveDownItem)
		self.Bind(wx.EVT_MENU, lambda evt: self._on_delete(None), deleteItem)
		self.Bind(wx.EVT_MENU, lambda evt: self._on_clear_all(), clearAllItem)
		self.PopupMenu(menu)
		menu.Destroy()

	def _on_toggle_pin(self, name):
		self.workspaceManager.togglePinned(name)
		self._refreshList(selectName=name)
		ui.message(_("Unpinned: {0}").format(name) if not self.workspaceManager.isPinned(name) else _("Pinned to top: {0}").format(name))

	def _on_move(self, name, delta):
		self.workspaceManager.moveWorkspace(name, delta)
		self._refreshList(selectName=name)

	def _on_clear_all(self):
		confirm = wx.MessageBox(
			_("Delete all saved workspaces? This cannot be undone."),
			_("Clear All Workspaces"),
			wx.YES_NO | wx.ICON_WARNING,
			self
		)
		if confirm != wx.YES:
			return
		self.workspaceManager.clearAllWorkspaces()
		self._refreshList()
		ui.message(_("All workspaces cleared"))

	def _on_load(self, event):
		name = self._selectedName()
		if not name:
			return
		self.workspaceManager.loadWorkspace(name)
		self.EndModal(wx.ID_OK)

	def _on_edit(self, event):
		name = self._selectedName()
		if not name:
			return
		workspaces = self.workspaceManager.getWorkspaces()
		existingPaths = workspaces.get(name, [])

		editDialog = WorkspaceEditDialog(self, existingPaths, workspaceManager=self.workspaceManager)
		editDialog.name_text.SetValue(name)
		try:
			if editDialog.ShowModal() == wx.ID_OK:
				newName = editDialog.workspaceName
				workspaces = self.workspaceManager.getWorkspaces()
				if newName != name:
					workspaces.pop(name, None)
				workspaces[newName] = editDialog.paths
				self.workspaceManager._saveWorkspaces(workspaces)
				ui.message(_("Workspace updated: {0}").format(newName))
				self._refreshList(selectName=newName)
		finally:
			editDialog.Destroy()

	def _on_delete(self, event):
		name = self._selectedName()
		if not name:
			return
		self.workspaceManager.deleteWorkspace(name)
		self._refreshList()
		ui.message(_("Workspace deleted: {0}").format(name))

	def _on_close_button(self, event):
		self.EndModal(wx.ID_CANCEL)

	def _on_close(self, event):
		self.EndModal(wx.ID_CANCEL)


class WorkspaceManager:
	"""Lets the user save a named group of frequently used paths (Projects,
	Source, Build, Downloads, etc.) and reopen every one of them at once,
	each in its own Explorer window."""

	def __init__(self, plugin):
		self.plugin = plugin
		self.dialog = None
		# The WorkspaceEditDialog currently open for an in-progress "save
		# current selection as a workspace" session, if any - lets repeated
		# NVDA+shift+m double-taps (each adding one more folder) target the
		# same dialog instead of popping up a new one every time.
		self._activeSaveDialog = None
		# workspaceName -> list of hwnds this manager itself opened for it,
		# so a repeat Load can close exactly those windows (toggle) rather
		# than reopening folders that are already open, and never touches
		# a window the workspace didn't open itself.
		self._lastLoadedWorkspaceWindows = {}
		# Guards against a rapid double-invocation of the same workspace
		# (e.g. an accidental double click) spawning two concurrent load
		# operations, which would multiply how many folders end up opened.
		self._workspaceLoadInProgress = set()

	def cleanup(self):
		if self.dialog:
			try:
				self.dialog.Destroy()
			except RuntimeError:
				pass
			self.dialog = None
		self._activeSaveDialog = None

	def _loadRaw(self):
		# On-disk shape: {"meta": {"order": [...], "pinned": [...]}, "workspaces": {name: [paths]}}.
		# Older installs only ever wrote the bare {name: [paths]} dict, so
		# that shape is treated as a migration source rather than an error -
		# it becomes the "workspaces" value with alphabetical order and no
		# pins, and gets written back out in the new shape on next save.
		emptyRaw = {"meta": {"order": [], "pinned": []}, "workspaces": {}}
		if not os.path.exists(WORKSPACES_FILE):
			return emptyRaw
		try:
			with open(WORKSPACES_FILE, "r", encoding="utf-8") as f:
				data = json.load(f)
		except (OSError, ValueError) as e:
			log.error(f"Error loading workspaces: {e}")
			return emptyRaw
		if isinstance(data, dict) and isinstance(data.get("workspaces"), dict):
			meta = data.get("meta", {})
			return {
				"meta": {
					"order": list(meta.get("order", [])),
					"pinned": list(meta.get("pinned", [])),
				},
				"workspaces": data["workspaces"],
			}
		if isinstance(data, dict):
			return {"meta": {"order": sorted(data.keys()), "pinned": []}, "workspaces": data}
		return emptyRaw

	def _saveRaw(self, raw):
		try:
			if not os.path.exists(CONFIG_DIR):
				os.makedirs(CONFIG_DIR)
			with open(WORKSPACES_FILE, "w", encoding="utf-8") as f:
				json.dump(raw, f, indent=2, ensure_ascii=False)
		except OSError as e:
			log.error(f"Error saving workspaces: {e}")

	def getWorkspaces(self):
		return self._loadRaw()["workspaces"]

	def _saveWorkspaces(self, workspaces):
		# Back-compat shim for callers (WorkspaceEditDialog's save flow,
		# WorkspaceListDialog's rename flow) that only ever hand back the
		# flat {name: [paths]} dict - folds it back into the ordered
		# structure on disk instead of changing their signatures.
		raw = self._loadRaw()
		knownNames = list(raw["meta"]["order"])
		for name in workspaces:
			if name not in knownNames:
				knownNames.append(name)
		raw["meta"]["order"] = [n for n in knownNames if n in workspaces]
		raw["meta"]["pinned"] = [n for n in raw["meta"]["pinned"] if n in workspaces]
		raw["workspaces"] = workspaces
		self._saveRaw(raw)

	def getOrderedWorkspaceNames(self):
		raw = self._loadRaw()
		names = set(raw["workspaces"].keys())
		order = [n for n in raw["meta"]["order"] if n in names]
		order += sorted(n for n in names if n not in order)
		pinned = [n for n in raw["meta"]["pinned"] if n in order]
		unpinned = [n for n in order if n not in pinned]
		return pinned + unpinned

	def isPinned(self, name):
		return name in self._loadRaw()["meta"]["pinned"]

	def togglePinned(self, name):
		raw = self._loadRaw()
		pinned = raw["meta"]["pinned"]
		if name in pinned:
			pinned.remove(name)
		else:
			pinned.insert(0, name)
		self._saveRaw(raw)

	def moveWorkspace(self, name, delta):
		raw = self._loadRaw()
		order = [n for n in raw["meta"]["order"] if n in raw["workspaces"]]
		for n in raw["workspaces"]:
			if n not in order:
				order.append(n)
		if name not in order:
			return
		currentIndex = order.index(name)
		newIndex = currentIndex + delta
		if newIndex < 0 or newIndex >= len(order):
			return
		order[currentIndex], order[newIndex] = order[newIndex], order[currentIndex]
		raw["meta"]["order"] = order
		self._saveRaw(raw)

	def clearAllWorkspaces(self):
		self._saveRaw({"meta": {"order": [], "pinned": []}, "workspaces": {}})

	def deleteWorkspace(self, name):
		workspaces = self.getWorkspaces()
		if name in workspaces:
			del workspaces[name]
			self._saveWorkspaces(workspaces)

	# Standard WM_CLOSE - used to close windows this workspace itself
	# opened, never ones it merely found already open.
	_WM_CLOSE = 0x0010

	def loadWorkspace(self, name):
		workspaces = self.getWorkspaces()
		paths = workspaces.get(name)
		if not paths:
			ui.message(_("Workspace not found: {0}").format(name))
			return
		if name in self._workspaceLoadInProgress:
			log.debug(f"xPlorer: ignoring overlapping load request for workspace '{name}'")
			return
		self._workspaceLoadInProgress.add(name)
		threading.Thread(target=self._loadWorkspaceWorker, args=(name, paths), daemon=True).start()

	def _getWindowFolderPath(self, window):
		# Document.Folder.Self.Path is a chain of three COM property
		# lookups, any of which can fail for window types that don't fully
		# support it (search results, libraries, etc.) - LocationURL is a
		# simpler, more universally supported property on the same Window
		# object, used here as a fallback rather than a replacement, since
		# it needs converting from a file:// URL back to a plain path.
		try:
			path = window.Document.Folder.Self.Path
			if path:
				return path
		except (COMError, AttributeError, OSError):
			pass
		try:
			locationURL = window.LocationURL
		except (COMError, AttributeError, OSError):
			return None
		if not locationURL or not locationURL.lower().startswith("file:///"):
			return None
		try:
			parsedPath = unquote(urlparse(locationURL).path)
		except ValueError:
			return None
		if parsedPath.startswith("/") and len(parsedPath) > 2 and parsedPath[2] == ":":
			parsedPath = parsedPath[1:]
		return parsedPath.replace("/", "\\")

	def _enumerateOpenExplorerFolders(self, shellApp):
		"""Returns {normalized folder path: hwnd} for every currently open
		Explorer window, and the raw set of all live hwnds."""
		openFolderPaths = {}
		liveHwnds = set()
		try:
			windows = shellApp.Windows()
			try:
				windowCount = windows.Count
			except (COMError, AttributeError, OSError):
				windowCount = "?"
			log.debug(f"xPlorer: workspace scan - Shell.Application reports {windowCount} open windows")
			for window in windows:
				try:
					hwnd = window.HWND
				except (COMError, AttributeError, OSError) as e:
					log.debug(f"xPlorer: workspace scan - could not read a window's HWND: {e}")
					continue
				liveHwnds.add(hwnd)
				folderPath = self._getWindowFolderPath(window)
				if folderPath:
					normalizedPath = os.path.normcase(os.path.normpath(folderPath))
					openFolderPaths[normalizedPath] = hwnd
					log.debug(f"xPlorer: workspace scan - hwnd={hwnd} path={folderPath!r} normalized={normalizedPath!r}")
				else:
					log.debug(f"xPlorer: workspace scan - hwnd={hwnd} could not resolve a folder path (not a filesystem folder window?)")
		except COMError as e:
			log.debug(f"xPlorer: could not enumerate open Explorer windows: {e}")
		return openFolderPaths, liveHwnds

	def _loadWorkspaceWorker(self, name, paths):
		try:
			comtypes.CoInitialize()
		except OSError:
			pass
		try:
			shellApp = comtypes.client.CreateObject("Shell.Application")

			# Toggle: if the windows this workspace opened last time are
			# still open, Load again closes them instead of reopening -
			# a folder the user opened themselves independently is never
			# touched, only ones this manager itself launched.
			previouslyOpenedHwnds = self._lastLoadedWorkspaceWindows.get(name, [])
			log.debug(f"xPlorer: workspace load '{name}' - previously tracked hwnds: {previouslyOpenedHwnds}")
			if previouslyOpenedHwnds:
				_openFolderPaths, liveHwnds = self._enumerateOpenExplorerFolders(shellApp)
				stillOpenHwnds = [h for h in previouslyOpenedHwnds if h in liveHwnds]
				log.debug(f"xPlorer: workspace load '{name}' - still-open tracked hwnds: {stillOpenHwnds}")
				if stillOpenHwnds:
					closedCount = 0
					for hwnd in stillOpenHwnds:
						try:
							ctypes.windll.user32.PostMessageW(hwnd, self._WM_CLOSE, 0, 0)
							closedCount += 1
						except OSError as e:
							log.debug(f"xPlorer: could not close workspace window {hwnd}: {e}")
					self._lastLoadedWorkspaceWindows.pop(name, None)
					wx.CallAfter(ui.message, _("Closed {count} folders from workspace {name}").format(count=closedCount, name=name))
					return
				# None of them are still open - fall through to a normal load.
				self._lastLoadedWorkspaceWindows.pop(name, None)

			openFolderPaths, _liveHwnds = self._enumerateOpenExplorerFolders(shellApp)

			openedHwnds = []
			openedCount = 0
			reusedCount = 0
			for path in paths:
				if not os.path.isdir(path):
					continue
				normalizedPath = os.path.normcase(os.path.normpath(path))
				existingHwnd = openFolderPaths.get(normalizedPath)
				log.debug(f"xPlorer: workspace load '{name}' - target={path!r} normalized={normalizedPath!r} alreadyOpenHwnd={existingHwnd}")
				if existingHwnd:
					reusedCount += 1
					openedHwnds.append(existingHwnd)
					try:
						ctypes.windll.user32.SetForegroundWindow(existingHwnd)
					except OSError as e:
						log.debug(f"xPlorer: could not foreground already-open workspace folder {path}: {e}")
					continue
				try:
					launchExplorer([path])
					openedCount += 1
				except OSError as e:
					log.error(f"Error opening workspace folder {path}: {e}")

			if openedCount or reusedCount:
				wx.CallAfter(
					ui.message,
					_("Loaded workspace {name}: opened {opened}, already open {reused}").format(
						name=name, opened=openedCount, reused=reusedCount
					)
				)
			else:
				wx.CallAfter(ui.message, _("None of the folders in workspace {0} could be found").format(name))

			# explorer.exe hands off to an existing host process
			# asynchronously, so freshly spawned windows' real hwnds aren't
			# known yet - captured shortly after instead, for next time's
			# close-toggle to be able to find them.
			core.callLater(
				1500,
				lambda: threading.Thread(
					target=self._captureWorkspaceWindowHwnds, args=(name, paths, openedHwnds), daemon=True
				).start()
			)
		except COMError as e:
			log.debug(f"xPlorer: loadWorkspace COM error for {name}: {e}")
		except Exception as e:
			log.error(f"Error in loadWorkspace worker for {name}: {e}")
		finally:
			self._workspaceLoadInProgress.discard(name)
			try:
				comtypes.CoUninitialize()
			except OSError:
				pass

	def _captureWorkspaceWindowHwnds(self, name, paths, alreadyKnownHwnds):
		try:
			comtypes.CoInitialize()
		except OSError:
			pass
		try:
			normalizedTargets = {os.path.normcase(os.path.normpath(p)) for p in paths if os.path.isdir(p)}
			hwnds = list(alreadyKnownHwnds)
			try:
				shellApp = comtypes.client.CreateObject("Shell.Application")
				for window in shellApp.Windows():
					try:
						hwnd = window.HWND
					except (COMError, AttributeError, OSError):
						continue
					folderPath = self._getWindowFolderPath(window)
					if folderPath and hwnd not in hwnds and os.path.normcase(os.path.normpath(folderPath)) in normalizedTargets:
						hwnds.append(hwnd)
			except COMError as e:
				log.debug(f"xPlorer: could not capture workspace window handles for {name}: {e}")
			log.debug(f"xPlorer: workspace '{name}' - captured hwnds for close-toggle: {hwnds}")
			self._lastLoadedWorkspaceWindows[name] = hwnds
		finally:
			try:
				comtypes.CoUninitialize()
			except OSError:
				pass

	def _runSaveEditDialog(self, initialPaths):
		def do_show():
			dialog = WorkspaceEditDialog(gui.mainFrame, initialPaths, workspaceManager=self)
			self._activeSaveDialog = dialog
			gui.mainFrame.prePopup()
			try:
				if dialog.ShowModal() == wx.ID_OK:
					workspaces = self.getWorkspaces()
					workspaces[dialog.workspaceName] = dialog.paths
					self._saveWorkspaces(workspaces)
					ui.message(_("Workspace saved: {0}").format(dialog.workspaceName))
			finally:
				gui.mainFrame.postPopup()
				self._activeSaveDialog = None
				dialog.Destroy()

		wx.CallAfter(do_show)

	def showSaveDialog(self):
		def handlePath(currentPath):
			self._runSaveEditDialog([currentPath] if currentPath else [])

		self.plugin._getCurrentPathFromExplorerAsync(handlePath)

	def addFolderToWorkspaceSession(self, folderPath):
		# Used by NVDA+shift+m's double-tap: if a Save-as-Workspace dialog
		# from an earlier tap in this same session is still open, just add
		# to it and announce the new folder's name; otherwise start a fresh
		# session with this one folder already in it.
		trimmedPath = folderPath.rstrip("\\/")
		displayName = os.path.basename(trimmedPath) or folderPath

		def do_add():
			if self._activeSaveDialog:
				try:
					if folderPath not in self._activeSaveDialog.paths:
						self._activeSaveDialog.paths.append(folderPath)
						self._activeSaveDialog._refreshPathsList()
						ui.message(_("Added {name}").format(name=displayName))
					else:
						ui.message(_("Already added: {name}").format(name=displayName))
					self._activeSaveDialog.Raise()
					return
				except RuntimeError:
					self._activeSaveDialog = None
			ui.message(_("Added {name}").format(name=displayName))
			self._runSaveEditDialog([folderPath])

		wx.CallAfter(do_add)

	def showWorkspaceList(self):
		def do_show():
			self.dialog = WorkspaceListDialog(gui.mainFrame, self)
			gui.mainFrame.prePopup()
			try:
				self.dialog.ShowModal()
			finally:
				gui.mainFrame.postPopup()
				self.dialog.Destroy()
				self.dialog = None

		wx.CallAfter(do_show)



