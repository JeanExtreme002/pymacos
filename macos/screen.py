# -*- coding: utf-8 -*-

"""
Take screenshots, and find text on the screen.

::

    path = macos.screenshot()                       # temporary PNG
    macos.screenshot("desk.jpg", region=(0, 0, 800, 600))
    macos.screen.find_text("Submit")                # [TextMatch(text='Submit', x=812, y=640, ...)]

Capturing other apps' windows needs the *Screen Recording* permission for the
app running Python (your terminal or IDE). Without it macOS doesn't fail: it
silently returns an image with only the wallpaper and the menu bar. This
module checks the permission first and raises
:class:`~macos.errors.PermissionDeniedError` instead.
"""

import ctypes
import os
import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from datetime import time as dt_time
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from . import _cf, _objc, defaults
from ._system import framework, private_framework, run as _run
from .errors import CommandTimeoutError, MacOSError, NotSupportedError, PermissionDeniedError

__all__ = [
    "screenshot",
    "TextMatch",
    "find_text",
    "wait_for_text",
    "color_at",
    "screenshot_folder",
    "set_screenshot_folder",
    "screenshot_format",
    "set_screenshot_format",
    "screenshot_shadow",
    "set_screenshot_shadow",
    "screensaver_delay",
    "screenshot_thumbnail",
    "set_screenshot_thumbnail",
    "set_screensaver_delay",
    "has_permission",
    "request_permission",
    "displays",
    "Display",
    "wallpaper",
    "set_wallpaper",
    "start_screensaver",
    "brightness",
    "set_brightness",
    "night_shift",
    "set_night_shift",
    "true_tone",
    "set_true_tone",
    "lock",
    "is_locked",
    "is_asleep",
    "record",
    "screenshot_name",
    "set_screenshot_name",
    "screenshot_target",
    "set_screenshot_target",
    "night_shift_schedule",
    "set_night_shift_schedule",
    "night_shift_strength",
    "set_night_shift_strength",
    "DisplayMode",
    "display_modes",
    "display_mode",
    "set_display_mode",
    "set_main_display",
    "mirrored",
    "mirror",
    "stop_mirroring",
]

_CAPTURE_TIMEOUT = 60.0  # seconds: a screenshot takes a fraction of one, but screencapture has hung on some Macs
_FORMATS = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".heic": "heic", ".tiff": "tiff", ".gif": "gif", ".pdf": "pdf"}


@lru_cache(maxsize=None)
def _graphics() -> Optional[ctypes.CDLL]:
    """CoreGraphics, or ``None`` before macOS 10.15, which had no Screen Recording permission."""
    cg = framework("CoreGraphics")
    if not hasattr(cg, "CGPreflightScreenCaptureAccess"):
        return None
    cg.CGPreflightScreenCaptureAccess.argtypes = ()
    cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    cg.CGRequestScreenCaptureAccess.argtypes = ()
    cg.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
    return cg


def has_permission() -> bool:
    """Whether this process may capture the screen, without prompting the user."""
    cg = _graphics()
    return cg is None or bool(cg.CGPreflightScreenCaptureAccess())


def request_permission() -> bool:
    """
    Ask for the Screen Recording permission, showing the system prompt if needed.

    Returns whether it is granted now. After the user grants it in System
    Settings, the app running Python must be restarted for it to take effect.
    """
    cg = _graphics()
    return cg is None or bool(cg.CGRequestScreenCaptureAccess())


def screenshot(
    path: Union[str, "os.PathLike[str]", None] = None,
    *,
    region: Optional[Tuple[int, int, int, int]] = None,
    display: Optional[int] = None,
    cursor: bool = False,
    check_permission: bool = True,
) -> Path:
    """
    Capture the screen to an image file and return its path.

    - ``path``: where to save it. The format follows the extension (``.png``,
      ``.jpg``, ``.heic``, ``.tiff``, ``.gif``, ``.pdf``). When omitted, a
      temporary ``.png`` is created; deleting it is up to you.
    - ``region``: ``(x, y, width, height)`` in points, from the top-left corner
      of the main display.
    - ``display``: capture this display, by its position (``1`` is the main
      one), instead of the main display: not a :class:`~macos.screen.Display`
      or its id.
    - ``cursor``: include the mouse pointer.
    - ``check_permission``: raise if the Screen Recording permission is
      missing. Pass ``False`` to accept a capture without other apps' windows.

    Raises :class:`~macos.errors.MacOSError` when ``screencapture`` saves
    nothing, and :class:`~macos.errors.CommandTimeoutError` when it doesn't
    finish within a minute.
    """
    options = ["-C"] if cursor else []
    if region is not None:
        x, y, width, height = region
        options.append("-R{},{},{},{}".format(x, y, width, height))
    if display is not None:
        options.append("-D{}".format(display))
    return _capture(path, options, check_permission)


def _capture(path: Union[str, "os.PathLike[str]", None], options: List[str], check_permission: bool = True) -> Path:
    """Run ``screencapture`` with ``options`` into ``path`` (or a temporary PNG), and return the file."""
    if check_permission and not has_permission():
        raise PermissionDeniedError(
            "Screen Recording permission is missing: allow the app running Python (your terminal or IDE) in "
            "System Settings › Privacy & Security › Screen & System Audio Recording, then restart it"
        )

    if path is None:
        descriptor, name = tempfile.mkstemp(prefix="screenshot-", suffix=".png")
        os.close(descriptor)
        target = Path(name)
    else:
        target = Path(path).expanduser().resolve()
        if target.suffix.lower() not in _FORMATS:
            raise ValueError(
                "unsupported image format {!r}; use one of {}".format(target.suffix, ", ".join(sorted(_FORMATS)))
            )
    extension = target.suffix.lower()

    args = ["screencapture", "-x", "-t", _FORMATS[extension], *options, str(target)]  # -x: no shutter sound

    try:
        _run(args, timeout=_CAPTURE_TIMEOUT)
        # screencapture can exit 0 without writing anything (a display that went away, a capture
        # cancelled by the system): an empty or missing file isn't a screenshot.
        try:
            written = target.stat().st_size
        except OSError:
            written = 0
        if not written:
            raise MacOSError("screencapture didn't save a screenshot to {}".format(target))
    except BaseException:
        if path is None:
            target.unlink(missing_ok=True)
        raise
    return target


