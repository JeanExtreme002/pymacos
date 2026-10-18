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


def test_apply_compares_only_the_part_of_a_dict_that_is_given(fake_settings, monkeypatch):
    values, changes, restarts = fake_settings

    # Any part of an export works: the entries left out don't make the setting differ.
    assert settings.apply({"trackpad": {"gestures": {"rotate": True}}}) == []
    assert changes == [] and restarts == []
    assert settings.apply({"trackpad": {"gestures": {"rotate": False}}}) == ["trackpad.gestures"]
    assert changes == [("gestures", {"rotate": False})]
    # A hot corner is compared whole: a modifier left out is no modifier, as set_hot_corner() takes it.
    corners = {"top_left": {"action": "desktop", "modifier": None}, "top_right": {"action": None, "modifier": "cmd"}}
    store = {"hot_corners": corners}

    def set_corners(value):
        if not _system.restart_later("Dock", lambda: restarts.append("dock")):
            raise AssertionError("changes must happen in a batch")
        for corner, wanted in value.items():
            store["hot_corners"][corner] = {"action": wanted.get("action"), "modifier": wanted.get("modifier")}

    monkeypatch.setitem(settings._SETTINGS["dock"], "hot_corners", settings._Setting(lambda: store["hot_corners"], set_corners))
    assert settings.apply({"dock": {"hot_corners": {"top_left": {"action": "desktop"}}}}) == []
    assert settings.apply({"dock": {"hot_corners": {"top_right": {"action": None}}}}) == ["dock.hot_corners"]
    assert store["hot_corners"]["top_right"] == {"action": None, "modifier": None}
    # Not a partial setting: the whole value is compared, as before.
    assert settings.apply({"dock": {"size": 48}}) == []


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
    # export() leaves the one it couldn't read out, says so, and exports the rest.
    with pytest.warns(RuntimeWarning, match="dock.size couldn't be read.*Night Shift"):
        exported = settings.export()
    assert "size" not in exported["dock"] and exported["dock"]["autohide"] is False


def test_export_leaves_out_a_preference_of_a_shape_its_reader_cannot_take(fake_settings, monkeypatch):
    def garbled():
        return ["an array"].get("IconViewSettings")  # a dict edited by hand into an array: AttributeError

    monkeypatch.setitem(settings._SETTINGS["dock"], "size", settings._Setting(garbled, lambda value: None))
    with pytest.warns(RuntimeWarning, match="dock.size couldn't be read"):
        exported = settings.export()
    assert "size" not in exported["dock"] and exported["dock"]["autohide"] is False


def test_export_leaves_out_a_value_apply_would_refuse(fake_settings, monkeypatch):
    def speed(value):
        if not 0 <= value <= 1:
            raise ValueError("must be from 0 to 1")

    table = settings._SETTINGS["dock"]
    monkeypatch.setitem(table, "size", settings._Setting(lambda: 1.667, table["size"].change, check=speed))
    with pytest.warns(RuntimeWarning, match=r"dock.size is 1.667, which apply\(\) can't set.*from 0 to 1"):
        exported = settings.export()
    assert "size" not in exported["dock"]
    assert settings.apply(json.loads(json.dumps(exported))) == []  # what's exported applies


def test_the_real_checks_refuse_what_hand_set_preferences_read_as(monkeypatch):
    # A scaling of 5 (a faster pointer than the slider gives) reads as 1.667; a beep path elsewhere as its stem.
    with pytest.raises(ValueError, match="from 0 to 1"):
        settings._SETTINGS["trackpad"]["tracking_speed"].check(1.667)
    monkeypatch.setattr(macos.sound, "names", lambda: ["Funk", "Glass"])
    with pytest.raises(ValueError, match="no alert sound is named 'Custom'"):
        settings._SETTINGS["sound"]["alert_sound"].check("Custom")
    settings._SETTINGS["sound"]["alert_sound"].check("Funk")


def test_apply_writes_a_setting_it_cannot_read(fake_settings, monkeypatch):
    values, changes, _ = fake_settings
    written = []

    def broken():
        raise ValueError("could not convert string to float: 'abc'")  # a garbled leaf, read by float()

    def change(value):
        written.append(value)

    monkeypatch.setitem(settings._SETTINGS["dock"], "size", settings._Setting(broken, change))
    # Writing the value given is what repairs it, and the other settings still apply.
    assert settings.apply({"dock": {"autohide": True, "size": 64}}) == ["dock.autohide", "dock.size"]
    assert written == [64] and values["autohide"] is True


