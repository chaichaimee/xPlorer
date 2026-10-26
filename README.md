# xPlorer

Faster, friendlier File Explorer for NVDA users: multi-tap hotkeys, a keyboard menu, file basket, workspaces, batch rename, Robocopy, archives, ISO creation and more.

**Author:** chai chaimee  
**URL:** https://github.com/chaichaimee/xPlorer


## Introduction

xPlorer adds a set of tools to Windows File Explorer that are built for keyboard and screen reader use. Most commands live on a few easy keys. Each key does something different when you tap it once, twice, three times or, for one key, four times. The same commands are also in a menu you can open from the keyboard.

Every dialog is a plain list, text box or button, so NVDA reads it normally. Long jobs such as compressing, copying or building an ISO are announced when they start and finish, and use tones to show progress.

xPlorer also tidies up what NVDA says in File Explorer. You can have NVDA select the first item when you enter a folder, say "Empty Folder" for an empty folder, stay quiet about "DirectUIHWND", "- File Explorer" and "Task Switching", and speak the size of each file or folder as you move through the list.


## Hot Keys

Press the key once, twice, three times or four times in quick succession. You have half a second between taps (0.3 seconds for the xPlorer menu key). All keys can be changed in NVDA's Input Gestures dialog, under the xPlorer category.

**NVDA+Shift+C**

- Single Tap : Copy the names of the selected files and folders to the clipboard
- Double Tap : Copy the text content of the selected file(s)
- Triple Tap : Copy the path shown in the current folder's address bar

**NVDA+Shift+V**

- Single Tap : Select every other item that has the same file extension as the focused item
- Double Tap : Invert the current selection
- Triple Tap : Turn Multi-select on or off (non-contiguous selection with the keyboard)

**NVDA+Shift+A**

- Single Tap : Open the Select by Search dialog
- Double Tap : Open Flat View
- Triple Tap : Open the Batch Rename tool

**NVDA+Shift+Z**

- Single Tap : Say the total size of the selection
- Double Tap : Compress the selection into a zip file
- Triple Tap : Extract the selected archive(s)
- Four Taps : Convert the selected folder into an ISO disc image

**NVDA+Shift+R**

- Single Tap : Robocopy - mark the selection to copy
- Double Tap : Robocopy - paste into the current folder
- Triple Tap : Robocopy - mark the selection to move

**NVDA+Shift+X**

- Single Tap : Open the xPlorer menu
- Double Tap : Open the Recent Locations list
- Triple Tap : Open the Current folder size list

**NVDA+Shift+F2**

- Single Tap : Rename the selected file
- Double Tap : Rename the selected item using the text on the clipboard
- Triple Tap : Undo the last batch rename

**NVDA+Shift+N**

- Single Tap : Add the selected items to the File Basket
- Double Tap : Open the File Basket
- Triple Tap : Clear the File Basket

**NVDA+Shift+M**

- Single Tap : Open the Workspace menu
- Double Tap : Add the selected folder to a new workspace, or save the current folder as a workspace
- Triple Tap : Open the Workspace editor (load, edit, pin, reorder or delete saved workspaces)

**Ctrl+Shift+N** : Create a new folder in File Explorer and paste the text on the clipboard into its name field

Outside File Explorer most of these keys are passed on to Windows unchanged, so they never get in your way. NVDA+Shift+A needs File Explorer and tells you when it cannot run. The xPlorer menu (single tap) and the Workspace keys work anywhere; outside File Explorer the menu shows only the commands that do not need an Explorer window.


## Features


### The xPlorer Menu

Press **NVDA+Shift+X** once. The menu is a single list. Use Up and Down to move, Right Arrow or Enter to open a submenu, Left Arrow or Escape to go back, and Enter to run a command. A command that cannot run is read as "unavailable". The menu is built fresh every time.

