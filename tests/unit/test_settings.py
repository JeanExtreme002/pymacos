"""Unit tests for the settings of the keyboard, trackpad, mouse, Dock, Finder, appearance, screen and system."""

from pathlib import Path

import pytest

import macos
from macos import _system, appearance, defaults, dock, finder, screen, system, trackpad, windows


@pytest.fixture
def prefs(monkeypatch):
    """The preferences in a dict keyed by (domain, key, current_host), and what was applied or restarted."""
    store, done = {}, []

    def read(domain, key=None, *, default=None, current_host=False):
        return store.get((domain, key, current_host), default)

    def write(domain, key, value, *, current_host=False):
        store[(domain, key, current_host)] = value

    def delete(domain, key, *, current_host=False):
        return store.pop((domain, key, current_host), None) is not None

    monkeypatch.setattr(defaults, "read", read)
    monkeypatch.setattr(defaults, "write", write)
    monkeypatch.setattr(defaults, "delete", delete)
    monkeypatch.setattr(_system, "apply_input_settings", lambda: done.append("input"))
    monkeypatch.setattr(trackpad, "apply_input_settings", lambda: done.append("input"))
    monkeypatch.setattr(dock, "restart", lambda: done.append("dock"))
    monkeypatch.setattr(finder, "restart", lambda: done.append("finder"))
    monkeypatch.setattr(appearance, "_announce", lambda *names: done.append(names))
    monkeypatch.setattr(screen, "_apply_capture_settings", lambda: done.append("capture"))
    for module, name in ((system, "_run"), (_system, "run")):  # _system.run: the killall of every restart
        monkeypatch.setattr(module, name, lambda args, **kwargs: done.append(args[-1]))
    return store, done


G = defaults.GLOBAL


def test_keyboard_settings(prefs):
    store, done = prefs

    assert macos.keyboard.key_repeat() == (0.09, 0.375)
    assert macos.keyboard.press_and_hold() and macos.keyboard.autocorrect()
    macos.keyboard.set_key_repeat(0.03, delay=0.225)
    macos.keyboard.set_press_and_hold(False)
    macos.keyboard.set_standard_function_keys(True)
    macos.keyboard.set_autocorrect(False)
    macos.keyboard.set_smart_quotes(False)
    macos.keyboard.set_smart_dashes(False)
    assert store == {
        (G, "KeyRepeat", False): 2,
        (G, "InitialKeyRepeat", False): 15,
        (G, "ApplePressAndHoldEnabled", False): False,
        (G, "com.apple.keyboard.fnState", False): True,
        (G, "NSAutomaticSpellingCorrectionEnabled", False): False,
        (G, "WebAutomaticSpellingCorrectionEnabled", False): False,
        (G, "NSAutomaticQuoteSubstitutionEnabled", False): False,
        (G, "NSAutomaticDashSubstitutionEnabled", False): False,
    }
    assert macos.keyboard.key_repeat() == (0.03, 0.225)
    assert macos.keyboard.standard_function_keys() and not macos.keyboard.smart_quotes()
    assert done == ["input"]  # only the function keys apply at once

    macos.keyboard.set_key_repeat(delay=0.5)
    assert store[(G, "KeyRepeat", False)] == 2 and store[(G, "InitialKeyRepeat", False)] == 33
    with pytest.raises(ValueError, match="give interval, delay"):
        macos.keyboard.set_key_repeat()
    with pytest.raises(ValueError, match="positive"):
        macos.keyboard.set_key_repeat(0)


def test_trackpad_and_mouse_settings(prefs):
    store, done = prefs

    assert not trackpad.tap_to_click() and trackpad.natural_scrolling()
    trackpad.set_tap_to_click()
    trackpad.set_natural_scrolling(False)
    trackpad.set_tracking_speed(0.5)
    macos.mouse.set_tracking_speed(1)
    assert store == {
        ("com.apple.AppleMultitouchTrackpad", "Clicking", False): True,
        ("com.apple.driver.AppleBluetoothMultitouch.trackpad", "Clicking", False): True,
        (G, "com.apple.mouse.tapBehavior", False): 1,
        (G, "com.apple.mouse.tapBehavior", True): 1,  # this Mac's copy, as System Settings keeps
        (G, "com.apple.swipescrolldirection", False): False,
        (G, "com.apple.trackpad.scaling", False): 1.5,
        (G, "com.apple.mouse.scaling", False): 3.0,
    }
    assert (trackpad.tracking_speed(), macos.mouse.tracking_speed()) == (0.5, 1.0)
    assert done == ["input"] * 4
    for speed in (-0.1, 1.1):
        with pytest.raises(ValueError, match="0.0 to 1.0"):
            trackpad.set_tracking_speed(speed)
        with pytest.raises(ValueError, match="0.0 to 1.0"):
            macos.mouse.set_tracking_speed(speed)


