"""Tests of :mod:`macos.ui` against the real system, on a window of their own. Skipped outside macOS."""

import time

import pytest

import macos


def _app_of(window):
    return next(app for app in macos.apps.running(include_background=True) if app.pid == window.pid)


def _until(read, check, seconds=3.0):
    """``read()`` again until ``check`` accepts it, or the time is up: the app redraws after a change."""
    deadline = time.monotonic() + seconds
    while True:
        found = read()
        if check(found) or time.monotonic() > deadline:
            return found
        time.sleep(0.1)


def test_elements_lists_the_window_controls(controls_window):
    app = _app_of(controls_window)
    controls_window.focus()

    found = macos.ui.elements(app)

    by_name = {element.name: element for element in found}
    assert by_name["Remember me"].role == "AXCheckBox"
    assert by_name["Remember me"].checked is False
    assert by_name["Your name"].role == "AXTextField"
    assert by_name["Push"].role == "AXButton" and "AXPress" in by_name["Push"].actions
    assert all(element.is_control and element.frame for element in found)
    # Inside the window, in points as the mouse takes them.
    x, y, width, height = controls_window.frame
    for element in found:
        center_x, center_y = element.center
        assert x <= center_x <= x + width and y <= center_y <= y + height


def test_press_set_value_and_focus(controls_window):
    app = _app_of(controls_window)
    controls_window.focus()

    checkbox = macos.ui.find(app, name="remember", role="check box")[0]
    checkbox.press()
    checked = _until(lambda: macos.ui.find(app, name="Remember me")[0], lambda element: element.checked)
    assert checked.checked is True

    field = macos.ui.find(app, name="Your name", role="text field")[0]
    field.set_value("Ada")
    assert _until(lambda: macos.ui.find(app, role="AXTextField")[0].value, lambda value: value == "Ada") == "Ada"

    field.focus()
    focused = _until(macos.ui.focused, lambda element: element is not None and element.role == "AXTextField")
    if focused is None or focused.pid != app.pid:
        pytest.skip("another app took the focus meanwhile")
    assert focused.role == "AXTextField"

    with pytest.raises(macos.MacOSError):
        macos.ui.find(app, name="Push")[0].set_value("no")  # a button holds no text


def test_at_and_wait_for(controls_window):
    app = _app_of(controls_window)
    controls_window.focus()
    button = macos.ui.find(app, name="Push", role="button")[0]

    there = _until(lambda: macos.ui.at(*button.center), lambda element: element is not None and element.pid == app.pid)
    if there is None or there.pid != app.pid:
        pytest.skip("another window covers the test window")
    assert there.role == "AXButton"

    assert macos.ui.wait_for(app, name="Push", timeout=2).name == "Push"
    assert macos.ui.wait_for(app, name="not in this window", timeout=0.3) is None


def test_children_and_text(controls_window):
    app = _app_of(controls_window)
    controls_window.focus()

    checkbox = macos.ui.find(app, name="Remember me")[0]

    assert checkbox.children() == []
    assert "Remember me" in checkbox.text()


def test_menu_items_of_finder():
    if not macos.windows.has_permission():
        pytest.skip("no Accessibility permission")
    finder = macos.apps.get("com.apple.finder")
    if finder is None:
        pytest.skip("Finder isn't running")

    items = macos.ui.menu_items(finder)

    assert items and all(len(item.path) >= 2 for item in items)
    assert any(item.shortcut and item.shortcut.startswith("cmd") for item in items)
    with pytest.raises(LookupError, match="no 'not a menu'"):
        macos.ui.click_menu_item("not a menu > nothing", app=finder)  # found nothing, so clicked nothing


def test_an_app_that_isnt_running():
    if not macos.windows.has_permission():
        pytest.skip("no Accessibility permission")

    with pytest.raises(macos.AppNotFoundError):
        macos.ui.elements("not an app that runs 7f3a")
