# freezeManager.py

import os
import json
import stat
import time
import threading
import globalVars
import api
import ui
import tones
import core
import wx
import gui
import winUser
import addonHandler
from logHandler import log
from speech.commands import BreakCommand
from speech.extensions import filter_speechSequence

addonHandler.initTranslation()

CONFIG_DIR = os.path.join(globalVars.appArgs.configPath, "ChaiChaimee", "xPlorer")
FREEZER_FILE = os.path.join(CONFIG_DIR, "freezer.json")

_BLOCKED_RESULTS = {
	"delete": _("Delete canceled"),
	"rename": _("Rename canceled"),
	"move": _("Move canceled"),
	"cut": _("Cut canceled"),
	"paste": _("Paste canceled"),
	"overwrite": _("Overwrite canceled"),
}

STATE_ACTIVE = "active"
STATE_MISSING = "missing"
STATE_REPLACED = "replaced"


def _keyOf(path):
	return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _withSeparator(key):
	return key if key.endswith(os.sep) else key + os.sep


def _fileIdOf(path):
	try:
		info = os.stat(path)
	except OSError:
		return None
	if not info.st_ino:
		return None
	return [info.st_dev, info.st_ino]


def _entryState(entry):
	"""An entry protects only the exact item it was created for. A missing
	path or a different item now sitting at the same path is not frozen."""
	try:
		info = os.stat(entry["path"])
	except OSError:
		return STATE_MISSING
	storedId = entry.get("id")
	if not storedId or not info.st_ino:
		return STATE_ACTIVE
	if storedId[0] != info.st_dev:
		# A different volume (another PC, a reformatted or re-serialized drive):
		# file IDs from the old volume cannot be compared, so the path decides.
		return STATE_ACTIVE
	if storedId[1] != info.st_ino:
		return STATE_REPLACED
	return STATE_ACTIVE


def _isReadOnly(path):
	return not (os.stat(path).st_mode & stat.S_IWRITE)


def _setReadOnly(path, enabled):
	os.chmod(path, stat.S_IREAD if enabled else stat.S_IREAD | stat.S_IWRITE)


def _iterFiles(path):
	if os.path.isfile(path):
		yield path
		return
	for root, _dirNames, fileNames in os.walk(path):
		for fileName in fileNames:
			yield os.path.join(root, fileName)


def _criticalFolders():
	folders = []
	for variable in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "PUBLIC"):
		value = os.environ.get(variable)
		if value:
			folders.append(value)
	profile = os.environ.get("USERPROFILE")
	if profile:
		folders.append(profile)
		folders.append(os.path.dirname(profile))
	return folders


def _isWithin(key, parentKey):
	if key == parentKey:
		return True
	return key.startswith(parentKey.rstrip(os.sep) + os.sep)


def isProtectedLocation(path):
	"""True for drive roots, core system folders and the folder that holds the freezer list itself."""
	if not path:
		return False
	key = _keyOf(path)
	if os.path.dirname(key) == key:
		return True
	criticalKeys = [_keyOf(folder) for folder in _criticalFolders()]
	if any(key == criticalKey or _isWithin(criticalKey, key) for criticalKey in criticalKeys):
		return True
	systemRoot = os.environ.get("SystemRoot") or os.environ.get("windir")
	if systemRoot and _isWithin(key, _keyOf(systemRoot)):
		return True
	configKey = _keyOf(CONFIG_DIR)
	return _isWithin(key, configKey) or _isWithin(configKey, key)


def _parseStoredId(rawId):
	if isinstance(rawId, list) and len(rawId) == 2 and all(isinstance(part, int) for part in rawId):
		return rawId
	return None