- **Create File**, **File Basket**, **Batch Rename Tool**, **Undo Last Rename**
- **Folder Sync & Compare** : Mark Left Folder, Run Compare
- **Duplicate Finder**, **Flat View**, **Folder to ISO**, **TXT to Folder**, **Create Multiple Folders**
- **Case Converter for Folders** : Uppercase, Lowercase, Title Case, Headline Case
- **Compress** : Compress zip, unCompress zip
- **Selection** : Select by Extension, Invert selection, Multi-select, Select by Search
- **Clipboard Operations** : Copy address bar, Copy content, Copy selected file and folder names
- **Rename selected file**
- **Robocopy** : copy, move, paste
- **Workspace Manager**, **Current folder size list**, **Recent Locations**, **Operation History**, **xPlorer Settings**
- **Properties**, **Say size**, and, when a folder is selected, **Folder info**

**Say size** and **Folder info** show their answer in the menu item itself. As soon as you arrow onto them the text changes to the size, for example "12.40 MB", or to the contents, for example "5 subfolders, 20 files". **Properties** opens a read-only list with the name, location, size, the created, modified and accessed dates, and, for a folder, the number of files and folders inside. For a drive it shows the drive letter, file system, free, used and total space.

Outside File Explorer the menu shows only File Basket, Undo Last Rename, Workspace Manager, Recent Locations, Operation History and xPlorer Settings.


### Copying Names, Text and Paths

- **Single tap** copies the names of the selected files and folders, folders first and then files, each sorted by name, and says how many were copied.
- **Double tap** copies the text inside the selected files. It works with plain text and code files (txt, py, js, html, css, xml, json, csv, md, ini, conf, cfg, java, cpp, c, h, php, rb, pl, sh, bat, ps1), with RTF files and with Word documents (doc and docx). Several files are joined with a blank line between them. NVDA says how many lines from how many files were copied. Folders cannot be copied this way, and the selection must not be larger than 15 MB in total.
- **Triple tap** copies the path of the folder that is open in the address bar.


### Selection Tools

- **Select by extension** (single tap of NVDA+Shift+V): put the focus on one file first. Every file with the same extension in the folder is selected.
- **Invert selection** (double tap): selected items become unselected and the other way round. Big folders are handled in the background.
- **Multi-select** (triple tap): lets you pick items that are not next to each other. A tone tells you it has started, and another tone tells you it has ended. While it is on, Up, Down, Home, End, Space and Enter work like they do while holding Ctrl, so you can move with the arrows and press Space to add or remove an item. Press Delete or Shift+Delete and Multi-select ends, then the delete goes ahead as normal. Any other key ends it too, and it switches itself off after five minutes. Triple tap again to turn it off yourself.


### Select by Search

Press NVDA+Shift+A once, or choose Select by Search from the menu. Type what you are looking for and the list of matching items updates as you type, and NVDA says how many there are.

- **Include subfolders** searches every level below the current folder, the way Flat View does. In that case the top-level items that contain a match are selected.
- **Search mode** is Normal search (the text appears in the name), Regex (a regular expression) or Wildcard (for example `*.txt` or `report_*.docx`; separate several patterns with a comma or a space). A bad regular expression is shown in the list instead of failing.
- Press OK and the matching items are selected in File Explorer.
- In the match list, press Enter to open the item, Ctrl+C or Ctrl+X to copy or cut, and Ctrl+Space to pick or unpick items. The context menu (Applications key or Shift+F10) has Copy, Cut, Open to path and Delete. Delete sends the items to the Recycle Bin after you confirm.

Your last mode, search text and subfolder choice are remembered.


### Flat View

Flat View lists every file in the current folder and all of its subfolders in one list, with the columns Name, Folder and Size. Type in the filter box to narrow the list. NVDA announces how many matches there are. Press Enter on a file to open it, or choose **Open Containing Folder** to show it in File Explorer. Very large trees are cut off at 50,000 files, and NVDA tells you when that happens.


