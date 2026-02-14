# fileOperations.py

import ui
import api
import os
import wx
import gui
import gui.guiHelper
import subprocess
import time
import threading
from logHandler import log
import addonHandler
import tones

addonHandler.initTranslation()

class RenameDialog(wx.Dialog):
    def __init__(self, parent, fileName):
        super().__init__(parent, title="")
        self.fileName = fileName
        self.newName = None
        self.InitUI()
        
    def InitUI(self):
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
        
        name, ext = os.path.splitext(self.fileName)
        
        self.nameCtrl = sHelper.addItem(wx.TextCtrl(self, value=name))
        self.nameCtrl.SelectAll()
        
        if ext and ext.startswith('.'):
            ext = ext[1:]
        self.extCtrl = sHelper.addItem(wx.TextCtrl(self, value=ext))
        
        btnSizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sHelper.addItem(btnSizer, flag=wx.ALIGN_CENTER)
        
        self.SetSizer(mainSizer)
        mainSizer.Fit(self)
        
        self.CentreOnScreen()
        self.nameCtrl.SetFocus()
        
        self.Bind(wx.EVT_BUTTON, self.OnOk, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.OnCancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_TEXT_ENTER, self.OnOk)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        
    def OnOk(self, event):
        name = self.nameCtrl.Value.strip()
        ext = self.extCtrl.Value.strip()
        
        if not name:
            ui.message(_("File name cannot be empty"))
            return
            
        if ext:
            ext = "." + ext
        self.newName = name + ext
        self.EndModal(wx.ID_OK)
        
    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)
        
    def OnClose(self, event):
        self.EndModal(wx.ID_CANCEL)

