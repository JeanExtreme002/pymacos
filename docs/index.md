---
og:description: Control your whole Mac from Python. Apps, notifications, input, screen, camera, microphone, OCR, media, Keychain, Touch ID and more, with one import and zero dependencies.
myst:
  html_meta:
    description: "Control your whole Mac from Python. Apps, notifications, input, screen, camera, microphone, OCR, media, Keychain, Touch ID and more, with one import and zero dependencies."
---

# pymacos

<p class="wordmark"><img alt="pymacos" src="_static/brand/wordmark-light.svg" width="360"></p>

<h2 class="tagline">A Pythonic interface to macOS</h2>

Control your whole Mac from Python: apps, notifications, input, screen, camera,
microphone, OCR, media, Keychain, Touch ID and more, with one import and zero
dependencies.

<table class="badge-table">
  <tr>
    <th>docs</th>
    <td>
      <a href="https://macos.readthedocs.io/?badge=latest"><img alt="Documentation Status" src="https://readthedocs.org/projects/macos/badge/?version=latest"></a>
    </td>
  </tr>
  <tr>
    <th>tests</th>
    <td>
      <a href="https://github.com/JeanExtreme002/pymacos/actions/workflows/lint.yml"><img alt="GitHub Actions build status (Lint)" src="https://github.com/JeanExtreme002/pymacos/actions/workflows/lint.yml/badge.svg"></a>
      <a href="https://github.com/JeanExtreme002/pymacos/actions/workflows/test.yml"><img alt="GitHub Actions build status (Test on macOS and Linux)" src="https://github.com/JeanExtreme002/pymacos/actions/workflows/test.yml/badge.svg"></a>
      <a href="https://github.com/JeanExtreme002/pymacos/actions/workflows/build.yml"><img alt="GitHub Actions build status (Build)" src="https://github.com/JeanExtreme002/pymacos/actions/workflows/build.yml/badge.svg"></a>
      <a href="https://app.codecov.io/gh/JeanExtreme002/pymacos"><img alt="Code coverage" src="https://codecov.io/gh/JeanExtreme002/pymacos/branch/main/graph/badge.svg"></a>
    </td>
  </tr>
  <tr>
    <th>package</th>
    <td>
      <a href="https://pypi.org/project/pymacos/"><img alt="Newest PyPI version" src="https://img.shields.io/pypi/v/pymacos.svg"></a>
      <a href="https://pypi.org/project/pymacos/"><img alt="Supported Python versions" src="https://img.shields.io/pypi/pyversions/pymacos.svg?color=8A2BE2"></a>
      <a href="https://pypi.org/project/pymacos/"><img alt="Platform" src="https://img.shields.io/badge/platform-macOS-lightgrey.svg"></a>
      <a href="https://pypi.org/project/pymacos/"><img alt="Typed" src="https://img.shields.io/pypi/types/pymacos.svg"></a>
      <a href="https://github.com/JeanExtreme002/pymacos/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/pypi/l/pymacos.svg"></a>
    </td>
  </tr>
</table>

```python
import macos

macos.notify("Build finished", title="CI")
macos.say("Done!")

macos.clipboard.copy("hello")
macos.appearance.is_dark()                      # True
macos.screenshot("screen.png")

macos.apps.open("Safari")                       # App(name='Safari', ...)
macos.keychain.get("my-app", "alice")           # 's3cret'

macos.power.battery()                           # Battery(percent=87, charging=True, ...)
macos.shortcuts.run("Translate", input="Hola")  # 'Hello'
macos.finder.trash("old.log")                   # moved to the Trash
```

## What's inside

| Area | Topics |
|---|---|
| **Apps & Automation** | [Apps](apps.md), [Browser](browser.md), [Clipboard](clipboard.md), [Events](events.md), [Hotkeys](hotkeys.md), [Keyboard](keyboard.md), [Maps](maps.md), [Menu Bar](menubar.md), [Mouse](mouse.md), [Music](music.md), [Schedule](schedule.md), [Shortcuts](shortcuts.md), [Windows](windows.md) |
| **User Interaction** | [Dialogs](dialog.md), [Notifications](notifications.md), [Sound](sound.md), [Speech](speech.md) |
| **Files & Documents** | [Audio Files](audio-files.md), [Documents](document.md), [Finder](finder.md), [Images](image.md), [PDF](pdf.md), [Spotlight](spotlight.md), [Video](video.md) |
| **Intelligence** | [Language](language.md), [Vision](vision.md) |
| **Security** | [Authentication](auth.md), [Keychain](keychain.md) |
| **System & Hardware** | [Appearance](appearance.md), [Audio](audio.md), [Bluetooth](bluetooth.md), [Camera](camera.md), [Defaults](defaults.md), [Dock](dock.md), [Network](network.md), [Power](power.md), [Printer](printer.md), [Screen](screen.md), [Settings](settings.md), [System](system.md), [Time Machine](time_machine.md), [Trackpad](trackpad.md), [Volume](volume.md) |

New here? Read [Why pymacos?](why.md), then start with
[Installation](installation.md) and the [Quick Start](quickstart.md).

```{toctree}
:caption: Getting Started
:hidden:

why
installation
quickstart
recipes
permissions
```

```{toctree}
:caption: Apps & Automation
:hidden:

apps
browser
clipboard
events
hotkeys
keyboard
maps
menubar
mouse
music
schedule
shortcuts
windows
```

```{toctree}
:caption: User Interaction
:hidden:

dialog
notifications
sound
speech
```

```{toctree}
:caption: Files & Documents
:hidden:

audio-files
document
finder
image
pdf
spotlight
video
```

```{toctree}
:caption: Intelligence
:hidden:

language
vision
```

```{toctree}
:caption: Security
:hidden:

auth
keychain
```

```{toctree}
:caption: System & Hardware
:hidden:

appearance
audio
bluetooth
camera
defaults
dock
network
power
printer
screen
settings
system
time_machine
trackpad
volume
```

```{toctree}
:caption: API Reference
:hidden:

api
errors
```

```{toctree}
:caption: Project
:hidden:

contributing
license
GitHub <https://github.com/JeanExtreme002/pymacos>
PyPI <https://pypi.org/project/pymacos/>
```
