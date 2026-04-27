# config.py

import os
import json
from logHandler import log

CONFIG_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "nvda", "ChaiChaimee")
CONFIG_FILE = os.path.join(CONFIG_DIR, "xplorer.json")

DEFAULT_CONFIG = {
	"autoSelectFirstItem": True,
	"announceEmptyFolder": True,
	"suppressDirectUIAnnounce": True,
	"sayFileExplorer": True,
	"autoPasteClipboardToRename": True,
}

def loadConfig():
	if not os.path.exists(CONFIG_FILE):
		return DEFAULT_CONFIG.copy()
	try:
		with open(CONFIG_FILE, "r", encoding="utf-8") as f:
			conf = json.load(f)
		for key, value in DEFAULT_CONFIG.items():
			if key not in conf:
				conf[key] = value
		return conf
	except Exception as e:
		log.error(f"Error loading config: {e}")
		return DEFAULT_CONFIG.copy()

def saveConfig(conf):
	try:
		if not os.path.exists(CONFIG_DIR):
			os.makedirs(CONFIG_DIR)
		with open(CONFIG_FILE, "w", encoding="utf-8") as f:
			json.dump(conf, f, indent=2, ensure_ascii=False)
	except Exception as e:
		log.error(f"Error saving config: {e}")