def test_dock_more_settings(prefs):
    store, done = prefs
    D = "com.apple.dock"

    assert dock.hot_corners() == dict.fromkeys(("top_left", "top_right", "bottom_left", "bottom_right"))
    dock.set_hot_corner("bottom_right", "lock_screen")
    assert store[(D, "wvous-br-corner", False)] == 13 and store[(D, "wvous-br-modifier", False)] == 0
    assert dock.hot_corners()["bottom_right"] == "lock_screen"
    dock.set_hot_corner("bottom_right", None)
    assert store[(D, "wvous-br-corner", False)] == 1

    dock.set_autohide_delay(0)
    dock.set_magnification(96)
    dock.set_show_recents(False)
    dock.set_minimize_effect("scale")
    assert (dock.autohide_delay(), dock.magnification(), dock.show_recents(), dock.minimize_effect()) == (0.0, 96, False, "scale")
    dock.set_magnification(None)
    assert dock.magnification() is None
    assert done == ["dock"] * 7

    with pytest.raises(ValueError, match="corner must be one of"):
        dock.set_hot_corner("middle", None)
    with pytest.raises(ValueError, match="action must be one of"):
        dock.set_hot_corner("top_left", "explode")
    with pytest.raises(ValueError, match="not be negative"):
        dock.set_autohide_delay(-1)
    with pytest.raises(ValueError, match="16 to 128"):
        dock.set_magnification(200)
    with pytest.raises(ValueError, match="'genie' or 'scale'"):
        dock.set_minimize_effect("suck")


def test_finder_more_settings(prefs, fake_run, tmp_path):
    store, done = prefs
    F = "com.apple.finder"

    assert (finder.default_view(), finder.search_scope(), finder.new_window_folder()) == ("icons", "this_mac", Path.home())
    finder.set_show_desktop_icons(False)
    finder.set_default_view("columns")
    finder.set_search_scope("current_folder")
    finder.set_show_full_path_in_title(True)
    finder.set_new_window_folder(tmp_path)
    assert store[(F, "CreateDesktop", False)] is False
    assert store[(F, "FXPreferredViewStyle", False)] == "clmv"
    assert store[(F, "FXDefaultSearchScope", False)] == "SCcf"
    assert store[(F, "_FXShowPosixPathInTitle", False)] is True
    assert store[(F, "NewWindowTarget", False)] == "PfLo"
    assert (finder.default_view(), finder.search_scope(), finder.new_window_folder()) == (
        "columns",
        "current_folder",
        tmp_path.resolve(),
    )
    assert done == ["finder"] * 5

    finder.set_show_library_folder(True)
    assert fake_run.args == ["chflags", "nohidden", str(Path.home() / "Library")]

    with pytest.raises(ValueError, match="view must be one of"):
        finder.set_default_view("cover_flow")
    with pytest.raises(ValueError, match="scope must be one of"):
        finder.set_search_scope("everywhere")
    with pytest.raises(FileNotFoundError):
        finder.set_new_window_folder(tmp_path / "missing")


def test_appearance_settings(prefs):
    store, done = prefs

    appearance.set_accent_color("purple")
    appearance.set_auto_mode(True)
    appearance.set_hide_menu_bar(True)
    assert store == {
        (G, "AppleAccentColor", False): 5,
        (G, "AppleInterfaceStyleSwitchesAutomatically", False): True,
        (G, "_HIHideMenuBar", False): True,
    }
    assert appearance.menu_bar_hidden()
    appearance.set_accent_color("multicolor")  # the key left unset
    assert (G, "AppleAccentColor", False) not in store
    assert done[0] == ("AppleColorPreferencesChangedNotification", "AppleAquaColorVariantChanged")
    assert len(done) == 4
    with pytest.raises(ValueError, match="name must be one of"):
        appearance.set_accent_color("teal")


def test_screen_and_system_settings(prefs, monkeypatch):
    store, _ = prefs
    commands = []
    monkeypatch.setattr(_system, "run", lambda args, **kwargs: commands.append(args))

    assert screen.screensaver_delay() == 20.0
    screen.set_screensaver_delay(5)
    assert store[("com.apple.screensaver", "idleTime", True)] == 300 and screen.screensaver_delay() == 5.0
    screen.set_screensaver_delay(None)
    assert store[("com.apple.screensaver", "idleTime", True)] == 0 and screen.screensaver_delay() is None
    screen.set_screensaver_delay(0.001)  # not 0 seconds, which would mean never
    assert store[("com.apple.screensaver", "idleTime", True)] == 1
    with pytest.raises(ValueError, match="positive"):
        screen.set_screensaver_delay(0)

    assert system.ds_store_on_network() and system.ds_store_on_usb() and not system.keep_windows_on_quit()
    system.set_ds_store_on_network(False)
    system.set_ds_store_on_usb(False)
    system.set_keep_windows_on_quit(True)
    system.set_show_battery_percentage(True)
    assert store[("com.apple.desktopservices", "DSDontWriteNetworkStores", False)] is True
    assert store[("com.apple.desktopservices", "DSDontWriteUSBStores", False)] is True
    assert store[(G, "NSQuitAlwaysKeepsWindows", False)] is True
    assert store[("com.apple.controlcenter", "BatteryShowPercentage", True)] is True
    assert not system.ds_store_on_network() and system.keep_windows_on_quit() and system.battery_percentage_shown()
    assert commands == [["killall", "ControlCenter"]]


def test_auth_required(monkeypatch):
    answers = []
    monkeypatch.setattr(macos.auth, "confirm", lambda reason, only_touch_id=False: answers.append((reason, only_touch_id)) or ok)

    @macos.auth.required("deploy", only_touch_id=True)
    def deploy(target):
        """Deploy it."""
        return "deployed " + target

    ok = True
    assert deploy("prod") == "deployed prod"
    assert (deploy.__name__, deploy.__doc__) == ("deploy", "Deploy it.")
    ok = False
    with pytest.raises(macos.PermissionDeniedError, match="deploy"):
        deploy("prod")
    assert answers == [("deploy", True)] * 2
    with pytest.raises(ValueError, match="reason must not be empty"):
        macos.auth.required(" ")


