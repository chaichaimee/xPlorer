# fileOperations.py

import ui
import api
import os
import json
import wx
import gui
import gui.guiHelper
import subprocess
import time
import threading
import ctypes
from logHandler import log
import addonHandler
import tones
import core
import speech
import winUser
from speech.extensions import filter_speechSequence
from speech.commands import BreakCommand
from .folderTools import CONFIG_DIR
from .isoBuilder import buildIso, IsoError, IsoCancelled

addonHandler.initTranslation()

class RenameDialog(wx.Dialog):
	def __init__(self, parent, file_name):
		super().__init__(parent, title="")
		self.file_name = file_name
		self.new_name = None
		self.name_ctrl = None
		self.ext_ctrl = None
		self._init_ui()
		
	def _init_ui(self):
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		
		name, ext = os.path.splitext(self.file_name)
		
		self.name_ctrl = s_helper.addItem(wx.TextCtrl(self, value=name))
		self.name_ctrl.SelectAll()
		
		if ext and ext.startswith('.'):
			ext = ext[1:]
		self.ext_ctrl = s_helper.addItem(wx.TextCtrl(self, value=ext))
		
		btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)
		
		self.SetSizer(main_sizer)
		main_sizer.Fit(self)
		self.CentreOnScreen()
		self.name_ctrl.SetFocus()
		
		self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
		self.Bind(wx.EVT_TEXT_ENTER, self._on_ok)
		self.Bind(wx.EVT_CLOSE, self._on_close)
		
	def _on_ok(self, event):
		name = self.name_ctrl.Value.strip()
		ext = self.ext_ctrl.Value.strip()
		
		if not name:
			ui.message(_("File name cannot be empty"))
			return
			
		if ext:
			ext = "." + ext
		self.new_name = name + ext
		self.EndModal(wx.ID_OK)
		
	def _on_cancel(self, event):
		self.EndModal(wx.ID_CANCEL)
		
	def _on_close(self, event):
		self.EndModal(wx.ID_CANCEL)

_SIZE_LIST_SETTINGS_FILE = os.path.join(CONFIG_DIR, "folderSizeList.json")

_SIZE_LIST_DEFAULTS = {
	"displayFormat": "nameFirst",
	"sortOrder": "nameAsc",
	"showItems": "all",
	"foldersFirst": True,
	"includeSubfolders": False,
}

_SIZE_LIST_CHOICES = {
	"displayFormat": ("nameFirst", "sizeFirst"),
	"sortOrder": ("nameAsc", "nameDesc", "sizeDesc", "sizeAsc"),
	"showItems": ("all", "foldersOnly", "filesOnly"),
}


class _ScanCancelled(Exception):
	pass


def loadSizeListSettings():
	settings = dict(_SIZE_LIST_DEFAULTS)
	try:
		with open(_SIZE_LIST_SETTINGS_FILE, "r", encoding="utf-8") as f:
			stored = json.load(f)
	except FileNotFoundError:
		return settings
	except (OSError, ValueError) as e:
		log.error(f"xPlorer: could not read folder size list settings: {e}")
		return settings
	if not isinstance(stored, dict):
		return settings
	for key, allowedValues in _SIZE_LIST_CHOICES.items():
		if stored.get(key) in allowedValues:
			settings[key] = stored[key]
	for key in ("foldersFirst", "includeSubfolders"):
		if isinstance(stored.get(key), bool):
			settings[key] = stored[key]
	return settings


def saveSizeListSettings(settings):
	tmpPath = _SIZE_LIST_SETTINGS_FILE + ".tmp"
	backupPath = _SIZE_LIST_SETTINGS_FILE + ".bak"
	try:
		os.makedirs(CONFIG_DIR, exist_ok=True)
		if os.path.exists(_SIZE_LIST_SETTINGS_FILE):
			try:
				with open(_SIZE_LIST_SETTINGS_FILE, "rb") as src:
					previousData = src.read()
				with open(backupPath, "wb") as dst:
					dst.write(previousData)
			except OSError as e:
				log.debug(f"xPlorer: could not refresh folder size list settings backup: {e}")
		with open(tmpPath, "w", encoding="utf-8") as f:
			json.dump(settings, f, indent=2)
			f.flush()
			os.fsync(f.fileno())
		os.replace(tmpPath, _SIZE_LIST_SETTINGS_FILE)
		return True
	except OSError as e:
		log.error(f"xPlorer: could not save folder size list settings: {e}")
		return False


def _formatByteSize(sizeInBytes):
	if sizeInBytes < 1024:
		return f"{sizeInBytes} bytes"
	if sizeInBytes < 1024 * 1024:
		return f"{sizeInBytes / 1024:.2f} KB"
	if sizeInBytes < 1024 * 1024 * 1024:
		return f"{sizeInBytes / (1024 * 1024):.2f} MB"
	return f"{sizeInBytes / (1024 * 1024 * 1024):.2f} GB"


def _walkFolderSize(folderPath, includeSubfolders, shouldStop):
	totalSize = 0
	pendingDirs = [folderPath]
	while pendingDirs:
		currentDir = pendingDirs.pop()
		try:
			with os.scandir(currentDir) as entries:
				for entry in entries:
					if shouldStop():
						raise _ScanCancelled()
					try:
						if entry.is_dir(follow_symlinks=False):
							if includeSubfolders:
								pendingDirs.append(entry.path)
						else:
							totalSize += entry.stat(follow_symlinks=False).st_size
					except OSError:
						continue
		except OSError:
			if currentDir == folderPath:
				return None
	return totalSize


def scanFolderEntries(folderPath, includeSubfolders, shouldStop):
	scanned = []
	with os.scandir(folderPath) as entries:
		for entry in entries:
			if shouldStop():
				raise _ScanCancelled()
			isDir = False
			try:
				isDir = entry.is_dir(follow_symlinks=False)
				if isDir:
					size = _walkFolderSize(entry.path, includeSubfolders, shouldStop)
				else:
					size = entry.stat(follow_symlinks=False).st_size
			except OSError:
				size = None
			scanned.append({"name": entry.name, "isDir": isDir, "size": size})
	return scanned


def filterSizeEntries(entries, showItems):
	if showItems == "foldersOnly":
		return [e for e in entries if e["isDir"]]
	if showItems == "filesOnly":
		return [e for e in entries if not e["isDir"]]
	return list(entries)


def sortSizeEntries(entries, sortOrder, foldersFirst):
	ordered = sorted(entries, key=lambda e: e["name"].casefold())
	if sortOrder == "nameDesc":
		ordered.reverse()
	elif sortOrder == "sizeDesc":
		ordered.sort(key=lambda e: e["size"] or 0, reverse=True)
	elif sortOrder == "sizeAsc":
		ordered.sort(key=lambda e: e["size"] or 0)
	if foldersFirst:
		ordered.sort(key=lambda e: not e["isDir"])
	return ordered