### Batch Rename Tool

Open it with NVDA+Shift+A pressed three times, or from the menu. It works on the files you selected. If you selected folders, every file inside them, including subfolders, is added. If nothing is selected, all the files in the current folder and its subfolders are used.

- **Rename mode** : Find and replace, or Tag pattern.
- **Find and replace** : type the text to find and the text to replace it with. Tick **Use regular expressions** to use a pattern. Only the file name changes; the extension is kept.
- **Tag pattern** : build the new name from tags. `[N]` is the original name, `[E]` is the extension, `[C]` is a counter, and `[D]` is the date the file was last changed (year-month-day). Set the **Counter start value**. For example `[N]_[C].[E]`. If your pattern has no extension, the original one is added back.
- **Preview** : the list of new names updates as you type. If two files would get the same name, a number is added to make them different.
- Press **Apply** to rename. A file is skipped if its new name already exists, and NVDA reads the first three problems. Nothing is ever overwritten.
- **Undo Last Rename** is a button in the dialog. It is also on the menu and on NVDA+Shift+F2 pressed three times, and it works even after the dialog has closed. Files that are missing, or whose old name is now taken, are reported and left alone.


### Renaming a File

- **Single tap** of NVDA+Shift+F2 opens a small rename box for the selected file.
- **Double tap** renames the selected file or folder at once with the text on the clipboard. The text must be a single line without characters that Windows does not allow, otherwise NVDA says it is not a valid name. If the text has no extension, a file keeps its own extension. If the new name is taken, nothing is changed and NVDA tells you.
- **Ctrl+Shift+N** creates a new folder in File Explorer and puts the clipboard text in its name box when it can be used as a name. Characters Windows does not allow are replaced the way you choose in the settings (a hyphen, an underscore, or removed). This can be turned off in the settings.


### Say Size and Folder Info

NVDA+Shift+Z once says the total size of everything you selected, for example "3 items 1.25 GB". Folders are counted with everything inside them. Beeps play while a large folder is being measured. **Folder info** from the menu says how many subfolders and files the selected folder has.


### Item Sizes While You Browse

Turn on **Announce the size of files and folders when moving through the list** in the settings and NVDA adds the size after each name as you arrow through File Explorer. You can limit this to files only, folders only, or both. File sizes are spoken at once. Folder sizes are worked out in the background, so a folder's size may be spoken a moment after its name, and remembered for the next visit. Folders that are too large to measure quickly are left out.


### Current Folder Size List

Triple tap NVDA+Shift+X, or choose it from the menu. You get a list of everything in the folder with its size, for example "Pictures, folder, 2.31 GB". A summary line says how many folders and files there are and their total size. Open the context menu on the list for **Settings**, **Include subfolder contents in folder sizes** and **Rescan**. In Settings you choose whether the name or the size comes first, the sort order (name A to Z or Z to A, size largest or smallest first), whether to show folders and files, only folders or only files, and whether folders are listed before files. Counting the contents of subfolders is slower. Your choices are remembered.


### Compress and Extract

- **Compress** (double tap NVDA+Shift+Z): the selection is packed into a zip file. A single item makes a zip with its own name next to it. Several items make a zip named after the folder they are in. If the name is taken, a number is added. A progress window with a Cancel button appears, and tones play until it is done. xPlorer uses 7-Zip when it is installed, and its own zip writer when it is not.
- **Extract** (triple tap): one archive opens a choice between extracting to a folder named after the archive, or extracting here. You can turn that question off in the settings and always use one way. If you select several archives, each one is extracted into its own folder.
- Supported archives are zip, rar, 7z, tar, gz, bz2, xz, tgz, iso, cab, wim and nvda-addon. Zip, nvda-addon and ISO files can be extracted without 7-Zip. The other kinds need 7-Zip, and NVDA tells you if it is missing.


### Folder to ISO