def test_apply_names_a_setting_it_could_not_read_when_putting_back(fake_settings, monkeypatch):
    values, changes, _ = fake_settings

    def broken():
        raise macos.MacOSError("hidutil answered in a form it can't read")

    def refused(value):
        raise macos.PermissionDeniedError("the domain isn't writable")

    table = settings._SETTINGS["dock"]
    monkeypatch.setitem(table, "size", settings._Setting(broken, lambda value: None))
    monkeypatch.setitem(table, "autohide", settings._Setting(table["autohide"].read, refused))
    with _notes_or_warning() as reported:
        with pytest.raises(macos.PermissionDeniedError) as caught:
            settings.apply({"dock": {"size": 64, "autohide": True}})
    text = " ".join(getattr(caught.value, "__notes__", [])) + " ".join(str(item.message) for item in reported)
    assert "dock.size (its value before couldn't be read)" in text


def test_export_leaves_out_a_value_it_cannot_make_sense_of(fake_settings, monkeypatch):
    def garbled():
        return int("big")  # a preference edited by hand into text, read by a getter that wants a number

    monkeypatch.setitem(settings._SETTINGS["dock"], "size", settings._Setting(garbled, lambda value: None))
    with pytest.warns(RuntimeWarning, match="dock.size couldn't be read"):
        exported = settings.export()
    assert "size" not in exported["dock"] and exported["trackpad"]["gestures"]["rotate"] is True


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


def test_apply_puts_back_a_setting_that_failed_half_way(fake_settings, monkeypatch):
    values, changes, _ = fake_settings
    state = {"size": 48}

    def two_writes(value):
        state["size"] = value  # the first preference is written...
        if value == 64:
            raise macos.PermissionDeniedError("the domain isn't writable")  # ...the second refused

    table = settings._SETTINGS["dock"]
    monkeypatch.setitem(table, "size", settings._Setting(lambda: state["size"], two_writes))
    with pytest.raises(macos.PermissionDeniedError):
        settings.apply({"dock": {"autohide": True, "size": 64}})
    assert state["size"] == 48  # the failing setting is put back too
    assert changes == [("autohide", True), ("autohide", False)] and values["autohide"] is False


def test_apply_names_the_settings_it_could_not_put_back(fake_settings, monkeypatch):
    values, changes, _ = fake_settings

    def stuck(value):
        values["autohide"] = value
        if value is False:  # the change went through, putting it back doesn't
            raise macos.PermissionDeniedError("the domain went read-only")

    def refused(value):
        raise macos.PermissionDeniedError("the domain isn't writable")

    table = settings._SETTINGS["dock"]
    monkeypatch.setitem(table, "autohide", settings._Setting(table["autohide"].read, stuck))
    monkeypatch.setitem(table, "size", settings._Setting(table["size"].read, refused))
    with _notes_or_warning() as reported:
        with pytest.raises(macos.PermissionDeniedError, match="isn't writable") as caught:
            settings.apply({"dock": {"autohide": True, "size": 64}})
    text = " ".join(getattr(caught.value, "__notes__", [])) + " ".join(str(item.message) for item in reported)
    assert "dock.autohide" in text and "went read-only" in text


def _notes_or_warning():
    """Python 3.11+ attaches the note to the error; older ones warn."""
    import sys
    import warnings

    if sys.version_info >= (3, 11):
        return warnings.catch_warnings(record=True)
    return pytest.warns(RuntimeWarning)


def test_apply_refuses_a_section_that_is_not_an_object(fake_settings):
    _, changes, _ = fake_settings
    with pytest.raises(ValueError, match="dock is True"):
        settings.apply({"dock": True})
    with pytest.raises(ValueError, match="object of sections"):
        settings.apply(["dock"])
    assert changes == []


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
        ("dock.size", 10 ** 400, "from 16 to 128"),
        ("dock.autohide_delay", float("inf"), "a number"),
        ("screen.screenshot_folder", "~/no such folder for pymacos", "no folder '~/no such folder for pymacos'"),
        ("finder.new_window_folder", "/no/such/folder", "create it first"),
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