@dataclass(frozen=True)
class TextMatch:
    """Where some text is on the screen, in points from the main display's top-left corner, like :func:`macos.mouse.click`."""

    text: str
    """The whole line of text the match is in."""
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> Tuple[int, int]:
        """The middle of the match: where to click it."""
        return (self.x + self.width // 2, self.y + self.height // 2)


def _area(region: Optional[Tuple[int, int, int, int]], display: Optional[int]) -> Tuple[float, float, float, float]:
    """The part of the screen a capture covers, in points."""
    if region is not None:
        return tuple(float(value) for value in region)  # type: ignore[return-value]
    found = displays()
    index = (1 if display is None else display) - 1
    if not 0 <= index < len(found):
        raise ValueError("there's no display {}: there are {}".format(display, len(found)))
    screen = found[index]
    return float(screen.x), float(screen.y), float(screen.width), float(screen.height)


def find_text(
    text: str,
    *,
    region: Optional[Tuple[int, int, int, int]] = None,
    display: Optional[int] = None,
    languages: Optional[Sequence[str]] = None,
) -> List[TextMatch]:
    """
    Find ``text`` on the screen, ignoring case, and return where it is, top to bottom.

    Reads the screen with Vision's text recognition, so it finds text in any
    app, even in images. Each :class:`TextMatch` surrounds the matching
    characters, and its :attr:`~TextMatch.center` is where to click::

        match = macos.screen.find_text("Submit")[0]
        macos.mouse.click(*match.center)

    ``region`` (``(x, y, width, height)`` in points) or ``display`` (``1`` is
    the main one) limit where to look; by default, the main display.
    ``languages`` works as in :func:`macos.vision.lines`. Needs the Screen
    Recording permission. See also :func:`macos.mouse.click_text`.
    """
    from . import vision

    if not text.strip():
        raise ValueError("text must not be empty")
    left, top, width, height = _area(region, display)
    shot = screenshot(region=region, display=None if region is not None else display)
    try:
        image = shot.read_bytes()
    finally:
        shot.unlink(missing_ok=True)
    return [
        TextMatch(
            text=line,
            x=round(left + box[0] * width),
            y=round(top + box[1] * height),
            width=max(1, round(box[2] * width)),
            height=max(1, round(box[3] * height)),
        )
        for line, box in vision._occurrences(image, text, languages)
    ]


def wait_for_text(
    text: str,
    *,
    timeout: Optional[float] = None,
    interval: float = 0.5,
    region: Optional[Tuple[int, int, int, int]] = None,
    display: Optional[int] = None,
    languages: Optional[Sequence[str]] = None,
) -> Optional[TextMatch]:
    """
    Wait until ``text`` shows up on the screen, and return where; ``None`` if ``timeout`` seconds pass first.

    Looks every ``interval`` seconds, as :func:`find_text` does::

        macos.screen.wait_for_text("Export complete", timeout=120)
    """
    if interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        found = find_text(text, region=region, display=display, languages=languages)
        if found:
            return found[0]
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return None
        time.sleep(interval if remaining is None else min(interval, remaining))  # then look one last time


def color_at(x: float, y: float) -> str:
    """
    The color of the screen at ``(x, y)`` (points from the main display's top-left corner), as ``'#rrggbb'``.

    Handy to check a status light or wait for a button to turn green.
    Needs the Screen Recording permission.
    """
    from . import image

    shot = screenshot(region=(int(x), int(y), 1, 1))
    try:
        return image.dominant_colors(shot, count=1)[0]
    finally:
        shot.unlink(missing_ok=True)


_CAPTURE_SETTINGS = "com.apple.screencapture"
_SETTING_FORMATS = ("png", "jpg", "heic", "tiff", "gif", "pdf", "bmp")


def _apply_capture_settings() -> None:
    # The screenshot shortcuts' UI reads the settings when it starts.
    try:
        _run(["killall", "SystemUIServer"])
    except MacOSError:
        pass  # not running: nothing to apply


def screenshot_folder() -> Path:
    """Where ⌘⇧3, ⌘⇧4 and ⌘⇧5 save screenshots: the Desktop unless changed."""
    location = defaults.read(_CAPTURE_SETTINGS, "location")
    return Path(os.path.expanduser(location)) if location else Path.home() / "Desktop"


def set_screenshot_folder(folder: Union[str, "os.PathLike[str]"]) -> None:
    """Save the screenshots taken with the keyboard shortcuts in ``folder``, which must exist."""
    target = Path(folder).expanduser().resolve()
    if not target.is_dir():
        raise NotADirectoryError(str(target))
    defaults.write(_CAPTURE_SETTINGS, "location", str(target))
    _apply_capture_settings()


def screenshot_format() -> str:
    """The format the screenshot shortcuts save in: ``'png'`` unless changed."""
    found = str(defaults.read(_CAPTURE_SETTINGS, "type", default="png")).lower()
    return "jpg" if found == "jpeg" else found


def set_screenshot_format(format: str) -> None:
    """
    Save the screenshots taken with the shortcuts in ``format``.

    One of ``'png'``, ``'jpg'``, ``'heic'``, ``'tiff'``, ``'gif'``, ``'pdf'`` or ``'bmp'``.
    """
    wanted = format.lower().lstrip(".")
    wanted = "jpg" if wanted == "jpeg" else wanted
    if wanted not in _SETTING_FORMATS:
        raise ValueError("format must be one of {}, not {!r}".format(", ".join(_SETTING_FORMATS), format))
    defaults.write(_CAPTURE_SETTINGS, "type", wanted)
    _apply_capture_settings()


def screenshot_thumbnail() -> bool:
    """Whether a screenshot first shows as a thumbnail in the corner, to edit or drag, before it's saved."""
    return bool(defaults.read(_CAPTURE_SETTINGS, "show-thumbnail", default=True))


def set_screenshot_thumbnail(on: bool = True) -> None:
    """Show the floating thumbnail after a screenshot, or save it at once (``False``)."""
    defaults.write(_CAPTURE_SETTINGS, "show-thumbnail", bool(on))
    _apply_capture_settings()


def screenshot_name() -> Optional[str]:
    """The name screenshots' files start with; ``None`` for macOS's own ("Screenshot", in the system's language)."""
    return defaults.read(_CAPTURE_SETTINGS, "name") or None


def set_screenshot_name(name: Optional[str]) -> None:
    """Start screenshots' file names with ``name`` (``"Capture"``...), or macOS's own (``None``). The date follows it."""
    if name is None:
        defaults.delete(_CAPTURE_SETTINGS, "name")
    else:
        if not name.strip() or "/" in name or ":" in name:
            raise ValueError("name must be a file name, without / or :, not {!r}".format(name))
        defaults.write(_CAPTURE_SETTINGS, "name", name)
    _apply_capture_settings()


_SCREENSHOT_TARGETS = ("file", "clipboard", "preview", "mail", "messages")


def screenshot_target() -> str:
    """Where the shortcuts send screenshots: ``'file'``, ``'clipboard'``, ``'preview'``, ``'mail'`` or ``'messages'``."""
    found = defaults.read(_CAPTURE_SETTINGS, "target", default="file")
    return found if found in _SCREENSHOT_TARGETS else "file"


def set_screenshot_target(target: str) -> None:
    """
    Send screenshots to a ``"file"`` (in :func:`screenshot_folder`), the ``"clipboard"``, or open them in
    ``"preview"``, ``"mail"`` or ``"messages"``, like the Options menu of ⌘⇧5.
    """
    if target not in _SCREENSHOT_TARGETS:
        raise ValueError("target must be one of {}, not {!r}".format(", ".join(_SCREENSHOT_TARGETS), target))
    defaults.write(_CAPTURE_SETTINGS, "target", target)
    _apply_capture_settings()


def screenshot_shadow() -> bool:
    """Whether screenshots of a window (⌘⇧4, then Space) keep its shadow."""
    return not defaults.read(_CAPTURE_SETTINGS, "disable-shadow", default=False)


def set_screenshot_shadow(on: bool = True) -> None:
    """Keep windows' shadows in screenshots of a window, or leave them out for tight images."""
    defaults.write(_CAPTURE_SETTINGS, "disable-shadow", not on)
    _apply_capture_settings()


@lru_cache(maxsize=None)
def _display_api() -> ctypes.CDLL:
    cg = framework("CoreGraphics")
    cg.CGGetActiveDisplayList.argtypes = (ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32))
    cg.CGGetActiveDisplayList.restype = ctypes.c_int32
    cg.CGMainDisplayID.argtypes = ()
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    cg.CGDisplayBounds.argtypes = (ctypes.c_uint32,)
    cg.CGDisplayBounds.restype = _objc.CGRect
    cg.CGDisplayIsBuiltin.argtypes = (ctypes.c_uint32,)
    cg.CGDisplayIsBuiltin.restype = ctypes.c_bool
    cg.CGDisplayCopyDisplayMode.argtypes = (ctypes.c_uint32,)
    cg.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
    cg.CGDisplayModeGetPixelWidth.argtypes = (ctypes.c_void_p,)
    cg.CGDisplayModeGetPixelWidth.restype = ctypes.c_size_t
    cg.CGDisplayModeGetPixelHeight.argtypes = (ctypes.c_void_p,)
    cg.CGDisplayModeGetPixelHeight.restype = ctypes.c_size_t
    cg.CGDisplayModeGetRefreshRate.argtypes = (ctypes.c_void_p,)
    cg.CGDisplayModeGetRefreshRate.restype = ctypes.c_double
    cg.CGDisplayModeRelease.argtypes = (ctypes.c_void_p,)
    cg.CGDisplayModeRelease.restype = None
    return cg