def formatSizeEntry(entry, displayFormat):
	if entry["size"] is None:
		sizeText = _("no access")
	else:
		sizeText = _formatByteSize(entry["size"])
	nameText = entry["name"]
	if entry["isDir"]:
		nameText = _("{name}, folder").format(name=entry["name"])
	if displayFormat == "sizeFirst":
		return f"{sizeText}, {nameText}"
	return f"{nameText}, {sizeText}"


def buildSizeListSummary(entries):
	folderCount = sum(1 for e in entries if e["isDir"])
	fileCount = len(entries) - folderCount
	totalSize = sum(e["size"] or 0 for e in entries)
	return _("Folders: {folders}, files: {files}, total size: {size}").format(
		folders=folderCount, files=fileCount, size=_formatByteSize(totalSize)
	)


class FolderSizeSettingsDialog(wx.Dialog):
	def __init__(self, parent, settings, onApply):
		super().__init__(parent, title=_("Current folder size list settings"))
		self._onApply = onApply
		self._formatChoices = (
			("nameFirst", _("Name followed by size")),
			("sizeFirst", _("Size followed by name")),
		)
		self._sortChoices = (
			("nameAsc", _("Name, A to Z")),
			("nameDesc", _("Name, Z to A")),
			("sizeDesc", _("Size, largest to smallest")),
			("sizeAsc", _("Size, smallest to largest")),
		)
		self._showChoices = (
			("all", _("Folders and files")),
			("foldersOnly", _("Folders only")),
			("filesOnly", _("Files only")),
		)

		sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self._formatBox = sHelper.addItem(wx.RadioBox(
			self, label=_("Display format"),
			choices=[label for _key, label in self._formatChoices],
			majorDimension=1, style=wx.RA_SPECIFY_COLS
		))
		self._sortBox = sHelper.addItem(wx.RadioBox(
			self, label=_("Sort order"),
			choices=[label for _key, label in self._sortChoices],
			majorDimension=1, style=wx.RA_SPECIFY_COLS
		))
		self._showBox = sHelper.addItem(wx.RadioBox(
			self, label=_("Show"),
			choices=[label for _key, label in self._showChoices],
			majorDimension=1, style=wx.RA_SPECIFY_COLS
		))
		self._foldersFirstBox = sHelper.addItem(wx.CheckBox(self, label=_("List folders before files")))
		self._subfoldersBox = sHelper.addItem(wx.CheckBox(
			self, label=_("Include the contents of subfolders in folder sizes (slower)")
		))

		self._formatBox.SetSelection(self._indexOf(self._formatChoices, settings["displayFormat"]))
		self._sortBox.SetSelection(self._indexOf(self._sortChoices, settings["sortOrder"]))
		self._showBox.SetSelection(self._indexOf(self._showChoices, settings["showItems"]))
		self._foldersFirstBox.SetValue(settings["foldersFirst"])
		self._subfoldersBox.SetValue(settings["includeSubfolders"])

		buttonRow = wx.BoxSizer(wx.HORIZONTAL)
		okButton = wx.Button(self, wx.ID_OK, label=_("OK"))
		okButton.SetDefault()
		cancelButton = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))
		applyButton = wx.Button(self, wx.ID_APPLY, label=_("Apply"))
		for button in (okButton, cancelButton, applyButton):
			buttonRow.Add(button, flag=wx.ALL, border=5)
		sHelper.addItem(buttonRow, flag=wx.ALIGN_CENTER)

		self.SetSizer(sHelper.sizer)
		sHelper.sizer.Fit(self)
		self.CentreOnParent()
		self._formatBox.SetFocus()

		self.Bind(wx.EVT_BUTTON, self._onOk, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self._onApplyClicked, id=wx.ID_APPLY)

	@staticmethod
	def _indexOf(choices, key):
		for index, (choiceKey, _label) in enumerate(choices):
			if choiceKey == key:
				return index
		return 0

	def _collect(self):
		return {
			"displayFormat": self._formatChoices[self._formatBox.GetSelection()][0],
			"sortOrder": self._sortChoices[self._sortBox.GetSelection()][0],
			"showItems": self._showChoices[self._showBox.GetSelection()][0],
			"foldersFirst": self._foldersFirstBox.GetValue(),
			"includeSubfolders": self._subfoldersBox.GetValue(),
		}

	def _onOk(self, event):
		self._onApply(self._collect())
		self.EndModal(wx.ID_OK)

	def _onApplyClicked(self, event):
		self._onApply(self._collect())
		ui.message(_("Applied"))


