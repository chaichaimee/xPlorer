<p align="center">
  <img src="https://www.nvaccess.org/files/nvda/documentation/userGuide/images/nvda.ico" alt="NVDA Logo" width="120">
  <br><br>
  <h1>xPlorer</h1>
  <p>NVDA Add-on that enhances File Explorer accessibility and productivity</p>
</p>

<p align="center">
  <a href="https://github.com/chaichaimee/xPlorer">
    <img src="https://img.shields.io/badge/GitHub-Repository-blue?logo=github" alt="GitHub Repository">
  </a>
  <img src="https://img.shields.io/badge/NVDA-Add--on-success" alt="NVDA Add-on">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python Version">
</p>

## Overview

**xPlorer** is an NVDA add-on designed to make working in Windows File Explorer faster, more convenient, and more accessible — especially for screen reader users.

The latest version introduces powerful new features including:

- **Copy address bar** (double-tap shortcut)
- **TXT to Folder** function — create multiple folders from a text list
- Compress to ZIP
- Safe rename with separate name/extension fields
- Copy file/folder names to clipboard
- Copy content from multiple text files without opening them
- Say size of files/folders/drives (including total size for multiple selections)
- Invert selection
- And more!

All main functions are conveniently gathered in one context menu (NVDA+Alt+X).

Here are some examples of File Explorer in action:

<grok-card data-id="4d128a" data-type="image_card"  data-arg-size="LARGE" ></grok-card>



<grok-card data-id="bb47a0" data-type="image_card"  data-arg-size="LARGE" ></grok-card>


## 🔑 Main Hotkeys

| Shortcut                              | Function                                                                                   |
|---------------------------------------|--------------------------------------------------------------------------------------------|
| `NVDA+Alt+X`                          | Open xPlorer Context Menu (all features in one place)                                      |
| `NVDA+Shift+Z`                        | Compress selected items to ZIP file                                                        |
| `NVDA+Shift+C`                        | Copy selected file/folder names to clipboard                                               |
| `NVDA+Shift+C` (double-tap)           | Copy current folder address bar path                                                       |
| `NVDA+Shift+F2`                       | Safe rename — opens window with separate filename and extension fields                    |
| `NVDA+Shift+V`                        | Copy content of selected text files (without opening them) — up to 10 MB per file         |
| `NVDA+Shift+I`                        | Invert selection (toggle selected/unselected items)                                       |
| `NVDA+Shift+X`                        | Announce size of selected file(s), folder(s), or drive(s) — shows total for multiples     |

> **Note**: All shortcuts can be customized in **NVDA → Input Gestures**.

### Safe Rename Feature Example
Edit filename and extension separately to prevent accidental changes:

<grok-card data-id="11891f" data-type="image_card"  data-arg-size="LARGE" ></grok-card>


### Compress to ZIP Example
Quickly compress files/folders using the built-in Windows function:

<grok-card data-id="9dcd40" data-type="image_card"  data-arg-size="LARGE" ></grok-card>


## Additional Features

Manage these via **NVDA menu → Preferences → Settings → xPlorer**:

- Automatically select the first item in folders
- Announce "Empty Folder" when entering empty directories
- Suppress announcement of DirectUIHWND class

### Advanced Tools

- **Robocopy integration** — smarter, resumable copy/move of large amounts of data (skips identical files)
- **Mirror Backup with Schedule** — automatic periodic mirror backups of folders using Robocopy
- **TXT to Folder** — select a .txt file containing a list → create a folder for each line item

## Installation

1. Download the latest `.nvda-addon` from [Releases](https://github.com/chaichaimee/xPlorer/releases)
2. Double-click the downloaded file
3. Confirm installation when prompted by NVDA
4. Restart NVDA

## Compatibility

- NVDA 2022.1 and later (recommended: latest version)
- Windows 10 / 11

## Author

**chai chaimee**  
GitHub: [@chaichaimee](https://github.com/chaichaimee)

## Donation

If you find **xPlorer** useful and would like to support development:  
💝 [Donate via GitHub Sponsors](https://github.com/chaichaimee)  
Thank you for your support!

---

Thank you for using **xPlorer** 🌟  
Make File Explorer work the way you want — faster and easier!
