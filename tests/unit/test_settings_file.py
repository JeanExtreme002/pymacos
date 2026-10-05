"""Unit tests for :mod:`macos.settings`, over fake settings. They run on any platform."""

import json

import pytest

import macos
from macos import _system, settings


@pytest.fixture
def fake_settings(monkeypatch):
    """Two sections of settings kept in a dict, and the restarts they asked for."""
    values = {"autohide": False, "size": 48, "key_repeat": (0.03, 0.225), "gestures": {"rotate": True, "smart_zoom": False}}
    changes, restarts = [], []

    def setter(name):
        def change(value):
            if _system.restart_later("Dock", lambda: restarts.append("dock")):
                changes.append((name, value))
                values[name] = value
                return
            raise AssertionError("changes must happen in a batch")

        return change

    def unsupported():
        raise macos.NotSupportedError("this Mac has no keyboard backlight")

    table = {
        "dock": {name: settings._Setting(lambda name=name: values[name], setter(name)) for name in ("autohide", "size")},
        "keyboard": {
            "key_repeat": settings._Setting(lambda: values["key_repeat"], setter("key_repeat")),
            "backlight_timeout": settings._Setting(unsupported, setter("backlight_timeout")),
        },
        "trackpad": {"gestures": settings._Setting(lambda: values["gestures"], setter("gestures"))},
    }
    monkeypatch.setattr(settings, "_SETTINGS", table)
    monkeypatch.setattr(settings, "require_macos", lambda: None)
    return values, changes, restarts


def test_export_is_json_and_skips_what_this_mac_lacks(fake_settings):
    exported = settings.export()
    assert exported == {
        "dock": {"autohide": False, "size": 48},
        "keyboard": {"key_repeat": (0.03, 0.225)},
        "trackpad": {"gestures": {"rotate": True, "smart_zoom": False}},
    }
    assert json.loads(json.dumps(exported))["keyboard"]["key_repeat"] == [0.03, 0.225]
    assert "keyboard.backlight_timeout" in settings.names()


def test_apply_changes_only_what_differs_and_restarts_once(fake_settings):
    values, changes, restarts = fake_settings
    saved = json.loads(json.dumps(settings.export()))  # through JSON, as from a file

    assert settings.apply(saved) == []  # the same settings: nothing to do
    changed = settings.apply({"dock": {"autohide": True, "size": 48}, "keyboard": {"key_repeat": [0.05, 0.3]}})
    assert changed == ["dock.autohide", "keyboard.key_repeat"]
    assert changes == [("autohide", True), ("key_repeat", [0.05, 0.3])]
    assert restarts == ["dock"]  # once, at the end


def test_apply_refuses_unknown_names_before_changing_anything(fake_settings):
    _, changes, _ = fake_settings
    with pytest.raises(ValueError, match="unknown settings: dock.colour, printer"):
        settings.apply({"dock": {"autohide": True, "colour": "red"}, "printer": {}})
    assert changes == []


def test_the_real_table_reads_and_changes_existing_functions():
    for section, table in settings._SETTINGS.items():
        for name, setting in table.items():
            assert callable(setting.read) and callable(setting.change), "{}.{}".format(section, name)
    assert len(settings.names()) == len(set(settings.names())) > 80


def test_apply_skips_what_this_mac_lacks(fake_settings, monkeypatch):
    values, changes, restarts = fake_settings

    def lacking(value):
        raise macos.NotSupportedError("this Mac has no keyboard backlight")

    table = settings._SETTINGS["keyboard"]
    monkeypatch.setitem(table, "backlight_timeout", settings._Setting(table["backlight_timeout"].read, lacking))
    changed = settings.apply({"keyboard": {"backlight_timeout": 10}, "dock": {"size": 64}})
    assert changed == ["dock.size"] and changes == [("size", 64)]


def test_other_failures_are_not_hidden(fake_settings, monkeypatch):
    def broken():
        raise macos.MacOSError("could not read the Night Shift status")

    monkeypatch.setitem(settings._SETTINGS["dock"], "size", settings._Setting(broken, lambda value: None))
    with pytest.raises(macos.MacOSError, match="Night Shift"):
        settings.export()
    with pytest.raises(macos.MacOSError, match="Night Shift"):
        settings.apply({"dock": {"size": 64}})


def test_folders_are_exported_relative_to_home(monkeypatch, tmp_path):
    monkeypatch.setattr(settings.Path, "home", staticmethod(lambda: tmp_path))
    assert settings._portable(tmp_path / "Pictures" / "Screenshots") == "~/Pictures/Screenshots"
    assert settings._portable(tmp_path) == "~"
    assert settings._portable(settings.Path("/Volumes/Shared")) == "/Volumes/Shared"


