"""Unit tests for :mod:`macos.keyboard`. They run on any platform."""

import pytest

import macos


def test_press_holds_the_modifiers_around_the_key(fake_events):
    macos.keyboard.press("cmd+shift+c")

    keys = [(event["code"], event["down"], event["flags"]) for event in fake_events.posted]
    cmd, shift = 1 << 20, 1 << 17
    assert keys == [
        (55, True, cmd),
        (56, True, cmd | shift),
        (8, True, cmd | shift),
        (8, False, cmd | shift),
        (56, False, cmd),
        (55, False, 0),
    ]


def test_press_a_modifier_alone_sets_its_flag(fake_events):
    macos.keyboard.press("shift")
    macos.keyboard.press("cmd+option")

    keys = [(event["code"], event["down"], event["flags"]) for event in fake_events.posted]
    shift, cmd, option = 1 << 17, 1 << 20, 1 << 19
    assert keys == [
        (56, True, shift),
        (56, False, 0),
        (55, True, cmd),
        (58, True, cmd | option),
        (58, False, cmd),
        (55, False, 0),
    ]


def test_press_adds_shift_for_shifted_characters(fake_events):
    macos.keyboard.press("cmd++")
    macos.keyboard.press("C")  # letters are keys: no Shift

    codes = [event["code"] for event in fake_events.posted if event["down"]]
    assert codes == [55, 56, 24, 8]


def test_type_sends_text_in_pieces_and_presses_enter_and_tab(fake_events):
    macos.keyboard.type("héllo 😀\n\tok")

    typed = [(event["code"], event["text"]) for event in fake_events.posted if event["down"]]
    assert typed == [(0, "héllo 😀"), (36, None), (48, None), (0, "ok")]
    assert [event["text"] for event in fake_events.posted if not event["down"]] == ["héllo 😀", None, None, "ok"]


def test_type_one_character_at_a_time_with_an_interval(fake_events, monkeypatch):
    monkeypatch.setattr(macos.keyboard.time, "sleep", lambda seconds: None)

    macos.keyboard.type("a😀", interval=0.01)

    assert [event["text"] for event in fake_events.posted if event["down"]] == ["a", "😀"]