class FolderSizeListDialog(wx.Dialog):
	def __init__(self, parent, folderPath):
		folderName = os.path.basename(folderPath.rstrip("\\")) or folderPath
		super().__init__(
			parent,
			title=_("Current folder size list - {name}").format(name=folderName),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP
		)
		self._folderPath = folderPath
		self._settings = loadSizeListSettings()
		self._entries = []
		self._scanGeneration = 0
		self._stopEvent = threading.Event()
		self._shutDown = False

		sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self._listBox = sHelper.addLabeledControl(
			_("Items"), wx.ListBox, choices=[], style=wx.LB_SINGLE, size=(520, 320)
		)
		closeButton = wx.Button(self, wx.ID_CLOSE, label=_("Close"))
		sHelper.addItem(closeButton, flag=wx.ALIGN_CENTER)
		self.SetSizer(sHelper.sizer)
		sHelper.sizer.Fit(self)
		self.SetEscapeId(wx.ID_CLOSE)
		self.CentreOnScreen()

		self._busyTimer = wx.Timer(self)
		self.Bind(wx.EVT_TIMER, self._onBusyTick, self._busyTimer)
		self.Bind(wx.EVT_BUTTON, self._onCloseClicked, id=wx.ID_CLOSE)
		self.Bind(wx.EVT_CLOSE, self._onCloseClicked)
		self._listBox.Bind(wx.EVT_CONTEXT_MENU, self._onListContextMenu)
		self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)

		self._listBox.SetFocus()
		self._startScan()

	def shutdown(self):
		self._shutDown = True
		self._stopEvent.set()
		if self._busyTimer.IsRunning():
			self._busyTimer.Stop()

	def _onCloseClicked(self, event):
		self.EndModal(wx.ID_CLOSE)

	def _onCharHook(self, event):
		keyCode = event.GetKeyCode()
		if keyCode == wx.WXK_ESCAPE:
			self.EndModal(wx.ID_CLOSE)
			return
		if keyCode == wx.WXK_F5:
			self._startScan()
			return
		event.Skip()

	def _onBusyTick(self, event):
		tones.beep(440, 100)

	def _startScan(self):
		self._stopEvent.set()
		stopEvent = threading.Event()
		self._stopEvent = stopEvent
		self._scanGeneration += 1
		generation = self._scanGeneration
		includeSubfolders = self._settings["includeSubfolders"]
		folderPath = self._folderPath

		self._listBox.Clear()
		self._listBox.Append(_("Scanning, please wait"))
		self._listBox.SetSelection(0)
		if self._busyTimer.IsRunning():
			self._busyTimer.Stop()
		self._busyTimer.Start(2000)

		def worker():
			try:
				scanned = scanFolderEntries(folderPath, includeSubfolders, stopEvent.is_set)
			except _ScanCancelled:
				return
			except OSError as e:
				log.error(f"xPlorer: folder size scan failed for {folderPath}: {e}")
				wx.CallAfter(self._onScanFailed, generation)
				return
			wx.CallAfter(self._onScanFinished, generation, scanned)

		threading.Thread(target=worker, daemon=True).start()

	def _onScanFinished(self, generation, scanned):
		if self._shutDown or generation != self._scanGeneration:
			return
		self._busyTimer.Stop()
		self._entries = scanned
		self._refreshList(announceSummary=True)

	def _onScanFailed(self, generation):
		if self._shutDown or generation != self._scanGeneration:
			return
		self._busyTimer.Stop()
		self._entries = []
		self._listBox.Clear()
		self._listBox.Append(_("Could not read this folder"))
		self._listBox.SetSelection(0)
		ui.message(_("Could not read this folder"))

	def _refreshList(self, announceSummary):
		visibleEntries = filterSizeEntries(self._entries, self._settings["showItems"])
		orderedEntries = sortSizeEntries(
			visibleEntries, self._settings["sortOrder"], self._settings["foldersFirst"]
		)
		self._listBox.Clear()
		if orderedEntries:
			self._listBox.AppendItems([
				formatSizeEntry(e, self._settings["displayFormat"]) for e in orderedEntries
			])
		else:
			self._listBox.Append(_("No items to show"))
		self._listBox.SetSelection(0)
		if announceSummary:
			ui.message(buildSizeListSummary(self._entries))

	def _onListContextMenu(self, event):
		menu = wx.Menu()
		settingsItem = menu.Append(wx.ID_ANY, _("Settings..."))
		subfoldersItem = menu.AppendCheckItem(
			wx.ID_ANY, _("Include subfolder contents in folder sizes")
		)
		subfoldersItem.Check(self._settings["includeSubfolders"])
		rescanItem = menu.Append(wx.ID_ANY, _("Rescan"))
		self.Bind(wx.EVT_MENU, lambda evt: wx.CallAfter(self._openSettingsDialog), settingsItem)
		self.Bind(wx.EVT_MENU, lambda evt: wx.CallAfter(self._toggleSubfolders), subfoldersItem)
		self.Bind(wx.EVT_MENU, lambda evt: wx.CallAfter(self._startScan), rescanItem)
		self.PopupMenu(menu)
		menu.Destroy()

	def _toggleSubfolders(self):
		if self._shutDown:
			return
		self._settings["includeSubfolders"] = not self._settings["includeSubfolders"]
		saveSizeListSettings(self._settings)
		if self._settings["includeSubfolders"]:
			ui.message(_("Including subfolders"))
		else:
			ui.message(_("Top level only"))
		self._startScan()

	def _openSettingsDialog(self):
		if self._shutDown:
			return
		settingsDialog = FolderSizeSettingsDialog(self, dict(self._settings), self._applySettings)
		try:
			settingsDialog.ShowModal()
		finally:
			settingsDialog.Destroy()
			if not self._shutDown:
				self._listBox.SetFocus()

	def _applySettings(self, newSettings):
		rescanNeeded = newSettings["includeSubfolders"] != self._settings["includeSubfolders"]
		self._settings = newSettings
		if not saveSizeListSettings(newSettings):
			ui.message(_("Could not save settings"))
		if rescanNeeded:
			self._startScan()
		else:
			self._refreshList(announceSummary=False)


_FOLDER_TOO_LARGE = -1
_ITEM_SIZE_CACHE_FILE = os.path.join(CONFIG_DIR, "itemSizes.json")
_ITEM_SIZE_CACHE_VERSION = 2
_ITEM_SIZE_CACHE_MAX_ENTRIES = 9000
_ITEM_SIZE_CACHE_MAX_PARENTS = 2000
_ITEM_SIZE_OCCASIONAL_TTL = 24 * 3600
_ITEM_SIZE_REGULAR_TTL = 2 * 24 * 3600
_ITEM_SIZE_REGULAR_MIN_DAYS = 3
_ITEM_SIZE_VISIT_WINDOW_DAYS = 14
_ITEM_SIZE_MIN_SAVE_GAP = 30


def _newItemSizeStore():
	return {"version": _ITEM_SIZE_CACHE_VERSION, "day": "", "parents": {}, "entries": {}}


def _dayString(secondsAgo=0):
	return time.strftime("%Y-%m-%d", time.localtime(time.time() - secondsAgo))


def _isRegularParent(store, parentKey):
	info = store["parents"].get(parentKey)
	if not info:
		return False
	cutoff = _dayString(_ITEM_SIZE_VISIT_WINDOW_DAYS * 86400)
	return len({day for day in info["days"] if day >= cutoff}) >= _ITEM_SIZE_REGULAR_MIN_DAYS


def _loadItemSizeStore():
	try:
		with open(_ITEM_SIZE_CACHE_FILE, "r", encoding="utf-8") as f:
			stored = json.load(f)
	except FileNotFoundError:
		return _newItemSizeStore()
	except (OSError, ValueError) as e:
		log.error(f"xPlorer: could not read item size cache: {e}")
		return _newItemSizeStore()
	if not isinstance(stored, dict) or stored.get("version") != _ITEM_SIZE_CACHE_VERSION:
		return _newItemSizeStore()
	store = _newItemSizeStore()
	if isinstance(stored.get("day"), str):
		store["day"] = stored["day"]
	if isinstance(stored.get("parents"), dict):
		for key, info in stored["parents"].items():
			if (isinstance(info, dict) and isinstance(info.get("days"), list)
					and all(isinstance(d, str) for d in info["days"]) and isinstance(info.get("last"), int)):
				store["parents"][key] = {"days": list(info["days"]), "last": info["last"]}
	if isinstance(stored.get("entries"), dict):
		for key, entry in stored["entries"].items():
			if (isinstance(entry, dict) and isinstance(entry.get("size"), int)
					and isinstance(entry.get("mtime"), int) and isinstance(entry.get("time"), int)):
				store["entries"][key] = {"size": entry["size"], "mtime": entry["mtime"], "time": entry["time"]}
	return store