def test_more_keyboard_settings(prefs):
    store, _ = prefs

    assert macos.keyboard.auto_capitalization() and macos.keyboard.double_space_period()
    assert not macos.keyboard.full_keyboard_access()
    macos.keyboard.set_auto_capitalization(False)
    macos.keyboard.set_double_space_period(False)
    macos.keyboard.set_full_keyboard_access(True)
    assert store == {
        (G, "NSAutomaticCapitalizationEnabled", False): False,
        (G, "NSAutomaticPeriodSubstitutionEnabled", False): False,
        (G, "AppleKeyboardUIMode", False): 2,
    }
    assert macos.keyboard.full_keyboard_access()
    store[(G, "AppleKeyboardUIMode", False)] = 3  # as older macOS wrote it
    assert macos.keyboard.full_keyboard_access()
    macos.keyboard.set_full_keyboard_access(False)
    assert store[(G, "AppleKeyboardUIMode", False)] == 1  # the other bit kept
    macos.keyboard.set_full_keyboard_access(True)
    assert store[(G, "AppleKeyboardUIMode", False)] == 3


def test_remap(monkeypatch):
    state = {"mappings": []}

    def hidutil(args):
        if args[2] == "--set":
            import json

            state["mappings"] = json.loads(args[3])["UserKeyMapping"]
            return ""
        blocks = "".join(
            "    {{\n        HIDKeyboardModifierMappingDst = {};\n        HIDKeyboardModifierMappingSrc = {};\n    }}\n".format(
                pair["HIDKeyboardModifierMappingDst"], pair["HIDKeyboardModifierMappingSrc"]
            )
            for pair in state["mappings"]
        )
        return "(\n{})\n".format(blocks) if state["mappings"] else "(null)\n"

    monkeypatch.setattr(_system, "run", hidutil)

    assert macos.keyboard.remappings() == {}
    macos.keyboard.remap("Caps_Lock", "esc")
    assert state["mappings"] == [{"HIDKeyboardModifierMappingSrc": 0x700000039, "HIDKeyboardModifierMappingDst": 0x700000029}]
    macos.keyboard.remap("right_option", "control")
    macos.keyboard.remap("fn", "f13")
    assert macos.keyboard.remappings() == {"caps_lock": "escape", "right_option": "ctrl", "fn": "f13"}
    macos.keyboard.remap("caps_lock", None)
    assert macos.keyboard.remappings() == {"right_option": "ctrl", "fn": "f13"}
    macos.keyboard.clear_remappings()
    assert macos.keyboard.remappings() == {}
    assert (macos.keyboard._HID_CODES["a"], macos.keyboard._HID_CODES["1"], macos.keyboard._HID_CODES["0"]) == (
        0x700000004,
        0x70000001E,
        0x700000027,
    )
    assert (macos.keyboard._HID_CODES["f12"], macos.keyboard._HID_CODES["f13"]) == (0x700000045, 0x700000068)
    with pytest.raises(ValueError, match="can't remap 'hyper'"):
        macos.keyboard.remap("hyper", "escape")


def test_more_trackpad_and_mouse_settings(prefs):
    store, done = prefs
    T = "com.apple.AppleMultitouchTrackpad"

    assert not trackpad.three_finger_drag() and trackpad.secondary_click() == "two_fingers"
    trackpad.set_three_finger_drag()
    trackpad.set_secondary_click("bottom_right")
    assert store[(T, "TrackpadThreeFingerDrag", False)] is True
    assert store[("com.apple.driver.AppleBluetoothMultitouch.trackpad", "TrackpadCornerSecondaryClick", False)] == 2
    assert trackpad.three_finger_drag() and trackpad.secondary_click() == "bottom_right"
    trackpad.set_secondary_click(None)
    assert trackpad.secondary_click() is None
    with pytest.raises(ValueError, match="how must be"):
        trackpad.set_secondary_click("three_fingers")

    assert (macos.mouse.scroll_speed(), macos.mouse.double_click_speed()) == (0.3125, 0.5)
    macos.mouse.set_scroll_speed(1)
    macos.mouse.set_double_click_speed(0.3)
    assert (macos.mouse.scroll_speed(), macos.mouse.double_click_speed()) == (1.0, 0.3)
    with pytest.raises(ValueError, match="not be negative"):
        macos.mouse.set_scroll_speed(-1)
    with pytest.raises(ValueError, match="positive"):
        macos.mouse.set_double_click_speed(0)
    assert done.count("input") == 4