@dataclass(frozen=True)
class Display:
    """A connected display. Sizes and positions are in points, like :func:`macos.screenshot`'s ``region``."""

    id: int
    """The CoreGraphics display ID."""
    name: Optional[str]
    """E.g. ``'Built-in Retina Display'`` (``None`` if macOS doesn't report one)."""
    width: int
    height: int
    x: int
    """Position relative to the main display's top-left corner."""
    y: int
    pixel_width: int
    """Physical resolution, e.g. twice the width on a Retina display."""
    pixel_height: int
    scale: float
    """Pixels per point: 2.0 on Retina displays, 1.0 otherwise."""
    refresh_rate: Optional[float]
    """In Hz; ``None`` when macOS doesn't report it."""
    is_main: bool
    """The display with the menu bar."""
    is_builtin: bool
    """A laptop's own screen."""


def _screens() -> List[Tuple[int, int]]:
    """``(display id, NSScreen)`` pairs, the main screen first. Call inside an autorelease pool."""
    framework("AppKit")
    pairs = []
    for screen in _objc.nsarray(_objc.send(_objc.cls("NSScreen"), "screens")):
        description = _objc.send(screen, "deviceDescription")
        number = _objc.send(description, "objectForKey:", _objc.nsstring("NSScreenNumber"), argtypes=(_objc.id,))
        if number:
            pairs.append((_objc.send(number, "unsignedIntValue", restype=ctypes.c_uint32), screen))
    return pairs


def _screen_names() -> Dict[int, str]:
    """Display names by CoreGraphics ID, from NSScreen (macOS 10.15+)."""
    names = {}
    with _objc.autorelease_pool():
        for display_id, screen in _screens():
            has_name = _objc.send(
                screen, "respondsToSelector:", _objc.sel("localizedName"), argtypes=(_objc.SEL,), restype=_objc.BOOL
            )
            name = _objc.pystring(_objc.send(screen, "localizedName")) if has_name else None
            if name:
                names[display_id] = name
    return names