def _dailyCleanup(store):
	today = _dayString()
	if store["day"] == today:
		return False
	now = time.time()
	cutoff = _dayString(_ITEM_SIZE_VISIT_WINDOW_DAYS * 86400)
	for parentKey in list(store["parents"]):
		info = store["parents"][parentKey]
		info["days"] = [day for day in info["days"] if day >= cutoff]
		if not info["days"]:
			del store["parents"][parentKey]
	for key in list(store["entries"]):
		keepEntry = (
			_isRegularParent(store, os.path.dirname(key))
			and now - store["entries"][key]["time"] < _ITEM_SIZE_REGULAR_TTL
		)
		if not keepEntry:
			del store["entries"][key]
	store["day"] = today
	return True


def _trimItemSizeStore(store):
	regularCache = {}

	def isRegular(parentKey):
		if parentKey not in regularCache:
			regularCache[parentKey] = _isRegularParent(store, parentKey)
		return regularCache[parentKey]

	entries = store["entries"]
	if len(entries) > _ITEM_SIZE_CACHE_MAX_ENTRIES:
		ordered = sorted(entries.items(), key=lambda kv: (isRegular(os.path.dirname(kv[0])), kv[1]["time"]))
		for key, _entry in ordered[:len(entries) - _ITEM_SIZE_CACHE_MAX_ENTRIES]:
			del entries[key]
	parents = store["parents"]
	if len(parents) > _ITEM_SIZE_CACHE_MAX_PARENTS:
		ordered = sorted(parents.items(), key=lambda kv: (isRegular(kv[0]), kv[1]["last"]))
		for key, _info in ordered[:len(parents) - _ITEM_SIZE_CACHE_MAX_PARENTS]:
			del parents[key]


def _snapshotItemSizeStore(store):
	return {
		"version": store["version"],
		"day": store["day"],
		"parents": {k: {"days": list(v["days"]), "last": v["last"]} for k, v in store["parents"].items()},
		"entries": {k: dict(v) for k, v in store["entries"].items()},
	}


def _saveItemSizeStore(snapshot):
	tmpPath = _ITEM_SIZE_CACHE_FILE + ".tmp"
	try:
		os.makedirs(CONFIG_DIR, exist_ok=True)
		with open(tmpPath, "w", encoding="utf-8") as f:
			json.dump(snapshot, f)
			f.flush()
			os.fsync(f.fileno())
		os.replace(tmpPath, _ITEM_SIZE_CACHE_FILE)
	except OSError as e:
		log.error(f"xPlorer: could not save item size cache: {e}")


