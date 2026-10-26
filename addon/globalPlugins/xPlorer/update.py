# update.py

import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import urllib.error
import urllib.request

import addonHandler
import globalVars
import gui
import ui
import wx
from logHandler import log

addonHandler.initTranslation()

GITHUB_OWNER = "chaichaimee"
# Wait after load before the first request, so a slow network at boot has time to come up.
STARTUP_DELAY_SECONDS = 30
# Extra attempts after a failed request, each preceded by this wait.
RETRY_DELAYS_SECONDS = (60, 180, 600)
REQUEST_TIMEOUT_SECONDS = 20
MAX_RELEASE_JSON_BYTES = 1024 * 1024
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
STATE_FILENAME = "updateCheck.json"

_GITHUB_PREFIX = "https://github.com/" + GITHUB_OWNER + "/"
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_VERSION_TEXT_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$")

_checker = None


def _versionKey(text):
	key = [int(n) for n in re.findall(r"\d+", text or "")]
	while key and key[-1] == 0:
		key.pop()
	return tuple(key)


def _isNewer(latest, installed):
	latestKey = _versionKey(latest)
	return bool(latestKey) and latestKey > _versionKey(installed)


def _releasesPageUrl(addonName):
	return "{}{}/releases".format(_GITHUB_PREFIX, addonName)


def _parseRelease(release, addonName):
	if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
		return None
	version = str(release.get("tag_name", "")).lstrip("vV")
	if not _VERSION_TEXT_RE.match(version):
		return None
	pageUrl = str(release.get("html_url", ""))
	if not pageUrl.startswith(_GITHUB_PREFIX):
		pageUrl = _releasesPageUrl(addonName)
	assets = [
		a for a in (release.get("assets") or [])
		if isinstance(a, dict)
		and str(a.get("name", "")).lower().endswith(".nvda-addon")
		and str(a.get("browser_download_url", "")).startswith(_GITHUB_PREFIX)
	]
	asset = next((a for a in assets if a["name"].lower() == addonName.lower() + ".nvda-addon"), None)
	if asset is None and assets:
		asset = assets[0]
	assetUrl = asset["browser_download_url"] if asset else ""
	digest = str(asset.get("digest") or "") if asset else ""
	sha256 = digest[len("sha256:"):] if digest.startswith("sha256:") else ""
	return {"version": version, "pageUrl": pageUrl, "assetUrl": assetUrl, "sha256": sha256}


def _statePath(addonName):
	return os.path.join(globalVars.appArgs.configPath, "ChaiChaimee", addonName, STATE_FILENAME)


def _loadState(path):
	try:
		with open(path, "r", encoding="utf-8") as stateFile:
			state = json.load(stateFile)
	except FileNotFoundError:
		return {}
	except (OSError, ValueError):
		log.debugWarning("update: state file unreadable, starting fresh", exc_info=True)
		return {}
	return state if isinstance(state, dict) else {}


def _saveState(path, state):
	tempPath = path + ".tmp"
	try:
		os.makedirs(os.path.dirname(path), exist_ok=True)
		with open(tempPath, "w", encoding="utf-8") as stateFile:
			json.dump(state, stateFile)
			stateFile.flush()
			os.fsync(stateFile.fileno())
		if os.path.exists(path):
			shutil.copyfile(path, path + ".bak")
		os.replace(tempPath, path)
	except OSError:
		log.error("update: could not save state file", exc_info=True)


def _request(url, addonName):
	return urllib.request.Request(url, headers={
		"User-Agent": addonName + "-nvda-addon",
		"Accept": "application/vnd.github+json",
	})


def _fetchLatestRelease(addonName):
	url = "https://api.github.com/repos/{}/{}/releases/latest".format(GITHUB_OWNER, addonName)
	with urllib.request.urlopen(_request(url, addonName), timeout=REQUEST_TIMEOUT_SECONDS) as response:
		raw = response.read(MAX_RELEASE_JSON_BYTES)
	return _parseRelease(json.loads(raw.decode("utf-8")), addonName)


def _removeQuietly(path):
	try:
		os.remove(path)
	except OSError:
		pass


def _download(assetUrl, sha256, addonName):
	path = os.path.join(tempfile.gettempdir(), addonName + "-update.nvda-addon")
	digest = hashlib.sha256()
	received = 0
	try:
		with urllib.request.urlopen(_request(assetUrl, addonName), timeout=REQUEST_TIMEOUT_SECONDS) as response:
			with open(path, "wb") as outFile:
				while True:
					chunk = response.read(65536)
					if not chunk:
						break
					received += len(chunk)
					if received > MAX_DOWNLOAD_BYTES:
						raise ValueError("download exceeds size limit")
					digest.update(chunk)
					outFile.write(chunk)
		if sha256 and digest.hexdigest().lower() != sha256.lower():
			raise ValueError("checksum mismatch")
	except (OSError, ValueError):
		_removeQuietly(path)
		raise
	return path


