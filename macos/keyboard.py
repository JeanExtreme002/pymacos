# -*- coding: utf-8 -*-

"""
Type text, press keys and shortcuts, and control the keyboard backlight.

::

    macos.keyboard.type("Hello, world!")
    macos.keyboard.press("enter")
    macos.keyboard.press("cmd+shift+4")        # the screenshot shortcut
    macos.keyboard.set_brightness(0.5)          # the keyboard backlight
    macos.keyboard.set_layout("ABC")            # the input source

    for key in macos.keyboard.watch():          # every key pressed, in any app
        print(key.shortcut)                     # 'cmd+shift+k'

Typing and pressing keys need the *Accessibility* permission for the app
running Python (your terminal or IDE); without it macOS silently drops the
keystrokes, so these functions raise :class:`~macos.errors.PermissionDeniedError`
instead. The backlight and the layouts need no permission.
"""

import ctypes
import json
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import _cf, _events, _objc
from ._system import framework, private_framework
from .errors import AppNotFoundError, MacOSError, NotSupportedError

__all__ = [
    "type",
    "press",
    "hold",
    "caps_lock",
    "KeyPress",
    "watch",
    "key_repeat",
    "set_key_repeat",
    "press_and_hold",
    "set_press_and_hold",
    "standard_function_keys",
    "set_standard_function_keys",
    "autocorrect",
    "set_autocorrect",
    "smart_quotes",
    "set_smart_quotes",
    "smart_dashes",
    "set_smart_dashes",
    "layout",
    "layouts",
    "set_layout",
    "has_permission",
    "request_permission",
    "brightness",
    "set_brightness",
    "auto_brightness",
    "set_auto_brightness",
    "auto_capitalization",
    "set_auto_capitalization",
    "double_space_period",
    "set_double_space_period",
    "full_keyboard_access",
    "set_full_keyboard_access",
    "remap",
    "remappings",
    "clear_remappings",
    "fn_key_action",
    "set_fn_key_action",
    "inline_predictions",
    "set_inline_predictions",
    "app_shortcuts",
    "set_app_shortcut",
    "SYSTEM_SHORTCUTS",
    "system_shortcuts",
    "set_system_shortcut",
    "backlight_timeout",
    "set_backlight_timeout",
]

has_permission = _events.has_permission
request_permission = _events.request_permission

# Virtual key codes (HIToolbox's kVK_*), which name physical keys.
_KEYS = {
    "enter": 36,
    "return": 36,
    "tab": 48,
    "space": 49,
    "delete": 51,
    "backspace": 51,
    "forward_delete": 117,
    "escape": 53,
    "esc": 53,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "home": 115,
    "end": 119,
    "page_up": 116,
    "page_down": 121,
    "help": 114,
    "caps_lock": 57,
}
_FUNCTION_KEYS = (122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90)
_KEYS.update({"f{}".format(number): code for number, code in enumerate(_FUNCTION_KEYS, start=1)})

# The keys of a US keyboard, used when the current layout can't be read.
_US_LAYOUT = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
    "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
    "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34,
    "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
    ".": 47, "`": 50,
}  # fmt: skip

# What Shift types on those keys.
_US_SHIFTED = dict(zip('~!@#$%^&*()_+{}|:"<>?', "`1234567890-=[]\\;',./"))

# Modifier keys: their flag (kCGEventFlagMask*) and key code.
_MODIFIERS = {
    "cmd": (1 << 20, 55),
    "command": (1 << 20, 55),
    "shift": (1 << 17, 56),
    "option": (1 << 19, 58),
    "opt": (1 << 19, 58),
    "alt": (1 << 19, 58),
    "ctrl": (1 << 18, 59),
    "control": (1 << 18, 59),
    "fn": (1 << 23, 63),
}

_SHIFT = _MODIFIERS["shift"]
_MODIFIER_FLAGS = {code: flag for flag, code in _MODIFIERS.values()}

# Names for the characters "+" can't spell in a shortcut.
_ALIASES = {"plus": "+", "minus": "-"}

# The numeric keypad's keys: shortcuts expect the main keys, which type the same.
_KEYPAD = {65, 67, 69, 71, 75, 76, 78, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92}

# The most UTF-16 units one keyboard event carries.
_CHUNK = 20


@lru_cache(maxsize=None)
def _text_input() -> ctypes.CDLL:
    carbon = framework("Carbon")
    pointer = ctypes.c_void_p
    carbon.TISCopyCurrentKeyboardLayoutInputSource.argtypes = ()
    carbon.TISCopyCurrentKeyboardLayoutInputSource.restype = pointer
    carbon.TISGetInputSourceProperty.argtypes = (pointer, pointer)
    carbon.TISGetInputSourceProperty.restype = pointer
    carbon.LMGetKbdType.argtypes = ()
    carbon.LMGetKbdType.restype = ctypes.c_uint8
    carbon.UCKeyTranslate.argtypes = (
        pointer,
        ctypes.c_uint16,
        ctypes.c_uint16,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_uint16),
    )
    carbon.UCKeyTranslate.restype = ctypes.c_int32
    carbon.TISCopyCurrentKeyboardInputSource.argtypes = ()
    carbon.TISCopyCurrentKeyboardInputSource.restype = pointer
    carbon.TISCreateInputSourceList.argtypes = (pointer, ctypes.c_bool)
    carbon.TISCreateInputSourceList.restype = pointer
    carbon.TISSelectInputSource.argtypes = (pointer,)
    carbon.TISSelectInputSource.restype = ctypes.c_int32
    return carbon


