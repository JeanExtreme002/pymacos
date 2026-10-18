# -*- coding: utf-8 -*-

"""
Configure the trackpad: tap to click, the scroll direction and the pointer speed.

::

    macos.trackpad.set_tap_to_click(True)
    macos.trackpad.set_natural_scrolling(False)
    macos.trackpad.set_tracking_speed(0.7)

No permission is needed. Most settings apply at once, as in System
Settings; the pointer speed waits for the next login.
"""

from typing import Dict, Optional, Union

from . import defaults
from ._system import apply_input_settings

__all__ = [
    "tap_to_click",
    "set_tap_to_click",
    "natural_scrolling",
    "set_natural_scrolling",
    "tracking_speed",
    "set_tracking_speed",
    "three_finger_drag",
    "set_three_finger_drag",
    "secondary_click",
    "set_secondary_click",
    "click_pressure",
    "set_click_pressure",
    "GESTURES",
    "gestures",
    "set_gesture",
]

# The built-in trackpad and Bluetooth ones (Magic Trackpad) keep their own copy.
_TRACKPADS = ("com.apple.AppleMultitouchTrackpad", "com.apple.driver.AppleBluetoothMultitouch.trackpad")
_SPEED_MAX = 3.0  # the slider's range in System Settings goes up to 3


def _is_on(domain: str, key: str, default: bool) -> bool:
    """A yes-or-no preference as macOS reads it: one written by hand as ``NO`` or ``0`` is off."""
    return defaults._as_bool(defaults.read(domain, key, default=default), default)


def tap_to_click() -> bool:
    """Whether a tap on the trackpad clicks, without pressing it."""
    return _is_on(_TRACKPADS[0], "Clicking", False)


def set_tap_to_click(on: bool = True) -> None:
    """Click with a tap on the trackpad, or only by pressing it (``False``)."""
    for domain in _TRACKPADS:
        defaults.write(domain, "Clicking", bool(on))
    for current_host in (False, True):
        defaults.write(defaults.GLOBAL, "com.apple.mouse.tapBehavior", 1 if on else 0, current_host=current_host)
    apply_input_settings()


def natural_scrolling() -> bool:
    """Whether content follows the fingers ("natural" scrolling, the default), for the trackpad and mice."""
    return _is_on(defaults.GLOBAL, "com.apple.swipescrolldirection", True)


def set_natural_scrolling(on: bool = True) -> None:
    """Scroll the "natural" way, or the classic way (``False``), for the trackpad and mice alike."""
    defaults.write(defaults.GLOBAL, "com.apple.swipescrolldirection", bool(on))
    apply_input_settings()


def tracking_speed() -> float:
    """
    The pointer speed with the trackpad, from 0.0 (slowest) to 1.0 (fastest).

    A speed set by hand past the slider's ends (``defaults write -g
    com.apple.trackpad.scaling 5``, or ``-1``) reads as 1.0 or 0.0, so it can
    be passed back to :func:`set_tracking_speed`.
    """
    scaling = defaults._as_float(defaults.read(defaults.GLOBAL, "com.apple.trackpad.scaling", default=1.0), 1.0)
    return round(min(max(scaling / _SPEED_MAX, 0.0), 1.0), 3)


def set_tracking_speed(speed: float) -> None:
    """
    Set the pointer speed with the trackpad, from 0.0 to 1.0, like the slider in System Settings.

    Takes effect at the next login.
    """
    if not 0.0 <= speed <= 1.0:
        raise ValueError("speed must be from 0.0 to 1.0, not {}".format(speed))
    defaults.write(defaults.GLOBAL, "com.apple.trackpad.scaling", round(speed * _SPEED_MAX, 3))
    apply_input_settings()


def three_finger_drag() -> bool:
    """Whether dragging with three fingers moves windows and selects text, without pressing."""
    return _is_on(_TRACKPADS[0], "TrackpadThreeFingerDrag", False)