def test_dock_spacers_and_spaces(prefs):
    store, done = prefs
    D = "com.apple.dock"

    def app(name, path):
        data = {"file-data": {"_CFURLString": "file://{}/".format(path)}, "file-label": name}
        return {"tile-data": data, "tile-type": "file-tile"}

    safari, mail = app("Safari", "/Applications/Safari.app"), app("Mail", "/System/Applications/Mail.app")
    store[(D, "persistent-apps", False)] = [safari, mail]

    dock.add_spacer(index=1)
    dock.add_spacer(small=True)
    assert [tile["tile-type"] for tile in store[(D, "persistent-apps", False)]] == [
        "file-tile",
        "spacer-tile",
        "file-tile",
        "small-spacer-tile",
    ]
    assert [app.name for app in dock.apps()] == ["Safari", "Mail"]
    assert dock.remove_spacers() == 2 and dock.remove_spacers() == 0
    assert store[(D, "persistent-apps", False)] == [safari, mail]

    assert dock.show_indicators() and not dock.minimize_to_app() and dock.autohide_duration() is None
    dock.set_show_indicators(False)
    dock.set_minimize_to_app(True)
    dock.set_autohide_duration(0)
    dock.set_auto_rearrange_spaces(False)
    dock.set_separate_spaces_per_display(False)
    assert (dock.show_indicators(), dock.minimize_to_app(), dock.autohide_duration()) == (False, True, 0.0)
    assert not dock.auto_rearrange_spaces() and not dock.separate_spaces_per_display()
    assert store[("com.apple.spaces", "spans-displays", False)] is True
    dock.set_autohide_duration(None)
    assert (D, "autohide-time-modifier", False) not in store
    assert done.count("dock") == 8  # the spaces per display wait for the next login
    with pytest.raises(ValueError, match="not be negative"):
        dock.set_autohide_duration(-1)


def test_more_finder_settings(prefs):
    store, done = prefs
    F = "com.apple.finder"

    assert not finder.folders_first() and finder.extension_change_warning() and not finder.remove_old_trash_items()
    finder.set_folders_first()
    finder.set_extension_change_warning(False)
    finder.set_remove_old_trash_items()
    assert store[(F, "_FXSortFoldersFirst", False)] and store[(F, "_FXSortFoldersFirstOnDesktop", False)]
    assert finder.folders_first() and not finder.extension_change_warning() and finder.remove_old_trash_items()

    assert finder.drives_on_desktop() == {"internal": False, "external": True, "removable": True, "servers": False}
    finder.set_show_drives_on_desktop(external=False, servers=True)
    assert finder.drives_on_desktop() == {"internal": False, "external": False, "removable": True, "servers": True}
    assert (F, "ShowHardDrivesOnDesktop", False) not in store
    assert done == ["finder"] * 4
    with pytest.raises(ValueError, match="say which disks"):
        finder.set_show_drives_on_desktop()


def test_window_appearance_screen_and_system_settings(prefs):
    store, done = prefs
    W = "com.apple.WindowManager"

    assert windows.double_click_title_bar() == "zoom" and windows.tiling() and windows.click_wallpaper_to_show_desktop()
    windows.set_double_click_title_bar("minimize")
    windows.set_tiling(False)
    windows.set_click_wallpaper_to_show_desktop(False)
    assert store[(G, "AppleActionOnDoubleClick", False)] == "Minimize"
    assert store[(W, "EnableTilingByEdgeDrag", False)] is False and store[(W, "EnableTopTilingByEdgeDrag", False)] is False
    assert windows.double_click_title_bar() == "minimize" and not windows.tiling()
    assert not windows.click_wallpaper_to_show_desktop()
    windows.set_double_click_title_bar(None)
    assert windows.double_click_title_bar() is None
    with pytest.raises(ValueError, match="action must be"):
        windows.set_double_click_title_bar("maximize")

    assert appearance.scroll_bars() == "automatic"
    appearance.set_scroll_bars("always")
    assert store[(G, "AppleShowScrollBars", False)] == "Always" and appearance.scroll_bars() == "always"
    with pytest.raises(ValueError, match="when must be"):
        appearance.set_scroll_bars("never")

    assert screen.screenshot_thumbnail()
    screen.set_screenshot_thumbnail(False)
    assert not screen.screenshot_thumbnail()

    assert system.save_to_icloud_by_default() and not system.expanded_save_dialog()
    system.set_save_to_icloud_by_default(False)
    system.set_expanded_save_dialog()
    assert store[(G, "NSNavPanelExpandedStateForSaveMode2", False)] is True
    assert not system.save_to_icloud_by_default() and system.expanded_save_dialog()

    assert system.clock_format() == {"seconds": False, "day_of_week": True, "am_pm": True, "analog": False, "date": "auto"}
    system.set_clock_format(seconds=True, date="never")
    assert system.clock_format()["seconds"] and system.clock_format()["date"] == "never"
    assert store[("com.apple.menuextra.clock", "ShowDate", False)] == 2
    with pytest.raises(ValueError, match="say what to change"):
        system.set_clock_format()
    with pytest.raises(ValueError, match="date must be"):
        system.set_clock_format(date="sometimes")

    assert done == ["WindowManager", "WindowManager", ("AppleShowScrollBarsSettingChanged",), "capture", "ControlCenter"]


# --- v1.14 ------------------------------------------------------------------


def test_fn_key_and_inline_predictions(prefs):
    store, done = prefs

    assert macos.keyboard.fn_key_action() == "emoji" and macos.keyboard.inline_predictions()
    macos.keyboard.set_fn_key_action(None)
    macos.keyboard.set_inline_predictions(False)
    assert store[("com.apple.HIToolbox", "AppleFnUsageType", False)] == 0
    assert macos.keyboard.fn_key_action() is None and not macos.keyboard.inline_predictions()
    macos.keyboard.set_fn_key_action("dictation")
    assert macos.keyboard.fn_key_action() == "dictation" and done == ["input", "input"]
    with pytest.raises(ValueError, match="action must be"):
        macos.keyboard.set_fn_key_action("siri")