def test_apply_checks_every_value_before_changing_anything(fake_settings, monkeypatch):
    _, changes, _ = fake_settings

    def size(value):
        if not 16 <= value <= 128:
            raise ValueError("must be from 16 to 128")

    table = settings._SETTINGS["dock"]
    monkeypatch.setitem(table, "size", table["size"]._replace(check=size))
    with pytest.raises(ValueError, match="invalid settings: dock.size must be from 16 to 128"):
        settings.apply({"dock": {"autohide": True, "size": 500}})
    assert changes == []  # autohide came first, but wasn't changed


def test_apply_puts_back_what_changed_when_a_later_change_fails(fake_settings, monkeypatch):
    values, changes, _ = fake_settings

    def refused(value):
        raise macos.PermissionDeniedError("the domain isn't writable")

    table = settings._SETTINGS["dock"]
    monkeypatch.setitem(table, "size", settings._Setting(table["size"].read, refused))
    with pytest.raises(macos.PermissionDeniedError):
        settings.apply({"dock": {"autohide": True, "size": 64}})
    assert changes == [("autohide", True), ("autohide", False)] and values["autohide"] is False


def test_every_real_setting_has_a_check_and_this_macs_values_pass_it():
    for section, table in settings._SETTINGS.items():
        for name, setting in table.items():
            assert setting.check is not settings._anything, "{}.{}".format(section, name)
    exported = {
        "keyboard": {"key_repeat": [0.03, 0.225], "fn_key_action": None, "remappings": {"caps_lock": "escape"}},
        "trackpad": {"tracking_speed": 0.5, "gestures": {"mission_control": 4, "pinch_to_zoom": False}},
        "dock": {
            "size": 48,
            "position": "bottom",
            "hot_corners": {"top_left": {"action": "mission_control", "modifier": "cmd"}},
            "autohide_duration": None,
        },
        "finder": {
            "default_view": "list",
            "new_window_folder": "~",
            "drives_on_desktop": {"internal": False, "servers": True},
            "desktop_view": {"icon_size": 64, "sort": None, "labels_on_bottom": True},
        },
        "screen": {"night_shift_schedule": ["22:00", "07:00"], "screenshot_format": "JPEG", "screenshot_name": None},
        "system": {"clock_format": {"seconds": False, "date": "auto"}, "menu_bar_spacing": None},
    }
    for section, values in exported.items():
        for name, value in values.items():
            settings._SETTINGS[section][name].check(value)


@pytest.mark.parametrize(
    "name, value, message",
    [
        ("dock.size", 500, "from 16 to 128"),
        ("dock.size", "48", "a number"),
        ("dock.autohide", "yes", "true or false"),
        ("dock.position", "top", "'left', 'bottom', 'right'"),
        ("dock.hot_corners", {"middle": {"action": None}}, "'middle' isn't one of"),
        ("dock.hot_corners", {"top_left": {"action": "explode"}}, "top_left: must be"),
        ("dock.hot_corners", {"top_left": {"action": None, "modifier": "hyper"}}, "modifier must be made of"),
        ("trackpad.tracking_speed", float("nan"), "a number"),
        ("trackpad.gestures", {"mission_control": 5}, "3 or 4 fingers"),
        ("keyboard.key_repeat", [0.03], r"\[interval, delay\]"),
        ("keyboard.remappings", {"caps_lock": "hyper"}, "can't remap 'hyper'"),
        ("finder.desktop_view", {"icon_size": 8}, "icon_size: must be from 16 to 128"),
        ("finder.desktop_view", {"zoom": 2}, "'zoom' isn't one of"),
        ("finder.drives_on_desktop", {}, "at least one"),
        ("screen.night_shift_schedule", ["22:00"], "null, 'sunset' or"),
        ("screen.night_shift_schedule", ["22:00", "late"], "HH:MM"),
        ("screen.screenshot_name", "a/b", "without /"),
        ("system.menu_bar_spacing", 4.5, "a whole number"),
        ("system.clock_format", {"date": "sometimes"}, "date: must be"),
    ],
)
def test_the_real_checks_refuse_bad_values(name, value, message):
    section, key = name.split(".")
    with pytest.raises(ValueError, match=message):
        settings._SETTINGS[section][key].check(value)


def test_remappings_are_built_in_full_before_the_swap(monkeypatch):
    from macos import keyboard

    swapped = []
    monkeypatch.setattr(keyboard, "_set_mappings", swapped.append)
    monkeypatch.setattr(keyboard, "clear_remappings", lambda: pytest.fail("must not clear the remappings first"))

    with pytest.raises(ValueError, match="can't remap"):
        settings._set_remappings({"caps_lock": "escape", "nope": "ctrl"})
    assert swapped == []  # the old remappings are still in place

    settings._set_remappings({"caps_lock": "escape", "0x700000064": "right_option", "tab": None})
    assert swapped == [{0x700000039: 0x700000029, 0x700000064: 0x7000000E6}]
