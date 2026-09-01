<div align="center">

![NVDA Logo](https://www.nvaccess.org/files/nvda/documentation/userGuide/images/nvda.ico)

# xPlorer

Your keyboard-only command center for File Explorer - copy, rename, compress, sync, and organize files without ever touching the mouse.

**author:** chai chaimee  
**url:** https://github.com/chaichaimee/xPlorer

</div>

## Introduction

xPlorer is a huge productivity toolkit for Windows File Explorer, built specifically for efficient, accessible use with NVDA. Instead of digging through Explorer's ribbon and right-click menus, almost everything xPlorer offers is reachable with a handful of NVDA hotkeys - many of which do three different things depending on how many times you tap them in quick succession.

With xPlorer you can: instantly hear the size of a selection or a whole folder tree; rename one file or hundreds at once with patterns and counters; gather files from many different folders into a virtual "basket" and then copy, move, zip, or mirror them all in one go; compare two folders and copy over only what's missing or different; find and clean up duplicate files; convert folder names to a different case in bulk; turn a plain text file into a stack of folders; browse an entire folder tree as one flat, filterable list; compress and extract archives; copy or move huge amounts of data reliably with Robocopy, complete with speed and time-remaining feedback; save and reopen whole "workspaces" of folders at once; and keep a running history of everything xPlorer has done, so you can always check what happened.

A large, accessible context menu (opened with a single hotkey) ties all of these tools together in one place, alongside a full xPlorer Settings panel for fine-tuning how Explorer behaves and speaks with NVDA.

### Hot Keys

> **NVDA+Shift+C**  
> Single Tap: Copy the selected file and folder names to the clipboard  
> Double Tap: Copy the text content of the selected file(s)  
> Triple Tap: Copy the current folder's address bar path

> **NVDA+Shift+V**  
> Single Tap: Select all other items that share the focused item's file extension  
> Double Tap: Invert the current selection  
> Triple Tap: Toggle Multi-select mode on or off (non-contiguous selection with the keyboard)

> **NVDA+Shift+A**  
> Single Tap: Open the Select by Search dialog  
> Double Tap: Open Flat View  
> Triple Tap: Open the Batch Rename Tool

> **NVDA+Shift+Z**  
> Single Tap: Announce the total size of the current selection  
> Double Tap: Compress the selection into a zip file  
> Triple Tap: Extract (unzip) the selected archive

> **NVDA+Shift+R**  
> Single Tap: Robocopy - mark the selection to copy  
> Double Tap: Robocopy - paste into the current folder  
> Triple Tap: Robocopy - mark the selection to move

> **NVDA+Shift+X**  
> Single Tap: Open the main xPlorer context menu  
> Double Tap: Open the Recent Locations menu

> **NVDA+Shift+F2**  
> Single Tap: Rename the selected file  
> Double Tap: Rename the selected file or folder using the current clipboard text  
> Triple Tap: Undo the last batch rename operation

> **NVDA+Shift+N**  
> Single Tap: Add the selected item(s) to the File Basket  
> Double Tap: Open the File Basket window  
> Triple Tap: Clear the File Basket

> **NVDA+Shift+M**  
> Single Tap: Open the Workspace menu  
> Double Tap: Add the selected folder to a new workspace, or save the current folder as a workspace  
> Triple Tap: Open the Workspace editor (rename, pin, reorder, or delete saved workspaces)

> **Control+Shift+N**  
> Single Tap: Create a new folder in the current location, then automatically paste the current clipboard text into the rename field

## Features

### Clipboard Operations (NVDA+Shift+C)

This one hotkey covers three related clipboard actions depending on how many times you press it within about half a second:

1. **Single tap** copies the names of every selected file and folder to the clipboard as plain text, folders listed first, then files, both alphabetically.
2. **Double tap** copies the actual text content of the selected file(s) - it only works with recognized text-based file types (.txt, .py, .js, .html, .csv, .md, and similar), and refuses if a folder is selected.
3. **Triple tap** copies the path currently shown in Explorer's address bar, regardless of what is selected.

### Selection Tools (NVDA+Shift+V and the Selection submenu)

1. **Single tap** - Select by Extension: looks at whichever file currently has focus, and selects every other item in the folder that shares the same file extension.
2. **Double tap** - Invert Selection: everything currently selected becomes unselected, and everything unselected becomes selected.
3. **Triple tap** - Multi-select mode: instead of NVDA intercepting your key presses, xPlorer genuinely holds the Ctrl key down at the operating system level. This means your own Arrow keys, Space, Enter, Ctrl+C, and Ctrl+X all behave exactly as if you were physically holding Ctrl while using Explorer's native selection - nothing is re-implemented or guessed. Pressing Delete or Shift+Delete while the layer is active is handled specially so it deletes normally instead of being seen as Ctrl+Delete. Pressing any other key, or leaving Explorer, automatically switches Multi-select mode off, and a five-minute safety timer will also turn it off automatically if you forget.

**Select by Search** (also reachable from the context menu's Selection submenu) opens a dialog where you can select items in the current folder by:

- **Normal search**: a plain, case-insensitive substring match.
- **Regex**: a full regular expression.
- **Wildcard**: patterns like `*.txt` or `report_*.docx`; you can separate several patterns with commas or spaces to match any of them.
- An optional **"Include subfolders"** checkbox extends the search recursively - a top-level folder is selected if a match is found anywhere inside it.
- As you type, a live results list updates automatically (after a short pause, so it doesn't lag while typing), showing exactly which items currently match.
- From the results list you can press Enter to open an item, Ctrl+C or Ctrl+X to copy or cut it, Ctrl+Space to pick individual items, or open a context menu (right-click or the Menu key) for Copy, Cut, Open to path, or Delete (which sends the item to the Recycle Bin, not a permanent delete).

### Say Size and Compress/Uncompress (NVDA+Shift+Z)

1. **Single tap** - Say size: calculates and announces the total size of everything currently selected. Folders are measured recursively, and a whole drive is measured using the drive's actual free/used space rather than walking every file. A periodic beep plays while a large calculation is still running.
2. **Double tap** - Compress zip: compresses the selection into a .zip file in the same folder, showing a progress dialog with percentage and beeping tones. If 7-Zip is installed, xPlorer uses it for speed; otherwise it falls back to Python's built-in zip support.
3. **Triple tap** - unCompress: extracts a selected archive (.zip, .rar, .7z, .tar, .gz, .iso, .nvda-addon, and more, when 7-Zip is available). Depending on your xPlorer Settings, you'll either be asked to choose between extracting into a new subfolder named after the archive or extracting directly into the current folder, or xPlorer will apply your preferred default automatically without asking.

### Robocopy (NVDA+Shift+R and the Robocopy submenu)

1. **Single tap** - Copy: marks the current selection to be copied.
2. **Double tap** - Paste: performs the transfer into whichever folder you are currently viewing in Explorer.
3. **Triple tap** - Move: marks the current selection to be moved instead of copied.

Transfers run through Windows' Robocopy utility in the background, with a progress dialog showing percentage complete, transfer speed, and an estimated time remaining. xPlorer automatically detects older or removable drives (like USB flash drives) and switches to gentler, more patient retry settings for them instead of the faster multi-threaded mode used for internal drives, and each file copy is verified afterward by comparing file sizes.

### Open xPlorer Context Menu / Recent Locations (NVDA+Shift+X)

1. **Single tap** opens the full xPlorer context menu - a single accessible list containing every tool below, organized with submenus where appropriate. Menu items that need a live Explorer selection (like Properties or Rename) are hidden automatically when you open the menu outside of Explorer.
2. **Double tap** opens Recent Locations directly (see below).

### Recent Locations

xPlorer quietly keeps track of the last 100 unique folders you've visited in Explorer. Opening this menu lets you jump straight back to any of them. Right-clicking (or pressing the Menu key on) an entry lets you Pin or Unpin it so it survives the "Clear all" action and the 100-item limit, clear every unpinned entry at once, and switch between showing paths normally or with their folder segments reversed (handy for very long paths in the narrow menu).

### Rename Selected File / Undo (NVDA+Shift+F2)

1. **Single tap** opens a small dialog with separate name and extension fields for the single selected file.
2. **Double tap** renames the selected file or folder using whatever text is currently on the clipboard - for files, if the clipboard text doesn't already include an extension, the file's original extension is kept automatically. Clipboard text containing line breaks or characters that aren't valid in a file name is rejected with a message.
3. **Triple tap** undoes the most recent Batch Rename Tool operation, restoring every renamed file to its original name.

### Create Folder with Auto-Paste (Control+Shift+N)

This works alongside Explorer's own "New Folder" shortcut: xPlorer creates the folder as normal, then - if enabled in xPlorer Settings - automatically types the current clipboard text into the folder's rename field for you, saving you from typing (or pasting) the name by hand. Several different low-level methods are tried in sequence to make sure the paste succeeds reliably.

### File Basket (NVDA+Shift+N)

The File Basket is a virtual staging area: nothing is actually copied or moved on disk until you tell it to. You can gather files and folders from several different locations across multiple Explorer windows into one basket, then act on the whole collection at once.

1. **Single tap** adds the current selection to the basket.
2. **Double tap** opens the File Basket window, listing every item currently gathered.
3. **Triple tap** empties the basket.

From the File Basket window you can remove individual items, clear everything, and run one of four bulk actions on the whole basket: **Copy**, **Move**, **Zip** (saved as a single archive you choose the name and location for), or **Mirror Copy** (copies items to the destination, replacing anything already there with the same name). The basket persists even if you restart NVDA, until you clear it.

### Workspace Manager (NVDA+Shift+M)

A workspace is simply a named group of folder paths you use together often.

1. **Single tap** opens the Workspace menu, listing every saved workspace plus an option to save the current selection as a new one.
2. **Double tap** either adds whichever folder(s) you currently have selected in Explorer to a new workspace, or, if nothing is selected, opens the Save Workspace dialog directly.
3. **Triple tap** opens the full Workspace editor, where you can rename, delete, pin to the top, and reorder your saved workspaces.

Loading a workspace opens every one of its folders, each in its own Explorer window. Loading the same workspace a second time closes exactly the windows xPlorer itself opened for it, acting as a convenient toggle, without ever touching a window it didn't open.

### Batch Rename Tool

Opened via NVDA+Shift+A (triple tap) or from the context menu, this tool renames many files at once using either of two modes:

- **Find and replace**: replace one piece of text with another across all selected file names, optionally treating the search text as a regular expression.
- **Tag pattern**: build a new name from a template such as **[N]_[C].[E]**, where **[N]** is the original name, **[C]** is an incrementing counter (with a starting value you choose), **[D]** is the file's last-modified date, and **[E]** is its extension.

A live preview list shows exactly what every file will be renamed to before you confirm, and duplicate resulting names are automatically numbered to avoid clashes. The whole operation can be undone afterward with the Undo Last Rename option (also available via NVDA+Shift+F2, triple tap).

### Duplicate Finder

Scans the selected folder (or the current folder if nothing is selected) recursively for duplicate files. Files are first grouped by exact size, then compared using a hash of the start of their content, so only genuine duplicates are grouped together. Results are shown as a list of duplicate groups; selecting a group shows every copy along with its modification date, and you can resolve a group with one click by choosing to keep the newest copy, the oldest copy, or specifically the copy that lives in the folder you originally scanned - everything else in that group is sent safely to the Recycle Bin, not permanently deleted.

### Folder Sync and Compare

A two-step, read-only comparison tool, reached from the context menu's Folder Sync & Compare submenu:

1. **Mark Left Folder** remembers the folder you're currently viewing as the "left" side of the comparison.
2. Navigate to a second folder and choose **Run Compare**, which becomes the "right" side.

xPlorer then walks both folder trees and reports every file that exists only on the left, only on the right, or exists on both but differs in size or modification date. Nothing is changed automatically - you can select any "left only" or "different" entry and use the Copy Selected to Right button to bring that specific file across when you decide it's needed.

### Case Converter for Folders

Found in the context menu's Case Converter for Folders submenu, this recursively renames the selected folder(s) and every subfolder inside them to one of four cases: **Uppercase**, **Lowercase**, **Title Case** (every word capitalized), or **Headline Case** (capitalizes major words while keeping small connecting words like "a", "the", "and", or "of" lowercase, except at the very start or end of the name).

### TXT to Folder

Select a single .txt or .rtf file and choose TXT to Folder from the context menu. xPlorer reads the file line by line and creates one new subfolder for every non-empty line, using that line's text as the folder's name (invalid characters are automatically cleaned up, and reserved Windows names like CON or PRN are adjusted). All of the new subfolders are created together inside one new folder named after the original text file.

### Create Multiple Folders

Opens a dialog where you specify a folder title and how many folders to create (up to 100). By default the folders are named "Title1", "Title2", and so on, but you can tick a checkbox to type a completely custom name for each one individually. There's also an option to create one main folder first and place all the numbered folders inside it as subfolders, rather than creating them all side by side in the current location. Folders are created in the background so the dialog stays responsive even for a large batch.

### Flat View

Reached via NVDA+Shift+A (double tap) or from the context menu, Flat View scans the entire folder tree under your current Explorer folder and lists every file it finds in one single, flat, filterable list - regardless of how deeply nested it is - showing each file's name, its relative subfolder, and its size. As you type into the filter box, the list narrows down live. Activating an entry opens the file directly, and there's also a button to jump straight to that file's actual location in Explorer.

### Create File

Opens a dialog for creating one or more new, empty files at once (up to 10) in the current folder, each with its own name and extension. If you leave a name blank, xPlorer fills in a sensible default like "new_file" automatically.

### Properties, Say Size, and Folder Info (context menu)

The **Properties** entry shows a read-only, fully reviewable panel with details about the selected item: its name, location, size, and created/modified/accessed dates (shown in friendly relative terms like "today" or "yesterday" when appropriate). For folders, the size and content counts are calculated in the background and filled in once ready. Selecting a whole drive instead shows drive-specific details: its volume name, file system type, and free, used, and total capacity.

**Say size** (also available directly through NVDA+Shift+Z, single tap) announces the total size of your current selection. **Folder info** appears only when a folder is selected, and announces the total number of subfolders and files contained within it, calculated recursively.

### Operation History

xPlorer keeps a running, timestamped log of what it has done for you - renames, copies, moves, extractions, and more - up to the most recent 200 entries. Open it from the context menu to review recent activity, or clear the whole history at any time.

### xPlorer Settings

A dedicated panel inside NVDA's own Settings dialog lets you fine-tune how xPlorer behaves:

- **Automatically select the first item**: when a file list gains focus, the first (or already-focused) item is automatically selected for you, matching Explorer's usual mouse behavior.
- **Announce "Empty Folder"**: controls whether NVDA speaks a clear "Empty Folder" message when you enter a folder with nothing in it.
- **Suppress announcement of DirectUIHWND class**: quiets a normally-unhelpful internal window class name that Explorer sometimes reports.
- **Suppress announcement of "- File Explorer" in window titles**: trims that suffix from spoken window titles for a cleaner announcement.
- **Automatically paste clipboard content into rename field**: controls the Control+Shift+N auto-paste behavior described above.
- **Show uncompress dialog**: when off, extracting an archive skips the "where should this go" prompt and always uses your chosen default action (extract to a named subfolder, or extract directly into the current folder) automatically.

> **Note:** Several tools that scan large folder trees (Say size, Folder info, Duplicate Finder) use a bounded, "good enough" scan that stops early on extremely large trees to keep NVDA responsive, rather than freezing while counting hundreds of thousands of files.

## Support Me

If this tool has made your life easier, consider fueling the next update with a small donation.

[![Support me](https://img.shields.io/badge/Donate-Support%20Me-blue?style=for-the-badge&logo=stripe)](https://buy.stripe.com/dRm9AU1xQ3Ds22N6VK1VK01)

Your support means the world. Let's build something great together

<div align="center">

&copy; 2026 Chai Chaimee NVDA Add-on Released under GNU GPL

</div>