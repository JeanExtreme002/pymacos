"""Unit tests for :mod:`macos.ui`. They run on any platform."""

import pytest

import macos
from macos import ui


def _element(**fields):
    """An Element read from ``fields`` (by their AX names), with no app behind it."""
    return ui.Element(0, fields, app="Test", pid=1)


def test_name_is_what_a_person_would_call_it():
    assert _element(AXRole="AXButton", AXTitle="Save", AXDescription="save the file").name == "Save"
    assert _element(AXRole="AXTextField", _label="Your name:", AXPlaceholderValue="Ada").name == "Your name:"
    assert _element(AXRole="AXButton", AXDescription="Back").name == "Back"
    assert _element(AXRole="AXStaticText", AXValue="Hello").name == "Hello"
    assert _element(AXRole="AXTextField", AXPlaceholderValue="Search").name == "Search"
    # A field's text isn't its name: it changes as it's typed.
    assert _element(AXRole="AXTextField", AXValue="typed").name is None
    # A window's buttons have no label: what they are names them.
    close = _element(AXRole="AXButton", AXSubrole="AXCloseButton", AXRoleDescription="close button")
    assert close.name == "close button"
    assert _element(AXRole="AXGroup", AXSubrole="AXApplicationGroup", AXRoleDescription="group").name is None


def test_text_loses_its_direction_marks():
    element = _element(AXRole="AXStaticText", AXValue="‎7‎×‎6")
    assert element.value == "7×6" and element.name == "7×6"
    assert _element(AXRole="AXButton", AXTitle="  ").name is None


def test_fields():
    element = _element(
        AXRole="AXCheckBox",
        AXValue=1,
        AXPosition=(10.4, 20.6),
        AXSize=(100.0, 24.0),
        AXEnabled=False,
        AXFocused=True,
        _actions=["AXPress"],
    )
    assert element.frame == (10, 21, 100, 24) and element.center == (60, 33)
    assert element.checked is True and element.enabled is False and element.focused is True
    assert element.role_description == "check box"  # when macOS gave none
    assert _element(AXRole="AXCheckBox", AXValue=2).checked is None  # mixed
    assert _element(AXRole="AXButton", AXValue=1).checked is None  # not a checkbox
    assert _element(AXRole="AXButton").frame is None and _element(AXRole="AXButton").center is None
    assert _element(AXRole="AXButton", AXValue=(1.0, 2.0)).value is None  # a point isn't a value to show
    assert _element().role == "AXUnknown" and _element(AXEnabled=None).enabled


def test_is_control():
    assert ui._is_control("AXButton", None, [], False)
    assert ui._is_control("AXStaticText", "AXSearchField", [], False)  # a search field built as text
    assert ui._is_control("AXRow", None, [], False)
    assert not ui._is_control("AXStaticText", None, ["AXPress"], False)
    assert not ui._is_control("AXWindow", None, ["AXRaise"], False)
    assert ui._is_control("AXGroup", None, ["AXPress"], False)
    # In a web page, Chrome says every paragraph can be pressed: only the role counts there.
    assert not ui._is_control("AXGroup", None, ["AXPress"], False, web=True)
    assert ui._is_control("AXLink", None, ["AXPress"], False, web=True)


def test_a_box_around_controls_is_left_out():
    box = {"AXRole": "AXGroup", "_actions": ["AXPress"]}
    button = {"AXRole": "AXButton", "AXTitle": "OK"}
    text = {"AXRole": "AXStaticText", "AXValue": "hi"}
    assert ui._wraps_controls([(1, box), (2, button)], 0)
    assert not ui._wraps_controls([(1, box), (2, text)], 0)  # it's the control, with only text in it
    assert not ui._wraps_controls([(1, dict(box, AXTitle="Card")), (2, button)], 0)  # named: kept
    assert not ui._wraps_controls([(1, button), (2, button)], 0)  # a control by its role: kept


def test_matches_a_role_said_any_way():
    field = _element(AXRole="AXTextField", AXSubrole="AXSearchField", AXRoleDescription="campo de busca",
                     AXPlaceholderValue="Search mail")
    for role in ("AXTextField", "text field", "Text_Field", "search field", "AXSearchField", "campo de busca"):
        assert ui._matches(field, None, role), role
    assert not ui._matches(field, None, "button")
    assert ui._matches(field, "MAIL", None)  # in its placeholder, ignoring case
    assert ui._matches(field, "mail", "text field") and not ui._matches(field, "inbox", "text field")
    assert ui._short_role("AXPopUpButton") == "pop up button"