class _FrozenStore:
	def __init__(self):
		self._lock = threading.RLock()
		self._entries = {}
		self._loaded = False
		self._hasAny = False
		self.readOnlyEnabled = True
		self.generation = 0

	def _ensureLoaded(self):
		if self._loaded:
			return
		self._loaded = True
		if not os.path.isfile(FREEZER_FILE):
			return
		try:
			with open(FREEZER_FILE, "r", encoding="utf-8") as freezerFile:
				raw = json.load(freezerFile)
			rawEntries = raw.get("entries", []) if isinstance(raw, dict) else []
			if isinstance(raw, dict):
				self.readOnlyEnabled = raw.get("readOnly", True) is not False
			for entry in rawEntries:
				path = entry.get("path") if isinstance(entry, dict) else None
				if not isinstance(path, str) or not path:
					continue
				rawSkip = entry.get("roSkip")
				self._entries[_keyOf(path)] = {
					"path": path,
					"folder": bool(entry.get("folder", False)),
					"id": _parseStoredId(entry.get("id")),
					"ro": bool(entry.get("ro", False)),
					"roSkip": [item for item in rawSkip if isinstance(item, str)] if isinstance(rawSkip, list) else [],
				}
			self._hasAny = bool(self._entries)
			log.debug(f"xPlorer: freezer loaded {len(self._entries)} entries")
		except (OSError, ValueError, AttributeError) as e:
			log.error(f"xPlorer: freezer list unreadable, keeping a backup and starting empty: {e}")
			self._entries.clear()
			self._hasAny = False
			try:
				os.replace(FREEZER_FILE, FREEZER_FILE + ".bad")
			except OSError as backupError:
				log.debug(f"xPlorer: could not back up the unreadable freezer list: {backupError}")

	def _save(self):
		tmpPath = FREEZER_FILE + ".tmp"
		payload = {"version": 3, "readOnly": self.readOnlyEnabled, "entries": list(self._entries.values())}
		try:
			os.makedirs(CONFIG_DIR, exist_ok=True)
			with open(tmpPath, "w", encoding="utf-8") as freezerFile:
				json.dump(payload, freezerFile, indent=2, ensure_ascii=False)
				freezerFile.flush()
				os.fsync(freezerFile.fileno())
			os.replace(tmpPath, FREEZER_FILE)
			return True
		except OSError as e:
			log.error(f"xPlorer: could not save freezer list: {e}")
			return False

	def hasEntries(self):
		# Called from the keyboard hook thread, so it must never wait for the
		# lock while another thread is saving or scanning.
		if not self._loaded:
			with self._lock:
				self._ensureLoaded()
		return self._hasAny

	def adoptForeignVolumes(self):
		"""Re-learns file IDs of entries that came from another volume.
		Returns the paths that were adopted so protection can be applied again."""
		adopted = []
		with self._lock:
			self._ensureLoaded()
			for entry in self._entries.values():
				storedId = entry.get("id")
				if not storedId:
					continue
				try:
					info = os.stat(entry["path"])
				except OSError:
					continue
				if info.st_ino and storedId[0] != info.st_dev:
					entry["id"] = [info.st_dev, info.st_ino]
					adopted.append(entry["path"])
			if adopted:
				self._save()
		return adopted

	def activeKeys(self):
		with self._lock:
			self._ensureLoaded()
			return [key for key, entry in self._entries.items() if _entryState(entry) == STATE_ACTIVE]

	def isFrozen(self, path, ignorePath=None):
		if not path:
			return False
		ignoreKey = _keyOf(ignorePath) if ignorePath else None
		with self._lock:
			self._ensureLoaded()
			if not self._entries:
				return False
			key = _keyOf(path)
			while True:
				entry = self._entries.get(key)
				if entry is not None and key != ignoreKey and _entryState(entry) == STATE_ACTIVE:
					return True
				parentKey = os.path.dirname(key)
				if parentKey == key:
					return False
				key = parentKey

	def containsFrozenDescendant(self, path):
		if not path:
			return False
		with self._lock:
			self._ensureLoaded()
			if not self._entries:
				return False
			prefix = _withSeparator(_keyOf(path))
			return any(
				key.startswith(prefix) and _entryState(entry) == STATE_ACTIVE
				for key, entry in self._entries.items()
			)

	def add(self, paths):
		"""Returns (addedPaths, saveOk). Paths already protected are skipped."""
		added = []
		with self._lock:
			self._ensureLoaded()
			for path in paths:
				if not path or self.isFrozen(path):
					continue
				self._entries[_keyOf(path)] = {
					"path": os.path.normpath(path),
					"folder": os.path.isdir(path),
					"id": _fileIdOf(path),
					"ro": False,
					"roSkip": [],
				}
				added.append(os.path.normpath(path))
			if not added:
				return [], True
			self._hasAny = True
			self.generation += 1
			return added, self._save()

	def remove(self, paths):
		"""Removes only entries that were frozen directly. Returns (removedEntries, saveOk)."""
		removed = []
		with self._lock:
			self._ensureLoaded()
			for path in paths:
				entry = self._entries.pop(_keyOf(path), None) if path else None
				if entry is not None:
					removed.append(entry)
			if not removed:
				return [], True
			self._hasAny = bool(self._entries)
			self.generation += 1
			return removed, self._save()

	def clear(self):
		with self._lock:
			self._ensureLoaded()
			removed = list(self._entries.values())
			if not removed:
				return [], True
			self._entries.clear()
			self._hasAny = False
			self.generation += 1
			return removed, self._save()

	def setProtection(self, path, applied, skipList):
		"""Returns False when the entry no longer exists."""
		with self._lock:
			self._ensureLoaded()
			entry = self._entries.get(_keyOf(path))
			if entry is None:
				return False
			entry["ro"] = applied
			entry["roSkip"] = list(skipList)
			self._save()
			return True

	def skipListOf(self, path):
		with self._lock:
			self._ensureLoaded()
			entry = self._entries.get(_keyOf(path))
			return list(entry.get("roSkip", [])) if entry else []

	def hasEntry(self, path):
		with self._lock:
			self._ensureLoaded()
			return _keyOf(path) in self._entries

	def snapshot(self):
		with self._lock:
			self._ensureLoaded()
			entries = [dict(entry) for entry in self._entries.values()]
		for entry in entries:
			entry["state"] = _entryState(entry)
		entries.sort(key=lambda entry: entry["path"].casefold())
		return entries