@pytest.mark.parametrize(
    "keys, code",
    [
        ("cmd+shift+e", "@$e"),
        ("Shift+Cmd+E", "@$e"),
        ("ctrl+option+cmd+t", "@~^t"),
        ("cmd+left", "@"),
        ("cmd+f5", "@"),
        ("cmd++", "@+"),
        ("cmd+,", "@,"),
        ("alt+control+delete", "~^\x7f"),
    ],
)
def test_app_shortcut_keys(keys, code):
    assert macos.keyboard._encode_shortcut(keys) == code
    assert macos.keyboard._encode_shortcut(macos.keyboard._decode_shortcut(code)) == code


def test_app_shortcuts(prefs, monkeypatch):
    store, _ = prefs
    installed = {"Safari": "/Applications/Safari.app", "zoom.us": "/Applications/zoom.us.app"}
    bundle_ids = {"/Applications/Safari.app": "com.apple.Safari", "/Applications/zoom.us.app": "us.zoom.xos"}

    def locate(app):
        if app not in installed:
            raise macos.AppNotFoundError(app)
        return installed[app]

    monkeypatch.setattr(macos.apps, "_locate", locate)
    monkeypatch.setattr(macos.apps, "_bundle_id", bundle_ids.get)

    macos.keyboard.set_app_shortcut("Safari", "Export as PDF…", "cmd+shift+e")
    macos.keyboard.set_app_shortcut("com.apple.Preview", "File > Export…", "cmd+e")
    macos.keyboard.set_app_shortcut(None, "Show Tab Bar", "cmd+option+t")
    assert store[("com.apple.Safari", "NSUserKeyEquivalents", False)] == {"Export as PDF…": "@$e"}
    assert store[("com.apple.Preview", "NSUserKeyEquivalents", False)] == {"\x1bFile\x1bExport…": "@e"}
    assert macos.keyboard.app_shortcuts("com.apple.Preview") == {"File > Export…": "cmd+e"}
    assert macos.keyboard.app_shortcuts() == {"Show Tab Bar": "cmd+option+t"}
    macos.keyboard.set_app_shortcut("zoom.us", "Mute Audio", "cmd+shift+a")  # a name with a dot, not a bundle ID
    assert store[("us.zoom.xos", "NSUserKeyEquivalents", False)] == {"Mute Audio": "@$a"}
    with pytest.raises(macos.AppNotFoundError):
        macos.keyboard.set_app_shortcut("NotAnApp", "Print…", "cmd+p")
    macos.keyboard.set_app_shortcut("Safari", "Export as PDF…", None)
    assert ("com.apple.Safari", "NSUserKeyEquivalents", False) not in store  # the last one: the key goes
    macos.keyboard.set_app_shortcut("Safari", "Missing", None)  # nothing to remove
    with pytest.raises(ValueError, match="can't read the shortcut"):
        macos.keyboard.set_app_shortcut("Safari", "Print…", "hyper+p")
    with pytest.raises(ValueError, match="unknown key"):
        macos.keyboard.set_app_shortcut("Safari", "Print…", "cmd+pgup")
    with pytest.raises(ValueError, match="menu_item"):
        macos.keyboard.set_app_shortcut("Safari", " ", "cmd+p")


def test_system_shortcuts(prefs):
    store, done = prefs
    H = ("com.apple.symbolichotkeys", "AppleSymbolicHotKeys", False)
    spotlight = {"enabled": True, "value": {"parameters": [65535, 49, 1048576], "type": "standard"}}
    store[H] = {"64": spotlight, "7": {"enabled": True}}

    assert macos.keyboard.system_shortcuts()["spotlight"]
    macos.keyboard.set_system_shortcut("spotlight", False)
    macos.keyboard.set_system_shortcut("screenshot_toolbar", False)  # not in the preferences yet
    assert store[H]["64"] == {"enabled": False, "value": {"parameters": [65535, 49, 1048576], "type": "standard"}}
    assert store[H]["184"] == {"enabled": False, "value": {"parameters": [53, 23, 1179648], "type": "standard"}}
    assert store[H]["7"] == {"enabled": True}  # the others stay
    found = macos.keyboard.system_shortcuts()
    assert not found["spotlight"] and not found["screenshot_toolbar"] and found["mission_control"]
    assert done == ["input", "input"]
    with pytest.raises(ValueError, match="name must be one of"):
        macos.keyboard.set_system_shortcut("siri", False)


