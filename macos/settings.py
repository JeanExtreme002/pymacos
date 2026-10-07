# -*- coding: utf-8 -*-

"""
Save this Mac's settings to a file and apply them to another Mac: dotfiles for macOS.

::

    import json

    json.dump(macos.settings.export(), open("my-mac.json", "w"), indent=2)
    # on the new Mac:
    macos.settings.apply(json.load(open("my-mac.json")))

It covers the keyboard, trackpad, mouse, Dock, Finder, windows, appearance,
screenshots, sounds and system settings this package reads and changes;
the file is plain JSON, to keep in a repository and edit by hand.
"""

import inspect
import math
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Tuple

from . import appearance, dock, finder, keyboard, mouse, screen, sound, system, trackpad, windows
from ._system import add_note, batched_restarts, require_macos
from .errors import NotSupportedError

__all__ = ["export", "apply", "names"]


def _anything(value: Any) -> None:
    """No check of its own: the setter's is enough (the tests' fake settings)."""


class _Setting(NamedTuple):
    read: Callable[[], Any]
    change: Callable[[Any], None]
    check: Callable[[Any], None] = _anything
    """Raises :class:`ValueError` for a value ``change`` would refuse, without changing anything."""


# --- Checking values before anything changes ----------------------------------
#
# apply() runs every check before the first change, so a typo in the tenth
# setting of a file doesn't leave the first nine changed and the rest not.
# Each check mirrors what its setter refuses (a range, a set of names, a
# shape); a setter that still fails midway (a permission, a missing sound
# file) is caught by apply()'s rollback instead.


def _flag(value: Any) -> None:
    # The setters take any truthy value; a hand-edited file may say 1 or 0.
    if not isinstance(value, bool) and value not in (0, 1):
        raise ValueError("must be true or false, not {!r}".format(value))


def _number(
    low: Optional[float] = None,
    high: Optional[float] = None,
    *,
    above: Optional[float] = None,
    optional: bool = False,
    whole: bool = False,
) -> Callable[[Any], None]:
    """A number from ``low`` to ``high``, or greater than ``above``; ``None`` too when ``optional``."""

    def check(value: Any) -> None:
        if value is None and optional:
            return
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        if not valid or (whole and not isinstance(value, int)):
            kind = "a whole number" if whole else "a number"
            raise ValueError("must be {}{}, not {!r}".format(kind, " or null" if optional else "", value))
        number = float(value)
        if (low is not None and number < low) or (high is not None and number > high) or (above is not None and number <= above):
            if above is not None:
                limits = "greater than {}".format(above)
            elif high is None:
                limits = "at least {}".format(low)
            else:
                limits = "from {} to {}".format(low, high)
            raise ValueError("must be {}, not {!r}".format(limits, value))

    return check


def _choice(options: Iterable[Optional[str]], *, optional: bool = False) -> Callable[[Any], None]:
    allowed = [option for option in options if option is not None]

    def check(value: Any) -> None:
        if value is None and optional:
            return
        if value not in allowed:
            names = ", ".join(repr(option) for option in allowed)
            raise ValueError("must be {}{}, not {!r}".format(names, " or null" if optional else "", value))

    return check


def _text(*, optional: bool = False) -> Callable[[Any], None]:
    def check(value: Any) -> None:
        if value is None and optional:
            return
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be {}text, not {!r}".format("null or " if optional else "", value))

    return check


def _entries(
    keys: Optional[Iterable[str]], check_value: Callable[[str, Any], None], *, at_least_one: bool = False
) -> Callable[[Any], None]:
    """A dict whose keys are among ``keys`` (any text when ``None``), each value checked by ``check_value(key, value)``."""
    allowed = None if keys is None else list(keys)

    def check(value: Any) -> None:
        if not isinstance(value, Mapping):
            raise ValueError("must be an object of names and values, not {!r}".format(value))
        if at_least_one and not value:
            raise ValueError("must name at least one entry")
        for key, item in value.items():
            if not isinstance(key, str) or (allowed is not None and key not in allowed):
                raise ValueError("{!r} isn't one of {}".format(key, ", ".join(allowed or [])))
            try:
                check_value(key, item)
            except ValueError as error:
                raise ValueError("{}: {}".format(key, error)) from None

    return check