_store = _FrozenStore()


_protectLock = threading.Lock()


def _isCovered(filePath, coverKeys):
	key = _keyOf(filePath)
	while True:
		if key in coverKeys:
			return True
		parentKey = os.path.dirname(key)
		if parentKey == key:
			return False
		key = parentKey


def _applyReadOnly(path):
	"""Marks every file under path read-only. Returns (filesAlreadyReadOnly, failedCount)."""
	alreadyReadOnly = []
	failed = 0
	otherKeys = set(_store.activeKeys())
	otherKeys.discard(_keyOf(path))
	for filePath in _iterFiles(path):
		try:
			if os.path.islink(filePath):
				continue
			if _isReadOnly(filePath):
				if not _isCovered(filePath, otherKeys):
					alreadyReadOnly.append(filePath)
				continue
			_setReadOnly(filePath, True)
		except OSError as e:
			failed += 1
			log.debug(f"xPlorer: could not make {filePath} read-only: {e}")
	return alreadyReadOnly, failed


def _restoreWritable(entry):
	"""Undoes _applyReadOnly for one removed entry. Returns the failed count."""
	if not entry.get("ro") or _entryState(entry) != STATE_ACTIVE:
		return 0
	keepReadOnly = {_keyOf(item) for item in entry.get("roSkip", [])}
	stillFrozenKeys = set(_store.activeKeys())
	failed = 0
	for filePath in _iterFiles(entry["path"]):
		try:
			if _keyOf(filePath) in keepReadOnly or os.path.islink(filePath):
				continue
			if _isCovered(filePath, stillFrozenKeys):
				continue
			if _isReadOnly(filePath):
				_setReadOnly(filePath, False)
		except OSError as e:
			failed += 1
			log.debug(f"xPlorer: could not make {filePath} writable again: {e}")
	return failed


READ_ONLY_SCAN_CAP = 20000


def readOnlyState(path):
	"""True when every file under path is read-only, False when none is, None when mixed.
	Folders are scanned up to a cap so a huge tree cannot stall the caller."""
	total = 0
	readOnlyCount = 0
	for filePath in _iterFiles(path):
		try:
			if os.path.islink(filePath):
				continue
			total += 1
			if _isReadOnly(filePath):
				readOnlyCount += 1
		except OSError:
			continue
		if total >= READ_ONLY_SCAN_CAP:
			break
	if not total or not readOnlyCount:
		return False
	return True if readOnlyCount == total else None


def setReadOnlyState(path, enabled):
	"""Sets or clears read-only on every file under path. Returns (changedCount, failedCount)."""
	changed = 0
	failed = 0
	for filePath in _iterFiles(path):
		try:
			if os.path.islink(filePath):
				continue
			if _isReadOnly(filePath) != enabled:
				_setReadOnly(filePath, enabled)
				changed += 1
		except OSError as e:
			failed += 1
			log.debug(f"xPlorer: could not change read-only on {filePath}: {e}")
	return changed, failed


def _protectWorker(paths, adopting=False):
	failed = 0
	startedAt = time.time()
	log.debug(f"xPlorer: freezer read-only protection started for {len(paths)} items")
	with _protectLock:
		for path in paths:
			if not _store.hasEntry(path):
				continue
			alreadyReadOnly, pathFailed = _applyReadOnly(path)
			if adopting:
				# Files that are read-only on arrival were locked by an earlier freeze,
				# so only the list recorded back then may stay locked after Unfreeze.
				alreadyReadOnly = _store.skipListOf(path)
			failed += pathFailed
			if not _store.setProtection(path, True, alreadyReadOnly):
				# Unfrozen while the files were being marked: undo straight away.
				failed += _restoreWritable({"path": path, "ro": True, "id": None, "roSkip": alreadyReadOnly})
	log.debug(f"xPlorer: freezer read-only protection finished in {time.time() - startedAt:.2f}s, failed={failed}")
	if failed:
		wx.CallAfter(ui.message, _("{count} files could not be made read-only").format(count=failed))


