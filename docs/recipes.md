# Recipes

Short scripts that solve everyday problems, each in a few lines. Copy one,
change the paths, and run it.

## Tidy the Downloads folder by itself

Move each new download into a folder for its kind, as soon as it arrives.
{func}`~macos.schedule.add` with `when_changed` runs the script whenever the
folder changes, even after a restart, with no Python left running:

```python
# tidy_downloads.py
from pathlib import Path

KINDS = {
    "Images": {".png", ".jpg", ".jpeg", ".heic", ".gif", ".webp"},
    "Documents": {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"},
    "Archives": {".zip", ".dmg", ".pkg", ".tar", ".gz"},
}

downloads = Path("~/Downloads").expanduser()

for file in downloads.iterdir():
    if not file.is_file() or file.name.startswith("."):
        continue

    for folder, extensions in KINDS.items():
        target = downloads / folder / file.name
        if file.suffix.lower() in extensions and not target.exists():
            target.parent.mkdir(exist_ok=True)
            file.rename(target)
```

```python
import macos

macos.schedule.add("tidy-downloads", "tidy_downloads.py", when_changed="~/Downloads")
```

Files still being downloaded end in `.download` or `.crdownload`, so they're
left alone until they're done. A download named like a file already sorted
stays where it is, rather than replacing it. Running the script from launchd, macOS asks
once for Python to access the Downloads folder.

## Black out Social Security numbers in a folder of PDFs

Share documents without the personal data in them. The text is removed,
not just covered, and the counts tell what was found:

```python
import re
from pathlib import Path

import macos

ssn = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
public = Path("public")
public.mkdir(exist_ok=True)

for pdf in Path("contracts").glob("*.pdf"):
    try:
        done = macos.pdf.redact(pdf, public / pdf.name, ssn)
    except ValueError:
        continue  # no SSN in this one
    print(pdf.name, done.matches[ssn.pattern], "SSNs on pages", sorted(done.pages))
```

Look over the results before sharing them: see what
{func}`~macos.pdf.redact` can't find, such as text inside pictures.

## Get warned before the AirPods run out

Check the battery of the Bluetooth devices every 15 minutes, and notify when
one runs low:

```python
# battery_check.py
import macos

for device in macos.bluetooth.devices():
    for part, percent in device.battery.items():
        if device.connected and percent <= 20:
            which = "Battery" if part == "main" else part.capitalize()   # Left, Right, Case
            macos.notify("{}: {}%".format(which, percent), title=device.name)
```

```python
import macos

macos.schedule.add("battery-check", "battery_check.py", every=15 * 60)
```

AirPods report each earbud and the case (`left`, `right`, `case`); a mouse
or a keyboard reports one level (`main`).

## A window manager in a few lines

Snap the window in front to a half of the screen, or tile every window, with
a keyboard shortcut:

```python
import macos

layouts = {
    "ctrl+option+left": "left",
    "ctrl+option+right": "right",
    "ctrl+option+up": "maximize"
}

def snap(layout):
    window = macos.windows.focused()
    if window is not None:   # the app in front may have no window
        window.snap(layout)

for keys, layout in layouts.items():
    macos.hotkeys.register(keys, lambda layout=layout: snap(layout))

macos.hotkeys.register("ctrl+option+t", lambda: macos.windows.tile_all(gap=8))

macos.hotkeys.run()   # until Ctrl-C
```

Listening to the shortcuts needs the [Input Monitoring](permissions.md#input-monitoring)
and [Accessibility](permissions.md#accessibility) permissions, for the app
running Python.

## Turn a folder of Word documents into PDFs

No Word needed:

```python
from pathlib import Path

import macos

for doc in Path("~/Reports").expanduser().glob("*.docx"):
    macos.document.convert(doc, doc.with_suffix(".pdf"), paper="a4")
```

The PDFs look like the documents opened in TextEdit: see
{func}`~macos.document.convert` for what a Word layout keeps.

## Know when a long job ends

Keep the Mac awake while a job runs, then say and show that it's done, so you
can walk away:

```python
import time

import macos

started = time.monotonic()

with macos.power.keep_awake():
    train_model()   # your long job

minutes = round((time.monotonic() - started) / 60)
macos.notify("Finished in {} minutes".format(minutes), title="Training", sound="Glass")

macos.say("Training finished")
```

## Copy the text out of your last screenshot

Take a screenshot of anything (a video, an image, a locked PDF) with ⌘⇧4,
then run this to have its text on the clipboard:

```python
import macos

# macOS marks every screenshot it takes: only those, not other images in the folder.
folder = macos.screen.screenshot_folder().resolve()
found = macos.spotlight.search("kMDItemIsScreenCapture == 1", folder=folder)
shots = [path for path in found if path.resolve().parent == folder]   # not in its subfolders

if shots:
    newest = max(shots, key=lambda path: path.stat().st_birthtime)   # taken last, not edited last
    text = macos.vision.text(newest)
    macos.clipboard.copy(text)
    macos.notify(text[:80] or "No text found", title="Copied")
```

It reads the newest screenshot in the folder screenshots go to (the Desktop,
unless you changed it), found through Spotlight, which takes a few seconds to
see a new one. {func}`~macos.vision.text` reads the text on the Mac
itself, with no internet needed. Add `languages=["fr-FR"]` for text in another language.