def displays() -> List[Display]:
    """Return the connected displays, the main one (with the menu bar) first."""
    cg = _display_api()
    ids = (ctypes.c_uint32 * 32)()
    count = ctypes.c_uint32()
    cg.CGGetActiveDisplayList(len(ids), ids, ctypes.byref(count))
    main = cg.CGMainDisplayID()
    names = _screen_names()

    found = []
    for display_id in ids[: count.value]:
        bounds = cg.CGDisplayBounds(display_id)
        mode = cg.CGDisplayCopyDisplayMode(display_id)
        try:
            pixel_width = cg.CGDisplayModeGetPixelWidth(mode) if mode else round(bounds.size.width)
            pixel_height = cg.CGDisplayModeGetPixelHeight(mode) if mode else round(bounds.size.height)
            refresh = cg.CGDisplayModeGetRefreshRate(mode) if mode else 0.0
        finally:
            if mode:
                cg.CGDisplayModeRelease(mode)
        width = round(bounds.size.width)
        found.append(
            Display(
                id=display_id,
                name=names.get(display_id),
                width=width,
                height=round(bounds.size.height),
                x=round(bounds.origin.x),
                y=round(bounds.origin.y),
                pixel_width=pixel_width,
                pixel_height=pixel_height,
                scale=pixel_width / width if width else 1.0,
                refresh_rate=refresh or None,  # 0 for displays that don't report it
                is_main=display_id == main,
                is_builtin=cg.CGDisplayIsBuiltin(display_id),
            )
        )
    return sorted(found, key=lambda display: not display.is_main)


@lru_cache(maxsize=None)
def _workspace() -> int:
    framework("AppKit")
    return _objc.send(_objc.cls("NSWorkspace"), "sharedWorkspace")


def _pick(pairs: List[Tuple[int, int]], display_id: Union[int, Display, None]) -> List[Tuple[int, int]]:
    if display_id is None:
        return pairs
    wanted = display_id.id if isinstance(display_id, Display) else display_id
    chosen = [pair for pair in pairs if pair[0] == wanted]
    if not chosen:
        raise ValueError("no connected display has the id {} (see macos.screen.displays())".format(wanted))
    return chosen


def wallpaper(display_id: Union[int, Display, None] = None) -> Optional[Path]:
    """
    Return the desktop picture of a display (the main one by default).

    ``display_id`` is a :class:`Display` from :func:`displays`, or its
    :attr:`~Display.id`. (It's not the position that :func:`macos.screenshot`'s
    ``display`` takes.) Returns ``None``
    when the desktop shows something other than a picture file, such as a
    solid color or a dynamic wallpaper that isn't a file.
    """
    with _objc.autorelease_pool():
        pairs = _pick(_screens(), display_id)
        if not pairs:
            return None
        url = _objc.send(_workspace(), "desktopImageURLForScreen:", pairs[0][1], argtypes=(_objc.id,))
        path = _objc.pystring(_objc.send(url, "path")) if url else None
        return Path(path) if path else None


def set_wallpaper(path: Union[str, "os.PathLike[str]"], *, display_id: Union[int, Display, None] = None) -> None:
    """
    Set the desktop picture, on every display or only on ``display_id``.

    ``path`` is an image file (JPEG, PNG, HEIC...). macOS keeps referring to
    that file, so don't delete it afterwards. ``display_id`` works as in
    :func:`wallpaper`. If macOS refuses the picture for one display, the ones
    before it keep the new picture and :class:`~macos.errors.MacOSError` is
    raised.
    """
    image = Path(path).expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(str(image))
    with _objc.autorelease_pool():
        url = _objc.file_url(image)
        options = _objc.send(_objc.cls("NSDictionary"), "dictionary")
        for _, screen in _pick(_screens(), display_id):
            error = ctypes.c_void_p()
            ok = _objc.send(
                _workspace(),
                "setDesktopImageURL:forScreen:options:error:",
                url,
                screen,
                options,
                ctypes.byref(error),
                argtypes=(_objc.id, _objc.id, _objc.id, ctypes.c_void_p),
                restype=_objc.BOOL,
            )
            if not ok:
                message = _objc.error_message(error) or "not an image macOS can show"
                raise MacOSError("could not set the wallpaper: {}".format(message))


def start_screensaver() -> None:
    """
    Start the screen saver now, like a hot corner does.

    If *Require password after screen saver begins* is on (System Settings ›
    Lock Screen), this also locks the Mac once the password delay passes.
    """
    _run(["open", "-a", "ScreenSaverEngine"])


@lru_cache(maxsize=None)
def _display_services() -> ctypes.CDLL:
    # DisplayServices is private: the public API (IOKit's IODisplay) doesn't
    # reach the built-in displays of Apple silicon Macs.
    services = private_framework("DisplayServices")
    for name in ("DisplayServicesCanChangeBrightness", "DisplayServicesGetBrightness", "DisplayServicesSetBrightness"):
        if not hasattr(services, name):
            raise NotSupportedError("this version of macOS doesn't expose the display brightness")
    services.DisplayServicesCanChangeBrightness.argtypes = (ctypes.c_uint32,)
    services.DisplayServicesCanChangeBrightness.restype = ctypes.c_bool
    services.DisplayServicesGetBrightness.argtypes = (ctypes.c_uint32, ctypes.POINTER(ctypes.c_float))
    services.DisplayServicesGetBrightness.restype = ctypes.c_int
    services.DisplayServicesSetBrightness.argtypes = (ctypes.c_uint32, ctypes.c_float)
    services.DisplayServicesSetBrightness.restype = ctypes.c_int
    return services


def _dimmable(display_id: Union[int, Display, None]) -> int:
    """The display whose brightness to use: ``display_id``, or the first one macOS can dim."""
    services = _display_services()
    if display_id is not None:
        wanted = display_id.id if isinstance(display_id, Display) else display_id
        if not services.DisplayServicesCanChangeBrightness(wanted):
            raise NotSupportedError("macOS can't change the brightness of display {}".format(wanted))
        return wanted
    for display in displays():
        if services.DisplayServicesCanChangeBrightness(display.id):
            return display.id
    raise NotSupportedError(
        "no display here has a brightness macOS controls (external monitors usually set it with their own buttons)"
    )


