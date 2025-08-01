xPlorer  

Author: 'chai chaimee  

URL: https://github.com/chaichaimee/xPlorer  
Overview:  

xPlorer is a simple NVDA add-on that improves the experience of using Windows File Explorer. It enhances feedback and navigation for screen reader users in common Explorer views such as folder lists, drive contents, and navigation panes.  

Features:  

    • Announce Size of Selected Item  
    Pressing the assigned gesture (e.g., NVDA+Ctrl+X) reports the size of a selected file or folder, or   used space of a drive in File Explorer.  
    • Auto-Speak for Empty Folders  
   Announces “Empty Folder” when navigating into a folder with no items.  
    • Auto-Select First Item  
    • Automatically selects and speaks the first item when entering a non-empty folder view in Explorer.  
    • Simplified Focus Reporting  
    • Suppresses redundant announcements like "View list items" for cleaner and more concise feedback in File Explorer.  
    • Improved Focus Handling  
    Resolves focus lag in some Explorer panes (e.g., Home view) by programmatically shifting focus after a delay.  
    • Enhanced File Item Feedback  
    If a folder contains only one item, selecting it will automatically report its name for better navigation clarity.  
    • Localized Overlay Classes  
    Adds a custom object overlay to suppress unnecessary focus ancestor output in certain UI elements like toolbars and lists.  
    • Safe Gesture Handling  
    Uses gesture.send() to return gestures back to NVDA when the active context is not File Explorer, ensuring compatibility with other applications and global NVDA commands.