class ItemSizeAnnouncer:
	CACHE_MAX_AGE = 10.0
	MIN_REFRESH_GAP = 1.5
	BACKGROUND_FOLDER_CAP = 150
	SIZE_PAUSE_MS = 500

	def __init__(self, fileOps):
		self._fileOps = fileOps
		self._plugin = fileOps.plugin
		self._context = None
		self._cacheTitle = None
		self._cacheTime = 0.0
		self._cacheGeneration = 0
		self._folderPath = None
		self._files = {}
		self._folders = {}
		self._folderMtimes = {}
		self._stems = {}
		self._store = _loadItemSizeStore()
		self._storeDirty = _dailyCleanup(self._store)
		self._lastSaveTime = 0.0
		self._refreshing = False
		self._lastRefreshStart = 0.0
		self._focusedName = None
		self._focusedAt = 0.0
		self._inlineFor = None
		self._pendingLateName = None
		self._waitingFolder = None
		self._priorityFolder = None
		self._sizingRunning = False
		self._sizingGeneration = -1
		self._scope = "all"
		self._shutDown = False
		filter_speechSequence.register(self._filterSpeech)
		self._maybeSave(force=True)

	def stop(self):
		self._shutDown = True
		self._context = None
		filter_speechSequence.unregister(self._filterSpeech)
		if self._storeDirty:
			_trimItemSizeStore(self._store)
			_saveItemSizeStore(_snapshotItemSizeStore(self._store))
			self._storeDirty = False

	def _maybeSave(self, force=False):
		if not self._storeDirty or self._shutDown:
			return
		now = time.time()
		if not force and now - self._lastSaveTime < _ITEM_SIZE_MIN_SAVE_GAP:
			return
		_trimItemSizeStore(self._store)
		snapshot = _snapshotItemSizeStore(self._store)
		self._storeDirty = False
		self._lastSaveTime = now
		threading.Thread(target=_saveItemSizeStore, args=(snapshot,), daemon=True).start()

	def _filterSpeech(self, speechSequence):
		context = self._context
		if context is None:
			return speechSequence
		name, sizeText = context
		for index, item in enumerate(speechSequence):
			if isinstance(item, str) and item.strip() == name.strip():
				self._context = None
				withSize = list(speechSequence)
				withSize[index + 1:index + 1] = [BreakCommand(self.SIZE_PAUSE_MS), sizeText]
				return withSize
		return speechSequence

	def endFocus(self):
		self._context = None

	def beginFocus(self, name, scope="all"):
		self._context = None
		self._scope = scope
		self._focusedName = name
		self._focusedAt = time.time()
		self._inlineFor = None
		self._pendingLateName = None
		self._waitingFolder = None
		if not name or self._shutDown:
			return
		title = self._currentTitle()
		titleMatches = title == self._cacheTitle
		if not titleMatches or time.time() - self._cacheTime > self.CACHE_MAX_AGE:
			self._requestRefresh()
		if not titleMatches:
			self._pendingLateName = name
			return
		kind, realName = self._resolve(name)
		if kind is None:
			self._pendingLateName = name
			self._requestRefresh()
		elif kind == "file":
			if scope != "folders":
				self._context = (name, _formatByteSize(self._files[realName]))
				self._inlineFor = name
		elif scope != "files":
			knownSize = self._folders[realName]
			if knownSize is None:
				self._waitingFolder = realName
				self._priorityFolder = realName
				self._ensureSizing()
			elif knownSize != _FOLDER_TOO_LARGE:
				self._context = (name, _formatByteSize(knownSize))
				self._inlineFor = name

	def _currentTitle(self):
		hwnd = winUser.getForegroundWindow()
		return winUser.getWindowText(hwnd) if hwnd else ""

	def _resolve(self, name):
		if name in self._files:
			return "file", name
		if name in self._folders:
			return "folder", name
		stemMatch = self._stems.get(name)
		if stemMatch in self._files:
			return "file", stemMatch
		if stemMatch in self._folders:
			return "folder", stemMatch
		return None, None

	def _requestRefresh(self):
		now = time.time()
		if self._refreshing and now - self._lastRefreshStart < 10:
			return
		if now - self._lastRefreshStart < self.MIN_REFRESH_GAP:
			return
		self._refreshing = True
		self._lastRefreshStart = now
		self._plugin._getCurrentPathDeferred(self._onPathResolved, 0)

	def _onPathResolved(self, folderPath):
		if self._shutDown:
			return
		if not folderPath:
			log.debug("xPlorer: item sizes - no current folder path available")
			self._refreshing = False
			return
		title = self._currentTitle()

		def worker():
			files = {}
			folders = {}
			mtimes = {}
			try:
				with os.scandir(folderPath) as entries:
					for entry in entries:
						try:
							if entry.is_dir(follow_symlinks=False):
								folders[entry.name] = None
								mtimes[entry.name] = entry.stat(follow_symlinks=False).st_mtime_ns
							else:
								files[entry.name] = entry.stat(follow_symlinks=False).st_size
						except OSError:
							continue
			except OSError as e:
				log.debug(f"xPlorer: item size scan failed for {folderPath}: {e}")
				wx.CallAfter(self._onScanFailed)
				return
			wx.CallAfter(self._onScanDone, folderPath, title, files, folders, mtimes)

		threading.Thread(target=worker, daemon=True).start()

	def _onScanFailed(self):
		self._refreshing = False

	def _recordVisit(self, parentKey):
		today = _dayString()
		info = self._store["parents"].setdefault(parentKey, {"days": [], "last": 0})
		if today not in info["days"]:
			info["days"].append(today)
			info["days"] = info["days"][-_ITEM_SIZE_VISIT_WINDOW_DAYS:]
		info["last"] = int(time.time())
		self._storeDirty = True

	def _onScanDone(self, folderPath, title, files, folders, mtimes):
		self._refreshing = False
		if self._shutDown:
			return
		now = time.time()
		parentKey = os.path.dirname(os.path.join(folderPath, "x")).lower()
		if folders:
			self._recordVisit(parentKey)
		ttl = _ITEM_SIZE_REGULAR_TTL if _isRegularParent(self._store, parentKey) else _ITEM_SIZE_OCCASIONAL_TTL
		for folderName in folders:
			persisted = self._store["entries"].get(os.path.join(folderPath, folderName).lower())
			if (persisted and persisted["mtime"] == mtimes.get(folderName)
					and now - persisted["time"] < ttl):
				folders[folderName] = persisted["size"]
		stemCounts = {}
		for entryName in list(files) + list(folders):
			stemCounts.setdefault(os.path.splitext(entryName)[0], []).append(entryName)
		self._stems = {stem: names[0] for stem, names in stemCounts.items() if len(names) == 1}
		self._files = files
		self._folders = folders
		self._folderMtimes = mtimes
		self._folderPath = folderPath
		self._cacheTitle = title
		self._cacheTime = now
		self._cacheGeneration += 1
		log.debug(f"xPlorer: item sizes loaded for {folderPath}: {len(files)} files, {len(folders)} folders")
		self._announceLate()
		self._ensureSizing()
		self._maybeSave()

	def _announceLate(self):
		name = self._pendingLateName
		self._pendingLateName = None
		if not name or name == self._inlineFor or name != self._focusedName:
			return
		if time.time() - self._focusedAt > 2.5 or self._currentTitle() != self._cacheTitle:
			return
		kind, realName = self._resolve(name)
		if kind == "file" and self._scope != "folders":
			ui.message(_formatByteSize(self._files[realName]))
		elif kind == "folder" and self._scope != "files":
			knownSize = self._folders[realName]
			if knownSize is None:
				self._waitingFolder = realName
				self._priorityFolder = realName
			elif knownSize != _FOLDER_TOO_LARGE:
				ui.message(_formatByteSize(knownSize))

	def _ensureSizing(self):
		if self._shutDown or not self._folderPath or self._scope == "files":
			return
		if self._sizingRunning and self._sizingGeneration == self._cacheGeneration:
			return
		if all(size is not None for size in self._folders.values()):
			return
		generation = self._cacheGeneration
		self._sizingRunning = True
		self._sizingGeneration = generation
		threading.Thread(
			target=self._sizingWorker,
			args=(generation, self._folderPath, self._folders),
			daemon=True
		).start()

	def _sizingWorker(self, generation, basePath, folders):
		attempted = set()
		backgroundCount = 0
		try:
			while not self._shutDown and generation == self._cacheGeneration:
				realName = None
				priority = self._priorityFolder
				if priority in folders and folders[priority] is None and priority not in attempted:
					realName = priority
				elif backgroundCount < self.BACKGROUND_FOLDER_CAP:
					realName = next(
						(n for n, size in list(folders.items()) if size is None and n not in attempted),
						None
					)
					backgroundCount += 1
				if realName is None:
					break
				attempted.add(realName)
				size = self._fileOps._computeBoundedFolderSize([os.path.join(basePath, realName)])
				wx.CallAfter(self._onFolderSizeReady, generation, realName, size)
				time.sleep(0.01)
		finally:
			wx.CallAfter(self._onSizingFinished, generation)

	def _onSizingFinished(self, generation):
		if generation == self._sizingGeneration:
			self._sizingRunning = False
		self._maybeSave()

	def _onFolderSizeReady(self, generation, realName, size):
		if self._shutDown or generation != self._cacheGeneration:
			return
		if size is None:
			log.debug(f"xPlorer: folder too large for automatic size announcement: {realName}")
			self._folders[realName] = _FOLDER_TOO_LARGE
		else:
			self._folders[realName] = size
			mtime = self._folderMtimes.get(realName)
			if mtime is not None:
				self._store["entries"][os.path.join(self._folderPath, realName).lower()] = {
					"size": size, "mtime": mtime, "time": int(time.time())
				}
				self._storeDirty = True
		if size is not None and self._waitingFolder == realName:
			self._waitingFolder = None
			if self._resolve(self._focusedName)[1] == realName:
				ui.message(_formatByteSize(size))