def brightness(display_id: Union[int, Display, None] = None) -> float:
    """
    The display brightness, from 0.0 to 1.0, as the slider in Control Center.

    By default, of the built-in display (or an Apple display). ``display_id``
    works as in :func:`wallpaper`. Most external monitors set their brightness
    with their own buttons, so they raise :class:`~macos.errors.NotSupportedError`.
    """
    target = _dimmable(display_id)
    value = ctypes.c_float()
    status = _display_services().DisplayServicesGetBrightness(target, ctypes.byref(value))
    if status != 0:
        raise MacOSError("could not read the brightness of display {} (error {})".format(target, status))
    return round(float(value.value), 3)


def set_brightness(value: float, *, display_id: Union[int, Display, None] = None) -> None:
    """
    Set the display brightness, from 0.0 (darkest, not off) to 1.0.

    ``display_id`` works as in :func:`brightness`. With *Automatically adjust
    brightness* on (System Settings › Displays), macOS keeps adapting it to
    the room's light afterwards.
    """
    if not 0.0 <= value <= 1.0:
        raise ValueError("brightness must be from 0.0 to 1.0, not {}".format(value))
    target = _dimmable(display_id)
    status = _display_services().DisplayServicesSetBrightness(target, float(value))
    if status != 0:
        raise MacOSError("could not change the brightness of display {} (error {})".format(target, status))


class _NightShiftTime(ctypes.Structure):
    _fields_ = [("hour", ctypes.c_int), ("minute", ctypes.c_int)]


class _NightShiftStatus(ctypes.Structure):
    # CoreBrightness's private StatusData, as the Night Shift settings read it.
    _fields_ = [
        ("active", ctypes.c_bool),
        ("enabled", ctypes.c_bool),
        ("sun_schedule_permitted", ctypes.c_bool),
        ("mode", ctypes.c_int),
        ("start", _NightShiftTime),
        ("end", _NightShiftTime),
        ("disable_flags", ctypes.c_ulonglong),
        ("available", ctypes.c_bool),
    ]


def _night_shift_client() -> int:
    """An autoreleased ``CBBlueLightClient``. Call inside an autorelease pool."""
    private_framework("CoreBrightness")
    framework("Foundation")
    try:
        _objc.cls("CBBlueLightClient")
    except LookupError:
        raise NotSupportedError("this version of macOS doesn't expose Night Shift") from None
    return _objc.new("CBBlueLightClient")


def _night_shift_status() -> _NightShiftStatus:
    status = _NightShiftStatus()
    with _objc.autorelease_pool():
        ok = _objc.send(
            _night_shift_client(), "getBlueLightStatus:", ctypes.byref(status), argtypes=(ctypes.c_void_p,), restype=_objc.BOOL
        )
    if not ok:
        raise MacOSError("could not read the Night Shift status")
    if not status.available:
        raise NotSupportedError("Night Shift isn't available on this Mac's displays")
    return status


def night_shift() -> bool:
    """
    Whether Night Shift is on right now, making the display warmer (yellower).

    It's on when turned on by hand or during its schedule (System Settings ›
    Displays › Night Shift).
    """
    return bool(_night_shift_status().enabled)


def set_night_shift(on: bool) -> None:
    """
    Turn Night Shift on or off now, like the switch in Control Center.

    Its schedule, if any, still applies: it turns on or off again at the
    scheduled times.
    """
    _night_shift_status()  # raises when unavailable
    with _objc.autorelease_pool():
        ok = _objc.send(_night_shift_client(), "setEnabled:", bool(on), argtypes=(_objc.BOOL,), restype=_objc.BOOL)
    if not ok:
        raise MacOSError("macOS refused to turn Night Shift {}".format("on" if on else "off"))


def _true_tone_client() -> int:
    """An autoreleased ``CBTrueToneClient`` for a Mac with True Tone. Call inside an autorelease pool."""
    private_framework("CoreBrightness")
    framework("Foundation")
    try:
        _objc.cls("CBTrueToneClient")
    except LookupError:
        raise NotSupportedError("this version of macOS doesn't expose True Tone") from None
    client = _objc.new("CBTrueToneClient")
    for name in ("supported", "available"):
        if not _objc.send(client, name, restype=_objc.BOOL):
            raise NotSupportedError("True Tone isn't available on this Mac's displays")
    return client


def true_tone() -> bool:
    """
    Whether True Tone is on, adapting the display's colors to the room's light.

    Raises :class:`~macos.errors.NotSupportedError` on Macs whose displays
    don't have it.
    """
    with _objc.autorelease_pool():
        return bool(_objc.send(_true_tone_client(), "enabled", restype=_objc.BOOL))


def set_true_tone(on: bool) -> None:
    """Turn True Tone on or off, like the switch in System Settings › Displays."""
    with _objc.autorelease_pool():
        ok = _objc.send(_true_tone_client(), "setEnabled:", bool(on), argtypes=(_objc.BOOL,), restype=_objc.BOOL)
    if not ok:
        raise MacOSError("macOS refused to turn True Tone {}".format("on" if on else "off"))


def lock() -> None:
    """
    Lock the screen now, like Ctrl-Cmd-Q or *Lock Screen* in the Apple menu.

    Apps keep running; the user needs their password (or Touch ID) to come
    back. Uses a private macOS framework, since there's no public one.
    """
    login = private_framework("login")
    if not hasattr(login, "SACLockScreenImmediate"):
        raise NotSupportedError("this version of macOS doesn't expose locking the screen")
    login.SACLockScreenImmediate.argtypes = ()
    login.SACLockScreenImmediate.restype = ctypes.c_int
    status = login.SACLockScreenImmediate()
    if status != 0:
        raise MacOSError("could not lock the screen (error {})".format(status))


def is_locked() -> bool:
    """
    Whether the screen is locked (by :func:`lock`, the user, or the screen saver asking for the password).

    A script can wait for the user to come back::

        while macos.screen.is_locked():
            time.sleep(5)
    """
    graphics = framework("CoreGraphics")
    graphics.CGSessionCopyCurrentDictionary.argtypes = ()
    graphics.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
    with _cf.owned(graphics.CGSessionCopyCurrentDictionary()) as session:
        if not session:
            raise MacOSError("could not read the login session")
        # Present, and true, only while the screen is locked.
        return _cf.to_bool(_cf.lookup(session, "CGSSessionScreenIsLocked"))