def test_the_folder_checks_take_a_folder_this_mac_has(tmp_path):
    for name in ("screen.screenshot_folder", "finder.new_window_folder"):
        section, key = name.split(".")
        settings._SETTINGS[section][key].check(str(tmp_path))
        settings._SETTINGS[section][key].check("~")
        with pytest.raises(ValueError, match="create it first"):
            settings._SETTINGS[section][key].check(str(tmp_path / "gone"))
        (tmp_path / "file").write_text("")
        with pytest.raises(ValueError, match="create it first"):
            settings._SETTINGS[section][key].check(str(tmp_path / "file"))


def test_apply_refuses_a_missing_folder_before_changing_anything(fake_settings, monkeypatch, tmp_path):
    _, changes, _ = fake_settings
    table = settings._SETTINGS["dock"]
    monkeypatch.setitem(table, "size", table["size"]._replace(check=settings._folder))
    with pytest.raises(ValueError, match="invalid settings: dock.size no folder"):
        settings.apply({"dock": {"autohide": True, "size": str(tmp_path / "QuickTime Recordings")}})
    assert changes == []


def test_a_finder_folder_that_is_not_a_folder_is_left_out_of_the_export():
    assert settings._portable(None) is None
    with pytest.raises(ValueError, match="must be text"):
        settings._SETTINGS["finder"]["new_window_folder"].check(None)


@pytest.mark.parametrize(
    "name, current, wanted",
    [
        ("keyboard.key_repeat", [0.03, 0.3], [None, 0.3]),
        ("keyboard.key_repeat", [0.03, 0.3], [0.03, None]),
        ("keyboard.remappings", {"caps_lock": "escape"}, {"caps_lock": "esc"}),
        ("keyboard.remappings", {"caps_lock": "escape"}, {"caps_lock": "escape", "tab": None}),
        ("keyboard.remappings", {"0x700000064": "right_option"}, {"0x700000064": "right_option"}),
        (
            "dock.hot_corners",
            {"top_left": {"action": "desktop", "modifier": "cmd+shift"}},
            {"top_left": {"action": "desktop", "modifier": "shift+cmd"}},
        ),
        ("screen.screenshot_format", "jpg", "JPEG"),
        ("screen.screenshot_format", "png", ".png"),
        ("screen.screenshot_folder", "~/Shots", "~/Shots/"),
        ("finder.new_window_folder", "~/Downloads", "~/Downloads/"),
        ("finder.new_window_folder", "~/Downloads", "~/Documents/../Downloads"),
    ],
)
def test_a_value_written_another_way_is_already_as_wanted(name, current, wanted, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(settings.Path, "home", staticmethod(lambda: tmp_path))
    section, key = name.split(".")
    setting = settings._SETTINGS[section][key]
    if name == "screen.screenshot_folder":
        wanted = str(tmp_path / "Shots") + "/"  # absolute, with a trailing slash
    assert settings._same(section, key, setting, settings._normalized(current), wanted)


@pytest.mark.parametrize(
    "name, current, wanted",
    [
        ("keyboard.key_repeat", [0.03, 0.3], [None, 0.5]),
        ("keyboard.remappings", {"caps_lock": "escape"}, {"caps_lock": "ctrl"}),
        ("keyboard.remappings", {"caps_lock": "escape"}, {}),
        ("dock.hot_corners", {"top_left": {"action": "desktop", "modifier": "cmd"}}, {"top_left": {"action": "desktop"}}),
        ("screen.screenshot_format", "jpg", "png"),
        ("finder.new_window_folder", "~/Downloads", "~/Documents"),
    ],
)
def test_a_value_that_really_differs_still_differs(name, current, wanted, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(settings.Path, "home", staticmethod(lambda: tmp_path))
    section, key = name.split(".")
    setting = settings._SETTINGS[section][key]
    assert not settings._same(section, key, setting, settings._normalized(current), wanted)


def test_apply_leaves_alone_a_value_already_in_place_written_another_way(fake_settings, monkeypatch):
    values, changes, restarts = fake_settings
    table = settings._SETTINGS["keyboard"]
    monkeypatch.setitem(table, "key_repeat", table["key_repeat"]._replace(canon=settings._key_repeat_canon))
    assert settings.apply({"keyboard": {"key_repeat": [None, 0.225]}}) == []
    assert settings.apply({"keyboard": {"key_repeat": [None, 0.3]}}) == ["keyboard.key_repeat"]
    assert changes == [("key_repeat", [None, 0.3])]  # the setter is given the value as it was
