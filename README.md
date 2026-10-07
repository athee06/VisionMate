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
| NVDA+Alt+G | Turn automatic descriptions of unlabeled images on or off |

- Press a command **once** for a quick spoken description.
- Press it **twice** for a longer, more detailed description, including visible text, in a window with Copy and Close buttons.
- Press **Control** to stop speaking.
- **Automatic descriptions** (off by default): images without a label are described in one sentence as you read web pages and documents.

You can change the commands in NVDA's Input Gestures dialog, under VisionMate.

## Settings

NVDA menu > Preferences > Settings > VisionMate: use the graphics card, get ready when NVDA starts,
answer in NVDA's language, beep while waiting, and automatic update checks.

## Requirements

- Windows 10 or 11, 64-bit
- NVDA 2024.1 or later
- About 2 GB of free disk space, and 8 GB of RAM or more (VisionMate uses about 3 GB while it is ready)
- A graphics chip or card that supports Vulkan makes it much faster. Without one, VisionMate uses the processor.

## What to expect

Measured on one laptop: Intel Core Ultra 5 135U with its built-in Intel graphics, 32 GB RAM.
Your computer may be faster or slower.

| | With graphics (default) | Processor only |
|---|---|---|
| Quick description: first words | about 2 seconds | about 5 seconds |
| Quick description: finished | 5 to 7 seconds | 8 to 11 seconds |
| Detailed description: first words | 3 to 5 seconds | 10 to 14 seconds |
| Detailed description: finished | 16 to 28 seconds | 40 to 47 seconds |
| Memory (RAM) while ready | about 2.8 GB, up to 3.1 GB | about 2.7 GB, up to 3.2 GB |

- Getting ready takes about 4 seconds. With "Get ready when NVDA starts" on (the default), this happens in the
  background when NVDA starts. If you turn it off, the first description takes about 4 seconds longer, and memory
  is used from then until NVDA restarts.
- Images full of text, like receipts and documents, take longer than photos.

## Accuracy

Descriptions are written by AI and can be wrong. VisionMate can miss or misread details, especially small text,
numbers, and busy screenshots. One-sentence automatic descriptions are the least detailed.
For anything important, such as amounts, dates, names or medicine labels, check another way,
for example with NVDA's built-in text recognition (NVDA+R).

## Privacy

VisionMate does not collect any information about you or your use. It connects to the internet only to download
its vision data and to check for updates.

## Credits

VisionMate uses [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT licence).
Licence information for the vision data is included with the data.