def test_trackpad_click_pressure_and_gestures(prefs):
    store, done = prefs
    T, B = "com.apple.AppleMultitouchTrackpad", "com.apple.driver.AppleBluetoothMultitouch.trackpad"

    assert trackpad.click_pressure() == "medium"
    trackpad.set_click_pressure("firm")
    assert store[(T, "FirstClickThreshold", False)] == 2 and store[(B, "SecondClickThreshold", False)] == 2
    assert trackpad.click_pressure() == "firm"

    found = trackpad.gestures()
    assert set(found) == set(trackpad.GESTURES) and found["pinch_to_zoom"] is True and found["mission_control"] == 3
    trackpad.set_gesture("pinch_to_zoom", False)
    assert store[(B, "TrackpadPinch", False)] is False
    assert store[(G, "com.apple.trackpad.pinchGesture", True)] == 0  # this Mac's copy
    trackpad.set_gesture("mission_control", 4)
    assert store[(T, "TrackpadThreeFingerVertSwipeGesture", False)] == 0
    assert store[(T, "TrackpadFourFingerVertSwipeGesture", False)] == 2
    assert store[("com.apple.dock", "showMissionControlGestureEnabled", False)] is True
    trackpad.set_gesture("notification_center", False)
    trackpad.set_gesture("swipe_between_pages", False)
    trackpad.set_gesture("launchpad", True)
    assert store[(T, "TrackpadFourFingerPinchGesture", False)] == 2
    trackpad.set_gesture("launchpad", False)
    assert store[(T, "TrackpadFourFingerPinchGesture", False)] == 2  # Show Desktop still uses the pinch
    trackpad.set_gesture("show_desktop", False)
    assert store[(T, "TrackpadFiveFingerPinchGesture", False)] == 0
    found = trackpad.gestures()
    assert found["mission_control"] == 4 and not found["pinch_to_zoom"] and not found["notification_center"]
    assert not found["swipe_between_pages"] and not found["launchpad"] and not found["show_desktop"]
    trackpad.set_gesture("mission_control", False)
    assert trackpad.gestures()["mission_control"] is False
    assert done.count("dock") == 5  # Mission Control twice, Launchpad twice, Show Desktop
    with pytest.raises(ValueError, match="3 or 4 fingers"):
        trackpad.set_gesture("mission_control", 5)
    with pytest.raises(ValueError, match="True or False"):
        trackpad.set_gesture("rotate", 3)
    with pytest.raises(ValueError, match="name must be one of"):
        trackpad.set_gesture("pinch_to_explode", True)
    with pytest.raises(ValueError, match="pressure must be"):
        trackpad.set_click_pressure("hard")


def test_mouse_acceleration(prefs, monkeypatch):
    store, _ = prefs
    commands = []
    monkeypatch.setattr(_system, "run", lambda args: commands.append(args) or "")

    assert macos.mouse.acceleration()
    macos.mouse.set_acceleration(False)
    assert store[(G, "com.apple.mouse.linear", False)] is True and not macos.mouse.acceleration()
    assert commands == [["hidutil", "property", "--set", '{"HIDUseLinearScalingMouseAcceleration": 1}']]


def test_dock_switches_and_hot_corner_modifiers(prefs):
    store, done = prefs
    D = "com.apple.dock"

    assert (dock.dim_hidden_apps(), dock.only_open_apps(), dock.launch_animation()) == (False, False, True)
    assert (dock.group_windows_by_app(), dock.switch_to_space_with_app()) == (False, True)
    dock.set_dim_hidden_apps()
    dock.set_only_open_apps()
    dock.set_launch_animation(False)
    dock.set_group_windows_by_app()
    dock.set_switch_to_space_with_app(False)
    assert store[(D, "showhidden", False)] and store[(D, "static-only", False)] and not store[(D, "launchanim", False)]
    assert store[(D, "expose-group-apps", False)] and store[(G, "AppleSpacesSwitchOnActivate", False)] is False
    assert done == ["dock"] * 5

    dock.set_hot_corner("top_left", "mission_control", modifier="cmd+option")
    assert store[(D, "wvous-tl-modifier", False)] == 1048576 | 524288
    assert dock.hot_corner_modifiers()["top_left"] == "cmd+option"
    dock.set_hot_corner("top_left", "mission_control")
    assert dock.hot_corner_modifiers()["top_left"] is None
    with pytest.raises(ValueError, match="modifier must be"):
        dock.set_hot_corner("top_left", None, modifier="hyper")


def test_dock_folders(prefs, tmp_path, monkeypatch):
    store, done = prefs
    monkeypatch.setattr(dock.os.path, "realpath", lambda path: path)
    folder = tmp_path / "Projects"
    folder.mkdir()

    added = dock.add_folder(folder, view="grid", sort="name", display="folder")
    assert added == dock.DockFolder(name="Projects", path=folder, view="grid", sort="name", display="folder")
    tile = store[("com.apple.dock", "persistent-others", False)][0]
    assert tile["tile-type"] == "directory-tile" and tile["tile-data"]["showas"] == 2 and tile["tile-data"]["arrangement"] == 1
    dock.add_folder(folder, view="list")  # updated, not added twice
    assert [found.view for found in dock.folders()] == ["list"]
    assert dock.remove_folder(folder) and not dock.remove_folder(folder) and dock.folders() == []
    assert done == ["dock"] * 3
    with pytest.raises(NotADirectoryError):
        dock.add_folder(tmp_path / "missing")
    with pytest.raises(ValueError, match="view must be"):
        dock.add_folder(folder, view="cover_flow")


