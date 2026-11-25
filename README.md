# VisionMate

Fast, fully offline image descriptions and an accessible overlay for the [NVDA screen reader](https://www.nvaccess.org/).

VisionMate describes what is on your screen, photos in chat apps, image viewers and File Explorer, on
your own computer. For windows and games NVDA cannot read, its overlay turns the window into a list you can move
through and click. Images are never sent to the internet. No accounts, no API keys, no usage limits.

## What's new in 6.0

**Working the mouse and the screen**

- **Pointer mode:** NVDA+Alt+U. The arrow keys move the mouse pointer and VisionMate says what is under it, from
  NVDA or by reading the text there. Enter clicks, Space holds the button for dragging, H hovers and says what
  appears, T gives touch and pen gestures, G is a game mouse for games that turn the view with the mouse.
- **Controller mode:** NVDA+Alt+Q, or hold View and Menu together: a game controller works the mouse pointer.
- **Find on screen:** NVDA+Alt+E. Type what you are looking for, like "Save button". VisionMate says roughly where
  it is and can click it, move the mouse there, or do more with it.

**The overlay**

- **Actions:** press A on an item for more than a click: hover and hear what appears, drag and drop, press and hold,
  set a drawn knob or slider to a number, work it with the arrow keys, write on the line next to a label of a
  scanned form, and touch or pen gestures.
- **It sees more:** fields and error messages a form marks in red (R moves to them), colour choices named by their
  measured colour, and the picture puzzles of checks that ask whether you are a person: the kind of check is named
  with the ways through it that need no sight, and each square is numbered and described. U moves to the most useful
  item. Tables are read row by row (T, and Control+Alt+arrows), and areas that scroll say "more below".
- **Cleaner:** an icon or thumbnail beside a label is part of that item, not a second one, and NVDA's mouse tracking
  no longer talks over the overlay.

**Descriptions**

- **The newest picture in a chat:** NVDA+Alt+Shift+A, leaving out emoji and the little pictures next to names.
- **Stop and how far:** NVDA+Alt+X stops a description or an answer. NVDA+Alt+P says how far it is.
- **Detailed window:** Read all text, Describe people, Describe colours, Where is..., and Save (Control+S).
  "What is in this photo, and is there any text in it?" is answered as two questions, and a question about colours
  first gets the colours measured from the pixels, like "navy blue 60 percent".
- **Memories and your own instructions:** type "remember that I am colour blind" in a description window, or add
  memories in settings. Every instruction VisionMate gives the vision data can be read and rewritten.

**And also**

- **Help offered:** where a window, dialog or control tells NVDA little, VisionMate says so once; NVDA+Alt+Y takes it.
- **VisionMate's own voice:** a different pitch, rate or volume for descriptions and answers.
- **Portable copy:** the add-on and its vision data for a flash drive or another computer, so it needs no download.
- **Faster and more reliable:** pressing again on a screen that barely changed starts speaking in under a second;
  the engine restarts by itself if it stops; a dropped download resumes by itself.
- **Settings** are in groups, with a Reset to defaults button.

## Install

- **From the NVDA Add-on Store** (recommended): NVDA menu > Tools > Add-on Store, search for VisionMate, and install it.
  Updates then come through the Add-on Store.
- Or **[download VisionMate](https://github.com/athee06/VisionMate/releases/latest/download/VisionMate.nvda-addon)**,
  open the file, confirm the installation, and restart NVDA.

After installing, a welcome window opens. VisionMate needs its vision data (about 1.5 GB), downloaded only once.
Press Enter to download it. While it downloads, press Space to hear the progress. With a portable copy of
VisionMate (see Settings), choose **From a portable copy** instead; on a flash drive it is found by itself.
If the connection drops, the download continues by itself from where it stopped.

## The keys

Every describe key works the same way: press it **once** for a quick spoken description, or **twice** for a detailed
description in a window. Press **Control** to stop speaking. You can change any key in NVDA's Input Gestures dialog,
under VisionMate.

### NVDA+Alt+A: the current element

Describes the element under the NVDA navigator, like an image, a button or a photo message. On a photo message it
describes the photo itself, not the name and time around it. On an image file in File Explorer or on the desktop,
it describes the file without opening it.

### NVDA+Alt+W: the current window

Describes the window in front. In an image viewer such as Photos, it describes the photo file at full quality.

### NVDA+Alt+F: the whole screen

Describes everything on the screen. Screen text is read exactly with Windows OCR.

### NVDA+Alt+D: the clipboard

Describes the image, or the copied image file, on the clipboard.

### NVDA+Alt+E: find on screen

Type what you are looking for, like "Save button", "search box" or just "Settings". VisionMate reads the window while
you type, then says what it found and roughly where, like "Save button, at the bottom right". Choose Click, or
Move the mouse there. If several things match, choose one from the list. Small spelling mistakes in the screen text
are fine.

### NVDA+Alt+O: the overlay

For programs and games whose buttons and menus NVDA cannot read. VisionMate shows the window as a list: its text,
its icons (named by the vision data), and what kind of item each one is, like "Save button", "Name edit field" or
"Remember me checkbox, checked". A window with a dialog, a sidebar or bars is split into areas, with the dialog first.

- Up and Down arrows, or Tab and Shift+Tab: move between items.
- H, B, E, X, K, D, T: next heading, button, edit field, checkbox or radio button, link, area, table.
  Add Shift for the previous one.
- Control+Alt+arrows: move by row and column in a table.
- Enter: click the item in the real window (desktop shortcuts and list items are opened). Space: a single click.
  Shift+Enter: a double click. Applications key: a right click.
- Escape, or NVDA+Alt+O again: close the overlay.

The overlay updates itself as the window changes. "Selected:" at the top says which entry of a menu is selected.
The overlay works from the picture of the window, so it can sometimes get a name or kind wrong. NVDA+Alt+N lets you
fix a name, and your names are kept.

### NVDA+Alt+G: automatic descriptions

Turns automatic descriptions on or off (off by default). When on, images without a label are described in one
sentence as you read web pages and documents, and photo messages, image files and photos opened in a viewer are
described when you stay on them.

### NVDA+Alt+B: button names

Turns names for buttons that have no name on or off. When on, such buttons are named from their icon.

### NVDA+Alt+N: your own names

Gives your own name to the current button, or to the current item in the overlay.

### NVDA+Alt+Shift+A: the newest picture in a chat

Finds the newest picture in the window, the lowest one that is bigger than emoji and the little pictures next to
names, brings it into view and describes it. Press twice for the detailed window.

### NVDA+Alt+P and NVDA+Alt+X: how far, and stop

NVDA+Alt+P says what VisionMate is doing and for how long. NVDA+Alt+X stops a description, an answer, or a held mouse
button.

### NVDA+Alt+U: pointer mode

Works the mouse pointer from the keyboard. While pointer mode is on:

- Arrows: move the pointer (Shift: a little, Control: far). What is under it is said, unless NVDA's mouse tracking
  says it already.
- Enter: click. Shift+Enter: double-click. Applications key: right-click.
- Space: hold the left button down, move with the arrows, Space again lets go. That is a drag.
- Page Up and Page Down: the mouse wheel. With Shift: sideways.
- Home: the middle of the window. S: say what is under the pointer. H: hover and say what appears.
- A: more actions. T: touch and pen gestures, like a pinch, a swipe with two fingers or a hard pen press. They need
  no touch screen and no pen.
- G: the game mouse. Many games turn the view with the mouse and take no notice of where the pointer is; with the
  game mouse the arrows move the mouse itself, the way such a game reads it.
- Escape, or NVDA+Alt+U again: leave pointer mode.

### NVDA+Alt+Q: controller mode

With an Xbox controller, or one Windows reads the same way, connected: the left stick moves the pointer, the right
stick scrolls, A clicks, B right-clicks, X double-clicks, Y says what is under the pointer, LB holds the button for
dragging, RB hovers, the D-pad moves a little. Hold View and Menu together to turn controller mode on or off.
Outside controller mode the controller only goes to the game.

### NVDA+Alt+Y: take the help offered

Where a window tells NVDA almost nothing, a dialog has nothing with the focus, or a button has no name, VisionMate
says so once. NVDA+Alt+Y opens the overlay on the most useful item, or names the button. Press it twice for no more
offers in that program, and twice again there to have them back. Offers can be turned off in settings.

## The overlay's actions

In the overlay, press **A** on an item, or choose **More** in find on screen:

- Click, double-click, right-click, move the mouse there.
- **Hover, and say what appears:** the pointer rests on it and the text that came up, like a tip, is read.
- **Start a drag here**, then on another item **Drop here**. Or **drag it a little or a lot** in a direction.
- **Press and hold** for a few seconds, for buttons and checks that ask for it.
- **Set it to a number:** a knob, dial or slider that is only drawn is moved step by step, and the number next to it is
  read after each step until it is the number you asked for. Where no number shows, it is left as it is.
- **Work it with the arrow keys:** dial mode. Up and down change it, and the number next to it is said. M tries
  another way of moving it.
- **Write on the line next to this label:** on a scanned form that is only a picture, the printed line or box next to
  the label is found, clicked, and what you type is written there and checked.
- **Touch or pen gesture here**, and **pointer mode from here**.

Also in the overlay: **U** moves to the most useful item, where a sighted person's eye goes first, like the selected
item, the Continue or OK button, or an empty field. **R** and Shift+R move to items the form marks in red.

## The detailed window

Press a describe key twice to open it. Read the description line by line, then:

- Type a question about the image in the Question box and press Enter. A question in several parts is answered one
  part at a time. A question about colours first gets the colours measured from the picture's pixels.
- Type **remember that** and something about you, like "remember that I am colour blind, always name colours".
  VisionMate gives it with every description and answer you ask for. "What do you remember" and "forget ..." work too.
- **Read all text:** every bit of text in the image, exactly as written.
- **Describe people** and **Describe colours:** answers straight away.
- **Where is...:** starts a question for you, like "Where is the".
- **Save** (Control+S): saves the description and your questions to a text file.
- **Copy**, and **Close** (or Escape).

## Photos in chat apps

- **WinZapp (WhatsApp):** VisionMate gets each photo through WinZapp's "Open image" button by itself and closes the
  viewer at once, so you stay on the message. The copy WinZapp writes for the viewer is deleted straight away.
- **Unigram (Telegram):** the full-size photo Unigram keeps on your computer is described, so small text is read clearly.
- **Other chat apps** that show photos on screen: the photo is cut out of the message.

WinZapp stickers cannot be described yet, because WinZapp offers no way to open them.

## Settings

NVDA menu > Preferences > Settings > VisionMate. The settings are in five groups:

- **Descriptions:** automatic descriptions, describing images further down the page in the background, names for
  buttons without a name, Windows OCR, answering in NVDA's language, and a soft tick while waiting. Two buttons open
  **what VisionMate remembers about you**, and **how VisionMate answers**: every instruction it gives the vision data,
  to read, rewrite or restore, and your own instruction for every answer.
- **Overlay:** keeping the overlay up to date as the window changes.
- **Status and help:** after how long "Still working" is said (or never), offering help where a window tells NVDA
  little, and the game controller: tell me when one is connected, listen quietly, or do not look for one.
- **VisionMate's voice:** a pitch, rate and volume change from NVDA's voice for descriptions and answers, and a button
  to hear it.
- **Speed and memory:** using the graphics card, getting ready when NVDA starts, and **making a portable copy** with
  the vision data, for a flash drive or another computer.

**Reset to defaults** sets them all back; press OK to keep that.

VisionMate frees its memory by itself when your computer runs low, and on computers with 16 GB of RAM or less after
30 minutes unused. Without "Get ready when NVDA starts", it still gets ready shortly after NVDA starts on computers
with plenty of memory, and frees it after 10 minutes unused.

VisionMate works with NVDA's screen curtain on, without ever turning it off. If a window can't be seen that way
(some games and video players), VisionMate asks you to turn the screen curtain off.

## Requirements

- Windows 10 or 11, 64-bit
- NVDA 2024.1 or later
- About 3 GB of free disk space while the vision data is installed (2 GB after), and 8 GB of RAM or more
  (VisionMate uses about 3 GB while it is ready)
- A graphics chip or card that supports Vulkan makes it much faster. Without one, VisionMate uses the processor.

## What to expect

Measured on one laptop: Intel Core Ultra 5 135U with its built-in Intel graphics, 32 GB RAM.
Your computer may be faster or slower.

| | With graphics (default) |
|---|---|
| Quick description: first words | about 2 seconds |
| The same screen again, within 30 seconds | under 1 second |
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
its vision data. What you ask it to remember, and your own instructions, are kept in files on your computer. Photos from chat apps are read on your computer and never copied or sent anywhere.
Add-on updates come through the NVDA Add-on Store.

## Credits

VisionMate uses [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT licence).
Licence information for the vision data is included with the data.
