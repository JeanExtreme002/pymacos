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

__version__ = "1.22.0"

import importlib
from typing import TYPE_CHECKING, Any, List

from .errors import (
    AppNotFoundError,
    CommandError,
    CommandTimeoutError,
    KeychainError,
    MacOSError,
    NotSupportedError,
    PermissionDeniedError,
    PromptTimeoutError,
    ShortcutNotFoundError,
)

if TYPE_CHECKING:  # what the lazy loading below provides, spelled out for type checkers
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
    from .launch import open, open_with
    from .notifications import notify
    from .screen import screenshot
    from .speech import say

# The submodules, and the shortcuts to their most used functions, are imported
# on first use (PEP 562): ``import macos`` stays fast, and a script that only
# sends a notification never loads the PDF or video code.
_SUBMODULES = frozenset({"appearance", "apps", "audio", "auth", "bluetooth", "browser", "camera", "clipboard", "defaults", "dialog", "dock", "document", "events", "finder", "hotkeys", "image", "keyboard", "keychain", "language", "maps", "menubar", "mouse", "music", "network", "notifications", "pdf", "power", "printer", "schedule", "screen", "settings", "shortcuts", "sound", "speech", "spotlight", "system", "time_machine", "trackpad", "video", "vision", "volume", "windows"})
_SHORTCUTS = {
    "open": "launch",
    "open_with": "launch",
    "notify": "notifications",
    "screenshot": "screen",
    "say": "speech",
}


def __getattr__(name: str) -> Any:
    if name in _SHORTCUTS:
        value = getattr(importlib.import_module("." + _SHORTCUTS[name], __name__), name)
        globals()[name] = value  # resolved once
        return value
    # Any submodule, private ones included, as when they were all imported up front.
    try:
        return importlib.import_module("." + name, __name__)
    except ModuleNotFoundError as error:
        if error.name != "{}.{}".format(__name__, name):
            raise  # a module that exists failed to import something else
    raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))


def __dir__() -> List[str]:
    return sorted(set(globals()) | _SUBMODULES | set(_SHORTCUTS))


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
    "CommandTimeoutError",
    "KeychainError",
    "MacOSError",
    "NotSupportedError",
    "PermissionDeniedError",
    "PromptTimeoutError",
    "ShortcutNotFoundError",
]
