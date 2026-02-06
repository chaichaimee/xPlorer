![NVDA Logo](https://www.nvaccess.org/nvda_200x200_op)

# xPlorer

**Author:** chai chaimee  
**URL:** [https://github.com/chaichaimee/xPlorer](https://github.com/chaichaimee/xPlorer)

## What's new in the latest version?

- Create File
- Edit new keyboard shortcuts: Make it more convenient to use and improve the Say Size function

## Overview

xPlorer is a tool designed to provide easier access to File Explorer operations.  
The latest version includes features for managing files and folders, such as:

- Compressing items into a ZIP
- Renaming files with a dedicated window that separates the filename and extension (to prevent accidental deletion)
- Reading the size of files, folders, or drives
- Copying selected file and folder names to the clipboard, etc.

## Hot Keys

- **NVDA+Shift+X** : Open xPlorer Context Menu  
  Select a file or folder and open the context menu. This submenu consolidates all xPlorer functions in one place, allowing you to access any feature immediately for convenience and speed.

- **NVDA+Shift+Z** (Single Tap) : Say size  
  Select a text file in the editor (one that already contains content), or select multiple files (each no larger than 10 MB).  
  Press the shortcut key to copy all of their contents without opening the files...  
  In the latest version, users can also select multiple files or folders to view the total size.

- **NVDA+Shift+Z** (Double Tap) : Compress selected items to ZIP  
  Select the files or select all, then press the shortcut key.  
  The selected items will be automatically compressed into a ZIP file.

- **NVDA+Shift+C** : Copy selected file and folder names to clipboard  
  Select the desired files (one or multiple) or select all, then press the shortcut key.  
  All selected file and folder names will be copied to the clipboard for pasting into a text editor.

- **NVDA+Shift+C** (Double Tap) : Copy address bar in File Explorer  
  When you are in the folder whose path you want to copy, simply double-tap the shortcut key to copy the address bar directly (faster than Ctrl+L).

- **NVDA+Shift+V** (Single Tap) : Copy Content  
  Select a text editor file (that already contains content) or multiple files (each ≤ 10 MB)...  
  Support file extensions: .txt, .rtf, .py, .js, .html, .css, .xml, .json, .csv, .md, .ini, .conf, .cfg, .java, .cpp, .c, .h, .php, .rb, .pl, .sh, .bat, .ps1

- **NVDA+Shift+V** (Double Tap) : Invert Selection  
  Select a file or folder, then press NVDA+Shift+V double-tap to invert the selection...

- **NVDA+Shift+F2** : Rename selected file  
  A window will open with separate fields for filename and extension. Edit and press Enter — only the edited part updates.

## Features

Additional features (can be enabled/disabled via NVDA menu → Preferences → Settings → xPlorer):

- Automatically select the first item
- Announce 'Empty Folder' when entering an empty folder
- Suppress announcement of DirectUIHWND class (checked)

**Create File**  
While in File Explorer, open xPlorer context menu → Create File. Specify name, extension, and number of files. Supports many text/code formats.

**Robocopy**  
A smarter way to "move" or "copy" folders/files (skips identical files, resumes interrupted copies). Ideal for large data transfers.

### Mirror Backup with Schedule

Set automatic mirror backups (using Robocopy) at chosen intervals (minutes, hours, days, weeks).

### TXT to Folder

Select a .txt file containing a list → NVDA+Alt+X → TXT to Folder.  
Creates a subfolder + individual folders from each line in the list.

## Donation

If you like my work, you can support via:  
[https://github.com/chaichaimee](https://github.com/chaichaimee)