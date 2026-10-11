# Quick Start

pymacos is a single import. Its functions take and return plain Python
(strings, numbers, {class}`~pathlib.Path` objects, dataclasses), so there's
nothing new to learn beyond the function names.

## Your first script

```python
import macos

macos.notify("Hello from Python", title="pymacos")
macos.say("Hello from Python")
```

A notification shows up in the corner of the screen, and your Mac says hello.

## A tour

One block per area, in the same order as the sidebar. Each links to its
full guide.

### Apps & Automation

```python
safari = macos.apps.open("Safari")                   # App(name='Safari', ...)
safari.quit()

macos.apps.open_with("report.pdf", "Preview")

macos.clipboard.copy("hello")
macos.clipboard.paste()                              # 'hello'

macos.keyboard.type("Hello from Python")
macos.keyboard.press("cmd+s")
macos.mouse.click(300, 400)
macos.mouse.click_text("Submit")                     # wherever it shows on the screen

macos.windows.focused().set_frame(0, 25, 1280, 800)
macos.windows.focused().snap("left")                 # the left half, like Rectangle

macos.shortcuts.run("Translate", input="Hola")       # 'Hello'
macos.music.now_playing()                            # Track(title='Imagine', artist='John Lennon', ...)

macos.browser.current_tab()                          # Tab(title='pymacos', url='https://github.com/...', ...)

macos.schedule.add("backup", "backup.py", every=3600)

macos.events.on("wake", lambda event: macos.say("Welcome back"))
macos.events.run()                                   # calls it on each wake, until Ctrl-C
```

The keyboard, the mouse and windows need the
[Accessibility permission](permissions.md#accessibility). See
[Apps](apps.md), [Clipboard](clipboard.md), [Keyboard](keyboard.md),
[Mouse](mouse.md), [Windows](windows.md), [Shortcuts](shortcuts.md),
[Music](music.md), [Browser](browser.md), [Events](events.md),
[Schedule](schedule.md) and [Maps](maps.md), plus [Hotkeys](hotkeys.md) for
global shortcuts.

### User Interaction

```python
macos.notifications.notify("3 tests failed", title="CI", sound="Basso")
macos.speech.say("Build finished")

if macos.dialog.confirm("Continue?"):
    name = macos.dialog.prompt("Your name:")
```

See [Notifications](notifications.md), [Speech](speech.md),
[Dialogs](dialog.md) and [Sound](sound.md).

### Files & Documents

```python
macos.finder.add_tags("report.pdf", "Work")
macos.finder.trash("old.log")
macos.spotlight.search("kind:pdf invoice")   # [PosixPath('.../invoice-march.pdf'), ...]
macos.finder.wait_for_change("~/Downloads")  # Event(path=..., kind='created', is_dir=False)

macos.image.convert("IMG_0042.heic", "IMG_0042.jpg")
macos.pdf.text("report.pdf")
macos.audio.trim("interview.m4a", "answer.m4a", start=95, duration=30)
macos.video.add_audio("trip.mov", "music.m4a", "trip-music.mp4", volume=0.4)
```

See [Finder](finder.md), [Spotlight](spotlight.md), [Images](image.md),
[PDF](pdf.md), [Documents](document.md), [Audio Files](audio-files.md) and
[Video](video.md).

### Intelligence

```python
macos.vision.text("receipt.png")                       # the text in the image
macos.vision.classify("beach.jpg")                     # [('beach', 0.91), ('sky', 0.84), ('people', 0.62)]
macos.vision.barcodes("poster.jpg")                    # [Barcode(payload='https://...', kind='QR', ...)]
macos.vision.remove_background("dog.jpg")              # PNG bytes of the dog alone
macos.vision.duplicates(["a.jpg", "b.jpg", "c.jpg"])   # the look-alike photos, in groups
macos.vision.body_pose("dance.jpg")                    # every person's joints: shoulders, wrists, knees...

macos.audio.classify("clip.m4a")            # [('dog_bark', 0.93), ('speech', 0.41)]

macos.language.detect("Où est la gare ?")              # 'fr'
macos.language.sentiment("This is broken and slow.")   # -0.8
macos.language.entities("Tim Cook announced the iPhone in Cupertino.")
# [Entity(text='Tim Cook', kind='person', ...), Entity(text='Cupertino', kind='place', ...)]
```

Everything runs on your Mac, offline, with Apple's own models. See
[Vision](vision.md), [Language](language.md) and [Audio Files](audio-files.md).

### Security

```python
macos.keychain.set("my-app", "alice", "s3cret")
macos.keychain.get("my-app", "alice")              # 's3cret'

if macos.auth.confirm("unlock the deploy token"):  # Touch ID or the password
    token = macos.keychain.get("deploy", "prod")
```

See [Keychain](keychain.md) and [Authentication](auth.md).

### System & Hardware

```python
macos.appearance.is_dark()                    # True
macos.volume.set(30)
macos.audio.set_output("AirPods")
macos.power.battery()                         # Battery(percent=87, charging=True, ...)
macos.dock.set_autohide(True)
macos.defaults.write("com.apple.finder", "ShowPathbar", True)

macos.screenshot("screen.png")
macos.screen.record("demo.mov", 10)
macos.camera.photo("me.jpg")                  # the webcam
macos.audio.record("memo.m4a", 10)            # the microphone

for device in macos.bluetooth.devices():
    print(device.name, device.battery)        # AirPods Pro {'left': 90, 'right': 85, 'case': 40}
```

See [Appearance](appearance.md), [Volume](volume.md), [Audio](audio.md),
[Dock](dock.md), [Defaults](defaults.md), [Time Machine](time_machine.md),
[Power](power.md), [Screen](screen.md), [Camera](camera.md),
[Bluetooth](bluetooth.md), [Network](network.md), [Printer](printer.md),
[Settings](settings.md), [Trackpad](trackpad.md) and [System](system.md).

## Putting it together

The pieces combine into small tools.

**Copy the text out of a screenshot:**

```python
shot = macos.screenshot(region=(0, 0, 800, 600))
macos.clipboard.copy(macos.vision.text(shot))
macos.notify("Text copied")
```

**Get told when a long job ends**, without the Mac falling asleep:

```python
with macos.power.keep_awake():
    train_model()

macos.notify("Training finished", title="ML", sound="Glass")
```

**Turn receipts into a PDF:**

```python
from pathlib import Path

photos = sorted(Path("~/Desktop/receipts").expanduser().glob("*.jpg"))
scans = [macos.vision.scan_document(photo) for photo in photos]   # cropped and straightened
macos.pdf.from_images([scan for scan in scans if scan], "receipts.pdf")
```

**Record a GIF of your screen with a shortcut:**

```python
def demo():
    macos.screen.record("demo.mov", 5)
    macos.video.to_gif("demo.mov", "demo.gif")
    macos.notify("demo.gif is ready")

macos.hotkeys.register("ctrl+option+r", demo)
macos.hotkeys.run()
```

## Permissions and errors

Some features need a privacy permission first (the screen, the camera,
Accessibility...). When one is missing, you get a clear error instead of a
silent failure. Everything macOS refuses or fails derives from
{class}`~macos.MacOSError`; a bad argument or a missing file raises the usual
builtin (`ValueError`, `FileNotFoundError`), as in [Errors](errors.md):

```python
try:
    macos.screenshot("screen.png")
except macos.PermissionDeniedError as error:
    print(error)   # says which permission to enable, and where
```

See [Permissions](permissions.md) for the list, and the
[API reference](api.md) for every function.