def test_finder_quit_menu_and_desktop_view(prefs):
    store, done = prefs
    F = "com.apple.finder"
    store[(F, "DesktopViewSettings", False)] = {"IconViewSettings": {"iconSize": 64.0, "arrangeBy": "none", "backgroundType": 0}}

    finder.set_quit_menu()
    assert finder.quit_menu()
    assert finder.desktop_view()["icon_size"] == 64 and finder.desktop_view()["sort"] is None
    finder.set_desktop_view(icon_size=48, sort="kind", show_item_info=True)
    icons = store[(F, "DesktopViewSettings", False)]["IconViewSettings"]
    assert icons == {"iconSize": 48.0, "arrangeBy": "kind", "backgroundType": 0, "showItemInfo": True}  # the rest kept
    finder.set_desktop_view(sort=None)
    assert finder.desktop_view()["sort"] is None
    assert store[(F, "DesktopViewSettings", False)]["IconViewSettings"]["arrangeBy"] == "none"
    assert done == ["finder"] * 3
    with pytest.raises(ValueError, match="icon_size must be from 16 to 128"):
        finder.set_desktop_view(icon_size=200)
    with pytest.raises(ValueError, match="sort must be one of"):
        finder.set_desktop_view(sort="color")
    with pytest.raises(ValueError, match="say what to change"):
        finder.set_desktop_view()


def test_windows_appearance_sound_and_screenshots(prefs, tmp_path, monkeypatch):
    store, done = prefs

    assert windows.animations() and appearance.font_smoothing()
    windows.set_animations(False)
    appearance.set_font_smoothing(False)
    assert store[(G, "AppleFontSmoothing", False)] == 0 and not appearance.font_smoothing() and not windows.animations()
    appearance.set_font_smoothing(True)
    assert (G, "AppleFontSmoothing", False) not in store

    sounds = tmp_path / "Sounds"
    sounds.mkdir()
    (sounds / "Funk.aiff").write_bytes(b"")
    monkeypatch.setattr(macos.sound, "_SOUND_FOLDERS", (sounds,))
    monkeypatch.setattr(macos.sound, "require_macos", lambda: None)
    assert macos.sound.alert_sound() is None and macos.sound.alert_volume() == 1.0 and macos.sound.ui_sounds()
    macos.sound.set_alert_sound("Funk")
    macos.sound.set_alert_volume(0.5)
    macos.sound.set_ui_sounds(False)
    assert store[(G, "com.apple.sound.beep.sound", False)] == str(sounds / "Funk.aiff")
    assert (macos.sound.alert_sound(), macos.sound.alert_volume(), macos.sound.ui_sounds()) == ("Funk", 0.5, False)
    with pytest.raises(ValueError, match="no alert sound is named"):
        macos.sound.set_alert_sound("Boop")
    for pattern in ("*", "F*", "../Sounds/Funk"):  # names, not patterns or paths
        with pytest.raises(ValueError, match="no alert sound is named"):
            macos.sound.set_alert_sound(pattern)
    with pytest.raises(ValueError, match="volume must be"):
        macos.sound.set_alert_volume(2)

    assert screen.screenshot_name() is None and screen.screenshot_target() == "file"
    screen.set_screenshot_name("Capture")
    screen.set_screenshot_target("clipboard")
    assert (screen.screenshot_name(), screen.screenshot_target()) == ("Capture", "clipboard")
    screen.set_screenshot_name(None)
    assert screen.screenshot_name() is None and done.count("capture") == 3
    with pytest.raises(ValueError, match="target must be"):
        screen.set_screenshot_target("printer")
    with pytest.raises(ValueError, match="file name"):
        screen.set_screenshot_name("a/b")


def test_system_region_photos_and_menu_bar(prefs, monkeypatch):
    store, done = prefs
    monkeypatch.setattr(system, "_locale_measurement", lambda: "us")

    assert system.measurement_units() == "us" and system.temperature_unit() == "fahrenheit"
    system.set_measurement_units("metric")
    system.set_temperature_unit("celsius")
    assert store[(G, "AppleMeasurementUnits", False)] == "Centimeters" and store[(G, "AppleMetricUnits", False)] is True
    assert (system.measurement_units(), system.temperature_unit()) == ("metric", "celsius")
    with pytest.raises(ValueError, match="units must be"):
        system.set_measurement_units("imperial")

    assert system.open_photos_on_device_connect()
    system.set_open_photos_on_device_connect(False)
    assert store[("com.apple.ImageCapture", "disableHotPlug", True)] is True and not system.open_photos_on_device_connect()

    assert system.menu_bar_spacing() is None
    system.set_menu_bar_spacing(6)
    assert store[(G, "NSStatusItemSpacing", True)] == 6 and store[(G, "NSStatusItemSelectionPadding", True)] == 6
    system.set_menu_bar_spacing(None)
    assert (G, "NSStatusItemSpacing", True) not in store
    with pytest.raises(ValueError, match="0 to 30"):
        system.set_menu_bar_spacing(40)

    system.set_menu_bar_items(bluetooth=True, now_playing=False)
    C = "com.apple.controlcenter"
    assert store[(C, "Bluetooth", True)] == 18 and store[(C, "NSStatusItem Visible Bluetooth", False)] is True
    assert store[(C, "NowPlaying", True)] == 8 and store[(C, "NSStatusItem Visible NowPlaying", False)] is False
    assert system.menu_bar_items()["bluetooth"] and not system.menu_bar_items()["now_playing"]
    assert done == ["ControlCenter"]
    with pytest.raises(ValueError, match="unknown menu bar items: siri"):
        system.set_menu_bar_items(siri=True)


