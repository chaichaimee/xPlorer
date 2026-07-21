# xPlorer

![NVDA Logo](https://www.nvaccess.org/files/nvda/documentation/userGuide/images/nvda.ico)

Enhance file management on Windows File Explorer with automation and intelligent tools that outperform the original.

**author:** chai chaimee  
**URL:** https://github.com/chaichaimee/xPlorer

---

## Introduction

**xPlorer** is an NVDA add‑on that lets you quickly save and access frequently used files and folders. It transforms Windows File Explorer into a powerful, keyboard‑driven command centre, reducing repetitive steps and giving you instant control over your files. Whether you are organising thousands of documents, managing code repositories, or simply keeping your desktop tidy, xPlorer provides the tools you need — all from the comfort of your screen reader.

---

## Hotkeys & Quick Reference

All xPlorer commands work inside a File Explorer window. Where a hotkey supports multi‑tap (single, double, or triple press), the action changes accordingly.

### NVDA+Shift+R – Robo System (Copy / Paste / Move)

- **Single tap:** Lock the selected file(s) or folder(s) as the source for copying.
- **Double tap:** Paste the locked source into the current folder (copy).
- **Triple tap:** Move the source to the current folder (cut & paste).

**How to use:** First, select the items you want to copy or move. Single tap to lock them. Then navigate to the destination folder and double‑tap to copy, or triple‑tap to move. The operation runs in the background with progress feedback.

### NVDA+Shift+X – xPlorer Context Menu

Opens a rich menu with all major xPlorer tools, including: create file, compress zip, invert selection, copy address bar, copy file content, copy selected names, rename file, say size, Robocopy sub‑menu, TXT to Folder, create multiple folders, case conversion for folders, folder info, and settings. Use the arrow keys to navigate and press Enter to activate.

### NVDA+Shift+Z – Size / Compress

- **Single tap:** Calculate and speak the total size of all selected files and folders.
- **Double tap:** Compress the selected items into a .zip archive using the built‑in compressor (or 7‑Zip if installed).

**How to use:** Select the items you want to check or compress. A single tap reports the size after a short calculation. Double‑tap starts compression; you will hear a progress beep and a completion tone.

### NVDA+Shift+C – Copy Names / Address

- **Single tap:** Copy the names of all selected files and folders to the clipboard (folders first, then files, sorted).
- **Double tap:** Copy the full path of the current folder to the clipboard.

**How to use:** Simply press once or twice. The add‑on announces how many names or the copied path.

### NVDA+Shift+V – Extract Content / Invert Selection

- **Single tap:** Extract the text content from selected text‑based files (.txt, .py, .html, .css, .json, .rtf, etc.) and copy it to the clipboard — without opening the files.
- **Double tap:** Invert the selection in the current folder (select all unselected items and deselect the currently selected ones).

**How to use:** Select the files you want to extract content from, then single‑tap. For invert selection, double‑tap; the operation works on large folders in batches to avoid slowing down NVDA.

### NVDA+Shift+F2 – Rename File (Keep Extension)

Opens a dialog where you can change the file name while preserving the extension. The extension field is separate, so you never accidentally lose it.

**How to use:** Select exactly one file, then press the hotkey. Enter the new name and extension, then press OK.

### Control+Shift+N – Create Folder with Automatic Naming

Creates a new folder and, if the clipboard contains suitable text (no invalid characters, not too long), automatically pastes that text as the folder name in the rename field — saving you from extra keystrokes.

**How to use:** Copy the desired folder name to the clipboard, then press this hotkey in any File Explorer window. The new folder is created and immediately renamed to the clipboard content.

All hotkeys work only when File Explorer is the foreground window. If you are in another application, the gesture passes through normally.

---

## Features in Depth

### 1. Robo System – Industrial‑Strength Copy & Move

The Robo System replaces traditional Ctrl+C and Ctrl+V with a faster, more reliable mechanism. It is especially effective when dealing with large files or folders containing thousands of sub‑items.

- **How to copy:** Select the items you want to copy. Press **NVDA+Shift+R** once to lock them as the source. Navigate to the destination folder and press the same hotkey twice. The items are copied using an optimised background process.
- **How to move:** Follow the same steps, but at the destination, press the hotkey three times. The source items are moved (cut and pasted) at maximum speed.
- The system uses direct file‑path logic and can be up to 50% faster than Windows' standard file operations, with clear audio feedback (beeps) to indicate progress.

### 2. Context Menu – All Tools in One Place

Press **NVDA+Shift+X** to open a comprehensive menu that gives you access to every xPlorer feature. This is the central hub for all advanced operations.

- **Create File:** Opens a dialog to create multiple new files at once. You can specify the base name, extension, and the number of files. Useful for quickly setting up project templates.
- **Compress Zip:** Same as double‑tapping NVDA+Shift+Z — compresses selected items into a .zip archive with automatic duplicate handling.
- **Invert Selection:** Toggles the selection state of all items in the folder. Works efficiently even with hundreds of items.
- **Copy Address Bar:** Copies the current folder path to the clipboard.
- **Copy Content:** Extracts text from selected text files (including RTF) and places it on the clipboard.
- **Copy Selected Names:** Copies the names of selected items (folders first, then files) to the clipboard.
- **Rename Selected File:** Opens the rename dialog with separate fields for name and extension.
- **Say Size:** Announces the total size of the selected items.
- **Robocopy sub‑menu:** Offers Copy, Move, and Paste actions — identical to the triple‑tap system but accessible from the menu.
- **TXT to Folder:** Creates a folder structure from a text file. Each line in the file becomes a subfolder inside a new parent folder. Supports both .txt and .rtf files.
- **Create Multiple Folders…** Opens a dialog where you can define a base name and the number of folders to create. You can also choose to create subfolders inside a main folder, and even edit each folder name individually.
- **Case Converter for Folders:** Renames selected folders to Uppercase, Lowercase, Title Case, or Headline Case. The conversion works recursively on all subfolders.
- **Folder Info:** Speaks the number of subfolders and files inside the selected folder (recursively).
- **xPlorer Settings:** Opens the add‑on settings panel where you can toggle auto‑select first item, empty folder announcement, suppression of DirectUIHWND class announcements, suppression of “- File Explorer” in window titles, and automatic clipboard paste on folder creation.

### 3. Smart Compression & Archiving

Whether you use the hotkey or the menu, xPlorer compresses selected files and folders into a .zip archive. It automatically checks for existing archive names and appends a counter if a duplicate is found. Audio beeps keep you informed of the progress, and you can cancel the operation at any time.

- **How to use:** Select the items you want to archive. Press **NVDA+Shift+Z** twice (or choose "Compress zip" from the menu). A progress dialog appears, and a success or failure tone plays when finished.

### 4. Instant File Content Extraction

When you need to quickly peek into a text file without opening it, use this feature. It reads the contents of selected text‑based files (including .txt, .py, .html, .css, .json, .rtf, and many more) and copies the combined text to the clipboard.

- **How to use:** Select one or more text files. Press **NVDA+Shift+V** once. The content is extracted and copied, and a message tells you how many files were processed.

### 5. Advanced Folder Creation and Management

- **Create Multiple Folders:** Use the menu option to open a dialog where you can specify a base name and the number of folders. You can even edit each folder name individually before creation. Optionally, you can create a main folder and subfolders within it.
- **TXT to Folder:** Select a .txt or .rtf file that contains a list of folder names (one per line). The add‑on creates a new parent folder (named after the file) and inside it, creates subfolders for each line. This is perfect for setting up directory structures from a list.
- **Auto‑paste from clipboard:** When you create a new folder (via Control+Shift+N), the add‑on automatically checks the clipboard for suitable text and uses it to name the new folder, saving you from extra keystrokes.

### 6. Case Conversion for Folders

You can rename selected folders (and all their subfolders) to a consistent case pattern. This is invaluable for keeping project files organised.

- **How to use:** Select one or more folders in File Explorer. Open the xPlorer context menu (**NVDA+Shift+X**), go to "Case Converter for Folders", and choose Uppercase, Lowercase, Title Case, or Headline Case. The operation runs in the background and announces the number of successfully renamed folders.

### 7. Intelligent Selection & Information

- **Invert Selection:** Double‑tap **NVDA+Shift+V** or choose from the menu. It toggles selection efficiently, even for folders with thousands of items.
- **Say Size:** Single‑tap **NVDA+Shift+Z** to get the total size of all selected items. The calculation is performed in the background, and a periodic beep indicates that it is still running. The final size is spoken in human‑readable units (KB, MB, GB).
- **Folder Info:** From the menu, select "Folder info" to hear the total number of subfolders and files inside the selected folder (recursively).

---

## Benefits

- **Save Time:** Automate repetitive file operations that normally require multiple clicks and keystrokes — now condensed into a single gesture.
- **Reduce Keystroke Fatigue:** Ergonomic hotkeys minimise finger travel, allowing you to work longer without discomfort.
- **Boost Productivity:** Stay in the flow by switching between tasks without losing focus. xPlorer eliminates unnecessary context switching.
- **Work with Confidence:** Clear audio feedback (beeps) and spoken confirmations keep you informed of every operation's status, so you never have to second‑guess.
- **Organise Like a Pro:** Tools like batch folder creation, case conversion, and TXT‑to‑folder help you maintain a clean, consistent file structure with minimal effort.

---

## Why Use xPlorer?

Windows File Explorer works — but it wasn't built for speed, and it certainly wasn't built with screen reader efficiency in mind. The gap between what you want to do and what you can do with a few keystrokes is often filled with tedious navigation, repetitive menu‑diving, and wasted motion. xPlorer closes that gap. It takes the most common file‑management tasks — copying, moving, renaming, compressing, and organising — and condenses them into intuitive, ergonomic hotkeys that work the way you think. If you touch files every day, xPlorer isn't just a nice‑to‑have; it's a must‑have.

---

## Take Control of Your File Workflow

xPlorer puts the power of a professional file management suite right under your fingertips — without the complexity, without the bloat, and without sacrificing accessibility. It's built for people who value their time and want every keystroke to count. Whether you're migrating terabytes of data, organising a decade of personal files, or just want to zip a few documents without the hassle, xPlorer delivers speed, reliability, and a level of control you never knew you were missing. Download it today and feel the difference.

---

## Support Me

If this tool has made your work easier and faster, you can support me here as encouragement to continue developing new features.

[![Donate](https://img.shields.io/badge/Donate-Support%20Me-blue?style=for-the-badge&logo=stripe)](https://buy.stripe.com/dRm9AU1xQ3Ds22N6VK1VK01)

Every support is a driving force for us to create the best tools for all users.

---

© 2026 Chai Chaimee NVDA Add-on Released under GNU GPL.