def _restoreWorker(entries):
	failed = 0
	startedAt = time.time()
	log.debug(f"xPlorer: freezer restore started for {len(entries)} items")
	with _protectLock:
		for entry in entries:
			failed += _restoreWritable(entry)
	log.debug(f"xPlorer: freezer restore finished in {time.time() - startedAt:.2f}s, failed={failed}")
	if failed:
		wx.CallAfter(ui.message, _("{count} files could not be made writable again").format(count=failed))


def protectAsync(paths, adopting=False):
	if paths and _store.readOnlyEnabled:
		threading.Thread(target=_protectWorker, args=(list(paths), adopting), daemon=True, name="xPlorerFreezeProtect").start()


def restoreAsync(entries):
	if entries:
		threading.Thread(target=_restoreWorker, args=(list(entries),), daemon=True, name="xPlorerFreezeRestore").start()


_UNLOCK_POLL_SECONDS = 1.0
_UNLOCK_QUIET_SECONDS = 10.0
_UNLOCK_NO_MATCH_SECONDS = 20.0
_UNLOCK_MAX_SECONDS = 900.0


def _birthTime(info):
	return getattr(info, "st_birthtime", info.st_ctime)


def _copyNameMatchers(sourcePaths):
	matchers = []
	for sourcePath in sourcePaths:
		name = os.path.basename(os.path.normpath(sourcePath))
		stem, extension = os.path.splitext(name)
		matchers.append((name.casefold(), stem.casefold(), extension.casefold()))
	return matchers


def _looksLikeCopy(entryName, matchers):
	folded = entryName.casefold()
	for name, stem, extension in matchers:
		if folded == name or (folded.startswith(stem) and folded.endswith(extension)):
			return True
	return False


def _unlockCopyTree(path, frozenKeys):
	"""Clears read-only on every file under path. Returns (fileCount, unlockedCount)."""
	fileCount = 0
	unlocked = 0
	for filePath in _iterFiles(path):
		fileCount += 1
		try:
			if os.path.islink(filePath) or _isCovered(filePath, frozenKeys):
				continue
			if _isReadOnly(filePath):
				_setReadOnly(filePath, False)
				unlocked += 1
		except OSError as e:
			log.debug(f"xPlorer: could not unlock copied file {filePath}: {e}")
	return fileCount, unlocked


def _unlockCopiesWorker(sourcePaths, destDir, startedAt, exactNames):
	matchers = _copyNameMatchers(sourcePaths)
	sourceKeys = {_keyOf(sourcePath) for sourcePath in sourcePaths}
	begun = time.time()
	lastActivity = begun
	lastFileCount = -1
	totalUnlocked = 0
	while time.time() - begun < _UNLOCK_MAX_SECONDS:
		frozenKeys = set(_store.activeKeys())
		fileCount = 0
		matched = False
		try:
			with os.scandir(destDir) as entries:
				for entry in entries:
					entryKey = _keyOf(entry.path)
					if entryKey in sourceKeys or _isCovered(entry.path, frozenKeys):
						continue
					if exactNames:
						isCopy = any(entry.name.casefold() == matcher[0] for matcher in matchers)
					else:
						isCopy = _looksLikeCopy(entry.name, matchers) and _birthTime(entry.stat()) >= startedAt - 5
					if not isCopy:
						continue
					matched = True
					count, unlocked = _unlockCopyTree(entry.path, frozenKeys)
					fileCount += count
					totalUnlocked += unlocked
					if unlocked:
						lastActivity = time.time()
		except OSError as e:
			log.debug(f"xPlorer: could not scan {destDir} for copies: {e}")
			break
		if fileCount != lastFileCount:
			lastFileCount = fileCount
			lastActivity = time.time()
		now = time.time()
		if matched and now - lastActivity > _UNLOCK_QUIET_SECONDS:
			break
		if not matched and now - begun > _UNLOCK_NO_MATCH_SECONDS:
			break
		time.sleep(_UNLOCK_POLL_SECONDS)
	if totalUnlocked:
		log.debug(f"xPlorer: unlocked {totalUnlocked} copied files in {destDir}")


def unlockCopiesAsync(sourcePaths, destDir, startedAt, exactNames=False):
	"""Makes copies of frozen items writable again. Copies keep the read-only
	attribute of the frozen original, so they are cleared once they appear."""
	if not sourcePaths or not destDir:
		return
	frozenSources = [path for path in sourcePaths if _store.isFrozen(path)]
	if not frozenSources:
		return
	threading.Thread(
		target=_unlockCopiesWorker,
		args=(frozenSources, destDir, startedAt, exactNames),
		daemon=True,
		name="xPlorerFreezeUnlock",
	).start()


def _adoptWorker():
	adopted = _store.adoptForeignVolumes()
	if not adopted:
		return
	log.debug(f"xPlorer: freezer adopted {len(adopted)} entries from another volume")
	protectAsync(adopted, adopting=True)