def test_shortcut():
    assert ui._shortcut("S", 0, None) == "cmd+s"
    assert ui._shortcut("S", 1, None) == "shift+cmd+s"
    assert ui._shortcut("Q", 2 | 4, None) == "ctrl+option+cmd+q"
    assert ui._shortcut("a", 8 | 4, None) == "ctrl+a"  # no command key
    assert ui._shortcut(None, 0, 36) == "cmd+return"  # no modifier flag: ⌘ alone
    assert ui._shortcut("\uf700", 8, None) == "up"  # the private-use character AppKit gives an arrow
    assert ui._shortcut("\uf704", 1 | 8, None) == "shift+f1"
    assert ui._shortcut("\x1b", 2, None) == "option+cmd+escape"  # Force Quit
    assert ui._shortcut(None, 0, None) is None and ui._shortcut("", 0, 9999) is None
    assert ui._shortcut("F", 8 | 16, None) == "fn+f"  # Enter Full Screen: the fn (🌐) key, without ⌘
    assert ui._shortcut("F", 16 | 4, None) == "fn+ctrl+cmd+f"
    # A picture of a key that can't be pressed isn't a shortcut to give.
    assert ui._shortcut("🎤", 8, 128) is None and ui._shortcut("🌐", 8, 128) is None
    assert ui._shortcut("ç", 0, None) == "cmd+ç"


def test_an_open_submenu_is_kept_once():
    # The submenu's range (found first) lies inside its menu's: each element once, in reading order.
    assert ui._within([(2, 4), (0, 5)], 5) == [0, 1, 2, 3, 4]
    assert ui._within([(1, 3), (4, 6)], 7) == [1, 2, 4, 5]
    assert ui._within([(1, 9)], 3) == [1, 2]


def test_menu_entries_release_every_item(monkeypatch):
    released = []
    monkeypatch.setattr(ui, "_owned_list", lambda menu, attribute: [1, 2, 3])
    monkeypatch.setattr(ui, "_read_many", lambda item, attributes: (ui._SUCCESS, {"AXTitle": "Item {}".format(item)}))
    monkeypatch.setattr(ui, "_python", lambda value: value)
    monkeypatch.setattr(ui._cf, "release", lambda ref: released.append(ref) if ref else None)

    entries = ui._menu_entries(0, ui._Budget())
    assert next(entries) == (1, {"AXTitle": "Item 1"})
    entries.close()  # as a walk that stops at its match

    assert released == [1, 2, 3]


def test_menu_paths():
    assert ui._parse_path("File > Save As…") == ["File", "Save As…"]
    assert ui._parse_path(["Format", " Font ", "Bold"]) == ["Format", "Font", "Bold"]
    for bad in ("File", "File > ", ["File"], ""):
        with pytest.raises(ValueError, match="must name a menu and an item"):
            ui._parse_path(bad)
    assert ui._same("Save As…", "save as...") and ui._same("Export…", "Export")
    assert not ui._same("Save", "Save As…")


def test_geometry():
    assert ui._intersection((0, 0, 100, 100), (50, 50, 100, 100)) == (50, 50, 50, 50)
    assert ui._intersection((0, 0, 10, 10), (10, 0, 10, 10)) is None  # touching isn't overlapping
    assert ui._inside((5, 5), (0, 0, 10, 10)) and not ui._inside((10, 5), (0, 0, 10, 10))


def test_find_needs_something_to_look_for():
    with pytest.raises(ValueError, match="give a name, a role, or both"):
        macos.ui.find("Safari")


def test_wait_for(monkeypatch):
    answers = iter([[], macos.AppNotFoundError("not yet"), ["the element"]])

    def find(app=None, name=None, role=None):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(ui, "find", find)
    monkeypatch.setattr(ui.time, "sleep", lambda seconds: None)

    assert ui.wait_for("Safari", name="Done") == "the element"  # waits for the app to start too
    monkeypatch.setattr(ui, "find", lambda app=None, name=None, role=None: [])
    assert ui.wait_for(name="Done", timeout=0) is None
    with pytest.raises(ValueError, match="interval must be positive"):
        ui.wait_for(name="Done", interval=0)


def test_values_to_set():
    with pytest.raises(ValueError, match="text, a number or True/False"):
        ui._to_cf(None)
    with pytest.raises(ValueError, match="finite"):
        ui._to_cf(float("nan"))


def test_at_checks_the_point():
    with pytest.raises(ValueError, match="finite"):
        macos.ui.at(float("inf"), 0)


def test_text_is_gathered_without_direction_marks(monkeypatch):
    read = {"AXRole": "AXStaticText", "AXValue": "\u200e7\u200e×\u200e6 "}
    monkeypatch.setattr(ui, "_read_many", lambda element, attributes: (ui._SUCCESS, dict(read)))
    monkeypatch.setattr(ui, "_python", lambda value: value)
    monkeypatch.setattr(ui._cf, "items", lambda ref: [])
    monkeypatch.setattr(ui._cf, "release", lambda ref: None)

    assert _element(AXRole="AXWindow").text() == "7×6"