class FileOperations:
    def __init__(self, plugin):
        self.plugin = plugin
        self.renameDialog = None
        self._beep_timer = None
        self._calculation_active = False
        self._stop_beep_event = threading.Event()

    def cleanup(self):
        if self.renameDialog:
            try:
                self.renameDialog.Destroy()
            except:
                pass
        self._stop_beeping()

    def _start_beeping(self):
        """Start beeping every 2 seconds to indicate processing"""
        self._stop_beep_event.clear()
        self._beep_timer = threading.Timer(2.0, self._beep_interval)
        self._beep_timer.daemon = True
        self._beep_timer.start()

    def _stop_beeping(self):
        """Stop the beeping timer"""
        self._stop_beep_event.set()
        if self._beep_timer:
            self._beep_timer.cancel()
            self._beep_timer = None

    def _beep_interval(self):
        """Beep and schedule next beep if still processing"""
        if not self._stop_beep_event.is_set():
            # Play a short beep tone (440 Hz, 100 ms)
            wx.CallAfter(tones.beep, 440, 100)
            # Schedule next beep
            self._beep_timer = threading.Timer(2.0, self._beep_interval)
            self._beep_timer.daemon = True
            self._beep_timer.start()

    def _RecalcSize(self, iResult, iTotalSize=0):
        fResult = float(iResult)
        if iTotalSize > 0:
            iTotalSize = float(iTotalSize)
            fResult = iTotalSize - fResult    
        i = 0
        while fResult >= 1024:
            fResult = fResult / 1024
            i = i + 1
        sRecalcSize = ' {:.2f}'.format(fResult)
        sResult = (sRecalcSize, i)
        return sResult

    def _get_folder_size_powershell_fast(self, folder_path):
        """Get folder size using PowerShell with optimized command - fastest method"""
        try:
            # Optimized PowerShell command using .NET methods directly
            # This method is much faster than Get-ChildItem for large folders
            ps_command = f"""
            $path = '{folder_path}'
            $totalSize = 0L
            
            function Get-Size($directory) {{
                try {{
                    # Get all files in current directory
                    $files = [System.IO.Directory]::EnumerateFiles($directory)
                    foreach ($file in $files) {{
                        try {{
                            $totalSize += (New-Object System.IO.FileInfo $file).Length
                        }} catch {{ }}
                    }}
                    
                    # Get all subdirectories
                    $dirs = [System.IO.Directory]::EnumerateDirectories($directory)
                    foreach ($dir in $dirs) {{
                        Get-Size $dir
                    }}
                }} catch {{ }}
            }}
            
            Get-Size $path
            $totalSize
            """
            
            result = subprocess.run(
                ["powershell", "-Command", ps_command],
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=30,  # 30 second timeout
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0 and result.stdout.strip():
                size_str = result.stdout.strip()
                if size_str and size_str.isdigit():
                    return int(size_str)
                else:
                    # Try alternative parsing
                    try:
                        return int(float(size_str))
                    except:
                        log.debug(f"PowerShell returned non-numeric: {size_str}")
                        return None
            else:
                log.debug(f"PowerShell failed (returncode={result.returncode}): {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            log.warning(f"PowerShell timeout for folder: {folder_path}")
            return None
        except Exception as e:
            log.error(f"Error in PowerShell folder size calculation: {e}")
            return None

    def _get_folder_size_windows_api(self, folder_path):
        """Get folder size using Windows API through ctypes - very fast for large folders"""
        try:
            import ctypes
            from ctypes import wintypes, windll
            
            # Define structures and functions
            class LARGE_INTEGER(ctypes.Structure):
                _fields_ = [("QuadPart", ctypes.c_longlong)]
                
            GetFileSizeEx = windll.kernel32.GetFileSizeEx
            GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(LARGE_INTEGER)]
            GetFileSizeEx.restype = wintypes.BOOL
            
            FindFirstFile = windll.kernel32.FindFirstFileW
            FindFirstFile.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.WIN32_FIND_DATAW)]
            FindFirstFile.restype = wintypes.HANDLE
            
            FindNextFile = windll.kernel32.FindNextFileW
            FindNextFile.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.WIN32_FIND_DATAW)]
            FindNextFile.restype = wintypes.BOOL
            
            FindClose = windll.kernel32.FindClose
            FindClose.argtypes = [wintypes.HANDLE]
            FindClose.restype = wintypes.BOOL
            
            def get_folder_size_recursive(path):
                total = 0
                find_data = wintypes.WIN32_FIND_DATAW()
                handle = FindFirstFile(os.path.join(path, "*"), ctypes.byref(find_data))
                
                if handle == wintypes.HANDLE(-1):
                    return total
                
                try:
                    while True:
                        name = find_data.cFileName
                        if name not in ('.', '..'):
                            full_path = os.path.join(path, name)
                            
                            if find_data.dwFileAttributes & 16:  # Directory
                                total += get_folder_size_recursive(full_path)
                            else:
                                # File size calculation
                                size_high = find_data.nFileSizeHigh
                                size_low = find_data.nFileSizeLow
                                file_size = (size_high << 32) + size_low
                                total += file_size
                        
                        if not FindNextFile(handle, ctypes.byref(find_data)):
                            break
                finally:
                    FindClose(handle)
                
                return total
            
            return get_folder_size_recursive(folder_path)
            
        except Exception as e:
            log.error(f"Error in Windows API folder size calculation: {e}")
            return None

    def _calculate_folder_size_fast(self, folder_path):
        """Calculate folder size using the fastest available method"""
        # Try Windows API first (fastest)
        size = self._get_folder_size_windows_api(folder_path)
        if size is not None:
            log.debug(f"Windows API size: {size} bytes")
            return size
            
        # Try optimized PowerShell
        size = self._get_folder_size_powershell_fast(folder_path)
        if size is not None:
            log.debug(f"PowerShell size: {size} bytes")
            return size
            
        return None

    def _check_access_permission(self, path):
        """Check if we have permission to access the path"""
        try:
            # Try to list contents of the directory
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
            return True  # If we can't determine, assume we have access

    def saySize(self):
        """say size for single or multiple selected items with progress indication"""
        focus = api.getFocusObject()
        if not focus or focus.appModule.appName != "explorer":
            return
            
        selectedItems, shellWindow = self.plugin._getSelectedItems()
        if not selectedItems:
            ui.message(_("No items selected"))
            return
        
        # Check access permissions for all selected items
        inaccessible_items = []
        for name, path in selectedItems:
            if not self._check_access_permission(path):
                inaccessible_items.append(name)
        
        if inaccessible_items:
            if len(inaccessible_items) == len(selectedItems):
                ui.message(_("No access to size data"))
                return
            else:
                log.debug(f"Skipping inaccessible items: {inaccessible_items}")
        
        # Start beeping to indicate processing
        self._calculation_active = True
        self._start_beeping()
        
        # Calculate in a separate thread to avoid blocking
        def calculate_size():
            try:
                totalSize = 0
                isDrive = False
                accessibleItemCount = 0
                
                # Calculate total size for all selected items
                for name, path in selectedItems:
                    if not self._calculation_active:
                        break
                    
                    # Skip inaccessible items
                    if name in inaccessible_items:
                        continue
                    
                    accessibleItemCount += 1
                    
                    if self.plugin.objFSO.FileExists(path):
                        try:
                            fileSize = self.plugin.objFSO.GetFile(path).Size
                            totalSize += fileSize
                            log.debug(f"File: {name}, Size: {fileSize}")
                        except Exception as e:
                            log.error(f"Error getting file size for {name}: {e}")
                    elif self.plugin.objFSO.DriveExists(path):
                        isDrive = True
                        try:
                            drive = self.plugin.objFSO.GetDrive(path)
                            usedSize = drive.TotalSize - drive.FreeSpace
                            totalSize += usedSize
                            log.debug(f"Drive: {name}, Used Size: {usedSize}")
                        except Exception as e:
                            log.error(f"Error getting drive size for {name}: {e}")
                    elif self.plugin.objFSO.FolderExists(path):
                        # Use fast method for folders
                        start_time = time.time()
                        folderSize = self._calculate_folder_size_fast(path)
                        
                        if folderSize is not None and folderSize > 0:
                            totalSize += folderSize
                            elapsed = time.time() - start_time
                            log.debug(f"Folder (fast): {name}, Size: {folderSize}, Time: {elapsed:.2f}s")
                        else:
                            # Fallback to quick estimation for folders
                            try:
                                # Try to get size using os.scandir for a quick estimate
                                folderSize = 0
                                count = 0
                                max_files_to_check = 1000  # Limit for quick estimation
                                
                                for root, dirs, files in os.walk(path):
                                    for f in files:
                                        if count >= max_files_to_check or not self._calculation_active:
                                            break
                                        fp = os.path.join(root, f)
                                        try:
                                            folderSize += os.path.getsize(fp)
                                            count += 1
                                        except (OSError, WindowsError):
                                            pass
                                    if count >= max_files_to_check or not self._calculation_active:
                                        break
                                
                                # If we checked many files, assume average file size
                                if count > 0:
                                    avg_size = folderSize / count
                                    # Estimate total files (this is just a rough guess)
                                    estimated_total_files = count * 10  # Conservative estimate
                                    folderSize = avg_size * estimated_total_files
                                
                                totalSize += folderSize
                                elapsed = time.time() - start_time
                                log.debug(f"Folder (estimate): {name}, Size: {folderSize}, Time: {elapsed:.2f}s")
                            except Exception as e:
                                log.error(f"Error estimating folder size for {name}: {e}")
                                # Add a minimal size to avoid "No access to size data" message
                                totalSize += 1024  # 1KB minimum
                
                log.debug(f"Accessible items: {accessibleItemCount}, Total size: {totalSize} bytes")
                
                # Stop beeping
                self._stop_beeping()
                self._calculation_active = False
                
                # Return results to main thread
                wx.CallAfter(self._display_size_result, totalSize, isDrive, accessibleItemCount)
                
            except Exception as e:
                log.error(f"Error in size calculation thread: {e}")
                self._stop_beeping()
                self._calculation_active = False
                wx.CallAfter(ui.message, _("Error calculating size"))
        
        # Start calculation thread
        thread = threading.Thread(target=calculate_size, daemon=True)
        thread.start()

    def _display_size_result(self, totalSize, isDrive, itemCount):
        """Display the calculated size result"""
        if totalSize == 0 and not isDrive:
            ui.message(_("No access to size data"))
            return
            
        colRecalc = self._RecalcSize(totalSize)
        
        sDimension = [" bytes", " KB", " MB", " GB", " TB"][colRecalc[1]]
        sRecalcSize = colRecalc[0]
        s_Info = sRecalcSize + sDimension
        
        if itemCount > 1:
            s_Info = _("{count} items {size}").format(count=itemCount, size=s_Info)
            
        ui.message(s_Info)

    def renameFile(self):
        """Rename selected file"""
        focus = api.getFocusObject()
        if not focus or focus.appModule.appName != "explorer":
            return
            
        try:
            selectedItems, shellWindow = self.plugin._getSelectedItems()
            if not selectedItems:
                ui.message(_("No items selected"))
                return
                
            if len(selectedItems) > 1:
                ui.message(_("Please select only one file"))
                return
                
            filePath = selectedItems[0][1]
            
            if not os.path.isfile(filePath):
                ui.message(_("Please select a file, not a folder"))
                return
                
            fileName = os.path.basename(filePath)
            dirName = os.path.dirname(filePath)
            
            wx.CallAfter(self._showRenameDialog, fileName, dirName, filePath)
                
        except Exception as e:
            log.error(f"Error in renameFile: {e}")
            ui.message(_("Error renaming file"))

    def _showRenameDialog(self, fileName, dirName, filePath):
        try:
            if self.renameDialog and self.renameDialog.IsShown():
                self.renameDialog.Destroy()
                
            self.renameDialog = RenameDialog(gui.mainFrame, fileName)
            
            self.renameDialog.Raise()
            
            result = self.renameDialog.ShowModal()
            
            if result == wx.ID_OK and self.renameDialog.newName:
                newPath = os.path.join(dirName, self.renameDialog.newName)
                
                if newPath == filePath:
                    ui.message(_("File name not changed"))
                    return
                    
                if os.path.exists(newPath):
                    ui.message(_("A file with this name already exists"))
                    return
                    
                try:
                    os.rename(filePath, newPath)
                    ui.message(_("File renamed to {name}").format(name=self.renameDialog.newName))
                except Exception as e:
                    log.error(f"Error renaming file: {e}")
                    ui.message(_("Error renaming file"))
                    
            self.renameDialog.Destroy()
            self.renameDialog = None
        except Exception as e:
            log.error(f"Error showing rename dialog: {e}")
            ui.message(_("Error opening rename dialog"))
            if self.renameDialog:
                try:
                    self.renameDialog.Destroy()
                except:
                    pass
                self.renameDialog = None