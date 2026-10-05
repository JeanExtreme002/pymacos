<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/JeanExtreme002/pymacos/main/docs/_static/brand/wordmark-dark.svg">
    <img alt="pymacos" src="https://raw.githubusercontent.com/JeanExtreme002/pymacos/main/docs/_static/brand/wordmark-light.svg" width="360">
  </picture>
</p>

<br>

## A Pythonic interface to macOS

Control your whole Mac from Python: apps, notifications, input, screen, camera, microphone, OCR, media, Keychain, Touch ID and more, with one import and zero dependencies.

<table>
    <tr>
        <th>docs</th>
        <td>
            <a href="https://macos.readthedocs.io/?badge=latest"><img
                alt="Documentation Status"
                src="https://readthedocs.org/projects/macos/badge/?version=latest"></a>
        </td>
    </tr>
    <tr>
        <th>tests</th>
        <td>
            <a href="https://github.com/JeanExtreme002/pymacos/actions/workflows/lint.yml"><img
                alt="GitHub Actions build status (Lint)"
                src="https://github.com/JeanExtreme002/pymacos/actions/workflows/lint.yml/badge.svg"></a>
            <a href="https://github.com/JeanExtreme002/pymacos/actions/workflows/test.yml"><img
                alt="GitHub Actions build status (Test on macOS and Linux)"
                src="https://github.com/JeanExtreme002/pymacos/actions/workflows/test.yml/badge.svg"></a>
            <a href="https://github.com/JeanExtreme002/pymacos/actions/workflows/build.yml"><img
                alt="GitHub Actions build status (Build: the package built, installed and tested)"
                src="https://github.com/JeanExtreme002/pymacos/actions/workflows/build.yml/badge.svg"></a>
            <a href="https://app.codecov.io/gh/JeanExtreme002/pymacos"><img
                alt="Code coverage"
                src="https://codecov.io/gh/JeanExtreme002/pymacos/branch/main/graph/badge.svg"></a>
        </td>
    </tr>
    <tr>
        <th>package</th>
        <td>
            <a href="https://pypi.org/project/pymacos/"><img
                alt="Newest PyPI version"
                src="https://img.shields.io/pypi/v/pymacos.svg"></a>
            <a href="https://pypi.org/project/pymacos/"><img
                alt="Supported Python versions"
                src="https://img.shields.io/pypi/pyversions/pymacos.svg?color=8A2BE2"></a>
            <a href="https://pypi.org/project/pymacos/"><img
                alt="Platform"
                src="https://img.shields.io/badge/platform-macOS-lightgrey.svg"></a>
            <a href="https://pypi.org/project/pymacos/"><img
                alt="Typed"
                src="https://img.shields.io/pypi/types/pymacos.svg"></a>
            <a href="https://github.com/JeanExtreme002/pymacos/blob/main/LICENSE"><img
                alt="License"
                src="https://img.shields.io/pypi/l/pymacos.svg"></a>
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
| **Apps & Automation** | [Apps](https://macos.readthedocs.io/en/latest/apps.html), [Browser](https://macos.readthedocs.io/en/latest/browser.html), [Clipboard](https://macos.readthedocs.io/en/latest/clipboard.html), [Events](https://macos.readthedocs.io/en/latest/events.html), [Hotkeys](https://macos.readthedocs.io/en/latest/hotkeys.html), [Keyboard](https://macos.readthedocs.io/en/latest/keyboard.html), [Maps](https://macos.readthedocs.io/en/latest/maps.html), [Menu Bar](https://macos.readthedocs.io/en/latest/menubar.html), [Mouse](https://macos.readthedocs.io/en/latest/mouse.html), [Music](https://macos.readthedocs.io/en/latest/music.html), [Schedule](https://macos.readthedocs.io/en/latest/schedule.html), [Shortcuts](https://macos.readthedocs.io/en/latest/shortcuts.html), [Windows](https://macos.readthedocs.io/en/latest/windows.html) |
| **User Interaction** | [Dialogs](https://macos.readthedocs.io/en/latest/dialog.html), [Notifications](https://macos.readthedocs.io/en/latest/notifications.html), [Sound](https://macos.readthedocs.io/en/latest/sound.html), [Speech](https://macos.readthedocs.io/en/latest/speech.html) |
| **Files & Documents** | [Audio Files](https://macos.readthedocs.io/en/latest/audio-files.html), [Documents](https://macos.readthedocs.io/en/latest/document.html), [Finder](https://macos.readthedocs.io/en/latest/finder.html), [Images](https://macos.readthedocs.io/en/latest/image.html), [PDF](https://macos.readthedocs.io/en/latest/pdf.html), [Spotlight](https://macos.readthedocs.io/en/latest/spotlight.html), [Video](https://macos.readthedocs.io/en/latest/video.html) |
| **Intelligence** | [Language](https://macos.readthedocs.io/en/latest/language.html), [Vision](https://macos.readthedocs.io/en/latest/vision.html) |
| **Security** | [Authentication](https://macos.readthedocs.io/en/latest/auth.html), [Keychain](https://macos.readthedocs.io/en/latest/keychain.html) |
| **System & Hardware** | [Appearance](https://macos.readthedocs.io/en/latest/appearance.html), [Audio](https://macos.readthedocs.io/en/latest/audio.html), [Bluetooth](https://macos.readthedocs.io/en/latest/bluetooth.html), [Camera](https://macos.readthedocs.io/en/latest/camera.html), [Defaults](https://macos.readthedocs.io/en/latest/defaults.html), [Dock](https://macos.readthedocs.io/en/latest/dock.html), [Network](https://macos.readthedocs.io/en/latest/network.html), [Power](https://macos.readthedocs.io/en/latest/power.html), [Printer](https://macos.readthedocs.io/en/latest/printer.html), [Screen](https://macos.readthedocs.io/en/latest/screen.html), [Settings](https://macos.readthedocs.io/en/latest/settings.html), [System](https://macos.readthedocs.io/en/latest/system.html), [Time Machine](https://macos.readthedocs.io/en/latest/time_machine.html), [Trackpad](https://macos.readthedocs.io/en/latest/trackpad.html), [Volume](https://macos.readthedocs.io/en/latest/volume.html) |

## Install

```bash
pip install pymacos
```

The package is installed as `pymacos` and imported as `macos`.

Requires macOS and Python 3.9+.

## Why

A notification from plain Python means AppleScript inside a string, which breaks as soon as the message contains a quote:

```python
subprocess.run(["osascript", "-e", 'display notification "Build finished" with title "CI"'])
```

With pymacos:

```python
macos.notify("Build finished", title="CI")
```

Across the whole package:

- No dependencies: no PyObjC, nothing to compile.
- Plain, typed functions that return Python objects.
- Any text is safe: nothing is pasted into shell or AppleScript source.
- Clear errors when macOS is missing a permission, instead of silent failures.

See [Why pymacos?](https://macos.readthedocs.io/en/latest/why.html) for a longer comparison.

## Documentation

The full guide and API reference are at **[macos.readthedocs.io](https://macos.readthedocs.io)**.

## License

Released under the [MIT License](https://github.com/JeanExtreme002/pymacos/blob/main/LICENSE) — free for personal and commercial use.

<sub>Not affiliated with or endorsed by Apple Inc. macOS is a trademark of Apple Inc.</sub>