def is_asleep(display_id: Union[int, Display, None] = None) -> bool:
    """
    Whether a display is asleep (turned off to save energy), the main one by default.

    ``display_id`` works as in :func:`wallpaper`.
    """
    graphics = _display_api()
    graphics.CGDisplayIsAsleep.argtypes = (ctypes.c_uint32,)
    graphics.CGDisplayIsAsleep.restype = ctypes.c_bool
    if display_id is None:
        target = graphics.CGMainDisplayID()
    else:
        target = display_id.id if isinstance(display_id, Display) else display_id
    return bool(graphics.CGDisplayIsAsleep(target))


def record(
    path: Union[str, "os.PathLike[str]"],
    seconds: float,
    *,
    region: Optional[Tuple[int, int, int, int]] = None,
    display: Optional[int] = None,
    audio: bool = False,
    clicks: bool = False,
) -> Path:
    """
    Record the screen for ``seconds`` into a ``.mov`` video, and return its path.

    This returns when the recording ends. ``region`` and ``display`` work as
    in :func:`macos.screenshot`. ``audio=True`` also records the default
    microphone (macOS asks for the Microphone permission the first time), and
    ``clicks=True`` shows the mouse clicks. Needs the Screen Recording
    permission, like screenshots::

        macos.screen.record("demo.mov", 10, region=(0, 0, 1280, 800))
        macos.video.convert("demo.mov", "demo.mp4", quality="medium")
    """
    if seconds <= 0:
        raise ValueError("seconds must be positive, not {}".format(seconds))
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".mov":
        raise ValueError("screen recordings are .mov videos, not {!r}".format(target.suffix))
    if not has_permission():
        raise PermissionDeniedError(
            "Screen Recording permission is missing: allow the app running Python (your terminal or IDE) in "
            "System Settings › Privacy & Security › Screen & System Audio Recording, then restart it"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    # -V stops after the given seconds; screencapture only takes whole seconds.
    args = ["screencapture", "-x", "-v", "-V{}".format(max(1, round(seconds)))]
    if region is not None:
        x, y, width, height = region
        args.append("-R{},{},{},{}".format(x, y, width, height))
    if display is not None:
        args.append("-D{}".format(display))
    if audio:
        args.append("-g")
    if clicks:
        args.append("-k")
    args.append(str(target))
    try:
        _run(args, timeout=max(1, round(seconds)) + 60)  # screencapture has hung on some Macs, VMs among them
    except CommandTimeoutError:
        raise MacOSError("screencapture didn't finish recording; the recording wasn't saved") from None
    if not target.exists():
        raise MacOSError("the screen recording wasn't saved")
    return target


def screensaver_delay() -> Optional[float]:
    """Minutes of inactivity before the screen saver starts; ``None`` when it never does."""
    seconds = defaults.read("com.apple.screensaver", "idleTime", default=1200, current_host=True)
    return round(float(seconds) / 60, 2) if seconds else None


def set_screensaver_delay(minutes: Optional[float]) -> None:
    """Start the screen saver after ``minutes`` of inactivity, or never (``None``), like System Settings › Lock Screen."""
    if minutes is not None and minutes <= 0:
        raise ValueError("minutes must be positive, or None for never, not {}".format(minutes))
    # At least a second: 0 is how macOS says "never".
    defaults.write("com.apple.screensaver", "idleTime", max(1, int(round(minutes * 60))) if minutes else 0, current_host=True)


# --- Night Shift's schedule and strength -----------------------------------

_NIGHT_SHIFT_MODES = {0: None, 1: "sunset", 2: "custom"}


class _NightShiftSchedule(ctypes.Structure):
    _fields_ = [("start", _NightShiftTime), ("end", _NightShiftTime)]


def _clock_time(value: Union[str, dt_time]) -> dt_time:
    if isinstance(value, dt_time):
        return value
    try:
        hour, minute = (int(part) for part in str(value).split(":"))
        return dt_time(hour, minute)
    except ValueError:
        raise ValueError("times must be datetime.time or 'HH:MM', not {!r}".format(value)) from None


def night_shift_schedule() -> Union[None, str, Tuple[dt_time, dt_time]]:
    """
    When Night Shift turns on by itself: ``None`` (never), ``'sunset'`` (sunset to sunrise), or ``(start, end)`` times.

    ::

        macos.screen.night_shift_schedule()   # (datetime.time(22, 0), datetime.time(7, 0))
    """
    status = _night_shift_status()
    mode = _NIGHT_SHIFT_MODES.get(status.mode)
    if mode == "custom":
        return dt_time(status.start.hour, status.start.minute), dt_time(status.end.hour, status.end.minute)
    return mode


def set_night_shift_schedule(schedule: Union[None, str, Tuple[Union[str, dt_time], Union[str, dt_time]]]) -> None:
    """
    Turn Night Shift on by itself from ``"sunset"`` to sunrise, between two times, or never (``None``).

    ::

        macos.screen.set_night_shift_schedule(("22:00", "07:00"))
        macos.screen.set_night_shift_schedule("sunset")      # needs Location Services
        macos.screen.set_night_shift_schedule(None)

    Like the Schedule menu in System Settings › Displays › Night Shift.
    """
    status = _night_shift_status()
    with _objc.autorelease_pool():
        client = _night_shift_client()
        if schedule is None or schedule == "sunset":
            if schedule == "sunset" and not status.sun_schedule_permitted:
                raise PermissionDeniedError(
                    "Night Shift needs Location Services to follow the sun: turn them on in System Settings › "
                    "Privacy & Security › Location Services"
                )
            mode = 1 if schedule == "sunset" else 0
        else:
            if isinstance(schedule, str) or len(schedule) != 2:
                raise ValueError("schedule must be None, 'sunset' or (start, end), not {!r}".format(schedule))
            start, end = (_clock_time(value) for value in schedule)
            times = _NightShiftSchedule(_NightShiftTime(start.hour, start.minute), _NightShiftTime(end.hour, end.minute))
            if not _objc.send(client, "setSchedule:", ctypes.byref(times), argtypes=(ctypes.c_void_p,), restype=_objc.BOOL):
                raise MacOSError("macOS refused Night Shift's schedule")
            mode = 2
        if not _objc.send(client, "setMode:", mode, argtypes=(ctypes.c_int,), restype=_objc.BOOL):
            raise MacOSError("macOS refused to change Night Shift's schedule")


def night_shift_strength() -> float:
    """How warm Night Shift makes the display, from 0.0 (least) to 1.0 (most)."""
    _night_shift_status()  # raises when unavailable
    strength = ctypes.c_float()
    with _objc.autorelease_pool():
        ok = _objc.send(
            _night_shift_client(), "getStrength:", ctypes.byref(strength), argtypes=(ctypes.c_void_p,), restype=_objc.BOOL
        )
    if not ok:
        raise MacOSError("could not read Night Shift's strength")
    return round(float(strength.value), 3)


def set_night_shift_strength(strength: float) -> None:
    """Set how warm Night Shift makes the display, from 0.0 to 1.0, like its Color Temperature slider."""
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength must be from 0.0 to 1.0, not {}".format(strength))
    _night_shift_status()
    with _objc.autorelease_pool():
        ok = _objc.send(
            _night_shift_client(),
            "setStrength:commit:",
            float(strength),
            True,
            argtypes=(ctypes.c_float, _objc.BOOL),
            restype=_objc.BOOL,
        )
    if not ok:
        raise MacOSError("macOS refused to change Night Shift's strength")


# --- Display modes, arrangement and mirroring ----------------------------------


@dataclass(frozen=True)
class DisplayMode:
    """A resolution a display can use. Sizes are in points, as the desktop lays out windows."""

    width: int
    height: int
    pixel_width: int
    pixel_height: int
    refresh_rate: float
    """In Hz; 0.0 when the display doesn't say (most built-in ones, besides ProMotion)."""

    @property
    def hidpi(self) -> bool:
        """Whether it draws with more pixels than points, for sharp text: Retina."""
        return self.pixel_width > self.width


_CONFIGURE_PERMANENTLY = 2  # kCGConfigurePermanently: kept after a restart, like System Settings


@lru_cache(maxsize=None)
def _arrangement_api() -> ctypes.CDLL:
    cg = _display_api()
    pointer = ctypes.c_void_p
    cg.CGDisplayCopyAllDisplayModes.argtypes = (ctypes.c_uint32, pointer)
    cg.CGDisplayCopyAllDisplayModes.restype = pointer
    for name in ("CGDisplayModeGetWidth", "CGDisplayModeGetHeight"):
        getattr(cg, name).argtypes = (pointer,)
        getattr(cg, name).restype = ctypes.c_size_t
    cg.CGDisplayModeIsUsableForDesktopGUI.argtypes = (pointer,)
    cg.CGDisplayModeIsUsableForDesktopGUI.restype = ctypes.c_bool
    cg.CGBeginDisplayConfiguration.argtypes = (ctypes.POINTER(pointer),)
    cg.CGBeginDisplayConfiguration.restype = ctypes.c_int32
    cg.CGConfigureDisplayWithDisplayMode.argtypes = (pointer, ctypes.c_uint32, pointer, pointer)
    cg.CGConfigureDisplayWithDisplayMode.restype = ctypes.c_int32
    cg.CGConfigureDisplayOrigin.argtypes = (pointer, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32)
    cg.CGConfigureDisplayOrigin.restype = ctypes.c_int32
    cg.CGConfigureDisplayMirrorOfDisplay.argtypes = (pointer, ctypes.c_uint32, ctypes.c_uint32)
    cg.CGConfigureDisplayMirrorOfDisplay.restype = ctypes.c_int32
    cg.CGCompleteDisplayConfiguration.argtypes = (pointer, ctypes.c_uint32)
    cg.CGCompleteDisplayConfiguration.restype = ctypes.c_int32
    cg.CGCancelDisplayConfiguration.argtypes = (pointer,)
    cg.CGCancelDisplayConfiguration.restype = ctypes.c_int32
    cg.CGGetOnlineDisplayList.argtypes = cg.CGGetActiveDisplayList.argtypes
    cg.CGGetOnlineDisplayList.restype = ctypes.c_int32
    cg.CGDisplayMirrorsDisplay.argtypes = (ctypes.c_uint32,)
    cg.CGDisplayMirrorsDisplay.restype = ctypes.c_uint32
    return cg


def _display_id(display: Union[None, int, Display]) -> int:
    if display is None:
        return int(_display_api().CGMainDisplayID())
    return int(display.id if isinstance(display, Display) else display)


def _mode(cg: ctypes.CDLL, ref: int) -> DisplayMode:
    return DisplayMode(
        width=int(cg.CGDisplayModeGetWidth(ref)),
        height=int(cg.CGDisplayModeGetHeight(ref)),
        pixel_width=int(cg.CGDisplayModeGetPixelWidth(ref)),
        pixel_height=int(cg.CGDisplayModeGetPixelHeight(ref)),
        refresh_rate=round(float(cg.CGDisplayModeGetRefreshRate(ref)), 2),
    )


def _all_modes(cg: ctypes.CDLL, display_id: int) -> int:
    """An owned CFArray of every mode, the Retina ("looks like") ones included."""
    key = _cf.constant(cg, "kCGDisplayShowDuplicateLowResolutionModes")
    with _cf.owned(_cf.dictionary({key: _cf.constant(_cf.lib(), "kCFBooleanTrue")})) as options:
        return cg.CGDisplayCopyAllDisplayModes(display_id, options)


def display_modes(display: Union[None, int, Display] = None) -> List[DisplayMode]:
    """
    The resolutions ``display`` (the main one by default) can use, largest first.

    ``display`` is a :class:`Display` from :func:`displays`, or its
    :attr:`~Display.id`: not the position :func:`macos.screenshot`'s
    ``display`` counts from 1.

    ::

        [f"{m.width}×{m.height} @ {m.refresh_rate:g} Hz" for m in macos.screen.display_modes()]

    Includes the scaled Retina ones System Settings › Displays shows as
    "looks like"; each is a :class:`DisplayMode`.
    """
    cg = _arrangement_api()
    found = set()
    with _cf.owned(_all_modes(cg, _display_id(display))) as modes:
        for ref in _cf.items(modes):
            if cg.CGDisplayModeIsUsableForDesktopGUI(ref):
                found.add(_mode(cg, ref))
    return sorted(found, key=lambda mode: (mode.width, mode.height, mode.hidpi, mode.refresh_rate), reverse=True)


def display_mode(display: Union[None, int, Display] = None) -> DisplayMode:
    """The resolution ``display`` (the main one by default) uses now; ``display`` works as in :func:`display_modes`."""
    cg = _arrangement_api()
    ref = cg.CGDisplayCopyDisplayMode(_display_id(display))
    if not ref:
        raise MacOSError("could not read the display's mode")
    try:
        return _mode(cg, ref)
    finally:
        cg.CGDisplayModeRelease(ref)


def _configure(change: Callable[[ctypes.CDLL, int], int]) -> None:
    """Make a display change the way System Settings does: in one configuration, kept after a restart."""
    cg = _arrangement_api()
    config = ctypes.c_void_p()
    if cg.CGBeginDisplayConfiguration(ctypes.byref(config)) != 0 or not config.value:
        raise MacOSError("could not start changing the displays")
    handle = config.value
    status = change(cg, handle)
    if status != 0:
        cg.CGCancelDisplayConfiguration(handle)
        raise MacOSError("macOS refused the display change (error {})".format(status))
    status = cg.CGCompleteDisplayConfiguration(handle, _CONFIGURE_PERMANENTLY)
    if status != 0:
        raise MacOSError("macOS refused the display change (error {})".format(status))


def set_display_mode(
    width: int,
    height: int,
    *,
    refresh_rate: Optional[float] = None,
    hidpi: Optional[bool] = None,
    display: Union[None, int, Display] = None,
) -> DisplayMode:
    """
    Change the resolution of ``display`` (the main one by default) to ``width`` × ``height`` points, and return it.

    ::

        macos.screen.set_display_mode(1728, 1117)                    # more space on a MacBook Pro
        macos.screen.set_display_mode(2560, 1440, refresh_rate=144, display=external)

    It must be one of :func:`display_modes`, and ``display`` works as there.
    With ``refresh_rate``, the closest to it; without, the highest. Without
    ``hidpi``, the sharp Retina mode when there's one.
    Kept after a restart, like System Settings › Displays. To go back, call
    it again with the :func:`display_mode` read before.
    """
    display_id = _display_id(display)
    cg = _arrangement_api()
    with _cf.owned(_all_modes(cg, display_id)) as modes:
        candidates = []
        for ref in _cf.items(modes):
            mode = _mode(cg, ref)
            if (mode.width, mode.height) != (width, height) or not cg.CGDisplayModeIsUsableForDesktopGUI(ref):
                continue
            if refresh_rate is not None and abs(mode.refresh_rate - refresh_rate) > 0.5:
                continue
            if hidpi is not None and mode.hidpi != hidpi:
                continue
            closeness = -abs(mode.refresh_rate - refresh_rate) if refresh_rate is not None else mode.refresh_rate
            candidates.append((mode.hidpi, closeness, mode.pixel_width, ref, mode))
        if not candidates:
            raise ValueError(
                "display {} has no {}×{} mode{}; see macos.screen.display_modes()".format(
                    display_id, width, height, " at {:g} Hz".format(refresh_rate) if refresh_rate else ""
                )
            )
        *_, chosen, mode = max(candidates, key=lambda candidate: candidate[:3])
        _configure(lambda cg, config: cg.CGConfigureDisplayWithDisplayMode(config, display_id, chosen, None))
    return mode


def _online() -> List[int]:
    cg = _arrangement_api()
    ids = (ctypes.c_uint32 * 32)()
    count = ctypes.c_uint32()
    cg.CGGetOnlineDisplayList(len(ids), ids, ctypes.byref(count))
    return list(ids[: count.value])


def set_main_display(display: Union[int, Display]) -> None:
    """
    Make ``display`` the main one, with the menu bar and the Dock, like dragging the menu bar in System Settings › Displays.

    ``display`` works as in :func:`display_modes`.

    The displays keep their places: the whole arrangement moves so that
    ``display`` is at its top-left corner.
    """
    display_id = _display_id(display)
    cg = _arrangement_api()
    if display_id not in _online():
        raise ValueError("no display {} is connected".format(display_id))
    target = cg.CGDisplayBounds(display_id).origin
    dx, dy = round(target.x), round(target.y)
    if (dx, dy) == (0, 0):
        return  # already the main display

    def move(cg: ctypes.CDLL, config: int) -> int:
        for other in _online():
            origin = cg.CGDisplayBounds(other).origin
            status = cg.CGConfigureDisplayOrigin(config, other, round(origin.x) - dx, round(origin.y) - dy)
            if status != 0:
                return int(status)
        return 0

    _configure(move)


def mirrored() -> bool:
    """Whether some display shows the same picture as another (mirroring)."""
    cg = _arrangement_api()
    return any(cg.CGDisplayMirrorsDisplay(display_id) for display_id in _online())


def mirror(display: Union[int, Display], of: Union[None, int, Display] = None) -> None:
    """
    Make ``display`` show the same picture as ``of`` (the main display by default), like Mirror Displays.

    Both work as ``display`` in :func:`display_modes`.

    ::

        projector = next(d for d in macos.screen.displays() if not d.is_builtin)
        macos.screen.mirror(projector)
    """
    display_id, source = _display_id(display), _display_id(of)
    if display_id == source:
        raise ValueError("a display can't mirror itself")
    if display_id not in _online():
        raise ValueError("no display {} is connected".format(display_id))
    _configure(lambda cg, config: cg.CGConfigureDisplayMirrorOfDisplay(config, display_id, source))


def stop_mirroring() -> None:
    """Give every display its own picture again: extend the desktop across them."""
    if not mirrored():
        return

    def extend(cg: ctypes.CDLL, config: int) -> int:
        for display_id in _online():
            status = cg.CGConfigureDisplayMirrorOfDisplay(config, display_id, 0)  # kCGNullDirectDisplay
            if status != 0:
                return int(status)
        return 0

    _configure(extend)
