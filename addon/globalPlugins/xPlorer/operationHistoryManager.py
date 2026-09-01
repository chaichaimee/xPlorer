# operationHistoryManager.py

import os
import json
import datetime
import threading
import wx
import gui
import gui.guiHelper
import ui
import addonHandler
from logHandler import log
from .folderTools import CONFIG_DIR

addonHandler.initTranslation()

HISTORY_FILE = os.path.join(CONFIG_DIR, "operation_history.json")
MAX_HISTORY_ENTRIES = 200


class OperationHistoryDialog(wx.Dialog):
	"""Read-only, accessible list of recent xPlorer operations, most recent
	first. Plain wx.ListBox so NVDA reads each entry normally on arrow."""

	def __init__(self, parent, entries):
		super().__init__(parent, title=_("Operation History"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.entries = entries
		self._init_ui()
		self.Bind(wx.EVT_CLOSE, self._on_close)

	def _init_ui(self):
		s_helper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		label = wx.StaticText(self, label=_("Recent operations (most recent first):"))
		s_helper.addItem(label)

		choices = [self._formatEntry(entry) for entry in self.entries]
		if not choices:
			choices = [_("No operations recorded yet")]
		self.history_list = wx.ListBox(self, choices=choices, size=(500, 300))
		s_helper.addItem(self.history_list, flag=wx.EXPAND, proportion=1)

		btn_sizer = wx.StdDialogButtonSizer()
		self.clear_btn = wx.Button(self, label=_("Clear History"))
		btn_sizer.AddButton(self.clear_btn)
		self.close_btn = wx.Button(self, wx.ID_CANCEL, label=_("Close"))
		btn_sizer.AddButton(self.close_btn)
		btn_sizer.Realize()
		s_helper.addItem(btn_sizer, flag=wx.ALIGN_CENTER)

		self.SetSizer(s_helper.sizer)
		s_helper.sizer.Fit(self)
		self.CentreOnScreen()

		self.clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
		self.close_btn.Bind(wx.EVT_BUTTON, self._on_close_button)
		self.history_list.SetFocus()

	def _formatEntry(self, entry):
		timestampText = entry.get("timestamp", "")
		try:
			dt = datetime.datetime.fromisoformat(timestampText)
			timestampText = dt.strftime("%H:%M:%S")
		except ValueError:
			pass
		return f"{timestampText} - {entry.get('description', '')}"

	def _on_clear(self, event):
		self.entries = []
		self.history_list.Set([_("No operations recorded yet")])
		clearHistory()
		ui.message(_("Operation history cleared"))

	def _on_close_button(self, event):
		self.EndModal(wx.ID_CANCEL)

	def _on_close(self, event):
		self.EndModal(wx.ID_CANCEL)


def _loadHistory():
	if not os.path.exists(HISTORY_FILE):
		return []
	try:
		with open(HISTORY_FILE, "r", encoding="utf-8") as f:
			data = json.load(f)
		if isinstance(data, list):
			return data
		return []
	except (OSError, ValueError) as e:
		log.error(f"Error loading operation history: {e}")
		return []


def _saveHistory(entries):
	try:
		if not os.path.exists(CONFIG_DIR):
			os.makedirs(CONFIG_DIR)
		with open(HISTORY_FILE, "w", encoding="utf-8") as f:
			json.dump(entries, f, indent=2, ensure_ascii=False)
	except OSError as e:
		log.error(f"Error saving operation history: {e}")


def clearHistory():
	_saveHistory([])


class OperationHistoryManager:
	"""Central append-only log of significant xPlorer operations (renames,
	copies, deletions, etc.), used to give the user a clear audit trail and
	to back the Undo feature. Persisting is offloaded to a background
	thread since it happens on the tail of otherwise-fast user actions and
	should never introduce a perceptible pause."""

	def __init__(self, plugin):
		self.plugin = plugin
		self.dialog = None
		self._writeLock = threading.Lock()

	def cleanup(self):
		if self.dialog:
			try:
				self.dialog.Destroy()
			except RuntimeError:
				pass
			self.dialog = None

	def addEntry(self, description):
		if not description:
			return

		def do_add():
			with self._writeLock:
				entries = _loadHistory()
				entries.insert(0, {
					"timestamp": datetime.datetime.now().isoformat(),
					"description": description,
				})
				entries = entries[:MAX_HISTORY_ENTRIES]
				_saveHistory(entries)

		threading.Thread(target=do_add, daemon=True).start()

	def show_dialog(self):
		def do_show():
			entries = _loadHistory()
			self.dialog = OperationHistoryDialog(gui.mainFrame, entries)
			gui.mainFrame.prePopup()
			try:
				self.dialog.ShowModal()
			finally:
				gui.mainFrame.postPopup()
				self.dialog.Destroy()
				self.dialog = None

		wx.CallAfter(do_show)

