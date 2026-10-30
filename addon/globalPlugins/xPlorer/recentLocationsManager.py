# recentLocationsManager.py

import os
import json
import time
import threading
import ui
import addonHandler
from logHandler import log
from .folderTools import CONFIG_DIR
from .explorerWindow import launchExplorer

addonHandler.initTranslation()

XPLORER_CONFIG_DIR = CONFIG_DIR
RECENT_LOCATIONS_FILE = os.path.join(XPLORER_CONFIG_DIR, "recent_locations.json")
# CONFIG_DIR itself used to resolve to a shared, incorrectly-rooted
# ChaiChaimee folder (see folderTools.py) with no per-addon separation at
# all - migrate forward from that real old location if anything is there.
_OLD_CONFIG_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "nvda", "ChaiChaimee")
_OLD_RECENT_LOCATIONS_FILE = os.path.join(_OLD_CONFIG_DIR, "xPlorer", "recent_locations.json")
MAX_RECENT_LOCATIONS = 100
_RECORD_MIN_INTERVAL_SECONDS = 1.5


class RecentLocationsManager:
	"""Maintains a rolling list of the last MAX_RECENT_LOCATIONS unique
	folder paths the user has visited in Explorer, exposed as a submenu so
	the user can jump straight back to a previous working directory instead
	of navigating there manually. recordPath() is called frequently (once
	per resolved Explorer path), so it stays cheap: an in-memory
	last-recorded check avoids most disk writes, and any write that does
	happen runs on a background thread.

	Entries can be pinned so they survive both the recency cap and the
	right-click "clear all" action, and the path shown in the menu can be
	displayed either normally or with its segments reversed (useful for
	very long paths in the narrow menu dialog) - both preferences persist
	alongside the location list itself."""

	def __init__(self, plugin):
		self.plugin = plugin
		self._lastRecordedPath = None
		self._lastRecordedTime = 0.0
		self._writeLock = threading.Lock()
		self._migrateOldConfigLocation()

	def cleanup(self):
		self._lastRecordedPath = None

	def _migrateOldConfigLocation(self):
		"""Moves recent_locations.json from the old, incorrectly-rooted
		per-user config folder (NVDA's actual active userConfig path was
		never consulted, so this pointed outside the current NVDA profile
		entirely) into the correct userConfig\\ChaiChaimee\\xPlorer folder.
		Runs once - if the new file already exists, or there is nothing to
		migrate, this is a no-op."""
		try:
			if os.path.exists(RECENT_LOCATIONS_FILE):
				return
			if not os.path.exists(_OLD_RECENT_LOCATIONS_FILE):
				return
			if not os.path.exists(XPLORER_CONFIG_DIR):
				os.makedirs(XPLORER_CONFIG_DIR)
			with open(_OLD_RECENT_LOCATIONS_FILE, "r", encoding="utf-8") as f:
				oldContent = f.read()
			with open(RECENT_LOCATIONS_FILE, "w", encoding="utf-8") as f:
				f.write(oldContent)
			os.remove(_OLD_RECENT_LOCATIONS_FILE)
		except OSError as e:
			log.error(f"Error migrating recent locations file: {e}")

	def recordPath(self, path):
		if not path or not os.path.isdir(path):
			return

		normalizedPath = os.path.normcase(os.path.normpath(path))
		currentTime = time.time()
		if normalizedPath == self._lastRecordedPath and currentTime - self._lastRecordedTime < _RECORD_MIN_INTERVAL_SECONDS:
			return
		self._lastRecordedPath = normalizedPath
		self._lastRecordedTime = currentTime

		threading.Thread(target=self._moveToFront, args=(path,), daemon=True).start()

	def _moveToFront(self, path):
		"""Moves path to the front of the stored list, carrying over its
		pinned flag if it was already tracked. Used both when Explorer
		navigates to a new folder (recordPath) and when a recent-location
		entry is opened from the menu (openLocation) - either way, using a
		location makes it the newest one again. Pinning itself never calls
		this - see togglePin."""
		with self._writeLock:
			data = self._loadData()
			locations = data.get("locations", [])
			normalizedPath = os.path.normcase(os.path.normpath(path))

			existingPinned = False
			remaining = []
			for entry in locations:
				if os.path.normcase(os.path.normpath(entry.get("path", ""))) == normalizedPath:
					existingPinned = entry.get("pinned", False)
					continue
				remaining.append(entry)

			remaining.insert(0, {"path": path, "pinned": existingPinned})
			data["locations"] = self._trimToMax(remaining)
			self._saveData(data)

	def _trimToMax(self, entries):
		if len(entries) <= MAX_RECENT_LOCATIONS:
			return entries
		pinnedEntries = [entry for entry in entries if entry.get("pinned")]
		unpinnedEntries = [entry for entry in entries if not entry.get("pinned")]
		allowedUnpinnedCount = max(0, MAX_RECENT_LOCATIONS - len(pinnedEntries))
		keptUnpinned = unpinnedEntries[:allowedUnpinnedCount]
		keptIds = {id(entry) for entry in pinnedEntries} | {id(entry) for entry in keptUnpinned}
		return [entry for entry in entries if id(entry) in keptIds]

	def _loadData(self):
		if not os.path.exists(RECENT_LOCATIONS_FILE):
			return {"locations": [], "reverseDisplay": False}
		try:
			with open(RECENT_LOCATIONS_FILE, "r", encoding="utf-8") as f:
				raw = json.load(f)
		except (OSError, ValueError) as e:
			log.error(f"Error loading recent locations: {e}")
			return {"locations": [], "reverseDisplay": False}

		if isinstance(raw, list):
			# Legacy format: a plain list of path strings, no pin data.
			locations = [{"path": p, "pinned": False} for p in raw if isinstance(p, str)]
			return {"locations": locations, "reverseDisplay": False}

		if isinstance(raw, dict):
			locations = raw.get("locations", [])
			normalizedLocations = []
			for entry in locations:
				if isinstance(entry, str):
					normalizedLocations.append({"path": entry, "pinned": False})
				elif isinstance(entry, dict) and entry.get("path"):
					normalizedLocations.append({"path": entry["path"], "pinned": bool(entry.get("pinned", False))})
			return {"locations": normalizedLocations, "reverseDisplay": bool(raw.get("reverseDisplay", False))}

		return {"locations": [], "reverseDisplay": False}

	def _saveData(self, data):
		try:
			if not os.path.exists(XPLORER_CONFIG_DIR):
				os.makedirs(XPLORER_CONFIG_DIR)
			with open(RECENT_LOCATIONS_FILE, "w", encoding="utf-8") as f:
				json.dump(data, f, indent=2, ensure_ascii=False)
		except OSError as e:
			log.error(f"Error saving recent locations: {e}")

	def getRecentLocations(self):
		"""Returns (path, pinned) tuples for entries that still exist on
		disk, in stored order (newest first). Pinning does not reorder the
		list - a pinned entry stays where it naturally falls by recency; it
		only survives Clear All and the recency-cap trim. An entry only
		jumps back to the front when it is actually used again, via
		recordPath or openLocation."""
		data = self._loadData()
		existingEntries = [entry for entry in data.get("locations", []) if os.path.isdir(entry.get("path", ""))]
		return [(entry["path"], entry.get("pinned", False)) for entry in existingEntries]

	def isPinned(self, path):
		normalizedPath = os.path.normcase(os.path.normpath(path))
		data = self._loadData()
		for entry in data.get("locations", []):
			if os.path.normcase(os.path.normpath(entry.get("path", ""))) == normalizedPath:
				return entry.get("pinned", False)
		return False

	def togglePin(self, path):
		"""Flips the pinned state of the given path and returns the new
		state. If the path is somehow no longer tracked, it is added as
		pinned."""
		with self._writeLock:
			data = self._loadData()
			normalizedPath = os.path.normcase(os.path.normpath(path))
			newPinnedState = True
			found = False
			for entry in data.get("locations", []):
				if os.path.normcase(os.path.normpath(entry.get("path", ""))) == normalizedPath:
					entry["pinned"] = not entry.get("pinned", False)
					newPinnedState = entry["pinned"]
					found = True
					break
			if not found:
				data.setdefault("locations", []).insert(0, {"path": path, "pinned": True})
			self._saveData(data)
			return newPinnedState

	def clearAllUnpinned(self):
		with self._writeLock:
			data = self._loadData()
			data["locations"] = [entry for entry in data.get("locations", []) if entry.get("pinned")]
			self._saveData(data)

	def getReverseDisplay(self):
		return bool(self._loadData().get("reverseDisplay", False))

	def setReverseDisplay(self, value):
		with self._writeLock:
			data = self._loadData()
			data["reverseDisplay"] = bool(value)
			self._saveData(data)

	def formatDisplayPath(self, path, reverseDisplay=None):
		if reverseDisplay is None:
			reverseDisplay = self.getReverseDisplay()
		if not reverseDisplay:
			return path
		segments = [segment for segment in path.split("\\") if segment]
		if not segments:
			return path
		return "\\".join(reversed(segments))

	def openLocation(self, path):
		if not os.path.isdir(path):
			ui.message(_("This folder no longer exists: {0}").format(path))
			return
		try:
			launchExplorer([path])
		except OSError as e:
			log.error(f"Error opening recent location {path}: {e}")
			ui.message(_("Error opening folder"))
			return
		threading.Thread(target=self._moveToFront, args=(path,), daemon=True).start()