def set_three_finger_drag(on: bool = True) -> None:
    """
    Drag with three fingers, without pressing the trackpad, or not.

    Swipes with three fingers (between spaces, to Mission Control) then
    clash with it: set them to four fingers in System Settings › Trackpad ›
    More Gestures.
    """
    _write("TrackpadThreeFingerDrag", bool(on))
    apply_input_settings()


# How: (TrackpadRightClick, TrackpadCornerSecondaryClick).
_SECONDARY_CLICKS = {"two_fingers": (True, 0), "bottom_right": (False, 2), "bottom_left": (False, 1), None: (False, 0)}


def secondary_click() -> Optional[str]:
    """
    How the trackpad right-clicks: ``'two_fingers'``, ``'bottom_right'`` or ``'bottom_left'`` (a corner), or ``None``.
    """
    if _is_on(_TRACKPADS[0], "TrackpadRightClick", True):
        return "two_fingers"
    corner = defaults._as_int(defaults.read(_TRACKPADS[0], "TrackpadCornerSecondaryClick", default=0), 0)
    return {1: "bottom_left", 2: "bottom_right"}.get(corner)


def set_secondary_click(how: Optional[str]) -> None:
    """
    Right-click with two fingers (``"two_fingers"``), in a corner (``"bottom_right"``, ``"bottom_left"``), or not (``None``).
    """
    if how not in _SECONDARY_CLICKS:
        raise ValueError("how must be 'two_fingers', 'bottom_right', 'bottom_left' or None, not {!r}".format(how))
    two_fingers, corner = _SECONDARY_CLICKS[how]
    _write("TrackpadRightClick", two_fingers)
    _write("TrackpadCornerSecondaryClick", corner)
    apply_input_settings()


# System Settings also keeps a copy of some trackpad settings for this Mac only, in the global domain.
_HOST_COPIES = {
    "Clicking": None,  # tap to click keeps com.apple.mouse.tapBehavior instead
    "TrackpadThreeFingerDrag": "com.apple.trackpad.threeFingerDragGesture",
    "TrackpadRightClick": "com.apple.trackpad.enableSecondaryClick",
    "TrackpadPinch": "com.apple.trackpad.pinchGesture",
    "TrackpadRotate": "com.apple.trackpad.rotateGesture",
    "TrackpadTwoFingerDoubleTapGesture": "com.apple.trackpad.twoFingerDoubleTapGesture",
    "TrackpadTwoFingerFromRightEdgeSwipeGesture": "com.apple.trackpad.twoFingerFromRightEdgeSwipeGesture",
    "TrackpadThreeFingerHorizSwipeGesture": "com.apple.trackpad.threeFingerHorizSwipeGesture",
    "TrackpadFourFingerHorizSwipeGesture": "com.apple.trackpad.fourFingerHorizSwipeGesture",
    "TrackpadThreeFingerVertSwipeGesture": "com.apple.trackpad.threeFingerVertSwipeGesture",
    "TrackpadFourFingerVertSwipeGesture": "com.apple.trackpad.fourFingerVertSwipeGesture",
    "TrackpadFourFingerPinchGesture": "com.apple.trackpad.fourFingerPinchSwipeGesture",
    "TrackpadFiveFingerPinchGesture": "com.apple.trackpad.fiveFingerPinchSwipeGesture",
}


def _write(key: str, value: object) -> None:
    """Write a trackpad setting where System Settings does: for both trackpads, and this Mac's copy."""
    for domain in _TRACKPADS:
        defaults.write(domain, key, value)
    copy = _HOST_COPIES.get(key)
    if copy:
        defaults.write(defaults.GLOBAL, copy, int(value) if isinstance(value, bool) else value, current_host=True)


def _read(key: str, default: object) -> object:
    return defaults.read(_TRACKPADS[0], key, default=default)


