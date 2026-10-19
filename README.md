# VisionMate

Fast, fully offline image descriptions and an accessible overlay for the [NVDA screen reader](https://www.nvaccess.org/).

VisionMate describes the current element, the current window, the whole screen, or an image on the clipboard, on your
own computer. For windows and games NVDA cannot read, its overlay turns the window into a list you can move through
and click. Images are never sent to the internet. No accounts, no API keys, no usage limits.

## Install

- **From the NVDA Add-on Store** (recommended): NVDA menu > Tools > Add-on Store, search for VisionMate, and install it.
  Updates then come through the Add-on Store.
- Or **[download VisionMate](https://github.com/athee06/VisionMate/releases/latest/download/VisionMate.nvda-addon)**,
  open the file, confirm the installation, and restart NVDA.

After installing, a welcome window opens. VisionMate needs its vision data (about 1.5 GB), downloaded only once.
Press Enter to download it. While it downloads, press Space to hear the progress.
If the download is interrupted, it continues from where it stopped.

## Commands

| Keys | What it does |
|---|---|
| NVDA+Alt+A | Describe the current element |
| NVDA+Alt+W | Describe the current window |
| NVDA+Alt+F | Describe the whole screen |
| NVDA+Alt+D | Describe the image, or copied image file, on the clipboard |
| NVDA+Alt+O | Open or close the overlay for the current window |
| NVDA+Alt+G | Turn automatic descriptions of unlabeled images on or off |
| NVDA+Alt+B | Turn names for buttons that have no name on or off |
| NVDA+Alt+N | Give your own name to the current button or overlay item |

- Press a describe command **once** for a quick spoken description.
- Press it **twice** for a detailed description in a window, where you can also **ask questions** about the image.
- Press **Control** to stop speaking.
- **Automatic descriptions** (off by default): images without a label are described in one sentence as you read
  web pages and documents.
- Screen text is read exactly with Windows OCR, and each event has its own short sound.
- Works with NVDA's screen curtain on, without ever turning it off. If a window can't be seen that way
  (some games and video players), VisionMate asks you to turn the screen curtain off.

You can change the commands in NVDA's Input Gestures dialog, under VisionMate.

## The overlay

For programs and games whose buttons and menus NVDA cannot read. Press NVDA+Alt+O and VisionMate shows the window
as a list: its text, its icons (named by the vision data), and what kind of item each one is, like
"Save button", "Name edit field" or "Remember me checkbox, checked". A window with a dialog, a sidebar or bars
is split into areas, with the dialog first.

- Up and Down arrows, or Tab and Shift+Tab: move between items.
- H, B, E, X, K, D: next heading, button, edit field, checkbox or radio button, link, area. Add Shift for the previous one.
- Enter: click the item in the real window (desktop shortcuts and list items are opened). Space: a single click.
  Shift+Enter: a double click. Applications key: a right click.
- Escape: close the overlay.

The overlay stays open and updates itself as the window changes. It works from the picture of the window,
so it can sometimes get a name or kind wrong. NVDA+Alt+N lets you fix a name, and your names are kept.

## Settings

NVDA menu > Preferences > Settings > VisionMate: automatic descriptions, describing images further down the page
in the background, names for buttons without a name, Windows OCR, keeping the overlay up to date, using the graphics
card, getting ready when NVDA starts, answering in NVDA's language, and a soft tick while
waiting. VisionMate frees its memory by itself when your computer runs low.

## Requirements

- Windows 10 or 11, 64-bit
- NVDA 2024.1 or later
- About 2 GB of free disk space, and 8 GB of RAM or more (VisionMate uses about 3 GB while it is ready)
- A graphics chip or card that supports Vulkan makes it much faster. Without one, VisionMate uses the processor.

## What to expect

Measured on one laptop: Intel Core Ultra 5 135U with its built-in Intel graphics, 32 GB RAM.
Your computer may be faster or slower.

| | With graphics (default) |
|---|---|
| Quick description: first words | about 2 seconds |
| Detailed description (press twice): first words | about 1.5 to 2 seconds after the first press |
| Overlay: list ready | about half a second, plus a few seconds to name new icons |
| Memory (RAM) while ready | about 3 GB |

- Without a graphics chip, a quick description starts in about 5 seconds.
- Getting ready takes about 4 seconds. With "Get ready when NVDA starts" on (the default), this happens in the
  background when NVDA starts.
- Images full of text, like receipts and documents, take longer than photos.

## Accuracy

VisionMate uses AI, and AI can make mistakes. Descriptions may miss or misread details,
so please double-check anything important.

## Privacy

VisionMate does not collect any information about you or your use. It connects to the internet only to download
its vision data. Add-on updates come through the NVDA Add-on Store.

## Credits

VisionMate uses [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT licence).
Licence information for the vision data is included with the data.