def _layout() -> Dict[str, Tuple[int, bool]]:
    """
    What each key of the current keyboard layout types: ``{"a": (0, False), "?": (44, True)}``.

    The ``bool`` says whether it needs Shift. Falls back to a US keyboard
    when the layout can't be read: macOS only allows it on the main thread.
    """
    fallback = {char: (code, False) for char, code in _US_LAYOUT.items()}
    fallback.update({char: (_US_LAYOUT[base], True) for char, base in _US_SHIFTED.items()})
    if threading.current_thread() is not threading.main_thread():
        return fallback
    carbon = _text_input()
    cf = _cf.lib()
    source = carbon.TISCopyCurrentKeyboardLayoutInputSource()
    if not source:
        return fallback
    try:
        key = ctypes.c_void_p.in_dll(carbon, "kTISPropertyUnicodeKeyLayoutData").value
        data = carbon.TISGetInputSourceProperty(source, key)
        if not data:
            return fallback
        layout = cf.CFDataGetBytePtr(data)
        keyboard_type = carbon.LMGetKbdType()
        found: Dict[str, Tuple[int, bool]] = {}
        # Unshifted characters win: "1" is the 1 key, not Shift+something.
        for shifted, modifiers in ((False, 0), (True, 0x02)):  # 0x02: shiftKey >> 8
            for code in range(128):
                if code in _KEYPAD:
                    continue
                dead = ctypes.c_uint32()
                length = ctypes.c_ulong()
                chars = (ctypes.c_uint16 * 4)()
                status = carbon.UCKeyTranslate(
                    layout, code, 3, modifiers, keyboard_type, 1, ctypes.byref(dead), 4, ctypes.byref(length), chars
                )
                if status == 0 and length.value == 1:
                    char = chr(chars[0])
                    if char.isprintable() and char.strip() and char not in found:
                        found[char] = (code, shifted)
        return found or fallback
    finally:
        _cf.release(source)


def _parse(keys: str) -> Tuple[List[Tuple[int, int]], int, bool]:
    """
    Split ``"cmd+shift+4"`` into its modifiers ``[(flag, key code), ...]``, the key code and whether Shift is added.
    """
    text = keys.strip()
    if not text:
        raise ValueError("press() needs a key, such as 'enter' or 'cmd+c'")
    # A last "+" is the key itself: "+" or "cmd++".
    if text == "+":
        parts = ["+"]
    elif text.endswith("++"):
        parts = text[:-2].split("+") + ["+"]
    else:
        parts = text.split("+")
    names, key = [part.strip() for part in parts[:-1]], parts[-1].strip() or parts[-1]
    modifiers = []
    for name in names:
        if name.lower() not in _MODIFIERS:
            raise ValueError("{!r} is not a modifier; use cmd, shift, option, ctrl or fn".format(name))
        modifiers.append(_MODIFIERS[name.lower()])
    if not key:
        raise ValueError("{!r} has no key after the modifiers".format(keys))
    if key.lower() in _KEYS:
        return modifiers, _KEYS[key.lower()], False
    if key.lower() in _MODIFIERS:  # a modifier alone, such as "shift"
        return modifiers, _MODIFIERS[key.lower()][1], False
    key = _ALIASES.get(key.lower(), key)
    if len(key) == 1:
        layout = _layout()
        # Letters work in either case, like the keys' labels: "cmd+C" is Cmd+C.
        for char in (key.lower(), key):
            if char in layout:
                code, shifted = layout[char]
                return modifiers, code, shifted
        raise ValueError("no key types {!r} on this keyboard layout; use type() for text".format(key))
    raise ValueError("unknown key {!r}; use a character or a name such as 'enter', 'tab', 'left' or 'f5'".format(key))


def _key_event(code: int, down: bool, flags: int, *, held: bool = True) -> int:
    """An owned keyboard event; ``held`` adds the modifiers :func:`hold` keeps down on this thread."""
    event = _events.graphics().CGEventCreateKeyboardEvent(None, code, down)
    if not event:
        raise MacOSError("could not create a keyboard event")
    _events.graphics().CGEventSetFlags(event, flags | (_events.held_flags() if held else 0))
    return event


def press(keys: str, *, times: int = 1) -> None:
    """
    Press a key or a shortcut, like ``"enter"``, ``"a"``, ``"cmd+c"`` or ``"cmd+shift+4"``, ``times`` times.

    Modifiers are ``cmd``, ``shift``, ``option`` (or ``alt``), ``ctrl`` and
    ``fn``, joined with ``+``. Keys are characters, found on the current
    keyboard layout (so ``"cmd+z"`` is undo on an AZERTY keyboard too), or
    names: ``enter``, ``tab``, ``space``, ``delete`` (backspace),
    ``forward_delete``, ``escape``, ``left``, ``right``, ``up``, ``down``,
    ``home``, ``end``, ``page_up``, ``page_down``, ``f1`` to ``f20``...

    The keystrokes go to the app in front. Needs the Accessibility permission.
    """
    if times < 1:
        raise ValueError("times must be at least 1, not {}".format(times))
    modifiers, code, shifted = _parse(keys)
    if shifted and _SHIFT not in modifiers:
        modifiers.append(_SHIFT)
    _events.require_permission()
    # A modifier pressed alone ("shift") sets its own flag while it's down.
    own = _MODIFIER_FLAGS.get(code, 0)
    for _ in range(times):
        flags = 0
        for flag, modifier in modifiers:
            flags |= flag
            _events.post(_key_event(modifier, True, flags))
        _events.post(_key_event(code, True, flags | own))
        _events.post(_key_event(code, False, flags))
        for flag, modifier in reversed(modifiers):
            flags &= ~flag
            _events.post(_key_event(modifier, False, flags))


@contextmanager
def hold(*keys: str) -> Iterator[None]:
    """
    Hold keys down while the ``with`` block runs, and release them at the end.

    For Shift-clicks, Cmd-clicks, Option-drags, or a key held in a game::

        with macos.keyboard.hold("shift"):
            macos.mouse.click(100, 200)
            macos.mouse.click(100, 400)      # selects the range in between

        with macos.keyboard.hold("cmd", "option"):
            macos.mouse.drag(600, 300)

    Each key is written as for :func:`press` (``"cmd+shift"`` holds both).
    The keys are released even when the block raises. They modify what this
    thread posts only: clicks and keys sent from other threads meanwhile
    don't carry them, nor does text :func:`type` types. Needs the
    Accessibility permission.
    """
    if not keys:
        raise ValueError("hold() needs at least one key, such as 'shift'")
    presses: List[Tuple[int, int]] = []
    for spec in keys:
        modifiers, code, shifted = _parse(spec)
        if shifted and _SHIFT not in modifiers:
            modifiers.append(_SHIFT)
        for entry in modifiers + [(_MODIFIER_FLAGS.get(code, 0), code)]:
            if entry not in presses:
                presses.append(entry)
    _events.require_permission()
    held = _events.held()
    pressed: List[Tuple[int, int]] = []
    try:
        for flag, code in presses:
            held.append(flag)
            pressed.append((flag, code))
            _events.post(_key_event(code, True, 0))
        yield
    finally:
        # Each key on its own: one that fails to come up must not leave the others down.
        failure: Optional[BaseException] = None
        for flag, code in reversed(pressed):
            held.remove(flag)
            try:
                _events.post(_key_event(code, False, 0))
            except Exception as error:
                failure = failure or error
        if failure is not None:
            raise failure