class _UpdateDialog(wx.Dialog):
	def __init__(self, parent, addonName, installedVersion, newVersion):
		# Translators: Title of the add-on update dialog. {name} is the add-on name.
		super().__init__(parent, title=_("{name} update").format(name=addonName))
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		message = wx.StaticText(
			self,
			# Translators: Text of the add-on update dialog.
			label=_("{name} {new} is available (installed: {old}).\nUpdate now?").format(
				name=addonName, new=newVersion, old=installedVersion
			),
		)
		mainSizer.Add(message, 0, wx.ALL, 10)
		buttonSizer = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: Button of the add-on update dialog.
		updateButton = wx.Button(self, wx.ID_OK, label=_("&Update now"))
		# Translators: Button of the add-on update dialog. Escape does the same.
		laterButton = wx.Button(self, wx.ID_CANCEL, label=_("&Later"))
		buttonSizer.Add(updateButton, 0, wx.ALL, 5)
		buttonSizer.Add(laterButton, 0, wx.ALL, 5)
		mainSizer.Add(buttonSizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
		self.SetSizerAndFit(mainSizer)
		self.SetAffirmativeId(wx.ID_OK)
		self.SetEscapeId(wx.ID_CANCEL)
		updateButton.SetDefault()
		self.CenterOnScreen()
		updateButton.SetFocus()


class _UpdateChecker:
	def __init__(self, addonName, installedVersion):
		self._addonName = addonName
		self._installedVersion = installedVersion
		self._statePath = _statePath(addonName)
		self._stopEvent = threading.Event()

	def start(self):
		threading.Thread(target=self._run, name=self._addonName + ".updateCheck", daemon=True).start()

	def stop(self):
		self._stopEvent.set()

	def _fetchWithRetry(self):
		"""Returns (succeeded, release). A 404 means no release is published, which is a valid answer."""
		for delay in (0,) + RETRY_DELAYS_SECONDS:
			if delay and self._stopEvent.wait(delay):
				return False, None
			try:
				return True, _fetchLatestRelease(self._addonName)
			except urllib.error.HTTPError as e:
				if e.code == 404:
					return True, None
				log.debugWarning("update: HTTP %s while checking for a release", e.code)
			except (OSError, ValueError):
				log.debugWarning("update: release check failed", exc_info=True)
		return False, None

	def _run(self):
		if self._stopEvent.wait(STARTUP_DELAY_SECONDS):
			return
		today = datetime.date.today().isoformat()
		state = _loadState(self._statePath)
		if state.get("lastCheckDate") == today:
			return
		succeeded, release = self._fetchWithRetry()
		if not succeeded or self._stopEvent.is_set():
			return
		state["lastCheckDate"] = today
		_saveState(self._statePath, state)
		if release and _isNewer(release["version"], self._installedVersion):
			wx.CallAfter(self._offer, release)

	def _offer(self, release):
		if self._stopEvent.is_set():
			return
		dialog = _UpdateDialog(gui.mainFrame, self._addonName, self._installedVersion, release["version"])
		gui.mainFrame.prePopup()
		try:
			answer = dialog.ShowModal()
		finally:
			dialog.Destroy()
			gui.mainFrame.postPopup()
		if answer != wx.ID_OK:
			return
		if not release["assetUrl"]:
			wx.LaunchDefaultBrowser(release["pageUrl"])
			return
		# Translators: Reported while the add-on update downloads.
		ui.message(_("Downloading {name} {version}").format(name=self._addonName, version=release["version"]))
		threading.Thread(
			target=self._install, args=(release,), name=self._addonName + ".updateDownload", daemon=True
		).start()

	def _install(self, release):
		try:
			path = _download(release["assetUrl"], release["sha256"], self._addonName)
		except (OSError, ValueError):
			log.error("update: downloading the add-on failed", exc_info=True)
			# Translators: Reported when the add-on update cannot be downloaded. The releases page opens instead.
			wx.CallAfter(ui.message, _("Could not download the update. Opening the releases page."))
			wx.CallAfter(wx.LaunchDefaultBrowser, release["pageUrl"])
			return
		wx.CallAfter(self._handOver, path, release["pageUrl"])

	def _handOver(self, path, pageUrl):
		# NVDA's own add-on installation takes over: confirmation, install, restart prompt.
		try:
			from gui import addonGui
			addonGui.handleRemoteAddonInstall(path)
		except (ImportError, AttributeError, TypeError):
			log.error("update: NVDA add-on installer entry point unavailable", exc_info=True)
			wx.LaunchDefaultBrowser(pageUrl)


def start():
	"""Starts the once-a-day release check for the add-on that contains this module.

	Call from the GlobalPlugin constructor, so the add-on can be identified from the call site.
	"""
	global _checker
	if _checker is not None or getattr(globalVars.appArgs, "secure", False):
		return
	try:
		addon = addonHandler.getCodeAddon()
		addonName = addon.name
		installedVersion = addon.version
		fromStore = getattr(addon, "_addonStoreData", None) is not None
	except Exception:
		# getCodeAddon raises when the caller is not inside an add-on package.
		log.debugWarning("update: could not identify the running add-on", exc_info=True)
		return
	if fromStore or not _NAME_RE.match(addonName):
		return
	_checker = _UpdateChecker(addonName, installedVersion)
	_checker.start()


def stop():
	global _checker
	if _checker is not None:
		_checker.stop()
	_checker = None
