# __init__.py

import globalPluginHandler
import ui
import api
import scriptHandler
from NVDAObjects import NVDAObject
from NVDAObjects.UIA import UIA
from controlTypes import Role, State
import addonHandler
from comtypes.client import CreateObject
from logHandler import log
import gui
import wx
import gui.guiHelper
from .config import loadConfig, saveConfig
from keyboardHandler import KeyboardInputGesture
import core
from threading import Timer, Thread
import winUser
import os
import sys
import subprocess
import shutil
import tones
import urllib.parse
import time
from .xPlorerManager import xPlorerSettingsPanel, ExplorerManager
from .fileOperations import FileOperations
from .compressionManager import CompressionManager
from .clipboardManager import ClipboardManager
from .selectionManager import SelectionManager
from .robocopyManager import RobocopyManager
from .txt2folder import TxtToFolder
from .createFile import CreateFileManager
from .contextMenu import ContextMenuManager

addonHandler.initTranslation()

# Global variables for double-tap detection with timer cancellation
_last_tap_time_compress = 0
_tap_count_compress = 0
_compress_timer = None

_last_tap_time_copy = 0
_tap_count_copy = 0
_copy_timer = None

_last_tap_time_invert = 0
_tap_count_invert = 0
_invert_timer = None

_double_tap_threshold = 0.3  # seconds

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = _("xPlorer")
    
    def __init__(self):
        super().__init__()
        self.objShellApp = CreateObject("Shell.Application")
        self.objFSO = CreateObject("scripting.FileSystemObject")
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(xPlorerSettingsPanel)
        self.manager = ExplorerManager(self)
        self.fileOps = FileOperations(self)
        self.compression = CompressionManager(self)
        self.clipboard = ClipboardManager(self)
        self.selection = SelectionManager(self)
        self.robocopy = RobocopyManager(self)
        self.txt2folder = TxtToFolder(self)
        self.createFileManager = CreateFileManager(self)
        self.contextMenuManager = ContextMenuManager(self)
        
        # Cache for better performance
        self._last_window = None
        self._last_window_hwnd = None
        self._last_window_time = 0
        self._last_path = None
        
        # Lazy import for striprtf to avoid startup delay
        self._striprtf_available = None
        tools_dir = os.path.join(os.path.dirname(__file__), "tools")
        if os.path.exists(tools_dir) and tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)

    def terminate(self):
        super().terminate()
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(xPlorerSettingsPanel)
        self.fileOps.cleanup()
        self.compression.cleanup()
        self.selection.cleanup()
        self.robocopy.cleanup()
        self.createFileManager.cleanup()
        
        # Cancel any pending timers
        self._cancelAllTimers()

    def _cancelAllTimers(self):
        """Cancel all pending timer callbacks"""
        global _compress_timer, _copy_timer, _invert_timer
        
        if _compress_timer:
            _compress_timer.Stop()
            _compress_timer = None
        
        if _copy_timer:
            _copy_timer.Stop()
            _copy_timer = None
            
        if _invert_timer:
            _invert_timer.Stop()
            _invert_timer = None

    def _getStriprtfModule(self):
        """Lazy import striprtf module to avoid startup delay"""
        if self._striprtf_available is None:
            try:
                from striprtf.striprtf import rtf_to_text
                self._striprtf_available = rtf_to_text
                log.info("striprtf module loaded successfully")
            except ImportError:
                log.warning("striprtf module not available")
                self._striprtf_available = False
            except Exception as e:
                log.error(f"Error loading striprtf: {e}")
                self._striprtf_available = False
        return self._striprtf_available

    def _getCurrentPathFromExplorer(self):
        """Get current opened folder path from Windows Explorer address bar using multiple reliable methods"""
        try:
            fg = api.getForegroundObject()
            if not fg or not fg.appModule or fg.appModule.appName != "explorer":
                return None

            shell = CreateObject("Shell.Application")
            if not shell:
                return None

            # Get target window handle
            target_hwnd = fg.windowHandle
            
            # First, try to find exact hwnd match with visible Explorer window
            for window in shell.Windows():
                try:
                    if not window or window.hwnd != target_hwnd:
                        continue

                    # Method 1: Primary - Document.Folder.Self.Path (most reliable for current tab)
                    if hasattr(window, "Document") and window.Document:
                        folder = window.Document.Folder
                        if folder and hasattr(folder, "Self"):
                            path = folder.Self.Path
                            if path and os.path.isdir(path):
                                # Cache this window
                                self._last_window = window
                                self._last_window_hwnd = window.hwnd
                                self._last_window_time = time.time()
                                return os.path.normpath(path)

                    # Method 2: Fallback - LocationURL (file:/// protocol)
                    if hasattr(window, "LocationURL") and window.LocationURL:
                        url = window.LocationURL
                        if url.startswith("file:///"):
                            # Convert file:///C:/Users/... to C:\Users\...
                            path = urllib.parse.unquote(url[8:])  # remove file:///
                            path = path.replace("/", "\\")
                            if os.path.isdir(path):
                                # Cache this window
                                self._last_window = window
                                self._last_window_hwnd = window.hwnd
                                self._last_window_time = time.time()
                                return os.path.normpath(path)

                    # Method 3: Very last resort - LocationName if it's a full path
                    if hasattr(window, "LocationName") and window.LocationName:
                        possible_path = window.LocationName
                        if os.path.isabs(possible_path) and os.path.isdir(possible_path):
                            # Cache this window
                            self._last_window = window
                            self._last_window_hwnd = window.hwnd
                            self._last_window_time = time.time()
                            return os.path.normpath(possible_path)

                except Exception:
                    continue

            # Fallback using focus object instead of foreground
            focus = api.getFocusObject()
            if focus and focus.appModule and focus.appModule.appName == "explorer":
                focus_hwnd = focus.windowHandle
                for window in shell.Windows():
                    try:
                        if not window or window.hwnd != focus_hwnd:
                            continue
                        
                        # Method 1: Primary - Document.Folder.Self.Path (most reliable for current tab)
                        if hasattr(window, "Document") and window.Document:
                            folder = window.Document.Folder
                            if folder and hasattr(folder, "Self"):
                                path = folder.Self.Path
                                if path and os.path.isdir(path):
                                    # Cache this window
                                    self._last_window = window
                                    self._last_window_hwnd = window.hwnd
                                    self._last_window_time = time.time()
                                    return os.path.normpath(path)
                    except Exception:
                        continue

            # If we have a cached window from recent activity, try it
            if (self._last_window and self._last_window_hwnd and 
                time.time() - self._last_window_time < 2.0):  # 2 second cache
                try:
                    # Check if cached window is still valid
                    if hasattr(self._last_window, "Document") and self._last_window.Document:
                        folder = self._last_window.Document.Folder
                        if folder and hasattr(folder, "Self"):
                            path = folder.Self.Path
                            if path and os.path.isdir(path):
                                return os.path.normpath(path)
                except Exception:
                    pass

        except Exception as e:
            log.error(f"Error in _getCurrentPathFromExplorer: {e}")
        
        return None

    def _getActiveExplorerWindow(self):
        """Get the active Explorer window using the reliable method from _getCurrentPathFromExplorer"""
        try:
            current_time = time.time()
            
            # Return cached window if recent
            if (self._last_window and self._last_window_hwnd and 
                current_time - self._last_window_time < 1.0):  # 1 second cache
                return self._last_window
            
            fg = api.getForegroundObject()
            if not fg or not fg.appModule or fg.appModule.appName != "explorer":
                return None

            shell = CreateObject("Shell.Application")
            if not shell:
                return None

            # Get target window handle
            target_hwnd = fg.windowHandle
            
            # Try exact hwnd match
            for window in shell.Windows():
                try:
                    if not window or window.hwnd != target_hwnd:
                        continue

                    # Check if it has a valid document
                    if hasattr(window, "Document") and window.Document:
                        # Cache and return
                        self._last_window = window
                        self._last_window_hwnd = window.hwnd
                        self._last_window_time = current_time
                        return window

                except Exception:
                    continue

            # Fallback using focus object
            focus = api.getFocusObject()
            if focus and focus.appModule and focus.appModule.appName == "explorer":
                focus_hwnd = focus.windowHandle
                for window in shell.Windows():
                    try:
                        if not window or window.hwnd != focus_hwnd:
                            continue
                        if hasattr(window, "Document") and window.Document:
                            # Cache and return
                            self._last_window = window
                            self._last_window_hwnd = window.hwnd
                            self._last_window_time = current_time
                            return window
                    except Exception:
                        continue

            # Last resort: return first visible File Explorer window
            for window in shell.Windows():
                try:
                    if window and window.Visible and window.Name == "File Explorer":
                        if hasattr(window, "Document") and window.Document:
                            # Cache and return
                            self._last_window = window
                            self._last_window_hwnd = window.hwnd
                            self._last_window_time = current_time
                            return window
                except Exception:
                    continue

            return None
            
        except Exception as e:
            log.error(f"Error getting active Explorer window: {e}")
            return None

    def _getCurrentPath(self):
        """Get current path from active Explorer window"""
        return self._getCurrentPathFromExplorer()

    def _getSelectedItems(self):
        """Get selected items from active Explorer window"""
        try:
            # Get active window
            shellWindow = self._getActiveExplorerWindow()
            if not shellWindow:
                return None, None
                
            # Get document
            try:
                if not hasattr(shellWindow, "document") or not shellWindow.document:
                    return None, None
                    
                document = shellWindow.document
                
                # Update document tracking
                if self.manager.lastExplorerDocument != document:
                    self.manager.lastExplorerDocument = document
                    log.debug(f"Switched to new Explorer document/tab")
                    
            except Exception as e:
                log.debug(f"Error getting document: {e}")
                return None, None
                
            # Get selected items
            selectedItems = []
            try:
                if hasattr(document, 'SelectedItems'):
                    selectedItemsCount = document.SelectedItems().Count
                    for i in range(selectedItemsCount):
                        item = document.SelectedItems().Item(i)
                        selectedItems.append((item.Name, item.Path))
            except Exception as e:
                log.debug(f"Error getting selected items: {e}")
                
            return selectedItems if selectedItems else None, shellWindow
            
        except Exception as e:
            log.debug(f"Error in _getSelectedItems: {e}")
            return None, None

    def _executeWithSilence(self, func):
        """Execute function with all announcements silenced"""
        import speech
        speech.cancelSpeech()
        self.manager.suppressAllAnnouncements = True
        try:
            func()
        finally:
            core.callLater(1000, lambda: setattr(self.manager, 'suppressAllAnnouncements', False))

    def _copyAddressBar(self):
        """Copy address bar path to clipboard"""
        path = self._getCurrentPath()
        if path:
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(path))
                wx.TheClipboard.Close()
                ui.message(_("Copied: {path}").format(path=path))
            else:
                ui.message(_("Could not open clipboard"))
        else:
            ui.message(_("Unable to get current path"))

    def _handleNonExplorerGesture(self, gesture):
        """Handle gesture when not in Explorer - send the original key press"""
        try:
            # Extract key name from gesture display name
            # Format is usually "kb(desktop):NVDA+shift+c"
            display_name = gesture.displayName
            if ":" in display_name:
                key_name = display_name.split(":", 1)[1]
                # Send the original key combination
                KeyboardInputGesture.fromName(key_name).send()
        except Exception as e:
            log.debug(f"Error sending original key: {e}")

    def script_copySelectedNamesOrAddressBar(self, gesture):
        """Handle copy selected names (single tap) or copy address bar (double tap)"""
        # Check if in Explorer
        focus = api.getFocusObject()
        if not focus or focus.appModule.appName != "explorer":
            self._handleNonExplorerGesture(gesture)
            return
            
        global _last_tap_time_copy, _tap_count_copy, _copy_timer
        
        current_time = time.time()
        
        # Reset tap count if too much time has passed
        if current_time - _last_tap_time_copy > _double_tap_threshold:
            _tap_count_copy = 0
            if _copy_timer:
                _copy_timer.Stop()
                _copy_timer = None
        
        _tap_count_copy += 1
        _last_tap_time_copy = current_time
        
        # Wait to see if this is a double tap
        if _tap_count_copy == 1:
            # Single tap - wait to see if it becomes double
            _copy_timer = wx.CallLater(int(_double_tap_threshold * 1000), self._processCopyTap)
        elif _tap_count_copy >= 2:
            # Double tap - process immediately
            # Cancel the single tap timer
            if _copy_timer:
                _copy_timer.Stop()
                _copy_timer = None
            self._processCopyTap()

    script_copySelectedNamesOrAddressBar.__doc__ = _("Copy selected names (single tap) or copy address bar (double tap)")
    script_copySelectedNamesOrAddressBar.category = _("xPlorer")
    script_copySelectedNamesOrAddressBar.gestures = ["kb(desktop):NVDA+shift+c"]

    def _processCopyTap(self):
        """Process copy tap action based on tap count"""
        global _tap_count_copy, _copy_timer
        
        # Ensure timer is cleaned up
        if _copy_timer:
            _copy_timer.Stop()
            _copy_timer = None
        
        if _tap_count_copy == 1:
            # Single tap - copy selected names
            self._executeWithSilence(self.clipboard.copySelectedNames)
        elif _tap_count_copy >= 2:
            # Double tap - copy address bar
            self._executeWithSilence(self._copyAddressBar)
        
        # Reset tap count
        _tap_count_copy = 0

    def script_invertSelection_double_tap(self, gesture):
        """Handle copy content (single tap) or invert selection (double tap)"""
        # Check if in Explorer
        focus = api.getFocusObject()
        if not focus or focus.appModule.appName != "explorer":
            self._handleNonExplorerGesture(gesture)
            return
            
        global _last_tap_time_invert, _tap_count_invert, _invert_timer
        
        current_time = time.time()
        
        # Reset tap count if too much time has passed
        if current_time - _last_tap_time_invert > _double_tap_threshold:
            _tap_count_invert = 0
            if _invert_timer:
                _invert_timer.Stop()
                _invert_timer = None
        
        _tap_count_invert += 1
        _last_tap_time_invert = current_time
        
        # Wait to see if this is a double tap
        if _tap_count_invert == 1:
            # Single tap - wait to see if it becomes double
            _invert_timer = wx.CallLater(int(_double_tap_threshold * 1000), self._processInvertTap)
        elif _tap_count_invert >= 2:
            # Double tap - process immediately
            # Cancel the single tap timer
            if _invert_timer:
                _invert_timer.Stop()
                _invert_timer = None
            self._processInvertTap()

    script_invertSelection_double_tap.__doc__ = _("Copy content (single tap) or invert selection (double tap)")
    script_invertSelection_double_tap.category = _("xPlorer")
    script_invertSelection_double_tap.gestures = ["kb(desktop):NVDA+shift+v"]

    def _processInvertTap(self):
        """Process invert tap action based on tap count"""
        global _tap_count_invert, _invert_timer
        
        # Ensure timer is cleaned up
        if _invert_timer:
            _invert_timer.Stop()
            _invert_timer = None
        
        if _tap_count_invert == 1:
            # Single tap - copy file content
            self._executeWithSilence(self.clipboard.copyFileContent)
        elif _tap_count_invert >= 2:
            # Double tap - invert selection
            self._executeWithSilence(self.selection.invertSelection)
        
        # Reset tap count
        _tap_count_invert = 0

    def script_compressZip_double_tap(self, gesture):
        """Handle say size (single tap) or compress zip (double tap)"""
        # Check if in Explorer
        focus = api.getFocusObject()
        if not focus or focus.appModule.appName != "explorer":
            self._handleNonExplorerGesture(gesture)
            return
            
        global _last_tap_time_compress, _tap_count_compress, _compress_timer
        
        current_time = time.time()
        
        # Reset tap count if too much time has passed
        if current_time - _last_tap_time_compress > _double_tap_threshold:
            _tap_count_compress = 0
            if _compress_timer:
                _compress_timer.Stop()
                _compress_timer = None
        
        _tap_count_compress += 1
        _last_tap_time_compress = current_time
        
        # Wait to see if this is a double tap
        if _tap_count_compress == 1:
            # Single tap - wait to see if it becomes double
            _compress_timer = wx.CallLater(int(_double_tap_threshold * 1000), self._processCompressTap)
        elif _tap_count_compress >= 2:
            # Double tap - process immediately
            # Cancel the single tap timer
            if _compress_timer:
                _compress_timer.Stop()
                _compress_timer = None
            self._processCompressTap()

    script_compressZip_double_tap.__doc__ = _("Say size (single tap) or compress zip (double tap)")
    script_compressZip_double_tap.category = _("xPlorer")
    script_compressZip_double_tap.gestures = ["kb(desktop):NVDA+shift+z"]

    def _processCompressTap(self):
        """Process compress tap action based on tap count"""
        global _tap_count_compress, _compress_timer
        
        # Ensure timer is cleaned up
        if _compress_timer:
            _compress_timer.Stop()
            _compress_timer = None
        
        if _tap_count_compress == 1:
            # Single tap - say size
            self._executeWithSilence(self.fileOps.saySize)
        elif _tap_count_compress >= 2:
            # Double tap - compress zip
            # Add a small delay to ensure the first tap processing is complete
            core.callLater(50, self._executeWithSilence, self.compression.compressZip)
        
        # Reset tap count
        _tap_count_compress = 0

    def script_openXPlorerContextMenu(self, gesture):
        """Open xPlorer context menu"""
        # Check if in Explorer
        focus = api.getFocusObject()
        if not focus or focus.appModule.appName != "explorer":
            self._handleNonExplorerGesture(gesture)
            return
        self._showContextMenu()

    script_openXPlorerContextMenu.__doc__ = _("Open xPlorer context menu")
    script_openXPlorerContextMenu.category = _("xPlorer")
    script_openXPlorerContextMenu.gestures = ["kb(desktop):NVDA+shift+x"]

    def _copyFileContent(self):
        self._executeWithSilence(self.clipboard.copyFileContent)

    def _renameFile(self):
        self._executeWithSilence(self.fileOps.renameFile)

    def script_renameFile(self, gesture):
        """Rename selected file"""
        # Check if in Explorer
        focus = api.getFocusObject()
        if not focus or focus.appModule.appName != "explorer":
            self._handleNonExplorerGesture(gesture)
            return
        self._renameFile()

    script_renameFile.__doc__ = _("Rename selected file")
    script_renameFile.category = _("xPlorer")
    script_renameFile.gestures = ["kb(desktop):NVDA+shift+f2"]

    def _openSettings(self):
        """Open xPlorer settings dialog"""
        try:
            # Use wx.CallAfter to open settings dialog from context menu
            wx.CallAfter(self._showSettingsDialog)
        except Exception as e:
            log.error(f"Error opening settings dialog: {e}")
            ui.message(_("Cannot open settings dialog"))

    def _showSettingsDialog(self):
        """Show the xPlorer settings dialog using the correct method"""
        try:
            # Use the non-deprecated method to open settings dialog
            gui.mainFrame.popupSettingsDialog(gui.settingsDialogs.NVDASettingsDialog, xPlorerSettingsPanel)
        except Exception as e:
            log.error(f"Error showing settings dialog: {e}")
            ui.message(_("Error opening settings"))

    def _showContextMenu(self):
        """Show the context menu asynchronously to avoid blocking"""
        self.contextMenuManager.showContextMenu()

    def chooseNVDAObjectOverlayClasses(self, obj, clsList):
        self.manager.chooseNVDAObjectOverlayClasses(obj, clsList)

    def event_gainFocus(self, obj, nextHandler):
        # Clear window cache when focus changes significantly
        if obj and obj.appModule.appName == "explorer":
            # Only clear if window handle changed
            if hasattr(obj, 'windowHandle'):
                if obj.windowHandle != self._last_window_hwnd:
                    self._last_window = None
                    self._last_window_hwnd = None
        self.manager.event_gainFocus(obj, nextHandler)

    def event_focusEntered(self, obj, nextHandler):
        self.manager.event_focusEntered(obj, nextHandler)

    def event_foreground(self, obj, nextHandler):
        # Clear cache when foreground changes
        self._last_window = None
        self._last_window_hwnd = None
        self.manager.event_foreground(obj, nextHandler)

    def event_UIA_elementSelected(self, obj, nextHandler):
        self.manager.event_UIA_elementSelected(obj, nextHandler)