Select one folder and tap NVDA+Shift+Z four times, or choose Folder to ISO from the menu. xPlorer writes an ISO disc image named after the folder, in the same place as the folder. If the name is taken, a number is added. It needs no other program.

- The image can be read by Windows and other systems. A folder with a file larger than 4 GB is written in the UDF format instead, and NVDA says "UDF format" when it is finished.
- Symbolic links and junction points are skipped, and NVDA says how many items were skipped.
- xPlorer checks there is enough free space first. Tones play while it works. A progress window with a Cancel button appears for large folders (256 MB or more).
- When it is finished, NVDA says the name and size of the ISO. A cancelled or failed job leaves no half-written file.


### Robocopy

Robocopy is the fast copy tool built into Windows. xPlorer puts it on three taps.

1. Select files or folders and tap NVDA+Shift+R once to mark them for **copy**, or three times to mark them for **move**. NVDA says how many items are ready.
2. Go to the destination folder, in the same window or another one, and tap NVDA+Shift+R twice to **paste**.
3. A progress window shows the percentage, which item is being copied, and the time remaining. Press Cancel to stop.

The percentage follows the bytes actually copied, so a single big file moves along too. USB flash drives get gentler settings with more patient retries. If a copy fails, xPlorer tries once more with slower settings. At the end NVDA says how many items succeeded and how many failed. If anything could not be copied, a warning window lists those items. A move removes the originals only after they have been copied. The list of marked items is cleared when the paste starts.


### File Basket

The File Basket collects files and folders from different places so you can deal with them together. What is in the basket is kept when NVDA restarts.

- **Single tap** of NVDA+Shift+N adds the selected items and says what was added. Items that are already there are not added twice.
- **Double tap** opens the basket. **Triple tap** empties it and says what was cleared. From the menu, File Basket adds the selection and opens the basket in one step.
- In the basket window choose an **Action** : Copy, Move, Zip or Mirror Copy. Choose the destination folder with **Browse**, then press **Execute**. For Zip you choose the name of the zip file.
- **Mirror Copy** replaces anything that has the same name in the destination with a fresh copy.
- **Remove Selected** (or the Delete key) takes one item out. **Clear Basket** removes them all.
- NVDA says how many items succeeded and failed when it is done.


### Workspaces

A workspace is a named group of folders that you open together, each in its own File Explorer window. It is good for a project that always needs the same few places.

- **Open the menu** with NVDA+Shift+M once. Choose a workspace to load it. Folders that are already open are brought to the front instead of opened twice. NVDA says how many it opened and how many were already open. Choose the same workspace again and the windows it opened are closed.
- **Save one** by tapping NVDA+Shift+M twice. If you have a folder selected it starts a new workspace with that folder. Repeat on other folders to add them. Otherwise the Save Workspace window opens with the current folder in it. In that window type a name, add folders with **Add Folder...**, or paste or type paths one per line, then press Save.
- **Edit them** with NVDA+Shift+M three times. The list offers Load, Edit and Delete. Open the context menu on a workspace for Pin to Top, Move Up, Move Down, Delete and Clear All Workspaces. Pinned workspaces stay at the top of the list.


### Recent Locations

xPlorer remembers the folders you visit, up to 100. Tap NVDA+Shift+X twice, or choose Recent Locations from the menu, and press Enter on one to open it. Open the context menu (Applications key or Shift+F10) for **Pin** or **Unpin**, **Clear all (except pinned)**, and a choice between **Normal display** and **Reversed display**, which reads the folder names from the innermost folder outwards. Pinned places are never dropped when the list is full. Folders that no longer exist are not listed.


### Folder Sync & Compare

1. Open the folder you want as the **left** side and choose **Mark Left Folder (Sync Compare)** from the menu.
2. Open the other folder and choose **Run Compare (Sync Compare)**.
3. A list shows only the differences, by path inside the folders: Only in left, Only in right, or Different (size/date).
4. Select an item and press **Copy Selected to Right** to copy it from the left folder to the right one. Missing subfolders are created. Files that exist only on the right side cannot be copied this way.