def test_typing_splits_long_text_without_breaking_characters():
    pieces = macos.keyboard._chunks("ab😀" * 10, 5)

    assert "".join(pieces) == "ab😀" * 10
    assert all(len(piece.encode("utf-16-le")) // 2 <= 5 for piece in pieces)


def test_events_need_the_accessibility_permission(fake_events, monkeypatch):
    from macos import _events

    monkeypatch.setattr(_events, "has_permission", lambda: False)

    for call in (lambda: macos.keyboard.type("x"), lambda: macos.mouse.click(), lambda: macos.mouse.scroll(1)):
        with pytest.raises(macos.PermissionDeniedError, match="Accessibility"):
            call()
    assert fake_events.posted == []


def test_hold_keeps_modifiers_down_for_clicks_and_keys(fake_events):
    shift, cmd = 1 << 17, 1 << 20

    with macos.keyboard.hold("shift"):
        macos.mouse.click(5, 5)
        with macos.keyboard.hold("cmd"):
            macos.keyboard.press("c")

    posted = [(event["kind"], event.get("code"), event.get("down"), event["flags"]) for event in fake_events.posted]
    assert posted == [
        ("key", 56, True, shift),
        (5, None, None, shift),  # the click and its move carry Shift
        (1, None, None, shift),
        (2, None, None, shift),
        ("key", 55, True, shift | cmd),
        ("key", 8, True, shift | cmd),
        ("key", 8, False, shift | cmd),
        ("key", 55, False, shift),
        ("key", 56, False, 0),
    ]
    assert macos._events.held() == []


def test_hold_releases_the_keys_when_the_block_fails(fake_events):
    with pytest.raises(RuntimeError):
        with macos.keyboard.hold("cmd+shift"):
            raise RuntimeError("boom")

    released = [(event["code"], event["flags"]) for event in fake_events.posted if not event["down"]]
    assert released == [(56, 1 << 20), (55, 0)]
    assert macos._events.held() == []


def _off_the_main_thread(function):
    import threading

    result = []

    def run():
        try:
            result.append(function())
        except Exception as error:
            result.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    worker.join()
    return result[0]


def test_shortcuts_off_the_main_thread_use_a_us_keyboard_on_a_us_layout(monkeypatch):
    monkeypatch.setattr(macos.keyboard, "_LAYOUTS", {})
    monkeypatch.setattr(macos.keyboard, "_current_layout_id", lambda: "com.apple.keylayout.ABC")

    parsed = _off_the_main_thread(lambda: [macos.keyboard._parse(keys) for keys in ("cmd+plus", "?", "a")])

    cmd = [(1 << 20, 55)]
    assert parsed == [(cmd, 24, True), ([], 44, True), ([], 0, False)]  # Shift+= types "+"


def test_shortcuts_off_the_main_thread_use_the_layout_the_main_thread_read(monkeypatch):
    azerty = {"a": (12, False), "q": (0, False)}
    monkeypatch.setattr(macos.keyboard, "_LAYOUTS", {"com.apple.keylayout.French": azerty})
    monkeypatch.setattr(macos.keyboard, "_current_layout_id", lambda: "com.apple.keylayout.French")

    assert _off_the_main_thread(lambda: macos.keyboard._parse("cmd+a")) == ([(1 << 20, 55)], 12, False)


def test_shortcuts_off_the_main_thread_refuse_a_layout_never_read(monkeypatch):
    # On AZERTY the US table's "a" is the Q key: Cmd+A would quit the app in front.
    monkeypatch.setattr(macos.keyboard, "_LAYOUTS", {})
    monkeypatch.setattr(macos.keyboard, "_current_layout_id", lambda: "com.apple.keylayout.French")

    error = _off_the_main_thread(lambda: macos.keyboard._parse("cmd+a"))

    assert isinstance(error, macos.MacOSError)
    assert "French" in str(error) and "main thread" in str(error)


def _layout_preferences(monkeypatch, current, enabled):
    import contextlib
    from types import SimpleNamespace

    saved = {"AppleCurrentKeyboardLayoutInputSourceID": current, "AppleEnabledInputSources": enabled}
    cf = SimpleNamespace(
        owned=contextlib.nullcontext,
        string=lambda text: 1,
        lib=lambda: SimpleNamespace(CFPreferencesAppSynchronize=lambda domain: True),
    )
    monkeypatch.setattr(macos.keyboard, "_cf", cf)
    monkeypatch.setattr(macos.defaults, "read", lambda domain, key, default=None: saved[key] or default)
    return saved


def _keyboard_layout(number):
    return {"InputSourceKind": "Keyboard Layout", "KeyboardLayout ID": number}


def test_the_layout_in_use_is_read_from_the_preferences(monkeypatch):
    _layout_preferences(monkeypatch, "com.apple.keylayout.French", [_keyboard_layout(1)])
    assert macos.keyboard._current_layout_id() == "com.apple.keylayout.French"


@pytest.mark.parametrize(
    "enabled, expected",
    [
        ([_keyboard_layout(0), {"InputSourceKind": "Non Keyboard Input Method"}], "com.apple.keylayout.US"),
        ([_keyboard_layout(252), _keyboard_layout(15000)], "com.apple.keylayout.US"),  # ABC, US International
        ([_keyboard_layout(0), _keyboard_layout(1)], ""),  # US and French: either may be in use
        ([], ""),
        (None, ""),
    ],
)
def test_an_unsaved_layout_is_taken_for_us_only_when_every_enabled_one_is(monkeypatch, enabled, expected):
    _layout_preferences(monkeypatch, None, enabled)
    assert macos.keyboard._current_layout_id() == expected


def test_a_layout_switch_shows_at_the_very_next_key(monkeypatch):
    # Not cached: Cmd+A pressed right after a switch to AZERTY must find the Q key, not the US A.
    saved = _layout_preferences(monkeypatch, "com.apple.keylayout.US", None)
    assert macos.keyboard._current_layout_id() == "com.apple.keylayout.US"
    saved["AppleCurrentKeyboardLayoutInputSourceID"] = "com.apple.keylayout.French"
    assert macos.keyboard._current_layout_id() == "com.apple.keylayout.French"


def test_an_unnamed_layout_off_the_main_thread_is_the_one_the_main_thread_read(monkeypatch):
    # A French-only account that never switched layouts doesn't save the ID: layout() on the main thread is enough.
    azerty = {"a": (12, False), "q": (0, False)}
    monkeypatch.setattr(macos.keyboard, "_LAYOUTS", {"com.apple.keylayout.French": azerty})
    monkeypatch.setattr(macos.keyboard, "_LAST_READ", ["com.apple.keylayout.French"])
    monkeypatch.setattr(macos.keyboard, "_current_layout_id", lambda: "")

    assert _off_the_main_thread(lambda: macos.keyboard._parse("cmd+a")) == ([(1 << 20, 55)], 12, False)

    monkeypatch.setattr(macos.keyboard, "_LAST_READ", [])  # never read: still refused
    assert isinstance(_off_the_main_thread(lambda: macos.keyboard._parse("cmd+a")), macos.MacOSError)


def test_press_releases_the_modifiers_down_when_a_post_fails(fake_events, monkeypatch):
    from macos import _events

    posted = []

    def post(event):
        fields = fake_events.events[event]
        if fields["code"] == 8 and fields["down"]:
            raise macos.MacOSError("the window server said no")
        posted.append((fields["code"], fields["down"]))

    monkeypatch.setattr(_events, "post", post)
    with pytest.raises(macos.MacOSError):
        macos.keyboard.press("cmd+shift+c")

    # The C key may have gone down before the error: it's let up too. Nothing is left down.
    assert posted == [(55, True), (56, True), (8, False), (56, False), (55, False)]


def test_ctrl_c_between_a_key_down_and_up_lets_the_key_up(fake_events, monkeypatch):
    from macos import _events

    posted = []
    interrupted = []

    def post(event):
        fields = fake_events.events[event]
        if fields["code"] == 8 and not fields["down"] and not interrupted:
            interrupted.append(True)
            raise KeyboardInterrupt  # in post()'s pause, after the key went down
        posted.append((fields["code"], fields["down"]))

    monkeypatch.setattr(_events, "post", post)
    with pytest.raises(KeyboardInterrupt):
        macos.keyboard.press("cmd+c")

    assert posted == [(55, True), (8, True), (8, False), (55, False)]  # C doesn't stay down, nor Cmd


def test_type_presses_enter_once_for_each_line_ending(fake_events):
    macos.keyboard.type("a\r\nb\rc\nd")

    typed = [(event["code"], event["text"]) for event in fake_events.posted if event["down"]]
    assert typed == [(0, "a"), (36, None), (0, "b"), (36, None), (0, "c"), (36, None), (0, "d")]


def test_caps_lock(fake_events):
    assert macos.keyboard.caps_lock() is False
    fake_events.flags_state = (1 << 16) | (1 << 17)  # Caps Lock and Shift
    assert macos.keyboard.caps_lock() is True


def test_keyboard_argument_checks():
    with pytest.raises(ValueError, match="0.0 to 1.0"):
        macos.keyboard.set_brightness(1.5)
    with pytest.raises(ValueError, match="interval"):
        macos.keyboard.type("x", interval=-1)
    with pytest.raises(ValueError, match="times"):
        macos.keyboard.press("enter", times=0)
    with pytest.raises(ValueError, match="needs a key"):
        macos.keyboard.press("  ")
    with pytest.raises(ValueError, match="not a modifier"):
        macos.keyboard.press("hyper+c")
    with pytest.raises(ValueError, match="no key after"):
        macos.keyboard.press("cmd+")
    with pytest.raises(ValueError, match="unknown key"):
        macos.keyboard.press("cmd+launch")
    with pytest.raises(ValueError, match="at least one key"):
        macos.keyboard.hold().__enter__()


def test_key_press_shortcut():
    key = macos.keyboard.KeyPress(key="k", modifiers=("cmd", "shift"), text="K", code=40, repeat=False)

    assert key.shortcut == "cmd+shift+k"
    assert macos.keyboard.KeyPress("enter", (), "", 36, False).shortcut == "enter"
    assert macos.keyboard._KEY_NAMES[36] == "enter" and macos.keyboard._KEY_NAMES[51] == "delete"


def test_type_ignores_the_keys_held(fake_events):
    with macos.keyboard.hold("cmd"):
        macos.keyboard.type("x\n")

    typed = [(event["code"], event["text"], event["flags"]) for event in fake_events.posted if event["code"] != 55]
    # Without Cmd: the text rides on the "a" key, which a held Cmd would make Cmd+A.
    assert typed == [(0, "x", 0), (0, "x", 0), (36, None, 0), (36, None, 0)]


def test_hold_releases_every_key_even_when_one_fails(fake_events, monkeypatch):
    from macos import _events

    posted = []

    def post(event):
        details = fake_events.events[event]
        if details["code"] == 56 and not details["down"]:
            raise macos.MacOSError("Shift is stuck")
        posted.append(details)

    monkeypatch.setattr(_events, "post", post)
    with pytest.raises(macos.MacOSError, match="Shift is stuck"):
        with macos.keyboard.hold("cmd+shift+option"):
            pass

    assert [event["code"] for event in posted if not event["down"]] == [58, 55]  # Option and Cmd still came up
    assert _events.held() == []


def test_keys_held_on_one_thread_do_not_reach_another(fake_events):
    import threading

    clicked = threading.Event()
    with macos.keyboard.hold("shift"):
        worker = threading.Thread(target=lambda: (macos.mouse.click(1, 1), clicked.set()))
        worker.start()
        worker.join()
    assert clicked.is_set()
    clicks = [event for event in fake_events.posted if event["kind"] != "key"]
    assert clicks and all(event["flags"] == 0 for event in clicks)


def test_layouts_only_on_the_main_thread():
    import threading

    errors = []

    def call():
        for function in (macos.keyboard.layout, macos.keyboard.layouts, lambda: macos.keyboard.set_layout("ABC")):
            try:
                function()
            except macos.MacOSError as error:
                errors.append(str(error))

    worker = threading.Thread(target=call)
    worker.start()
    worker.join()
    assert len(errors) == 3 and all("main thread" in error for error in errors)


def test_backlight_ids_are_released(monkeypatch):
    from macos import keyboard

    sent = []

    class FakeObjC:
        BOOL = bool

        def cls(self, name):
            return name

        def new(self, name):
            return "client"

        def nsarray(self, array):
            return [7] if array else []

        def send(self, receiver, selector, *args, **kwargs):
            sent.append((receiver, selector))
            if selector == "copyKeyboardBacklightIDs":
                return "ids"
            if selector == "unsignedLongLongValue":
                return 7
            return True

    monkeypatch.setattr(keyboard, "private_framework", lambda name: None)
    monkeypatch.setattr(keyboard, "framework", lambda name: None)
    monkeypatch.setattr(keyboard, "_objc", FakeObjC())

    assert keyboard._backlight() == ("client", 7)
    assert ("ids", "release") in sent  # copy… returns an array we own


def test_shortcut_keys_are_appkit_function_keys():
    keys = macos.keyboard._SHORTCUT_KEYS
    assert (keys["up"], keys["page_down"], keys["f1"]) == ("", "", "")


def test_a_layout_read_for_one_keyboard_is_read_again_for_another(monkeypatch):
    from types import SimpleNamespace

    # ISO and ANSI keyboards put some keys elsewhere: a table read for one isn't the other's.
    kind = [41]  # ISO
    carbon = SimpleNamespace(
        TISCopyCurrentKeyboardLayoutInputSource=lambda: 1,
        LMGetKbdType=lambda: kind[0],
        TISGetInputSourceProperty=lambda source, key: None,  # read again: no data, so the US table
    )
    iso = {"a": (12, False)}
    monkeypatch.setattr(macos.keyboard, "_text_input", lambda: carbon)
    monkeypatch.setattr(macos.keyboard, "_source_property", lambda source, name: "com.apple.keylayout.French")
    monkeypatch.setattr(macos.keyboard._cf, "lib", lambda: None)
    monkeypatch.setattr(macos.keyboard._cf, "release", lambda ref: None)
    monkeypatch.setattr(macos.keyboard.ctypes.c_void_p, "in_dll", lambda library, name: SimpleNamespace(value=1))
    monkeypatch.setattr(macos.keyboard, "_LAYOUTS", {"com.apple.keylayout.French": iso})
    monkeypatch.setattr(macos.keyboard, "_KEYBOARD_TYPES", {"com.apple.keylayout.French": 41})
    monkeypatch.setattr(macos.keyboard, "_LAST_READ", [])

    assert macos.keyboard._layout() is iso  # the same keyboard: the table already read
    kind[0] = 40  # an ANSI keyboard plugged in
    assert macos.keyboard._layout() is not iso