def adoptForeignVolumesAsync():
	threading.Thread(target=_adoptWorker, daemon=True, name="xPlorerFreezeAdopt").start()


def hasFrozenItems():
	return _store.hasEntries()


def isFrozen(path):
	return _store.isFrozen(path)


def isOperationBlocked(path):
	return _store.isFrozen(path) or _store.containsFrozenDescendant(path)


def filterBlocked(paths):
	if not _store.hasEntries():
		return []
	return [path for path in paths if isOperationBlocked(path)]


def announceBlocked(action, paths):
	if not paths:
		return
	result = _BLOCKED_RESULTS.get(action, _("Action canceled"))
	if len(paths) == 1:
		name = os.path.basename(paths[0].rstrip("\\/")) or paths[0]
		text = _("{name} is frozen. {result}").format(name=name, result=result)
	else:
		text = _("{count} frozen items. {result}").format(count=len(paths), result=result)
	tones.beep(200, 150)
	wx.CallAfter(ui.message, text)


class FreezerDialog(wx.Dialog):
	def __init__(self, parent, manager):
		super().__init__(parent, title=_("Freezer"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._manager = manager
		self._entries = []

		mainSizer = wx.BoxSizer(wx.VERTICAL)
		listLabel = wx.StaticText(self, label=_("&Frozen items:"))
		mainSizer.Add(listLabel, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
		self._list = wx.ListBox(self, style=wx.LB_EXTENDED, size=(560, 280), name=_("Frozen items"))
		mainSizer.Add(self._list, 1, wx.ALL | wx.EXPAND, 10)

		buttonSizer = wx.BoxSizer(wx.HORIZONTAL)
		self._unfreezeButton = wx.Button(self, label=_("&Unfreeze selected"))
		self._unfreezeAllButton = wx.Button(self, label=_("Unfreeze &all"))
		closeButton = wx.Button(self, wx.ID_CANCEL, label=_("&Close"))
		buttonSizer.Add(self._unfreezeButton, 0, wx.RIGHT, 8)
		buttonSizer.Add(self._unfreezeAllButton, 0, wx.RIGHT, 8)
		buttonSizer.Add(closeButton, 0)
		mainSizer.Add(buttonSizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
		self.SetSizerAndFit(mainSizer)
		self.SetEscapeId(wx.ID_CANCEL)

		self._unfreezeButton.Bind(wx.EVT_BUTTON, self._onUnfreezeSelected)
		self._unfreezeAllButton.Bind(wx.EVT_BUTTON, self._onUnfreezeAll)
		self._list.Bind(wx.EVT_CONTEXT_MENU, self._onContextMenu)
		self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
		self.Bind(wx.EVT_CLOSE, self._onClose)
		self.refresh()

	def refresh(self, selectIndex=0):
		self._entries = _store.snapshot()
		labels = []
		for entry in self._entries:
			kind = _("Folder") if entry["folder"] else _("File")
			name = os.path.basename(entry["path"].rstrip("\\/")) or entry["path"]
			label = _("{name}, {kind}, in {location}").format(
				name=name, kind=kind, location=os.path.dirname(entry["path"].rstrip("\\/")) or entry["path"]
			)
			if entry["state"] == STATE_MISSING:
				label = _("{label}, not found").format(label=label)
			elif entry["state"] == STATE_REPLACED:
				label = _("{label}, replaced by another item").format(label=label)
			labels.append(label)
		self._list.Set(labels)
		if labels:
			self._list.SetSelection(min(selectIndex, len(labels) - 1))
		self.SetTitle(_("Freezer - {count} frozen items").format(count=len(labels)))
		hasItems = bool(labels)
		self._unfreezeButton.Enable(hasItems)
		self._unfreezeAllButton.Enable(hasItems)

	def _selectedPaths(self):
		return [self._entries[index]["path"] for index in self._list.GetSelections() if index < len(self._entries)]

	def _onUnfreezeSelected(self, event):
		paths = self._selectedPaths()
		if not paths:
			ui.message(_("No item selected"))
			return
		firstIndex = min(self._list.GetSelections())
		removedEntries, saveOk = _store.remove(paths)
		restoreAsync(removedEntries)
		self.refresh(firstIndex)
		self._manager.onStoreChanged()
		if not saveOk:
			ui.message(_("Could not save the freezer list"))
			return
		ui.message(_("Unfreeze, {count} items").format(count=len(removedEntries)))
		if not self._list.GetCount():
			self._list.SetFocus()

	def _onUnfreezeAll(self, event):
		count = len(self._entries)
		if not count:
			return
		answer = wx.MessageBox(
			_("Unfreeze all {count} items?").format(count=count),
			_("Unfreeze all"), wx.YES_NO | wx.ICON_QUESTION, self
		)
		if answer != wx.YES:
			return
		removedEntries, saveOk = _store.clear()
		restoreAsync(removedEntries)
		self.refresh()
		self._manager.onStoreChanged()
		self._list.SetFocus()
		if not saveOk:
			ui.message(_("Could not save the freezer list"))
			return
		ui.message(_("Unfreeze all, {count} items").format(count=len(removedEntries)))

	def _onContextMenu(self, event):
		if not self._entries:
			return
		menu = wx.Menu()
		unfreezeItem = menu.Append(wx.ID_ANY, _("Unfreeze"))
		unfreezeAllItem = menu.Append(wx.ID_ANY, _("Unfreeze all files and folders"))
		self.Bind(wx.EVT_MENU, self._onUnfreezeSelected, unfreezeItem)
		self.Bind(wx.EVT_MENU, self._onUnfreezeAll, unfreezeAllItem)
		self._list.PopupMenu(menu)
		menu.Destroy()

	def _onCharHook(self, event):
		keyCode = event.GetKeyCode()
		focused = self.FindFocus()
		if focused is self._list:
			if keyCode == wx.WXK_DELETE:
				self._onUnfreezeSelected(None)
				return
			if keyCode == wx.WXK_MENU or (keyCode == wx.WXK_F10 and event.ShiftDown()):
				self._onContextMenu(None)
				return
		event.Skip()

	def _onClose(self, event):
		self._manager.onDialogClosed()
		self.Destroy()


class FreezeManager:
	CACHE_MAX_AGE = 3.0
	MIN_REFRESH_GAP = 0.5
	FREEZING_PAUSE_MS = 120
	LATE_ANNOUNCE_WINDOW = 2.0

	def __init__(self, plugin):
		self.plugin = plugin
		self._shutDown = False
		self._context = None
		self._cacheValid = False
		self._epoch = 0
		self._requestEpoch = 0
		self._cacheTitle = None
		self._cacheTime = 0.0
		self._cacheGeneration = -1
		self._requestTitle = None
		self._folderPath = None
		self._folderFrozen = False
		self._frozenNames = frozenset()
		self._blockedNames = frozenset()
		self._refreshing = False
		self._lastRefreshStart = 0.0
		self._pendingName = None
		self._pendingAt = 0.0
		self._dialog = None
		self._focusBeforeDialog = None
		filter_speechSequence.register(self._filterSpeech)
		adoptForeignVolumesAsync()

	def cleanup(self):
		self._shutDown = True
		self._context = None
		filter_speechSequence.unregister(self._filterSpeech)
		dialog = self._dialog
		self._dialog = None
		if dialog:
			try:
				dialog.Destroy()
			except RuntimeError as e:
				log.debug(f"xPlorer: freezer dialog already destroyed: {e}")

	def hasFrozenItems(self):
		return _store.hasEntries()

	def invalidate(self):
		"""Marks the remembered folder as unknown. Safe to call from any thread."""
		self._epoch += 1
		self._cacheValid = False

	def needsCheck(self, action):
		"""Cheap verdict for the input thread: True when the key must be held
		back and checked against the real selection. Reads plain attributes
		only, so it never touches Explorer or the file system."""
		if not self._cacheValid or self._cacheGeneration != _store.generation:
			return True
		if self._folderFrozen:
			return True
		if action == "paste":
			return False
		return bool(self._blockedNames)

	def onStoreChanged(self):
		self._cacheTime = 0.0
		if self._folderPath and self._cacheValid:
			self._rebuildNames()

	def _currentTitle(self):
		hwnd = winUser.getForegroundWindow()
		return winUser.getWindowText(hwnd) if hwnd else ""

	def _filterSpeech(self, speechSequence):
		name = self._context
		if name is None:
			return speechSequence
		for index, item in enumerate(speechSequence):
			if isinstance(item, str) and item.strip() == name.strip():
				self._context = None
				withMarker = list(speechSequence)
				withMarker[index + 1:index + 1] = [BreakCommand(self.FREEZING_PAUSE_MS), _("Freezing")]
				return withMarker
		return speechSequence

	def endFocus(self):
		self._context = None

	def beginFocus(self, name):
		self._context = None
		self._pendingName = None
		if self._shutDown or not name or not _store.hasEntries():
			return
		viewKnown = self._cacheValid and self._currentTitle() == self._cacheTitle
		if viewKnown and self._cacheGeneration != _store.generation:
			self._rebuildNames()
		if not viewKnown:
			self._cacheValid = False
			self._pendingName = name
			self._pendingAt = time.time()
		if not viewKnown or time.time() - self._cacheTime > self.CACHE_MAX_AGE:
			self._requestRefresh()
		if not viewKnown:
			return
		if self._isNameFrozen(name):
			self._context = name

	def _isNameFrozen(self, name):
		return self._folderFrozen or name.casefold() in self._frozenNames

	def _requestRefresh(self):
		now = time.time()
		if self._refreshing and now - self._lastRefreshStart < 10:
			return
		if now - self._lastRefreshStart < self.MIN_REFRESH_GAP:
			return
		self._refreshing = True
		self._lastRefreshStart = now
		self._requestTitle = self._currentTitle()
		self._requestEpoch = self._epoch
		# The shell-window lookup runs on a worker thread. The breadcrumb walk
		# is skipped because it traverses the UI tree on the main thread.
		self.plugin._getCurrentPathFromExplorerAsync(self._onPathResolved, skipBreadcrumb=True)

	def _onPathResolved(self, folderPath):
		self._refreshing = False
		if self._shutDown or not folderPath:
			return
		self._folderPath = folderPath
		self._cacheTitle = self._requestTitle
		self._cacheTime = time.time()
		self._cacheValid = self._requestEpoch == self._epoch and self._currentTitle() == self._requestTitle
		self._rebuildNames()
		pendingName = self._pendingName
		self._pendingName = None
		if not self._cacheValid or not pendingName or time.time() - self._pendingAt > self.LATE_ANNOUNCE_WINDOW:
			return
		try:
			focusName = api.getFocusObject().name
		except (AttributeError, RuntimeError):
			return
		if focusName == pendingName and self._isNameFrozen(pendingName):
			ui.message(_("Freezing"))

	def _rebuildNames(self):
		self._cacheGeneration = _store.generation
		folderPath = self._folderPath
		if not folderPath:
			self._folderFrozen = False
			self._frozenNames = frozenset()
			self._blockedNames = frozenset()
			return
		self._folderFrozen = _store.isFrozen(folderPath)
		folderPrefix = _withSeparator(_keyOf(folderPath))
		frozenNames = set()
		blockedNames = set()
		for entry in _store.snapshot():
			if entry["state"] != STATE_ACTIVE:
				continue
			entryKey = _keyOf(entry["path"])
			if not entryKey.startswith(folderPrefix):
				continue
			relative = entryKey[len(folderPrefix):]
			firstPart, separator, _rest = relative.partition(os.sep)
			if separator:
				blockedNames.add(firstPart.casefold())
				continue
			childName = os.path.basename(entry["path"].rstrip("\\/")).casefold()
			frozenNames.add(childName)
			blockedNames.add(childName)
			if not entry["folder"]:
				stem = os.path.splitext(childName)[0]
				frozenNames.add(stem)
				blockedNames.add(stem)
		self._frozenNames = frozenset(frozenNames)
		self._blockedNames = frozenset(blockedNames)

	def _blockedByFocusName(self):
		if not self._cacheValid or not self._folderPath:
			return None
		try:
			focusName = api.getFocusObject().name
		except (AttributeError, RuntimeError):
			return None
		if not focusName:
			return None
		if self._folderFrozen or focusName.casefold() in self._blockedNames:
			return [focusName]
		return []

	def guardSelection(self, action, onAllowed, attempt=0):
		if not _store.hasEntries():
			onAllowed()
			return

		def handleSelection(selectedItems, _hwnd):
			if self._shutDown:
				onAllowed()
				return
			if selectedItems is None and attempt < 1:
				core.callLater(150, self.guardSelection, action, onAllowed, attempt + 1)
				return
			try:
				if selectedItems:
					blocked = filterBlocked([path for _name, path in selectedItems])
				else:
					blocked = self._blockedByFocusName()
					if blocked is None:
						log.debug("xPlorer: freeze guard could not resolve the selection, allowing the key")
						blocked = []
			except (OSError, ValueError, TypeError, RuntimeError) as e:
				log.error(f"xPlorer: freeze guard failed, allowing the key: {e}")
				onAllowed()
				return
			log.debug(
				f"xPlorer: freeze guard action={action} selected={selectedItems!r} blocked={blocked!r}"
			)
			if blocked:
				announceBlocked(action, blocked)
				return
			onAllowed()

		self.plugin._getSelectedItemsAsync(handleSelection)

	def guardPaste(self, onAllowed, attempt=0):
		if not _store.hasEntries():
			onAllowed()
			return
		if self._cacheValid and self._folderPath:
			if self._cacheGeneration != _store.generation:
				self._rebuildNames()
			if self._folderFrozen:
				announceBlocked("paste", [self._folderPath])
				return
			onAllowed()
			return

		def handlePath(folderPath):
			if self._shutDown:
				onAllowed()
				return
			if not folderPath:
				if attempt < 1:
					core.callLater(150, self.guardPaste, onAllowed, attempt + 1)
					return
				log.debug("xPlorer: freeze guard could not resolve the folder, allowing the paste")
				onAllowed()
				return
			if _store.isFrozen(folderPath):
				announceBlocked("paste", [folderPath])
				return
			onAllowed()

		self.plugin._getCurrentPathFromExplorerAsync(handlePath, skipBreadcrumb=True)

	def watchPaste(self, startedAt):
		# Called from the key hook thread, so only hand the work to the main thread.
		wx.CallAfter(self._readPasteSources, startedAt, 0)

	def _readPasteSources(self, startedAt, attempt):
		if self._shutDown:
			return
		fileData = wx.FileDataObject()
		sources = []
		if wx.TheClipboard.Open():
			try:
				if wx.TheClipboard.GetData(fileData):
					sources = list(fileData.GetFilenames())
			finally:
				wx.TheClipboard.Close()
		elif attempt < 2:
			core.callLater(100, self._readPasteSources, startedAt, attempt + 1)
			return
		frozenSources = [path for path in sources if _store.isFrozen(path)]
		if not frozenSources:
			return
		self.plugin._getCurrentPathFromExplorerAsync(
			lambda folderPath: unlockCopiesAsync(frozenSources, folderPath, startedAt),
			skipBreadcrumb=True,
		)

	def freezeSelected(self):
		self.plugin._getSelectedItemsAsync(self._onFreezeSelection)

	def _onFreezeSelection(self, selectedItems, _hwnd):
		if not selectedItems:
			ui.message(_("No items selected"))
			return
		refusedNames = [name for name, path in selectedItems if isProtectedLocation(path)]
		allowedPaths = [path for _name, path in selectedItems if not isProtectedLocation(path)]
		if refusedNames and not allowedPaths:
			tones.beep(200, 150)
			ui.message(_("{name} is a system location and cannot be frozen").format(name=refusedNames[0]))
			return
		addedPaths, saveOk = _store.add(allowedPaths)
		added = len(addedPaths)
		protectAsync(addedPaths)
		self._afterStoreChange()
		if refusedNames:
			ui.message(_("{count} system locations skipped").format(count=len(refusedNames)))
		if not saveOk:
			ui.message(_("Could not save the freezer list"))
			return
		if not added:
			ui.message(_("Already frozen"))
			return
		tones.beep(600, 80)
		if added == 1:
			ui.message(_("Freeze"))
		else:
			ui.message(_("Freeze, {count} items").format(count=added))

	def unfreezeSelected(self):
		self.plugin._getSelectedItemsAsync(self._onUnfreezeSelection)

	def _onUnfreezeSelection(self, selectedItems, _hwnd):
		if not selectedItems:
			ui.message(_("No items selected"))
			return
		paths = [path for _name, path in selectedItems]
		removedEntries, saveOk = _store.remove(paths)
		removed = len(removedEntries)
		restoreAsync(removedEntries)
		self._afterStoreChange()
		if not saveOk:
			ui.message(_("Could not save the freezer list"))
			return
		if removed:
			tones.beep(400, 80)
			if removed == 1:
				ui.message(_("Unfreeze"))
			else:
				ui.message(_("Unfreeze, {count} items").format(count=removed))
			return
		if any(_store.isFrozen(path) for path in paths):
			ui.message(_("Frozen by a parent folder. Unfreeze the parent folder instead"))
			return
		ui.message(_("Not frozen"))

	def _afterStoreChange(self):
		self.onStoreChanged()
		if self._dialog:
			try:
				self._dialog.refresh()
			except RuntimeError:
				self._dialog = None

	def showDialog(self):
		if self._shutDown:
			return
		if self._dialog:
			try:
				self._dialog.Raise()
				self._dialog.SetFocus()
				return
			except RuntimeError:
				self._dialog = None
		self._focusBeforeDialog = api.getFocusObject()
		gui.mainFrame.prePopup()
		dialog = FreezerDialog(gui.mainFrame, self)
		self._dialog = dialog
		dialog.CentreOnScreen()
		dialog.Show()
		dialog.Raise()
		core.callLater(250, self._announceDialogOpened)

	def _announceDialogOpened(self):
		if self._dialog and not _store.hasEntries():
			ui.message(_("The freezer is empty"))

	def onDialogClosed(self):
		self._dialog = None
		gui.mainFrame.postPopup()
		previousFocus = self._focusBeforeDialog
		self._focusBeforeDialog = None
		if previousFocus:
			core.callLater(150, self._restoreFocus, previousFocus)

	def _restoreFocus(self, focusObject):
		try:
			focusObject.setFocus()
		except (AttributeError, RuntimeError, OSError) as e:
			log.debug(f"xPlorer: could not restore focus after the freezer dialog: {e}")