# How firmly a click must press: FirstClickThreshold and SecondClickThreshold's values.
_PRESSURES = ("light", "medium", "firm")


def click_pressure() -> str:
    """How firmly the trackpad must be pressed to click: ``'light'``, ``'medium'`` or ``'firm'``."""
    found = defaults._as_int(_read("FirstClickThreshold", 1), 1)
    return _PRESSURES[found] if 0 <= found < len(_PRESSURES) else "medium"


def set_click_pressure(pressure: str) -> None:
    """Make a click need a ``"light"``, ``"medium"`` or ``"firm"`` press, like the Click slider in System Settings."""
    if pressure not in _PRESSURES:
        raise ValueError("pressure must be 'light', 'medium' or 'firm', not {!r}".format(pressure))
    for key in ("FirstClickThreshold", "SecondClickThreshold"):
        _write(key, _PRESSURES.index(pressure))
    apply_input_settings()


# --- Gestures ---------------------------------------------------------------

# Gestures that are on or off: name -> (key, value when on).
_SWITCHES = {
    "pinch_to_zoom": ("TrackpadPinch", True),
    "rotate": ("TrackpadRotate", True),
    "smart_zoom": ("TrackpadTwoFingerDoubleTapGesture", 1),
    "notification_center": ("TrackpadTwoFingerFromRightEdgeSwipeGesture", 3),
}
# Gestures made with three or four fingers: name -> (three fingers' key, four fingers' key, the Dock's switch).
_SWIPES = {
    "swipe_between_full_screen_apps": ("TrackpadThreeFingerHorizSwipeGesture", "TrackpadFourFingerHorizSwipeGesture", None),
    "mission_control": (
        "TrackpadThreeFingerVertSwipeGesture",
        "TrackpadFourFingerVertSwipeGesture",
        "showMissionControlGestureEnabled",
    ),
}
# Gestures the Dock performs, on the swipes and pinches above: name -> its switch.
_DOCK_GESTURES = {
    "app_expose": "showAppExposeGestureEnabled",
    "launchpad": "showLaunchpadGestureEnabled",
    "show_desktop": "showDesktopGestureEnabled",
}
_PINCHES = ("TrackpadFourFingerPinchGesture", "TrackpadFiveFingerPinchGesture")  # Launchpad's and Show Desktop's
_GESTURE = 2  # the value that turns a swipe or pinch into a system gesture
GESTURES = ("swipe_between_pages", *_SWITCHES, *_SWIPES, *_DOCK_GESTURES)
"""The gestures :func:`set_gesture` turns on and off."""


def gestures() -> Dict[str, Union[bool, int]]:
    """
    Which trackpad gestures are on, like System Settings › Trackpad › Scroll & Zoom and More Gestures.

    ``{"pinch_to_zoom": True, "mission_control": 3, "launchpad": False, ...}``:
    gestures made with three or four fingers give the number of fingers,
    or ``False`` when they're off.
    """
    found: Dict[str, Union[bool, int]] = {
        "swipe_between_pages": _is_on(defaults.GLOBAL, "AppleEnableSwipeNavigateWithScrolls", True),
    }
    for name, (key, on) in _SWITCHES.items():
        found[name] = _is_on(_TRACKPADS[0], key, bool(on))  # off is False or 0
    for name, (three, four, dock_switch) in _SWIPES.items():
        if dock_switch and not _is_on("com.apple.dock", dock_switch, True):
            found[name] = False
        elif _read(three, _GESTURE) == _GESTURE:
            found[name] = 3
        elif _read(four, 0) == _GESTURE:
            found[name] = 4
        else:
            found[name] = False
    for name, dock_switch in _DOCK_GESTURES.items():
        found[name] = _is_on("com.apple.dock", dock_switch, True)
    if not _vertical_swipe():
        found["app_expose"] = False  # it swipes down on Mission Control's swipe
    return found