def _options(setter: Callable[..., None], **checks: Callable[[Any], None]) -> Callable[[Any], None]:
    """A dict of a keyword-only setter's options, such as ``finder.set_desktop_view``'s, checked one by one."""
    parameters = inspect.signature(setter).parameters.items()
    names = [name for name, parameter in parameters if parameter.kind is inspect.Parameter.KEYWORD_ONLY]
    return _entries(names, lambda name, value: checks.get(name, _anything)(value), at_least_one=True)


def _key_repeat(value: Any) -> None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("must be [interval, delay], not {!r}".format(value))
    for part in value:
        _number(above=0, optional=True)(part)
    if value[0] is None and value[1] is None:
        raise ValueError("needs an interval, a delay, or both")


def _remap_code(key: Any) -> int:
    """A key named for :func:`keyboard.remap`, or one :func:`keyboard.remappings` could only give as hex (``'0x7000000e0'``)."""
    if isinstance(key, str) and key.lower().startswith("0x"):
        try:
            return int(key, 16)
        except ValueError:
            pass
    if not isinstance(key, str):
        raise ValueError("keys are named, such as 'caps_lock', not {!r}".format(key))
    return keyboard._hid_code(key)


def _remappings(remappings: Mapping[str, Optional[str]]) -> Dict[int, int]:
    """The remappings as hidutil codes; raises before any is changed when one key is unknown."""
    if not isinstance(remappings, Mapping):
        raise ValueError("must be an object such as {{\"caps_lock\": \"escape\"}}, not {!r}".format(remappings))
    codes = {}
    for key, target in remappings.items():
        source = _remap_code(key)
        if target is not None:  # None: the key acts as itself
            codes[source] = _remap_code(target)
    return codes


def _check_remappings(remappings: Any) -> None:
    _remappings(remappings)  # converting them all is the check


def _gesture(name: str, value: Any) -> None:
    if name in trackpad._SWIPES:
        if not isinstance(value, bool) and value not in (0, 3, 4):
            raise ValueError("takes 3 or 4 fingers, true or false, not {!r}".format(value))
    elif not isinstance(value, bool):
        raise ValueError("must be true or false, not {!r}".format(value))


def _hot_corner(corner: str, wanted: Any) -> None:
    if not isinstance(wanted, Mapping):
        raise ValueError("must be {{\"action\": ..., \"modifier\": ...}}, not {!r}".format(wanted))
    _choice(dock.HOT_CORNER_ACTIONS, optional=True)(wanted.get("action"))
    modifier = wanted.get("modifier")
    if modifier is not None and not isinstance(modifier, str):
        raise ValueError("modifier must be text such as 'cmd+shift', not {!r}".format(modifier))
    dock._corner_flags(modifier)


def _night_shift(schedule: Any) -> None:
    if schedule is None or schedule == "sunset":
        return
    if isinstance(schedule, str) or not isinstance(schedule, (list, tuple)) or len(schedule) != 2:
        raise ValueError("must be null, 'sunset' or [start, end], not {!r}".format(schedule))
    for moment in schedule:
        screen._clock_time(moment)