class FileOperations:
	ISO_PROGRESS_MIN_BYTES = 256 * 1024 * 1024

	def __init__(self, plugin):
		self.plugin = plugin
		self.rename_dialog = None
		self._beep_timer = None
		self._calculation_active = False
		self._stop_beep_event = threading.Event()
		self._size_thread = None
		self._sizeCalcGeneration = 0
		self.folderSizeDialog = None
		self.itemSizes = ItemSizeAnnouncer(self)
		self._isoRunning = False
		self._isoGeneration = 0
		self._isoStopEvent = threading.Event()
		self._isoBeepTask = None
		self._isoProgressDialog = None
		self._isoLastDecade = -1
		self._isoReturnHwnd = None

	def cleanup(self):
		self._stop_calculation()
		self.itemSizes.stop()
		self._isoStopEvent.set()
		self._isoRunning = False
		self._closeIsoProgress()
		if self._isoBeepTask:
			try:
				self._isoBeepTask.Stop()
			except (RuntimeError, AttributeError):
				pass
			self._isoBeepTask = None
		if self.folderSizeDialog:
			try:
				self.folderSizeDialog.shutdown()
				self.folderSizeDialog.EndModal(wx.ID_CLOSE)
			except (RuntimeError, AttributeError):
				pass
			self.folderSizeDialog = None
		if self.rename_dialog:
			try:
				self.rename_dialog.Destroy()
			except (RuntimeError, AttributeError):
				pass

	def _stop_calculation(self):
		self._calculation_active = False
		self._stop_beeping()
		if self._size_thread and self._size_thread.is_alive():
			self._size_thread.join(timeout=1.0)

	def _start_beeping(self):
		self._stop_beep_event.clear()
		self._beep_timer = threading.Timer(2.0, self._beep_interval)
		self._beep_timer.daemon = True
		self._beep_timer.start()

	def _stop_beeping(self):
		self._stop_beep_event.set()
		if self._beep_timer:
			self._beep_timer.cancel()
			self._beep_timer = None

	def _beep_interval(self):
		if not self._stop_beep_event.is_set():
			core.callLater(0, tones.beep, 440, 100)
			self._beep_timer = threading.Timer(2.0, self._beep_interval)
			self._beep_timer.daemon = True
			self._beep_timer.start()

	def _format_size(self, size_in_bytes):
		if size_in_bytes < 1024:
			return f"{size_in_bytes} bytes"
		elif size_in_bytes < 1024 * 1024:
			return f"{size_in_bytes / 1024:.2f} KB"
		elif size_in_bytes < 1024 * 1024 * 1024:
			return f"{size_in_bytes / (1024 * 1024):.2f} MB"
		else:
			return f"{size_in_bytes / (1024 * 1024 * 1024):.2f} GB"

	FAST_SIZE_FILE_CAP = 9000

	def _computeBoundedFolderSize(self, folder_paths, maxFiles=None):
		"""Try to get an exact recursive size for the given folders, bailing
		out (returning None) as soon as the file count exceeds maxFiles.
		Byte size is irrelevant to how long this takes - stat() costs the
		same for a 1KB file as a 1GB one - only the number of entries
		scanned matters, so the cap is on file count."""
		if maxFiles is None:
			maxFiles = self.FAST_SIZE_FILE_CAP
		total_size = 0
		file_count = 0
		pendingDirs = list(folder_paths)
		while pendingDirs:
			current_dir = pendingDirs.pop()
			try:
				with os.scandir(current_dir) as entries:
					for entry in entries:
						try:
							if entry.is_dir(follow_symlinks=False):
								pendingDirs.append(entry.path)
							else:
								total_size += entry.stat(follow_symlinks=False).st_size
								file_count += 1
								if file_count > maxFiles:
									return None
						except OSError:
							continue
			except OSError:
				continue
		return total_size

	def _get_folder_size_accurate(self, folder_path):
		total_size = 0
		try:
			pendingDirs = [folder_path]
			while pendingDirs:
				if not self._calculation_active:
					return 0
				current_dir = pendingDirs.pop()
				try:
					with os.scandir(current_dir) as entries:
						for entry in entries:
							if not self._calculation_active:
								return 0
							try:
								if entry.is_dir(follow_symlinks=False):
									pendingDirs.append(entry.path)
								else:
									# DirEntry.stat() reuses the stat info the OS already
									# returned while listing this directory, instead of a
									# second syscall via os.path.getsize() per file - a real
									# speedup on large trees and slow/network drives.
									total_size += entry.stat(follow_symlinks=False).st_size
							except OSError:
								continue
				except OSError:
					continue
			return total_size
		except Exception as e:
			log.error(f"Error calculating folder size for {folder_path}: {e}")
			return 0

	def _check_access_permission(self, path):
		try:
			if os.path.isdir(path):
				next(os.scandir(path), None)
				return True
			elif os.path.isfile(path):
				with open(path, 'rb') as f:
					f.read(1)
				return True
			return False
		except (PermissionError, OSError, WindowsError):
			return False
		except Exception:
			return True

	def saySize(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			return

		def handleSelection(selected_items, _hwnd):
			if not selected_items:
				ui.message(_("No items selected"))
				return

			inaccessible_items = []
			for name, path in selected_items:
				if not self._check_access_permission(path):
					inaccessible_items.append(name)

			if inaccessible_items and len(inaccessible_items) == len(selected_items):
				ui.message(_("No access to size data"))
				return

			# Signal any still-running calculation from a previous
			# invocation (e.g. a slow folder-size walk left over from
			# another tab) to stop without blocking the main thread waiting
			# for it to actually exit - the generation check below is what
			# makes it safe to let it keep running harmlessly in the
			# background instead of joining it here.
			self._calculation_active = False
			self._stop_beeping()
			self._sizeCalcGeneration += 1
			myGeneration = self._sizeCalcGeneration
			self._calculation_active = True
			self._start_beeping()

			def calculate_size():
				try:
					total_size = 0
					accessible_item_count = 0
					is_drive = False

					for name, path in selected_items:
						if not self._calculation_active or myGeneration != self._sizeCalcGeneration:
							break
						if name in inaccessible_items:
							continue

						accessible_item_count += 1

						if os.path.isfile(path):
							try:
								file_size = os.path.getsize(path)
								total_size += file_size
							except Exception as e:
								log.error(f"Error getting file size for {name}: {e}")

						elif os.path.isdir(path):
							try:
								drive_letter = os.path.splitdrive(path)[0]
								if drive_letter and len(drive_letter) == 2 and drive_letter[1] == ':':
									if path == drive_letter + "\\":
										is_drive = True
										import ctypes
										free_bytes = ctypes.c_ulonglong(0)
										total_bytes = ctypes.c_ulonglong(0)
										if ctypes.windll.kernel32.GetDiskFreeSpaceExW(
											ctypes.c_wchar_p(path), None,
											ctypes.byref(total_bytes),
											ctypes.byref(free_bytes)
										):
											used_size = total_bytes.value - free_bytes.value
											total_size += used_size
										continue

								folder_size = self._get_folder_size_accurate(path)
								total_size += folder_size
							except Exception as e:
								log.error(f"Error getting folder size for {name}: {e}")

					if myGeneration != self._sizeCalcGeneration:
						# Superseded by a newer say-size request (e.g. the
						# user switched tabs/windows and asked again before
						# this one finished) - discard silently instead of
						# speaking a size for whatever used to be selected.
						return

					self._stop_beeping()
					self._calculation_active = False

					formatted_size = self._format_size(total_size)

					if accessible_item_count == 0:
						display_message = _("No access to size data")
					elif accessible_item_count == 1:
						if is_drive:
							display_message = formatted_size
						else:
							display_message = formatted_size
					else:
						display_message = _("{count} items {size}").format(
							count=accessible_item_count,
							size=formatted_size
						)

					core.callLater(0, ui.message, display_message)

				except Exception as e:
					log.error(f"Error in size calculation thread: {e}")
					if myGeneration == self._sizeCalcGeneration:
						self._stop_beeping()
						self._calculation_active = False
						core.callLater(0, ui.message, _("Error calculating size"))

			self._size_thread = threading.Thread(target=calculate_size, daemon=True)
			self._size_thread.start()

		self.plugin._getSelectedItemsAsync(handleSelection)

	def convertFolderToIso(self):
		focus = api.getFocusObject()
		if not focus or not focus.appModule or focus.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			return
		if self._isoRunning:
			ui.message(_("ISO creation is already running"))
			return

		def handleSelection(selectedItems, _hwnd):
			folders = [path for _name, path in (selectedItems or []) if os.path.isdir(path)]
			if not folders:
				ui.message(_("Please select a folder"))
				return
			if len(folders) > 1:
				ui.message(_("Please select only one folder"))
				return
			self._startIsoCreation(folders[0])

		self.plugin._getSelectedItemsAsync(handleSelection)

	def _uniqueIsoPath(self, outputDir, folderName):
		candidate = os.path.join(outputDir, folderName + ".iso")
		number = 1
		while os.path.exists(candidate) or os.path.exists(candidate + ".part"):
			number += 1
			candidate = os.path.join(outputDir, f"{folderName} ({number}).iso")
		return candidate

	def _hasFreeSpace(self, directory, requiredBytes):
		freeBytes = ctypes.c_ulonglong(0)
		if not ctypes.windll.kernel32.GetDiskFreeSpaceExW(directory, None, None, ctypes.byref(freeBytes)):
			return True
		return freeBytes.value >= requiredBytes + 16 * 1024 * 1024

	def _startIsoCreation(self, folderPath):
		sourcePath = folderPath.rstrip("\\/")
		outputDir = os.path.dirname(sourcePath)
		folderName = os.path.basename(sourcePath)
		if not folderName or not outputDir:
			ui.message(_("This folder cannot be converted to ISO"))
			return
		finalPath = self._uniqueIsoPath(outputDir, folderName)
		self._isoRunning = True
		self._isoGeneration += 1
		self._isoLastDecade = -1
		try:
			self._isoReturnHwnd = api.getForegroundObject().windowHandle
		except (AttributeError, RuntimeError):
			self._isoReturnHwnd = None
		generation = self._isoGeneration
		stopEvent = threading.Event()
		self._isoStopEvent = stopEvent
		tones.beep(800, 150)
		self._scheduleIsoBeep(generation)

		def checkSpace(requiredBytes, _stats):
			if not self._hasFreeSpace(outputDir, requiredBytes):
				raise IsoError(_("Not enough free disk space"))
			if requiredBytes >= self.ISO_PROGRESS_MIN_BYTES:
				wx.CallAfter(self._showIsoProgress, generation)

		def onProgress(doneBytes, totalBytes):
			if totalBytes > 0:
				wx.CallAfter(self._updateIsoProgress, generation, int(doneBytes * 100 / totalBytes))

		def worker():
			partPath = finalPath + ".part"
			try:
				stats = buildIso(sourcePath, partPath, folderName, stopEvent.is_set, checkSpace, onProgress=onProgress)
				os.replace(partPath, finalPath)
			except IsoCancelled:
				self._removeQuietly(partPath)
				wx.CallAfter(self._onIsoFinished, generation, None, None)
				return
			except (IsoError, OSError) as e:
				log.error(f"ISO creation failed for {sourcePath}: {e}")
				self._removeQuietly(partPath)
				wx.CallAfter(self._onIsoFinished, generation, None, str(e))
				return
			wx.CallAfter(self._onIsoFinished, generation, finalPath, stats)

		threading.Thread(target=worker, daemon=True).start()

	def _removeQuietly(self, path):
		try:
			os.remove(path)
		except OSError:
			pass

	def _scheduleIsoBeep(self, generation):
		self._isoBeepTask = core.callLater(2000, self._isoBeepTick, generation)

	def _isoBeepTick(self, generation):
		self._isoBeepTask = None
		if not self._isoRunning or generation != self._isoGeneration:
			return
		tones.beep(600, 60)
		self._scheduleIsoBeep(generation)

	def _showIsoProgress(self, generation):
		if not self._isoRunning or generation != self._isoGeneration or self._isoProgressDialog:
			return
		if self._isoBeepTask:
			self._isoBeepTask.Stop()
			self._isoBeepTask = None
		style = wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME | wx.STAY_ON_TOP
		try:
			self._isoProgressDialog = wx.ProgressDialog(
				_("Creating ISO"), _("Starting..."), maximum=100, parent=gui.mainFrame, style=style
			)
			self._isoProgressDialog.Raise()
			wx.CallAfter(self._isoProgressDialog.SetFocus)
			ui.message(_("Creating ISO"))
		except RuntimeError as e:
			log.error(f"Could not show ISO progress dialog: {e}")
			self._isoProgressDialog = None

	def _updateIsoProgress(self, generation, percent):
		if not self._isoProgressDialog or generation != self._isoGeneration:
			return
		percent = min(percent, 99)
		try:
			continueRunning, _skip = self._isoProgressDialog.Update(percent, _("Creating ISO: {percent}%").format(percent=percent))
		except RuntimeError:
			return
		if percent // 10 != self._isoLastDecade:
			self._isoLastDecade = percent // 10
			tones.beep(800 + percent * 2, 50)
		if not continueRunning:
			self._isoStopEvent.set()

	def _closeIsoProgress(self):
		dialog = self._isoProgressDialog
		self._isoProgressDialog = None
		if dialog:
			try:
				dialog.Destroy()
			except RuntimeError:
				pass
			if self._isoReturnHwnd:
				hwnd = self._isoReturnHwnd
				core.callLater(100, self._returnToExplorer, hwnd)

	def _returnToExplorer(self, hwnd):
		try:
			winUser.setForegroundWindow(hwnd)
		except (OSError, AttributeError) as e:
			log.debug(f"Could not return focus to Explorer: {e}")

	def _onIsoFinished(self, generation, isoPath, outcome):
		if generation != self._isoGeneration:
			return
		self._isoRunning = False
		self._closeIsoProgress()
		if self._isoBeepTask:
			self._isoBeepTask.Stop()
			self._isoBeepTask = None
		if isoPath is None:
			if outcome:
				tones.beep(300, 300)
				ui.message(_("ISO creation failed: {error}").format(error=outcome))
			return
		try:
			sizeText = _formatByteSize(os.path.getsize(isoPath))
		except OSError:
			sizeText = ""
		tones.beep(1000, 200)
		skipped = outcome.get("skipped", 0)
		message = _("ISO created: {name}, {size}").format(name=os.path.basename(isoPath), size=sizeText)
		if outcome.get("format") == "UDF":
			message += _(", UDF format")
		if skipped:
			message += _(", {count} items skipped").format(count=skipped)
		ui.message(message)
		operationHistory = getattr(self.plugin, "operationHistory", None)
		if operationHistory:
			operationHistory.addEntry(_("Created ISO {name}").format(name=os.path.basename(isoPath)))

	def showFolderSizeList(self):
		focus = api.getFocusObject()
		if not focus or not focus.appModule or focus.appModule.appName != "explorer":
			ui.message(_("Not in File Explorer"))
			return
		if self.folderSizeDialog:
			return

		def onPath(folderPath):
			if not folderPath or not os.path.isdir(folderPath):
				ui.message(_("Unable to get current path"))
				return
			wx.CallAfter(self._openFolderSizeList, folderPath)

		self.plugin._getCurrentPathDeferred(onPath, 100)

	def _openFolderSizeList(self, folderPath):
		if self.folderSizeDialog:
			return
		manager = self.plugin.manager
		speech.cancelSpeech()
		manager.contextMenuActive = True
		manager.suppressAllAnnouncements = True
		dialog = None
		try:
			dialog = FolderSizeListDialog(gui.mainFrame, folderPath)
			self.folderSizeDialog = dialog
			gui.mainFrame.prePopup()
			try:
				dialog.Raise()
				dialog.ShowModal()
			finally:
				gui.mainFrame.postPopup()
		except Exception as e:
			log.error(f"Error showing folder size list: {e}")
			ui.message(_("Error opening current folder size list"))
		finally:
			if dialog:
				try:
					dialog.shutdown()
					dialog.Destroy()
				except RuntimeError:
					pass
			self.folderSizeDialog = None
			core.callLater(1000, lambda: setattr(manager, "suppressAllAnnouncements", False))
			core.callLater(100, lambda: setattr(manager, "contextMenuActive", False))

	def renameFile(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			return

		def handleSelection(selectedItems, _hwnd):
			try:
				if not selectedItems:
					ui.message(_("No items selected"))
					return
				if len(selectedItems) > 1:
					ui.message(_("Please select only one file"))
					return
				file_path = selectedItems[0][1]
				if not os.path.isfile(file_path):
					ui.message(_("Please select a file, not a folder"))
					return
				file_name = os.path.basename(file_path)
				dir_name = os.path.dirname(file_path)
				wx.CallAfter(self._show_rename_dialog, file_name, dir_name, file_path)
			except Exception as e:
				log.error(f"Error in renameFile: {e}")
				ui.message(_("Error renaming file"))

		self.plugin._getSelectedItemsAsync(handleSelection)

	def autoPasteRenameFromClipboard(self):
		focus = api.getFocusObject()
		if not focus or focus.appModule.appName != "explorer":
			return

		def handleSelection(selectedItems, _hwnd):
			try:
				if not selectedItems:
					ui.message(_("No items selected"))
					return
				if len(selectedItems) > 1:
					ui.message(_("Please select only one item"))
					return
				file_path = selectedItems[0][1]
				is_folder = os.path.isdir(file_path)
				if not is_folder and not os.path.isfile(file_path):
					ui.message(_("Selected item no longer exists"))
					return

				clipboard_text = None
				try:
					if wx.TheClipboard.Open():
						try:
							data = wx.TextDataObject()
							if wx.TheClipboard.GetData(data):
								clipboard_text = data.GetText().strip()
						finally:
							wx.TheClipboard.Close()
				except Exception as e:
					log.error(f"Error reading clipboard for auto paste rename: {e}")

				if not clipboard_text:
					ui.message(_("Clipboard is empty"))
					return

				invalid_chars = '<>:"/\\|?*'
				if '\n' in clipboard_text or '\r' in clipboard_text or any(c in clipboard_text for c in invalid_chars):
					ui.message(_("Clipboard text is not a valid name"))
					return

				original_dir = os.path.dirname(file_path)
				original_name = os.path.basename(file_path)

				if is_folder:
					# Folders don't have a meaningful "extension" to
					# preserve - use the clipboard text as the new folder
					# name as-is.
					new_name = clipboard_text
				else:
					original_ext = os.path.splitext(original_name)[1]
					# If the clipboard text already looks like "name.ext",
					# use it verbatim (extension included). Otherwise treat
					# it as just a new name and keep the selected file's
					# own extension, per the requested behavior.
					_clipboard_base, clipboard_ext = os.path.splitext(clipboard_text)
					new_name = clipboard_text if clipboard_ext else clipboard_text + original_ext

				new_path = os.path.join(original_dir, new_name)

				if os.path.normcase(new_path) == os.path.normcase(file_path):
					ui.message(_("New name is the same as the current name"))
					return

				if os.path.exists(new_path):
					ui.message(_("An item named {name} already exists").format(name=new_name))
					return

				try:
					os.rename(file_path, new_path)
					ui.message(_("Renamed to {name}").format(name=new_name))
					operationHistory = getattr(self.plugin, "operationHistory", None)
					if operationHistory:
						operationHistory.addEntry(_("Renamed {old} to {new}").format(old=original_name, new=new_name))
				except OSError as e:
					log.error(f"Error renaming file via clipboard auto-paste: {e}")
					ui.message(_("Error renaming file"))
			except Exception as e:
				log.error(f"Error in autoPasteRenameFromClipboard: {e}")
				ui.message(_("Error renaming file"))

		self.plugin._getSelectedItemsAsync(handleSelection)

	def _show_rename_dialog(self, file_name, dir_name, file_path):
		dialog = None
		try:
			if gui.mainFrame:
				gui.mainFrame.prePopup()
			
			dialog = RenameDialog(gui.mainFrame, file_name)
			dialog.CentreOnScreen()
			dialog.Raise()
			
			result = dialog.ShowModal()
			
			if result == wx.ID_OK and dialog.new_name:
				new_path = os.path.join(dir_name, dialog.new_name)
				if new_path == file_path:
					ui.message(_("File name not changed"))
					return
				if os.path.exists(new_path):
					ui.message(_("A file with this name already exists"))
					return
				try:
					os.rename(file_path, new_path)
					ui.message(_("File renamed to {name}").format(name=dialog.new_name))
					batchRename = getattr(self.plugin, "batchRename", None)
					if batchRename:
						batchRename.saveUndoMapping([{"original": file_path, "renamed": new_path}])
						batchRename.logOperation(_("Renamed 1 file"))
				except Exception as e:
					log.error(f"Error renaming file: {e}")
					ui.message(_("Error renaming file"))
		except Exception as e:
			log.error(f"Error showing rename dialog: {e}")
			ui.message(_("Error opening rename dialog"))
		finally:
			if dialog:
				dialog.Destroy()
			if gui.mainFrame:
				gui.mainFrame.postPopup()