def _vertical_swipe() -> bool:
    """Whether a swipe up or down with three or four fingers is a system gesture, for Mission Control and App Exposé."""
    three, four, _ = _SWIPES["mission_control"]
    return _read(three, _GESTURE) == _GESTURE or _read(four, 0) == _GESTURE


def set_gesture(name: str, on: Union[bool, int]) -> None:
    """
    Turn a trackpad gesture on or off.

    ::

        macos.trackpad.set_gesture("pinch_to_zoom", False)
        macos.trackpad.set_gesture("mission_control", 4)   # swipe up with four fingers
        macos.trackpad.set_gesture("launchpad", True)

    ``name`` is one of :data:`GESTURES`. ``"swipe_between_full_screen_apps"``
    and ``"mission_control"`` take the number of fingers, ``3`` or ``4``
    (``True`` is 3), freeing the other number for three-finger drag, say.
    App Exposé swipes down with as many fingers as Mission Control swipes
    up, as in System Settings: moving one moves the other, and the swipe
    stays while either is on. Putting the full-screen apps on three fingers
    takes three fingers from "swipe between pages"; putting them elsewhere
    leaves a three-finger page swipe alone.
    Changes to the Dock's gestures (Mission Control, App Exposé, Launchpad,
    Show Desktop) restart the Dock.
    """
    from . import dock

    if name not in GESTURES:
        raise ValueError("name must be one of {}, not {!r}".format(", ".join(GESTURES), name))
    if name in _SWIPES:
        fingers = 3 if on is True else (on or 0)
        if fingers not in (0, 3, 4):
            raise ValueError("{} takes 3 or 4 fingers, True or False, not {!r}".format(name, on))
    elif not isinstance(on, bool):
        raise ValueError("{} is on or off: pass True or False, not {!r}".format(name, on))

    restart_dock = False
    if name == "swipe_between_pages":
        defaults.write(defaults.GLOBAL, "AppleEnableSwipeNavigateWithScrolls", bool(on))
    elif name in _SWITCHES:
        key, value = _SWITCHES[name]
        _write(key, value if on else (False if isinstance(value, bool) else 0))
    elif name in _SWIPES:
        three, four, dock_switch = _SWIPES[name]
        if fingers or not dock_switch or not _is_on("com.apple.dock", _DOCK_GESTURES["app_expose"], True):
            # As System Settings writes it: three fingers turns on the four-finger swipe too. The
            # horizontal three-finger key's 1 is "swipe between pages" with three fingers: keep it (unset is 2).
            if fingers == 3 or dock_switch or _read(three, _GESTURE) == _GESTURE:
                _write(three, _GESTURE if fingers == 3 else 0)
            _write(four, _GESTURE if fingers else 0)
        # else Mission Control is off but App Exposé is on: keep their swipe, and only turn off the Dock's switch.
        if dock_switch:
            defaults.write("com.apple.dock", dock_switch, bool(fingers))
            restart_dock = True
    else:
        defaults.write("com.apple.dock", _DOCK_GESTURES[name], bool(on))
        if name == "app_expose":
            # It swipes down on Mission Control's swipe: give it one (three fingers) if there is none, and
            # drop it when Mission Control is off too.
            three, four, _ = _SWIPES["mission_control"]
            if on and not _vertical_swipe():
                _write(three, _GESTURE)
                _write(four, _GESTURE)
            elif not on and not _is_on("com.apple.dock", "showMissionControlGestureEnabled", True):
                _write(three, 0)
                _write(four, 0)
        elif name in ("launchpad", "show_desktop"):
            # Both are a pinch with the thumb and three fingers: keep it while either is on.
            other = _DOCK_GESTURES["show_desktop" if name == "launchpad" else "launchpad"]
            pinch = bool(on) or _is_on("com.apple.dock", other, True)
            for key in _PINCHES:
                _write(key, _GESTURE if pinch else 0)
        restart_dock = True
    apply_input_settings()
    if restart_dock:
        dock.restart()