def _screenshot_format(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("must be text such as 'png', not {!r}".format(value))
    wanted = value.lower().lstrip(".")
    _choice(screen._SETTING_FORMATS)("jpg" if wanted == "jpeg" else wanted)


def _screenshot_name(name: Any) -> None:
    _text(optional=True)(name)
    if name is not None and ("/" in name or ":" in name):
        raise ValueError("must be a file name, without / or :, not {!r}".format(name))


def _alert_sound(name: Any) -> None:
    _text(optional=True)(name)
    if name is not None and name not in sound.names():
        raise ValueError("no alert sound is named {!r}; see macos.sound.names()".format(name))


def _each(change: Callable[..., None]) -> Callable[[Mapping[str, Any]], None]:
    """A setter for a dict of settings, called once per entry: ``change(name, value)``."""

    def apply_all(values: Mapping[str, Any]) -> None:
        for name, value in values.items():
            change(name, value)

    return apply_all


def _hot_corners() -> Dict[str, Dict[str, Optional[str]]]:
    modifiers = dock.hot_corner_modifiers()
    return {corner: {"action": action, "modifier": modifiers[corner]} for corner, action in dock.hot_corners().items()}


def _set_hot_corners(corners: Mapping[str, Mapping[str, Optional[str]]]) -> None:
    for corner, wanted in corners.items():
        dock.set_hot_corner(corner, wanted.get("action"), modifier=wanted.get("modifier"))


def _set_remappings(remappings: Mapping[str, Optional[str]]) -> None:
    # Build the whole new list first, then swap it in with one hidutil call:
    # clearing and re-adding one by one would leave the keyboard with no
    # remapping at all if a key further down the list were unknown.
    keyboard._set_mappings(_remappings(remappings))


def _night_shift_schedule() -> Any:
    found = screen.night_shift_schedule()
    if isinstance(found, tuple):
        return [moment.strftime("%H:%M") for moment in found]
    return found


def _portable(folder: Path) -> str:
    """A folder under the home folder as ``~/...``, so it works on a Mac with another user name."""
    home = Path.home()
    try:
        return os.path.join("~", str(folder.relative_to(home))) if folder != home else "~"
    except ValueError:
        return str(folder)


def _set_night_shift_schedule(schedule: Any) -> None:
    screen.set_night_shift_schedule(tuple(schedule) if isinstance(schedule, list) else schedule)


# Section -> name -> how to read and change it, with JSON values.
_SETTINGS: Dict[str, Dict[str, _Setting]] = {
    "keyboard": {
        "key_repeat": _Setting(
            lambda: list(keyboard.key_repeat()), lambda value: keyboard.set_key_repeat(value[0], delay=value[1])
        ),
        "press_and_hold": _Setting(keyboard.press_and_hold, keyboard.set_press_and_hold),
        "standard_function_keys": _Setting(keyboard.standard_function_keys, keyboard.set_standard_function_keys),
        "fn_key_action": _Setting(keyboard.fn_key_action, keyboard.set_fn_key_action),
        "autocorrect": _Setting(keyboard.autocorrect, keyboard.set_autocorrect),
        "smart_quotes": _Setting(keyboard.smart_quotes, keyboard.set_smart_quotes),
        "smart_dashes": _Setting(keyboard.smart_dashes, keyboard.set_smart_dashes),
        "auto_capitalization": _Setting(keyboard.auto_capitalization, keyboard.set_auto_capitalization),
        "double_space_period": _Setting(keyboard.double_space_period, keyboard.set_double_space_period),
        "inline_predictions": _Setting(keyboard.inline_predictions, keyboard.set_inline_predictions),
        "full_keyboard_access": _Setting(keyboard.full_keyboard_access, keyboard.set_full_keyboard_access),
        "system_shortcuts": _Setting(keyboard.system_shortcuts, _each(keyboard.set_system_shortcut)),
        "remappings": _Setting(keyboard.remappings, _set_remappings),
        "backlight_timeout": _Setting(keyboard.backlight_timeout, keyboard.set_backlight_timeout),
    },
    "trackpad": {
        "tap_to_click": _Setting(trackpad.tap_to_click, trackpad.set_tap_to_click),
        "natural_scrolling": _Setting(trackpad.natural_scrolling, trackpad.set_natural_scrolling),
        "tracking_speed": _Setting(trackpad.tracking_speed, trackpad.set_tracking_speed),
        "click_pressure": _Setting(trackpad.click_pressure, trackpad.set_click_pressure),
        "secondary_click": _Setting(trackpad.secondary_click, trackpad.set_secondary_click),
        "three_finger_drag": _Setting(trackpad.three_finger_drag, trackpad.set_three_finger_drag),
        "gestures": _Setting(trackpad.gestures, _each(trackpad.set_gesture)),
    },
    "mouse": {
        "tracking_speed": _Setting(mouse.tracking_speed, mouse.set_tracking_speed),
        "acceleration": _Setting(mouse.acceleration, mouse.set_acceleration),
        "scroll_speed": _Setting(mouse.scroll_speed, mouse.set_scroll_speed),
        "double_click_speed": _Setting(mouse.double_click_speed, mouse.set_double_click_speed),
    },
    "dock": {
        "autohide": _Setting(dock.autohide, dock.set_autohide),
        "autohide_delay": _Setting(dock.autohide_delay, dock.set_autohide_delay),
        "autohide_duration": _Setting(dock.autohide_duration, dock.set_autohide_duration),
        "size": _Setting(dock.size, dock.set_size),
        "position": _Setting(dock.position, dock.set_position),
        "magnification": _Setting(dock.magnification, dock.set_magnification),
        "minimize_effect": _Setting(dock.minimize_effect, dock.set_minimize_effect),
        "minimize_to_app": _Setting(dock.minimize_to_app, dock.set_minimize_to_app),
        "show_recents": _Setting(dock.show_recents, dock.set_show_recents),
        "show_indicators": _Setting(dock.show_indicators, dock.set_show_indicators),
        "dim_hidden_apps": _Setting(dock.dim_hidden_apps, dock.set_dim_hidden_apps),
        "only_open_apps": _Setting(dock.only_open_apps, dock.set_only_open_apps),
        "launch_animation": _Setting(dock.launch_animation, dock.set_launch_animation),
        "hot_corners": _Setting(_hot_corners, _set_hot_corners),
        "group_windows_by_app": _Setting(dock.group_windows_by_app, dock.set_group_windows_by_app),
        "switch_to_space_with_app": _Setting(dock.switch_to_space_with_app, dock.set_switch_to_space_with_app),
        "auto_rearrange_spaces": _Setting(dock.auto_rearrange_spaces, dock.set_auto_rearrange_spaces),
        "separate_spaces_per_display": _Setting(dock.separate_spaces_per_display, dock.set_separate_spaces_per_display),
    },
    "finder": {
        "show_hidden_files": _Setting(finder.show_hidden_files, finder.set_show_hidden_files),
        "show_extensions": _Setting(finder.show_extensions, finder.set_show_extensions),
        "show_path_bar": _Setting(finder.show_path_bar, finder.set_show_path_bar),
        "show_status_bar": _Setting(finder.show_status_bar, finder.set_show_status_bar),
        "show_full_path_in_title": _Setting(finder.show_full_path_in_title, finder.set_show_full_path_in_title),
        "show_library_folder": _Setting(finder.show_library_folder, finder.set_show_library_folder),
        "show_desktop_icons": _Setting(finder.show_desktop_icons, finder.set_show_desktop_icons),
        "default_view": _Setting(finder.default_view, finder.set_default_view),
        "new_window_folder": _Setting(lambda: _portable(finder.new_window_folder()), finder.set_new_window_folder),
        "search_scope": _Setting(finder.search_scope, finder.set_search_scope),
        "folders_first": _Setting(finder.folders_first, finder.set_folders_first),
        "extension_change_warning": _Setting(finder.extension_change_warning, finder.set_extension_change_warning),
        "remove_old_trash_items": _Setting(finder.remove_old_trash_items, finder.set_remove_old_trash_items),
        "quit_menu": _Setting(finder.quit_menu, finder.set_quit_menu),
        "drives_on_desktop": _Setting(finder.drives_on_desktop, lambda value: finder.set_show_drives_on_desktop(**value)),
        "desktop_view": _Setting(finder.desktop_view, lambda value: finder.set_desktop_view(**value)),
    },
    "windows": {
        "double_click_title_bar": _Setting(windows.double_click_title_bar, windows.set_double_click_title_bar),
        "tiling": _Setting(windows.tiling, windows.set_tiling),
        "click_wallpaper_to_show_desktop": _Setting(
            windows.click_wallpaper_to_show_desktop, windows.set_click_wallpaper_to_show_desktop
        ),
        "animations": _Setting(windows.animations, windows.set_animations),
    },
    "appearance": {
        "auto_mode": _Setting(appearance.is_auto, appearance.set_auto_mode),
        "hide_menu_bar": _Setting(appearance.menu_bar_hidden, appearance.set_hide_menu_bar),
        "scroll_bars": _Setting(appearance.scroll_bars, appearance.set_scroll_bars),
        "font_smoothing": _Setting(appearance.font_smoothing, appearance.set_font_smoothing),
    },
    "screen": {
        "screenshot_folder": _Setting(lambda: _portable(screen.screenshot_folder()), screen.set_screenshot_folder),
        "screenshot_format": _Setting(screen.screenshot_format, screen.set_screenshot_format),
        "screenshot_name": _Setting(screen.screenshot_name, screen.set_screenshot_name),
        "screenshot_target": _Setting(screen.screenshot_target, screen.set_screenshot_target),
        "screenshot_shadow": _Setting(screen.screenshot_shadow, screen.set_screenshot_shadow),
        "screenshot_thumbnail": _Setting(screen.screenshot_thumbnail, screen.set_screenshot_thumbnail),
        "screensaver_delay": _Setting(screen.screensaver_delay, screen.set_screensaver_delay),
        "night_shift_schedule": _Setting(_night_shift_schedule, _set_night_shift_schedule),
        "night_shift_strength": _Setting(screen.night_shift_strength, screen.set_night_shift_strength),
    },
    "sound": {
        "alert_sound": _Setting(sound.alert_sound, sound.set_alert_sound),
        "alert_volume": _Setting(sound.alert_volume, sound.set_alert_volume),
        "ui_sounds": _Setting(sound.ui_sounds, sound.set_ui_sounds),
    },
    "system": {
        "clock_format": _Setting(system.clock_format, lambda value: system.set_clock_format(**value)),
        "menu_bar_items": _Setting(system.menu_bar_items, lambda value: system.set_menu_bar_items(**value)),
        "menu_bar_spacing": _Setting(system.menu_bar_spacing, system.set_menu_bar_spacing),
        "battery_percentage": _Setting(system.battery_percentage_shown, system.set_show_battery_percentage),
        "measurement_units": _Setting(system.measurement_units, system.set_measurement_units),
        "temperature_unit": _Setting(system.temperature_unit, system.set_temperature_unit),
        "keep_windows_on_quit": _Setting(system.keep_windows_on_quit, system.set_keep_windows_on_quit),
        "save_to_icloud_by_default": _Setting(system.save_to_icloud_by_default, system.set_save_to_icloud_by_default),
        "expanded_save_dialog": _Setting(system.expanded_save_dialog, system.set_expanded_save_dialog),
        "ds_store_on_network": _Setting(system.ds_store_on_network, system.set_ds_store_on_network),
        "ds_store_on_usb": _Setting(system.ds_store_on_usb, system.set_ds_store_on_usb),
        "open_photos_on_device_connect": _Setting(
            system.open_photos_on_device_connect, system.set_open_photos_on_device_connect
        ),
    },
}


# The check of each setting that isn't a plain on/off flag.
_CHECKS: Dict[str, Dict[str, Callable[[Any], None]]] = {
    "keyboard": {
        "key_repeat": _key_repeat,
        "fn_key_action": _choice(("emoji", "input_source", "dictation"), optional=True),
        "system_shortcuts": _entries(keyboard.SYSTEM_SHORTCUTS, lambda name, on: _flag(on)),
        "remappings": _check_remappings,
        "backlight_timeout": _number(above=0, optional=True),
    },
    "trackpad": {
        "tracking_speed": _number(0, 1),
        "click_pressure": _choice(("light", "medium", "firm")),
        "secondary_click": _choice(("two_fingers", "bottom_right", "bottom_left"), optional=True),
        "gestures": _entries(trackpad.GESTURES, _gesture),
    },
    "mouse": {
        "tracking_speed": _number(0, 1),
        "scroll_speed": _number(0),
        "double_click_speed": _number(above=0),
    },
    "dock": {
        "autohide_delay": _number(0),
        "autohide_duration": _number(0, optional=True),
        "size": _number(16, 128),
        "position": _choice(("left", "bottom", "right")),
        "magnification": _number(16, 128, optional=True),
        "minimize_effect": _choice(("genie", "scale")),
        "hot_corners": _entries(dock._CORNERS, _hot_corner),
    },
    "finder": {
        "default_view": _choice(finder._VIEWS),
        "new_window_folder": _text(),
        "search_scope": _choice(finder._SCOPES),
        "drives_on_desktop": _options(
            finder.set_show_drives_on_desktop, internal=_flag, external=_flag, removable=_flag, servers=_flag
        ),
        "desktop_view": _options(
            finder.set_desktop_view,
            icon_size=_number(16, 128, optional=True),
            grid_spacing=_number(1, 100, optional=True),
            text_size=_number(10, 16, optional=True),
            sort=_choice(finder._DESKTOP_SORTS, optional=True),
            show_item_info=_flag,
            labels_on_bottom=_flag,
        ),
    },
    "windows": {
        "double_click_title_bar": _choice(("zoom", "fill", "minimize"), optional=True),
    },
    "appearance": {
        "scroll_bars": _choice(appearance._SCROLL_BARS),
    },
    "screen": {
        "screenshot_folder": _text(),
        "screenshot_format": _screenshot_format,
        "screenshot_name": _screenshot_name,
        "screenshot_target": _choice(screen._SCREENSHOT_TARGETS),
        "screensaver_delay": _number(above=0, optional=True),
        "night_shift_schedule": _night_shift,
        "night_shift_strength": _number(0, 1),
    },
    "sound": {
        "alert_sound": _alert_sound,
        "alert_volume": _number(0, 1),
    },
    "system": {
        "clock_format": _options(
            system.set_clock_format,
            seconds=_flag, day_of_week=_flag, am_pm=_flag, analog=_flag,
            date=_choice(("auto", "always", "never"), optional=True),
        ),
        "menu_bar_items": _entries(system.MENU_BAR_ITEMS, lambda name, on: _flag(on), at_least_one=True),
        "menu_bar_spacing": _number(0, 30, optional=True, whole=True),
        "measurement_units": _choice(("metric", "us")),
        "temperature_unit": _choice(("celsius", "fahrenheit")),
    },
}
for _section, _table in _SETTINGS.items():
    for _name, _setting in _table.items():
        _SETTINGS[_section][_name] = _setting._replace(check=_CHECKS.get(_section, {}).get(_name, _flag))
del _section, _table, _name, _setting


def names() -> List[str]:
    """Every setting :func:`export` saves, as ``"section.name"``: ``["keyboard.key_repeat", ...]``."""
    return ["{}.{}".format(section, name) for section, settings in _SETTINGS.items() for name in settings]


def export() -> Dict[str, Dict[str, Any]]:
    """
    This Mac's settings, as JSON-ready values by section: ``{"dock": {"autohide": True, ...}, ...}``.

    Settings this Mac doesn't have (a keyboard backlight, Night Shift...) are left out.
    """
    require_macos()
    found: Dict[str, Dict[str, Any]] = {}
    for section, settings in _SETTINGS.items():
        for name, setting in settings.items():
            try:
                found.setdefault(section, {})[name] = setting.read()
            except NotSupportedError:
                continue  # this Mac lacks it
    return found


def _normalized(value: Any) -> Any:
    """Compare values as JSON gives them back: tuples as lists."""
    if isinstance(value, (list, tuple)):
        return [_normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in value.items()}
    return value


def apply(settings: Mapping[str, Mapping[str, Any]]) -> List[str]:
    """
    Change this Mac's settings to those of ``settings``, as :func:`export` gives them, and return those that changed.

    ::

        macos.settings.apply({"dock": {"autohide": True, "size": 48}, "finder": {"show_extensions": True}})

    Any part of an export works: settings left out stay as they are. Those
    already as wanted aren't touched, and the Dock and Finder restart once
    at the end. Unknown names and invalid values (a size out of range, an
    unknown hot corner action, a key that can't be remapped) raise
    :class:`ValueError` before anything changes; if a change still fails
    midway (a permission...), the settings already changed are put back
    before the error is raised. Settings this Mac lacks (a keyboard
    backlight, Night Shift...) are skipped. Returns ``["dock.autohide", ...]``.
    """
    require_macos()
    if not isinstance(settings, Mapping):
        raise ValueError("settings must be an object of sections, not {!r}".format(settings))
    not_objects = [section for section, values in settings.items() if not isinstance(values, Mapping)]
    if not_objects:
        raise ValueError(
            "each section must be an object of names and values, as export() gives: {}".format(
                ", ".join("{} is {!r}".format(section, settings[section]) for section in not_objects)
            )
        )
    unknown = []
    for section, values in settings.items():
        if section not in _SETTINGS:
            unknown.append(section)
        else:
            unknown.extend("{}.{}".format(section, name) for name in values if name not in _SETTINGS[section])
    if unknown:
        raise ValueError("unknown settings: {}; see macos.settings.names()".format(", ".join(sorted(set(unknown)))))
    # Every value is checked before the first change: a bad one in the middle
    # of a file mustn't leave the settings before it changed and those after not.
    bad = []
    for section, values in settings.items():
        for name, value in values.items():
            try:
                _SETTINGS[section][name].check(value)
            except ValueError as error:
                bad.append("{}.{} {}".format(section, name, error))
    if bad:
        raise ValueError("invalid settings: {}".format("; ".join(bad)))
    changed: List[str] = []
    undo: List[Tuple[str, _Setting, Any]] = []  # (name, setting, its value before), to put back if a later change fails
    with batched_restarts():
        try:
            for section, values in settings.items():
                for name, value in values.items():
                    setting = _SETTINGS[section][name]
                    try:
                        current = _normalized(setting.read())
                    except NotSupportedError:
                        continue  # this Mac lacks it (a keyboard backlight, Night Shift...): the others still apply
                    if current == _normalized(value):
                        continue
                    # Noted before the change: one that fails half-way (two preferences, the
                    # second refused) is put back too.
                    undo.append(("{}.{}".format(section, name), setting, current))
                    try:
                        setting.change(value)
                    except NotSupportedError:
                        undo.pop()  # nothing changed: this Mac lacks it (a keyboard backlight, Night Shift...)
                        continue
                    changed.append("{}.{}".format(section, name))
        except BaseException as error:
            # What the checks can't foresee (a permission, a file gone): put
            # back the settings already changed, newest first, then raise.
            # The original error is the one raised; those that couldn't be put
            # back are named alongside it, so nobody is left guessing.
            stuck = []
            for name, setting, before in reversed(undo):
                try:
                    setting.change(before)
                except Exception as failure:
                    stuck.append("{} ({})".format(name, failure))
            if stuck:
                add_note(error, "these settings were changed and couldn't be put back: {}".format("; ".join(stuck)))
            raise
    return changed
