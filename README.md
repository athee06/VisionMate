# VisionMate

Fast, fully offline image descriptions for the [NVDA screen reader](https://www.nvaccess.org/).

VisionMate describes the current element, the whole screen, or an image on the clipboard, on your own computer.
Images are never sent to the internet. No accounts, no API keys, no usage limits.

## Install

1. **[Download VisionMate](https://github.com/athee06/VisionMate/releases/latest/download/VisionMate.nvda-addon)**
2. Open the downloaded file, confirm the installation, and restart NVDA.
3. A welcome window opens. VisionMate needs its vision data (about 1.5 GB), downloaded only once.
   Press Enter to download it. While it downloads, press Space to hear the progress.
   If the download is interrupted, it continues from where it stopped.

## Commands

| Keys | What it does |
|---|---|
| NVDA+Alt+A | Describe the current element |
| NVDA+Alt+F | Describe the whole screen |
| NVDA+Alt+D | Describe the image, or copied image file, on the clipboard |

- Press a command **once** for a quick spoken description.
- Press it **twice** for a detailed description that reads all text, in a window with Copy and Close buttons.
- Press **Control** to stop speaking.

You can change the commands in NVDA's Input Gestures dialog, under VisionMate.

## Settings

NVDA menu > Preferences > Settings > VisionMate: use the graphics card, get ready when NVDA starts,
answer in NVDA's language, beep while waiting, and automatic update checks.

## Requirements

- Windows 10 or 11, 64-bit
- NVDA 2024.1 or later
- About 2 GB of free disk space and 8 GB of RAM or more. A graphics card that supports Vulkan makes it much faster;
  without one, VisionMate uses the processor.

## Privacy

VisionMate does not collect any information about you or your use. It connects to the internet only to download
its vision data and to check for updates.

## Credits

VisionMate uses [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT licence).
Licence information for the vision data is included with the data.