def test_security_status(monkeypatch):
    answers = {
        "fdesetup": "FileVault is On.\n",
        "/usr/libexec/ApplicationFirewall/socketfilterfw": "Firewall is enabled. (State = 1)\n",
        "spctl": "assessments disabled\n",
        "csrutil": "System Integrity Protection status: unknown (Custom Configuration).\n",
    }
    monkeypatch.setattr(system, "require_macos", lambda: None)
    monkeypatch.setattr(system, "_run", lambda args: answers[args[0]])

    assert system.security_status() == system.SecurityStatus(filevault=True, firewall=True, gatekeeper=False, sip=None)

    def failing(args):
        raise macos.MacOSError("no")

    monkeypatch.setattr(system, "_run", failing)
    assert system.security_status() == system.SecurityStatus(None, None, None, None)


def test_defaults_restored(monkeypatch):
    store = {("com.example", "keep"): 1, ("com.example", "other"): "x"}

    def read(domain, key=None, *, default=None, current_host=False):
        if key is None:
            return {name: value for (where, name), value in store.items() if where == domain}
        return store.get((domain, key), default)

    def write(domain, key, value, *, current_host=False):
        store[(domain, key)] = value

    def delete(domain, key, *, current_host=False):
        return store.pop((domain, key), None) is not None

    monkeypatch.setattr(defaults, "read", read)
    monkeypatch.setattr(defaults, "_own", lambda domain, key, default, current_host: store.get((domain, key), default))
    monkeypatch.setattr(defaults, "write", write)
    monkeypatch.setattr(defaults, "delete", delete)
    monkeypatch.setattr(defaults, "keys", lambda domain, *, current_host=False: sorted(k for d, k in store if d == domain))

    with defaults.restored(("com.example", "keep"), ("com.example", "absent")):
        store[("com.example", "keep")] = 2
        store[("com.example", "absent")] = True
    assert store == {("com.example", "keep"): 1, ("com.example", "other"): "x"}
    with pytest.raises(RuntimeError):
        with defaults.restored("com.example"):
            store[("com.example", "other")] = "y"
            store[("com.example", "added")] = 3
            raise RuntimeError("the block failed")
    assert store == {("com.example", "keep"): 1, ("com.example", "other"): "x"}


def test_batched_restarts():
    ran = []

    def fake_restart():
        if _system.restart_later("Dock", fake_restart):
            return
        ran.append("dock")

    with _system.batched_restarts():
        fake_restart()
        fake_restart()
        with _system.batched_restarts():  # nested: still one batch
            fake_restart()
        assert ran == []
    assert ran == ["dock"]
    with pytest.raises(RuntimeError):
        with _system.batched_restarts():
            fake_restart()
            raise RuntimeError("failed")
    assert ran == ["dock", "dock"]  # restarted anyway, to apply what changed


def test_one_failed_restart_neither_skips_the_others_nor_hides_the_error(monkeypatch):
    ran = []
    warned = []
    monkeypatch.setattr(_system, "add_note", lambda error, message: warned.append(message))

    def restarter(name, fails=False):
        def restart():
            if _system.restart_later(name, restart):
                return
            ran.append(name)
            if fails:
                raise macos.CommandError(["killall", name], 2, "killall: timed out")

        return restart

    with pytest.raises(RuntimeError, match="the setting failed"):  # the block's own error, not killall's
        with _system.batched_restarts():
            restarter("SystemUIServer", fails=True)()
            restarter("Dock")()
            raise RuntimeError("the setting failed")
    assert ran == ["SystemUIServer", "Dock"]  # the Dock still restarted
    assert warned == ["restarting SystemUIServer failed too: 'killall' exited with status 2: killall: timed out"]

    with pytest.raises(macos.CommandError):  # alone, the failed restart is the error
        with _system.batched_restarts():
            restarter("SystemUIServer", fails=True)()


def test_hardware_setting_checks():
    with pytest.raises(ValueError, match="seconds must be positive"):
        macos.keyboard.set_backlight_timeout(0)
    with pytest.raises(ValueError, match="strength must be"):
        screen.set_night_shift_strength(1.5)
    assert screen._clock_time("07:30") == screen.dt_time(7, 30)
    with pytest.raises(ValueError, match="HH:MM"):
        screen._clock_time("7h30")
    mode = screen.DisplayMode(width=1512, height=982, pixel_width=3024, pixel_height=1964, refresh_rate=120.0)
    assert mode.hidpi and not screen.DisplayMode(1920, 1080, 1920, 1080, 60.0).hidpi


def test_defaults_delete_checks_the_domain(fake_run):
    for domain in ("", "   "):
        with pytest.raises(ValueError):
            defaults.delete(domain, "key")


def test_control_center_restart_only_overlooks_it_not_running(monkeypatch):
    def killall(status, message):
        def run(args, **kwargs):
            raise macos.CommandError(args, status, message)

        return run

    # No process: it reads the settings when it starts.
    monkeypatch.setattr(_system, "run", killall(1, "No matching processes belonging to you were found"))
    system._restart_control_center()
    # The same status 1 when it found one it couldn't signal: that restart failed.
    monkeypatch.setattr(_system, "run", killall(1, "kill: 812: Operation not permitted"))
    with pytest.raises(macos.CommandError, match="not permitted"):
        system._restart_control_center()
    monkeypatch.setattr(_system, "run", killall(2, "killall: permission denied"))
    with pytest.raises(macos.CommandError, match="permission denied"):
        system._restart_control_center()