Files are compared by size and by date and time of change. Subfolders are included. Nothing is deleted or changed unless you press the copy button.


### Duplicate Finder

Select a folder, or just open one, and choose Duplicate Finder from the menu. xPlorer scans it and everything inside it for files that are the same.

- Two files count as the same when they have the same size and the same first 64 KB of content. Empty files are ignored. Check the files before you delete if exactness matters to you.
- The window has a list of **Duplicate groups**, each shown as "2 copies, 1.5 MB each", with the biggest waste first, and a list of the files in the selected group.
- Press **Keep Newest**, **Keep Oldest** or **Keep File in This Folder** to keep one file and move all the other copies of that group to the Recycle Bin. Keep File in This Folder keeps the copy that sits directly in the folder you scanned.


### Creating Files and Folders

- **Create File** : choose how many files to create (1 to 10) and give each a name and an extension (txt by default). A number is added if a name is already used. The files are empty, apart from a one-line encoding header in py, html, css, xml, xaml and svg files.
- **Create Multiple Folders** : type a title and a number of folders (1 to 100) to make folders named like Title1, Title2 and so on. Tick **Edit individual folder names** to type each name yourself. Tick **Create main folder and then subfolders** to make the title folder first and put the others inside it.
- **TXT to Folder** : select one txt or rtf file. Every non-empty line becomes a folder, inside a new folder named after the file.


### Case Converter for Folders

Choose Uppercase, Lowercase, Title Case or Headline Case on the menu. The selected folders and every subfolder inside them are renamed. Files are not touched. Headline Case keeps small words such as "and", "of" and "the" in lower case, except at the start and end. A folder is skipped if the new name already exists. NVDA says how many folders were converted.


### Operation History

xPlorer keeps a list of what it has done: renames and undone renames, zip files, extractions, ISO files, Robocopy jobs, File Basket actions, created files and removed duplicates. It holds the last 200, most recent first. Open it from the menu. The **Clear History** button empties it.


### Settings

Open NVDA's Settings and choose the xPlorer category, or choose xPlorer Settings on the menu.

- Automatically select the first item (when you enter a folder).
- Announce "Empty Folder" when entering an empty folder, and instead of "Working on it".
- Suppress the announcement of DirectUIHWND, of "- File Explorer" in window titles, and of "Task Switching".
- Announce and select the item when it is the only one in a folder.
- Announce the size of files and folders when moving through the list, with a choice of File only, Folder only or All files and folders.
- Announce the item position, linked to NVDA's own Object Presentation setting.
- Move the focus into the file list when File Explorer is activated with the focus stuck on the window frame.
- Automatically paste clipboard content into the rename field, and what to replace forbidden characters with: a hyphen, an underscore, or nothing.
- Show the uncompress dialog, and what to do when it is hidden: extract to a subfolder named after the archive, or extract here.

The settings are kept in the NVDA configuration folder in use, under ChaiChaimee\xPlorer. Lists such as workspaces, recent locations, the basket and the history are saved there too.


### Automatic Updates

When installed from a downloaded file (not from the Add-on Store), xPlorer looks on GitHub once a day for a newer release, a short time after NVDA starts. If there is one you are asked **Update now** or **Later**. If you choose to update, the file is downloaded and handed to NVDA's own add-on installer. If the download fails, the releases page opens in your browser.


## Support Me

If this tool has made your life easier, consider fueling the next update with a small donation.

[![Support me](https://img.shields.io/badge/Donate-Support%20Me-blue?style=for-the-badge&logo=stripe)](https://buy.stripe.com/dRm9AU1xQ3Ds22N6VK1VK01)

Your support means the world. Let's build something great together.

---

&copy; 2026 Chai Chaimee. NVDA add-on released under the GNU GPL.
