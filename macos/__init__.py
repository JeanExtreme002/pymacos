# -*- coding: utf-8 -*-

"""
pymacos (imported as ``macos``) — a Pythonic interface to macOS.

Notifications, clipboard, webcam and microphone, keyboard and mouse, windows,
hotkeys, menu bar icons, appearance, apps, Keychain, speech, screenshots, power, Shortcuts,
Finder, volume, Spotlight, dialogs, system info, Bluetooth, music, browser
tabs, system events, scheduled scripts, OCR, document scanning, images,
videos, PDFs and language detection in one import, with no dependencies::

    import macos

    macos.notify("Build finished", title="CI")
    macos.clipboard.copy("hello")
    macos.appearance.is_dark()
    macos.apps.running()
    macos.keychain.get("my-app", "alice")
    macos.say("Done!")
    macos.screenshot("screen.png")
    macos.power.battery()
    macos.shortcuts.run("Resize Image", input=Path("photo.jpg"))
    macos.finder.trash("old.log")
    macos.volume.set(30)
    macos.spotlight.search("kind:pdf invoice")
    macos.dialog.confirm("Continue?")
    macos.system.idle_time()
    macos.vision.text("screenshot.png")
    macos.open_with("report.pdf", "Preview")
    macos.image.convert("IMG_0042.heic", "IMG_0042.jpg")
    macos.pdf.text("report.pdf")
    macos.language.detect("Hola, ¿cómo estás?")
    macos.vision.remove_background("photo.jpg")
    macos.vision.scan_document("receipt.jpg")
    macos.audio.set_output("AirPods")
    macos.keyboard.press("cmd+c")
    macos.mouse.click(300, 400)
    macos.bluetooth.devices()
    macos.windows.focused().set_frame(0, 25, 1280, 800)
    macos.hotkeys.wait("ctrl+option+s")
    macos.video.convert("screen.mov", "screen.mp4", quality="medium")
    macos.music.now_playing()
    macos.browser.current_tab()
    macos.events.wait("wake")
    macos.schedule.add("backup", "backup.py", every=3600)
    macos.finder.watch("~/Downloads")

The package imports on any platform (so it can sit in cross-platform code and
docs builds), but its functions raise :class:`NotSupportedError` outside macOS.
"""

__version__ = "1.20.0"

from . import (
    appearance,
    apps,
    audio,
    auth,
    bluetooth,
    browser,
    camera,
    clipboard,
    defaults,
    dialog,
    dock,
    document,
    events,
    finder,
    hotkeys,
    image,
    keyboard,
    keychain,
    language,
    maps,
    menubar,
    mouse,
    music,
    network,
    notifications,
    pdf,
    power,
    printer,
    schedule,
    screen,
    settings,
    shortcuts,
    sound,
    speech,
    spotlight,
    system,
    time_machine,
    trackpad,
    video,
    vision,
    volume,
    windows,
)
from .errors import (
    AppNotFoundError,
    CommandError,
    KeychainError,
    MacOSError,
    NotSupportedError,
    PermissionDeniedError,
    ShortcutNotFoundError,
)
from .launch import open, open_with
from .notifications import notify
from .screen import screenshot
from .speech import say

__all__ = [
    "appearance",
    "apps",
    "audio",
    "auth",
    "bluetooth",
    "browser",
    "camera",
    "clipboard",
    "defaults",
    "dialog",
    "dock",
    "document",
    "events",
    "finder",
    "hotkeys",
    "image",
    "keyboard",
    "keychain",
    "language",
    "maps",
    "menubar",
    "mouse",
    "music",
    "network",
    "notifications",
    "pdf",
    "power",
    "printer",
    "schedule",
    "screen",
    "settings",
    "shortcuts",
    "sound",
    "speech",
    "spotlight",
    "system",
    "time_machine",
    "trackpad",
    "video",
    "vision",
    "volume",
    "windows",
    "notify",
    "open_with",
    "say",
    "screenshot",
    "AppNotFoundError",
    "CommandError",
    "KeychainError",
    "MacOSError",
    "NotSupportedError",
    "PermissionDeniedError",
    "ShortcutNotFoundError",
]