_ALPHA_SHIFT = 1 << 16  # kCGEventFlagMaskAlphaShift: Caps Lock is on
_HID_STATE = 1  # kCGEventSourceStateHIDSystemState: the hardware's own state


def caps_lock() -> bool:
    """Whether Caps Lock is on. Needs no permission."""
    return bool(_events.graphics().CGEventSourceFlagsState(_HID_STATE) & _ALPHA_SHIFT)


def _chunks(text: str, size: int) -> List[str]:
    """Split ``text`` into pieces of at most ``size`` UTF-16 units, never inside a character."""
    pieces: List[str] = []
    current, units = "", 0
    for char in text:
        width = len(char.encode("utf-16-le")) // 2
        if current and units + width > size:
            pieces.append(current)
            current, units = "", 0
        current += char
        units += width
    if current:
        pieces.append(current)
    return pieces


def type(text: str, *, interval: float = 0.0) -> None:
    """
    Type ``text`` into the app in front, as if typed on the keyboard.

    Any character works (accents, emoji...), whatever the keyboard layout.
    New lines press Enter and tabs press Tab. ``interval`` is the pause
    between characters, in seconds, for apps that can't keep up. The keys
    :func:`hold` holds down don't apply: the text comes out as written. Needs
    the Accessibility permission.
    """
    if interval < 0:
        raise ValueError("interval must not be negative, not {}".format(interval))
    _events.require_permission()
    cg = _events.graphics()
    pieces: List[str] = []
    for line_index, line in enumerate(text.split("\n")):
        if line_index:
            pieces.append("\n")
        for tab_index, part in enumerate(line.split("\t")):
            if tab_index:
                pieces.append("\t")
            if part:
                pieces.extend(_chunks(part, 1 if interval else _CHUNK))
    for piece in pieces:
        if piece in ("\n", "\t"):
            code = _KEYS["enter" if piece == "\n" else "tab"]
            _events.post(_key_event(code, True, 0, held=False))
            _events.post(_key_event(code, False, 0, held=False))
        else:
            encoded = piece.encode("utf-16-le")
            units = (ctypes.c_uint16 * (len(encoded) // 2)).from_buffer_copy(encoded)
            # The text rides on the "a" key: with a held Cmd, it would be Cmd+A.
            for down in (True, False):
                event = _key_event(0, down, 0, held=False)
                cg.CGEventKeyboardSetUnicodeString(event, len(units), units)
                _events.post(event)
        if interval:
            time.sleep(interval)


# Keyboard layouts (input sources), through Text Input Sources.


def _require_main_thread(what: str) -> None:
    # Text Input Sources only work on the main thread: elsewhere macOS may
    # answer wrong, or stop the process.
    if threading.current_thread() is not threading.main_thread():
        raise MacOSError("{} only works on the main thread, as macOS requires for keyboard layouts".format(what))


def _tis_constant(name: str) -> int:
    return ctypes.c_void_p.in_dll(_text_input(), name).value or 0


def _source_property(source: int, name: str) -> str:
    return _cf.to_str(_text_input().TISGetInputSourceProperty(source, _tis_constant(name))) or ""


@contextmanager
def _input_sources() -> Iterator[List[Tuple[int, str, str]]]:
    """The enabled keyboard input sources, as ``(source, name, id)``, alive inside the ``with`` block."""
    cf = _cf.lib()
    wanted = _cf.dictionary(
        {
            _tis_constant("kTISPropertyInputSourceCategory"): _tis_constant("kTISCategoryKeyboardInputSource"),
            _tis_constant("kTISPropertyInputSourceIsSelectCapable"): _cf.constant(cf, "kCFBooleanTrue"),
        }
    )
    with _cf.owned(wanted):
        found = _text_input().TISCreateInputSourceList(wanted, False)
    with _cf.owned(found):
        yield [
            (
                source,
                _source_property(source, "kTISPropertyLocalizedName"),
                _source_property(source, "kTISPropertyInputSourceID"),
            )
            for source in _cf.items(found)
        ]


def layouts() -> List[str]:
    """
    Return the keyboard layouts and input methods enabled in the menu bar's input menu: ``['ABC', 'French']``.

    Add more in System Settings › Keyboard › Text Input. Call it from the main thread.
    """
    _require_main_thread("macos.keyboard.layouts()")
    with _input_sources() as sources:
        return [name for _, name, _ in sources]


def layout() -> str:
    """Return the keyboard layout (input source) in use, such as ``'ABC'`` or ``'French'``. Call it from the main thread."""
    _require_main_thread("macos.keyboard.layout()")
    carbon = _text_input()
    with _cf.owned(carbon.TISCopyCurrentKeyboardInputSource()) as source:
        if not source:
            raise MacOSError("could not read the keyboard layout")
        return _source_property(source, "kTISPropertyLocalizedName")


def set_layout(name: str) -> str:
    """
    Switch to one of the enabled keyboard layouts, like picking it in the input menu, and return its name.

    ``name`` is as :func:`layouts` returns it, its identifier (such as
    ``'com.apple.keylayout.ABC'``) or part of its name when that matches only
    one layout. Call it from the main thread.
    """
    _require_main_thread("macos.keyboard.set_layout()")
    with _input_sources() as sources:
        exact = [entry for entry in sources if name in (entry[1], entry[2])]
        loose = [entry for entry in sources if name.casefold() in entry[1].casefold()]
        chosen = exact or loose
        names = ", ".join(repr(entry[1]) for entry in sources)
        if not chosen:
            raise ValueError("no enabled keyboard layout matches {!r}; enabled: {}".format(name, names))
        if len(chosen) > 1:
            raise ValueError("{!r} matches several keyboard layouts ({}); use the full name".format(name, names))
        source, found, _ = chosen[0]
        status = _text_input().TISSelectInputSource(source)
    if status != 0:
        raise MacOSError("could not switch to {!r} (OSStatus {})".format(found, status))
    return found


# The keyboard backlight, through CoreBrightness (a private framework).


def _backlight() -> Tuple[int, int]:
    """The ``KeyboardBrightnessClient`` (autoreleased) and the backlit keyboard's ID. Call inside a pool."""
    private_framework("CoreBrightness")
    framework("Foundation")
    try:
        _objc.cls("KeyboardBrightnessClient")
    except LookupError:
        raise NotSupportedError("this version of macOS doesn't expose the keyboard backlight") from None
    client = _objc.new("KeyboardBrightnessClient")
    found = _objc.send(client, "copyKeyboardBacklightIDs")  # a copy: ours to release
    try:
        ids = [int(_objc.send(number, "unsignedLongLongValue", restype=ctypes.c_uint64)) for number in _objc.nsarray(found)]
    finally:
        if found:
            _objc.send(found, "release", restype=None)
    if not ids:
        raise NotSupportedError("this Mac has no keyboard backlight")
    built_in = [
        keyboard
        for keyboard in ids
        if _objc.send(client, "isKeyboardBuiltIn:", keyboard, argtypes=(ctypes.c_uint64,), restype=_objc.BOOL)
    ]
    return client, (built_in or ids)[0]


def brightness() -> float:
    """
    The keyboard backlight's brightness, from 0.0 (off) to 1.0.

    Raises :class:`~macos.errors.NotSupportedError` on a Mac without a
    backlit keyboard.
    """
    with _objc.autorelease_pool():
        client, keyboard = _backlight()
        value = _objc.send(client, "brightnessForKeyboard:", keyboard, argtypes=(ctypes.c_uint64,), restype=ctypes.c_float)
    return round(float(value), 3)


def set_brightness(value: float) -> None:
    """
    Set the keyboard backlight's brightness, from 0.0 (off) to 1.0.

    With automatic brightness on (see :func:`auto_brightness`), macOS keeps
    adjusting it to the room's light afterwards.
    """
    if not 0.0 <= value <= 1.0:
        raise ValueError("brightness must be from 0.0 to 1.0, not {}".format(value))
    with _objc.autorelease_pool():
        client, keyboard = _backlight()
        ok = _objc.send(
            client,
            "setBrightness:forKeyboard:",
            float(value),
            keyboard,
            argtypes=(ctypes.c_float, ctypes.c_uint64),
            restype=_objc.BOOL,
        )
    if not ok:
        raise MacOSError("macOS refused to change the keyboard backlight")


def auto_brightness() -> bool:
    """Whether the keyboard backlight follows the room's light, as set in System Settings › Keyboard."""
    with _objc.autorelease_pool():
        client, keyboard = _backlight()
        return bool(
            _objc.send(
                client, "isAutoBrightnessEnabledForKeyboard:", keyboard, argtypes=(ctypes.c_uint64,), restype=_objc.BOOL
            )
        )


def set_auto_brightness(on: bool) -> None:
    """Turn on or off the keyboard backlight's automatic brightness."""
    with _objc.autorelease_pool():
        client, keyboard = _backlight()
        ok = _objc.send(
            client,
            "enableAutoBrightness:forKeyboard:",
            bool(on),
            keyboard,
            argtypes=(_objc.BOOL, ctypes.c_uint64),
            restype=_objc.BOOL,
        )
    if not ok:
        raise MacOSError("macOS refused to change the keyboard backlight")


@dataclass(frozen=True)
class KeyPress:
    """A key pressed, as :func:`watch` sees it."""

    key: str
    """The key, named as :func:`press` takes it: ``'a'``, ``'1'``, ``'enter'``, ``'f5'``, ``'left'``..."""
    modifiers: Tuple[str, ...]
    """The modifiers held, among ``'cmd'``, ``'ctrl'``, ``'option'`` and ``'shift'``."""
    text: str
    """What the key typed, such as ``'A'`` with Shift; ``''`` for keys that type nothing."""
    code: int
    """The virtual key code, which names the physical key whatever the layout."""
    repeat: bool
    """Whether it comes from holding the key down."""

    @property
    def shortcut(self) -> str:
        """The key and its modifiers as :func:`press` and :mod:`macos.hotkeys` write them, such as ``'cmd+shift+k'``."""
        return "+".join(self.modifiers + (self.key,))


# Names for the codes of the keys that type nothing (the first name of each in _KEYS).
_KEY_NAMES: Dict[int, str] = {}
for _name, _code in _KEYS.items():
    _KEY_NAMES.setdefault(_code, _name)

_WATCHED_MODIFIERS = (("cmd", 1 << 20), ("ctrl", 1 << 18), ("option", 1 << 19), ("shift", 1 << 17))
_KEY_DOWN = 10  # kCGEventKeyDown
_AUTOREPEAT = 8  # kCGKeyboardEventAutorepeat
_KEYCODE = 9  # kCGKeyboardEventKeycode


def _typed(event: int) -> str:
    length = ctypes.c_ulong()
    chars = (ctypes.c_uint16 * 8)()
    _events.graphics().CGEventKeyboardGetUnicodeString(event, len(chars), ctypes.byref(length), chars)
    text = bytes(chars)[: length.value * 2].decode("utf-16-le", "replace")
    return text if text.isprintable() else ""


def watch(*, timeout: Optional[float] = None) -> Iterator[KeyPress]:
    """
    Yield a :class:`KeyPress` for each key pressed, in any app, as it happens.

    ::

        for key in macos.keyboard.watch():
            if key.shortcut == "ctrl+option+q":
                break
            log.write(key.text)

    It only listens: the keys still reach the app in front (to take a
    shortcut for yourself, see :mod:`macos.hotkeys`). It goes on until you
    ``break`` out of the loop, or ``timeout`` seconds pass. Needs the *Input
    Monitoring* permission. macOS hides the keys typed in password fields.
    """
    unshifted = {code: char for char, (code, shifted) in _layout().items() if not shifted}
    cg = _events.graphics()

    def convert(kind: int, event: int) -> KeyPress:
        code = int(cg.CGEventGetIntegerValueField(event, _KEYCODE))
        flags = cg.CGEventGetFlags(event)
        text = _typed(event)
        key = _KEY_NAMES.get(code) or unshifted.get(code) or text.lower() or "key{}".format(code)
        return KeyPress(
            key=key,
            modifiers=tuple(name for name, flag in _WATCHED_MODIFIERS if flags & flag),
            text="" if code in _KEY_NAMES and code != _KEYS["space"] else text,
            code=code,
            repeat=bool(cg.CGEventGetIntegerValueField(event, _AUTOREPEAT)),
        )

    return _events.listen(
        [_KEY_DOWN],
        convert,
        timeout,
        "listening to the keyboard needs the Input Monitoring permission: allow the app running Python (your "
        "terminal or IDE) in System Settings › Privacy & Security › Input Monitoring, then restart it",
    )


# --- Settings ---------------------------------------------------------------

_KEY_REPEAT_UNIT = 0.015  # KeyRepeat and InitialKeyRepeat count 15 ms steps


def _global(key: str, default: object) -> object:
    from . import defaults

    return defaults.read(defaults.GLOBAL, key, default=default)


def _set_global(key: str, value: object, apply: bool = True) -> None:
    from . import defaults
    from ._system import apply_input_settings

    defaults.write(defaults.GLOBAL, key, value)
    if apply:
        apply_input_settings()


def key_repeat() -> Tuple[float, float]:
    """``(interval, delay)``: seconds between the repeats of a held key, and before the first one."""
    interval = float(_global("KeyRepeat", 6)) * _KEY_REPEAT_UNIT  # type: ignore[arg-type]
    delay = float(_global("InitialKeyRepeat", 25)) * _KEY_REPEAT_UNIT  # type: ignore[arg-type]
    return round(interval, 3), round(delay, 3)


def set_key_repeat(interval: Optional[float] = None, *, delay: Optional[float] = None) -> None:
    """
    Set how fast a held key repeats: ``interval`` seconds between repeats, after ``delay`` seconds.

    ::

        macos.keyboard.set_key_repeat(0.03, delay=0.25)   # fast, the favorite of developers

    System Settings' fastest are 0.03 and 0.225 seconds; shorter ones work
    too. Takes effect at the next login.
    """
    if interval is None and delay is None:
        raise ValueError("give interval, delay, or both")
    for label, value in (("interval", interval), ("delay", delay)):
        if value is not None and value <= 0:
            raise ValueError("{} must be positive, not {}".format(label, value))
    if interval is not None:
        _set_global("KeyRepeat", max(1, round(interval / _KEY_REPEAT_UNIT)), apply=False)
    if delay is not None:
        _set_global("InitialKeyRepeat", max(1, round(delay / _KEY_REPEAT_UNIT)), apply=False)


def press_and_hold() -> bool:
    """Whether holding a key shows the accents menu (é, ê, è...) instead of repeating it."""
    return bool(_global("ApplePressAndHoldEnabled", True))


def set_press_and_hold(on: bool = True) -> None:
    """
    Show the accents menu when a key is held, or repeat the key instead (``False``).

    Apps pick it up when they're reopened.
    """
    _set_global("ApplePressAndHoldEnabled", bool(on), apply=False)


def standard_function_keys() -> bool:
    """Whether F1, F2... act as function keys without holding Fn (instead of brightness, volume...)."""
    return bool(_global("com.apple.keyboard.fnState", False))


def set_standard_function_keys(on: bool = True) -> None:
    """Make F1, F2... act as function keys without Fn, like System Settings › Keyboard › Keyboard Shortcuts › Function Keys."""
    _set_global("com.apple.keyboard.fnState", bool(on))


def autocorrect() -> bool:
    """Whether macOS corrects spelling as you type."""
    return bool(_global("NSAutomaticSpellingCorrectionEnabled", True))


def set_autocorrect(on: bool = True) -> None:
    """Correct spelling as you type, or not. Apps pick it up when they're reopened."""
    _set_global("NSAutomaticSpellingCorrectionEnabled", bool(on), apply=False)
    _set_global("WebAutomaticSpellingCorrectionEnabled", bool(on), apply=False)


def smart_quotes() -> bool:
    """Whether typed quotes become curly ones (“ ”), which break code pasted anywhere."""
    return bool(_global("NSAutomaticQuoteSubstitutionEnabled", True))


def set_smart_quotes(on: bool = True) -> None:
    """Turn typed quotes into curly ones, or keep them straight (``False``). Apps pick it up when reopened."""
    _set_global("NSAutomaticQuoteSubstitutionEnabled", bool(on), apply=False)


def smart_dashes() -> bool:
    """Whether a typed ``--`` becomes a dash (—)."""
    return bool(_global("NSAutomaticDashSubstitutionEnabled", True))


def set_smart_dashes(on: bool = True) -> None:
    """Turn a typed ``--`` into a dash, or keep it (``False``). Apps pick it up when reopened."""
    _set_global("NSAutomaticDashSubstitutionEnabled", bool(on), apply=False)


def auto_capitalization() -> bool:
    """Whether the first letter of a sentence is capitalized as you type."""
    return bool(_global("NSAutomaticCapitalizationEnabled", True))


def set_auto_capitalization(on: bool = True) -> None:
    """Capitalize the first letter of sentences as you type, or not. Apps pick it up when they're reopened."""
    _set_global("NSAutomaticCapitalizationEnabled", bool(on), apply=False)


def double_space_period() -> bool:
    """Whether typing two spaces adds a period and a space, as on the iPhone."""
    return bool(_global("NSAutomaticPeriodSubstitutionEnabled", True))


def set_double_space_period(on: bool = True) -> None:
    """Make two spaces type a period, or not. Apps pick it up when they're reopened."""
    _set_global("NSAutomaticPeriodSubstitutionEnabled", bool(on), apply=False)


_KEYBOARD_NAVIGATION = 2  # AppleKeyboardUIMode's bit for "Keyboard navigation"


def full_keyboard_access() -> bool:
    """Whether Tab moves between every control (buttons, checkboxes, menus...), not only text fields and lists."""
    return bool(int(_global("AppleKeyboardUIMode", 0)) & _KEYBOARD_NAVIGATION)  # type: ignore[call-overload]


def set_full_keyboard_access(on: bool = True) -> None:
    """
    Let Tab move between every control, like *Keyboard navigation* in System Settings › Keyboard, or not.

    Apps pick it up when they're reopened.
    """
    # A bit mask: only its navigation bit changes, the others stay as they are.
    mode = int(_global("AppleKeyboardUIMode", 0))  # type: ignore[call-overload]
    _set_global("AppleKeyboardUIMode", mode | _KEYBOARD_NAVIGATION if on else mode & ~_KEYBOARD_NAVIGATION, apply=False)


# --- Remapping keys ---------------------------------------------------------

_HID_PAGE = 0x700000000  # the keyboard's HID usage page, as hidutil numbers keys
_HID_USAGES = {
    "caps_lock": 0x39,
    "escape": 0x29,
    "enter": 0x28,
    "tab": 0x2B,
    "space": 0x2C,
    "delete": 0x2A,
    "forward_delete": 0x4C,
    "left": 0x50,
    "right": 0x4F,
    "down": 0x51,
    "up": 0x52,
    "home": 0x4A,
    "end": 0x4D,
    "page_up": 0x4B,
    "page_down": 0x4E,
    "ctrl": 0xE0,
    "shift": 0xE1,
    "option": 0xE2,
    "cmd": 0xE3,
    "right_ctrl": 0xE4,
    "right_shift": 0xE5,
    "right_option": 0xE6,
    "right_cmd": 0xE7,
}
_HID_USAGES.update({chr(ord("a") + index): 0x04 + index for index in range(26)})
_HID_USAGES.update({str(digit): 0x1E + (digit - 1) % 10 for digit in range(10)})
_HID_USAGES.update({"f{}".format(number): 0x3A + number - 1 for number in range(1, 13)})
_HID_USAGES.update({"f{}".format(number): 0x68 + number - 13 for number in range(13, 21)})
_HID_CODES = {name: _HID_PAGE | usage for name, usage in _HID_USAGES.items()}
_HID_CODES["fn"] = 0xFF0100000003  # Apple's own usage page
_HID_NAMES = {code: name for name, code in _HID_CODES.items()}
_HID_ALIASES = {
    "esc": "escape",
    "return": "enter",
    "backspace": "delete",
    "command": "cmd",
    "left_cmd": "cmd",
    "opt": "option",
    "alt": "option",
    "left_option": "option",
    "control": "ctrl",
    "left_ctrl": "ctrl",
    "left_shift": "shift",
}


def _hid_code(key: str) -> int:
    name = key.lower()
    name = _HID_ALIASES.get(name, name)
    if name not in _HID_CODES:
        raise ValueError(
            "can't remap {!r}: use a letter, a digit, f1 to f20, a modifier (cmd, right_option...) "
            "or one of caps_lock, escape, enter, tab, space, delete, forward_delete, the arrows, "
            "home, end, page_up, page_down, fn".format(key)
        )
    return _HID_CODES[name]


def _mappings() -> Dict[int, int]:
    from ._system import run

    output = run(["hidutil", "property", "--get", "UserKeyMapping"])
    found = {}
    for block in re.findall(r"\{(.*?)\}", output, re.S):
        source = re.search(r"HIDKeyboardModifierMappingSrc\s*=\s*(\d+)", block)
        target = re.search(r"HIDKeyboardModifierMappingDst\s*=\s*(\d+)", block)
        if source and target:
            found[int(source.group(1))] = int(target.group(1))
    return found


def _set_mappings(mappings: Dict[int, int]) -> None:
    from ._system import run

    pairs = [
        {"HIDKeyboardModifierMappingSrc": source, "HIDKeyboardModifierMappingDst": target} for source, target in mappings.items()
    ]
    run(["hidutil", "property", "--set", json.dumps({"UserKeyMapping": pairs})])


def remappings() -> Dict[str, str]:
    """The keys remapped, as ``{"caps_lock": "escape"}``; ``{}`` when none is."""
    return {_HID_NAMES.get(source, hex(source)): _HID_NAMES.get(target, hex(target)) for source, target in _mappings().items()}


def remap(key: str, to: Optional[str]) -> None:
    """
    Make ``key`` act as ``to`` on every keyboard, or undo it (``to=None``).

    ::

        macos.keyboard.remap("caps_lock", "escape")      # a favorite of Vim users
        macos.keyboard.remap("right_option", "ctrl")
        macos.keyboard.remap("caps_lock", None)          # back to Caps Lock

    Keys are named as for :func:`press`, plus the right-hand modifiers:
    letters, digits, ``f1`` to ``f20``, modifiers (``cmd``, ``right_cmd``,
    ``option``, ``right_option``, ``ctrl``,
    ``shift``, ``fn``...) and ``caps_lock``, ``escape``, ``enter``, ``tab``...
    Applies at once, without a permission, until the Mac restarts: to keep
    it, run it at login with :func:`macos.schedule.add`.
    """
    source = _hid_code(key)
    mappings = _mappings()
    if to is None:
        mappings.pop(source, None)
    else:
        mappings[source] = _hid_code(to)
    _set_mappings(mappings)


def clear_remappings() -> None:
    """Undo every key remapping: each key acts as itself again."""
    _set_mappings({})


# --- More settings ----------------------------------------------------------

# AppleFnUsageType's values.
_FN_ACTIONS = {None: 0, "input_source": 1, "emoji": 2, "dictation": 3}


def fn_key_action() -> Optional[str]:
    """
    What pressing Fn (🌐) alone does: ``'emoji'``, ``'input_source'``, ``'dictation'``, or ``None`` (nothing).
    """
    from . import defaults

    code = int(defaults.read("com.apple.HIToolbox", "AppleFnUsageType", default=2))
    return {value: name for name, value in _FN_ACTIONS.items()}.get(code, "emoji")


def set_fn_key_action(action: Optional[str]) -> None:
    """
    Make pressing Fn (🌐) alone show the ``"emoji"`` picker, switch the ``"input_source"``, start ``"dictation"``,
    or do nothing (``None``), like System Settings › Keyboard.

    ``None`` stops the emoji picker popping up when Fn is pressed by itself.
    """
    from . import defaults
    from ._system import apply_input_settings

    if action not in _FN_ACTIONS:
        raise ValueError("action must be 'emoji', 'input_source', 'dictation' or None, not {!r}".format(action))
    defaults.write("com.apple.HIToolbox", "AppleFnUsageType", _FN_ACTIONS[action])
    apply_input_settings()


def inline_predictions() -> bool:
    """Whether macOS suggests the end of words and sentences in gray as you type (macOS 14 and later)."""
    return bool(_global("NSAutomaticInlinePredictionEnabled", True))


def set_inline_predictions(on: bool = True) -> None:
    """Show predictive text inline as you type, or not. Apps pick it up when they're reopened. Needs macOS 14 or later."""
    _set_global("NSAutomaticInlinePredictionEnabled", bool(on), apply=False)


# --- Shortcuts for apps' menu items -----------------------------------------

# NSUserKeyEquivalents writes the modifiers as these characters, before the key.
_SHORTCUT_MODIFIERS = (("cmd", "@"), ("shift", "$"), ("option", "~"), ("ctrl", "^"))
_SHORTCUT_MODIFIER_ALIASES = {"command": "cmd", "control": "ctrl", "opt": "option", "alt": "option"}
# Keys that aren't a character, as AppKit's code points for them (NSUpArrowFunctionKey...).
_SHORTCUT_KEYS = {
    "up": "\uf700",
    "down": "\uf701",
    "left": "\uf702",
    "right": "\uf703",
    "forward_delete": "\uf728",
    "home": "\uf729",
    "end": "\uf72b",
    "page_up": "\uf72c",
    "page_down": "\uf72d",
    "delete": "\x7f",
    "backspace": "\x7f",
    "tab": "\t",
    "enter": "\r",
    "return": "\r",
    "escape": "\x1b",
    "esc": "\x1b",
    "space": " ",
    "plus": "+",
}
_SHORTCUT_KEYS.update({"f{}".format(number): chr(0xF704 + number - 1) for number in range(1, 21)})
# The first name of each key, for reading shortcuts back.
_SHORTCUT_KEY_NAMES: Dict[str, str] = {}
for _name, _character in _SHORTCUT_KEYS.items():
    _SHORTCUT_KEY_NAMES.setdefault(_character, _name)
_SHORTCUT_KEY_NAMES["+"] = "+"
_MENU_PATH = "\x1b"  # NSUserKeyEquivalents' separator between a menu and its item
_MENU_SEPARATOR = " > "


def _encode_shortcut(keys: str) -> str:
    """``"cmd+shift+e"`` as NSUserKeyEquivalents writes it: ``"@$e"``."""
    text = keys.strip().lower()
    if text.endswith("+"):  # the "+" key itself: "cmd++"
        key, rest = "+", text[:-1].rstrip("+")
    else:
        rest, _, key = text.rpartition("+")
    names = [part.strip() for part in rest.split("+") if part.strip()]
    wanted = {_SHORTCUT_MODIFIER_ALIASES.get(name, name) for name in names}
    if wanted - {name for name, _ in _SHORTCUT_MODIFIERS} or not key.strip():
        raise ValueError("can't read the shortcut {!r}: write it like 'cmd+shift+e'".format(keys))
    key = key.strip()
    if key in _SHORTCUT_KEYS:
        key = _SHORTCUT_KEYS[key]
    elif len(key) != 1:
        raise ValueError("unknown key {!r} in {!r}: use a character, f1 to f20, or a name like 'left'".format(key, keys))
    return "".join(symbol for name, symbol in _SHORTCUT_MODIFIERS if name in wanted) + key


def _decode_shortcut(code: str) -> str:
    """``"@$e"`` back as ``"cmd+shift+e"``."""
    symbols = {symbol: name for name, symbol in _SHORTCUT_MODIFIERS}
    index = 0
    found = set()
    while index < len(code) - 1 and code[index] in symbols:
        found.add(symbols[code[index]])
        index += 1
    key = code[index:]
    names = [name for name, _ in _SHORTCUT_MODIFIERS if name in found]
    return "+".join(names + [_SHORTCUT_KEY_NAMES.get(key, key)])


def _shortcut_domain(app: Optional[str]) -> str:
    from . import apps, defaults

    if app is None:
        return defaults.GLOBAL
    try:
        path = apps._locate(app)  # names (even "zoom.us"), bundle IDs and paths
    except AppNotFoundError:
        if app.count(".") >= 2 and "/" not in app:
            return app  # the bundle ID of an app not installed yet
        raise
    bundle_id = apps._bundle_id(path)
    if not bundle_id:
        raise MacOSError("{!r} has no bundle ID to keep its shortcuts under".format(app))
    return bundle_id


def _menu_title(menu_item: str) -> str:
    if _MENU_SEPARATOR not in menu_item:
        return menu_item
    return "".join(_MENU_PATH + part.strip() for part in menu_item.split(_MENU_SEPARATOR))


def app_shortcuts(app: Optional[str] = None) -> Dict[str, str]:
    """
    The shortcuts given to ``app``'s menu items, as ``{"Export as PDF…": "cmd+shift+e"}``; ``None`` for every app's.

    An item under a given menu is written ``"File > Export…"``.
    """
    from . import defaults

    found = defaults.read(_shortcut_domain(app), "NSUserKeyEquivalents", default={}) or {}
    return {
        title.lstrip(_MENU_PATH).replace(_MENU_PATH, _MENU_SEPARATOR): _decode_shortcut(code) for title, code in found.items()
    }


def set_app_shortcut(app: Optional[str], menu_item: str, keys: Optional[str]) -> None:
    """
    Give a menu item a keyboard shortcut, like System Settings › Keyboard › Keyboard Shortcuts › App Shortcuts.

    ::

        macos.keyboard.set_app_shortcut("Safari", "Export as PDF…", "cmd+shift+e")
        macos.keyboard.set_app_shortcut("Preview", "File > Export…", "cmd+e")      # the one in the File menu
        macos.keyboard.set_app_shortcut(None, "Show Tab Bar", "cmd+option+t")     # in every app
        macos.keyboard.set_app_shortcut("Safari", "Export as PDF…", None)         # remove it

    ``app`` is a name, bundle ID or path, as for :func:`macos.apps.open`, or
    ``None`` for every app. ``menu_item`` is the title exactly as the menu
    shows it, in the system's language, the ellipsis (…) included; write
    ``"Menu > Item"`` when several menus have an item with that title.
    ``keys`` is written as for :func:`press`. Apps pick it up when they're
    reopened.
    """
    from . import defaults

    if not menu_item.strip():
        raise ValueError("menu_item must not be empty")
    domain = _shortcut_domain(app)
    title = _menu_title(menu_item)
    found = dict(defaults.read(domain, "NSUserKeyEquivalents", default={}) or {})
    if keys is None:
        if found.pop(title, None) is None:
            return
    else:
        found[title] = _encode_shortcut(keys)
    if found:
        defaults.write(domain, "NSUserKeyEquivalents", found)
    else:
        defaults.delete(domain, "NSUserKeyEquivalents")


# --- macOS's own shortcuts ---------------------------------------------------

# Name: (its number in AppleSymbolicHotKeys, its default keys: character, key code, modifier flags).
_SYSTEM_SHORTCUTS = {
    "spotlight": (64, [65535, 49, 1048576]),
    "finder_search": (65, [65535, 49, 1572864]),
    "previous_input_source": (60, [32, 49, 262144]),
    "next_input_source": (61, [32, 49, 786432]),
    "screenshot": (28, [51, 20, 1179648]),
    "screenshot_to_clipboard": (29, [51, 20, 1441792]),
    "screenshot_area": (30, [52, 21, 1179648]),
    "screenshot_area_to_clipboard": (31, [52, 21, 1441792]),
    "screenshot_toolbar": (184, [53, 23, 1179648]),
    "mission_control": (32, [65535, 126, 262144]),
    "application_windows": (33, [65535, 125, 262144]),
    "show_desktop": (36, [65535, 103, 0]),
    "move_left_a_space": (79, [65535, 123, 262144]),
    "move_right_a_space": (81, [65535, 124, 262144]),
    "dock_hiding": (52, [100, 2, 1572864]),
}
SYSTEM_SHORTCUTS = tuple(_SYSTEM_SHORTCUTS)
"""The macOS shortcuts :func:`set_system_shortcut` turns on and off, such as ``"spotlight"`` (⌘Space)."""


def _hotkeys() -> Dict[str, Any]:
    from . import defaults

    return dict(defaults.read("com.apple.symbolichotkeys", "AppleSymbolicHotKeys", default={}) or {})


def system_shortcuts() -> Dict[str, bool]:
    """Which of macOS's shortcuts are on: ``{"spotlight": True, "screenshot": True, ...}``."""
    found = _hotkeys()
    return {name: bool(found.get(str(number), {}).get("enabled", True)) for name, (number, _) in _SYSTEM_SHORTCUTS.items()}


def set_system_shortcut(name: str, on: bool) -> None:
    """
    Turn one of macOS's shortcuts on or off, like System Settings › Keyboard › Keyboard Shortcuts.

    ::

        macos.keyboard.set_system_shortcut("spotlight", False)   # free ⌘Space for Raycast or Alfred

    ``name`` is one of :data:`SYSTEM_SHORTCUTS`. The keys stay as they
    were: only the shortcut is turned on or off. Applies at once.
    """
    from . import defaults
    from ._system import apply_input_settings

    if name not in _SYSTEM_SHORTCUTS:
        raise ValueError("name must be one of {}, not {!r}".format(", ".join(SYSTEM_SHORTCUTS), name))
    number, keys = _SYSTEM_SHORTCUTS[name]
    found = _hotkeys()
    entry = dict(found.get(str(number), {}))
    # Without its keys, a shortcut turned back on may not work: keep them, or write the defaults.
    entry.setdefault("value", {"parameters": list(keys), "type": "standard"})
    entry["enabled"] = bool(on)
    found[str(number)] = entry
    defaults.write("com.apple.symbolichotkeys", "AppleSymbolicHotKeys", found)
    apply_input_settings()


# --- The backlight's timeout -------------------------------------------------


def backlight_timeout() -> Optional[float]:
    """Seconds without use before the keyboard backlight turns off; ``None`` when it stays on."""
    with _objc.autorelease_pool():
        client, keyboard = _backlight()
        seconds = _objc.send(client, "idleDimTimeForKeyboard:", keyboard, argtypes=(ctypes.c_uint64,), restype=ctypes.c_double)
    return float(seconds) if seconds > 0 else None


def set_backlight_timeout(seconds: Optional[float]) -> None:
    """
    Turn the keyboard backlight off after ``seconds`` without use, or never (``None``).

    System Settings › Keyboard offers 5, 10 and 30 seconds, 1 and 5
    minutes; other durations work too. Raises
    :class:`~macos.errors.NotSupportedError` on a Mac without a backlit keyboard.
    """
    if seconds is not None and seconds <= 0:
        raise ValueError("seconds must be positive, or None for never, not {}".format(seconds))
    with _objc.autorelease_pool():
        client, keyboard = _backlight()
        ok = _objc.send(
            client,
            "setIdleDimTime:forKeyboard:",
            float(seconds or 0),
            keyboard,
            argtypes=(ctypes.c_double, ctypes.c_uint64),
            restype=_objc.BOOL,
        )
    if not ok:
        raise MacOSError("macOS refused to change the keyboard backlight's timeout")
