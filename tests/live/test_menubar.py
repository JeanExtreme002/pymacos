"""Tests of :mod:`macos.menubar` against the real system. Skipped outside macOS.

Each test shows an item in the menu bar for a moment and removes it. Clicks are
made from code (``performActionForItemAtIndex:``), the same path a click takes.
"""

import threading
import time

import pytest

import macos
from macos import _objc, menubar
from macos._objc import BOOL, NSInteger
from tests.helpers import small_png


@pytest.fixture
def item():
    created = []

    def make(*args, **kwargs):
        made = macos.menubar.Item(*args, **kwargs)
        created.append(made)
        return made

    yield make
    for made in created:
        made.remove()
    menubar._clicks.clear()
    menubar._calls.clear()


def _titles(item):
    titles = []
    for index in range(_objc.send(item._menu, "numberOfItems", restype=NSInteger)):
        native = _objc.send(item._menu, "itemAtIndex:", index, argtypes=(NSInteger,))
        separator = _objc.send(native, "isSeparatorItem", restype=BOOL)
        titles.append("-" if separator else _objc.pystring(_objc.send(native, "title")))
    return titles


def _click(item, title):
    index = _titles(item).index(title)
    _objc.send(item._menu, "performActionForItemAtIndex:", index, argtypes=(NSInteger,), restype=None)


def test_menu_entries_go_above_quit_and_run_their_actions(item):
    calls = []
    bar = item("pymacos", tooltip="pymacos test")
    bar.add("Start", lambda: calls.append("start"))
    bar.separator()

    @bar.action("Toggle", key="t", checked=True)
    def toggle():
        calls.append("toggle")

    bar.add("Later", enabled=False)
    assert _titles(bar) == ["Start", "-", "Toggle", "Later", "-", "Quit"]
    assert [entry.title for entry in bar.entries] == ["Start", "Toggle", "Later"]
    assert _objc.pystring(_objc.send(bar._button, "toolTip")) == "pymacos test"

    _click(bar, "Start")
    _click(bar, "Toggle")
    assert calls == []  # actions run in run(), on this thread
    macos.menubar.run(timeout=0.3)
    assert calls == ["start", "toggle"]


def test_entries_and_title_update(item):
    bar = item("pymacos")
    entry = bar.add("Option", checked=True)
    later = bar.add("Later", enabled=False)

    entry.set_checked(False)
    entry.set_title("Renamed")
    later.set_enabled(True)
    bar.set_title("25:00")
    assert (entry.checked, entry.title, later.enabled, bar.title) == (False, "Renamed", True, "25:00")
    assert _objc.send(entry._native, "state", restype=NSInteger) == 0
    assert _objc.pystring(_objc.send(entry._native, "title")) == "Renamed"
    assert _objc.send(later._native, "isEnabled", restype=BOOL)
    assert _objc.pystring(_objc.send(bar._button, "title")) == "25:00"


def test_changes_from_another_thread_wait_for_run(item):
    bar = item("pymacos")
    worker = threading.Thread(target=lambda: bar.set_title("from a thread"))
    worker.start()
    worker.join()
    assert _objc.pystring(_objc.send(bar._button, "title")) == "pymacos"  # not yet: queued
    macos.menubar.run(timeout=0.2)
    assert _objc.pystring(_objc.send(bar._button, "title")) == "from a thread"


def test_every_and_quit(item):
    bar = item("pymacos")
    ticks = []
    timer = macos.menubar.every(0.1, lambda: ticks.append(1))
    try:
        macos.menubar.run(timeout=0.55)
    finally:
        timer.cancel()
    assert 3 <= len(ticks) <= 6

    start = time.monotonic()
    _click(bar, "Quit")
    macos.menubar.run(timeout=5)
    assert time.monotonic() - start < 1


def test_without_quit_entry_and_renamed(item):
    assert _titles(item("a", quit=None)) == []
    assert _titles(item("b", quit="Exit"))[-1] == "Exit"


def test_icon(item, tmp_path):
    png = small_png(32, 16)
    bar = item(icon=png)
    image = _objc.send(bar._button, "image")
    size = _objc.send(image, "size", restype=_objc.CGSize)
    assert (size.width, size.height) == (36, 18)  # menu bar height, same proportions
    assert _objc.send(image, "isTemplate", restype=BOOL)

    path = tmp_path / "icon.png"
    path.write_bytes(png)
    bar.set_icon(path, template=False)
    assert not _objc.send(_objc.send(bar._button, "image"), "isTemplate", restype=BOOL)
    bar.set_icon(None)
    assert not _objc.send(bar._button, "image")

    with pytest.raises(FileNotFoundError):
        bar.set_icon(tmp_path / "missing.png")
    with pytest.raises(ValueError, match="not an image"):
        bar.set_icon(b"not an image")


def test_an_action_error_stops_run(item):
    bar = item("pymacos")

    def broken():
        raise RuntimeError("boom")

    bar.add("Broken", broken)
    _click(bar, "Broken")
    with pytest.raises(RuntimeError, match="boom"):
        macos.menubar.run(timeout=1)


def test_main_thread_only():
    errors = []

    def create():
        try:
            macos.menubar.Item("pymacos")
        except RuntimeError as error:
            errors.append(str(error))

    worker = threading.Thread(target=create)
    worker.start()
    worker.join()
    assert errors and "main thread" in errors[0]


def test_a_bad_icon_leaves_nothing_in_the_menu_bar(monkeypatch):
    calls = []
    send = _objc.send

    def recording(receiver, selector, *args, **kwargs):
        calls.append(selector)
        return send(receiver, selector, *args, **kwargs)

    monkeypatch.setattr(menubar._objc, "send", recording)
    count = len(menubar._items)
    with pytest.raises(ValueError, match="not an image"):
        macos.menubar.Item("pymacos", icon=b"not an image")
    assert "statusItemWithLength:" not in calls  # failed before installing anything
    assert len(menubar._items) == count


def test_remove_forgets_actions_and_detaches_entries(item):
    calls = []
    bar = item("pymacos")
    entry = bar.add("Act", lambda: calls.append(1))
    tags = [entry._tag, bar._quit_entry._tag]
    _click(bar, "Act")  # clicked just before removal: must not run afterwards
    bar.remove()
    assert all(tag not in menubar._actions for tag in tags)
    assert entry._native is None and bar._removed
    entry.set_title("gone")  # no crash: changes to a removed item do nothing
    entry.set_checked(True)
    bar.set_title("gone")
    macos.menubar.run(timeout=0.2)
    assert calls == []


def test_nothing_can_be_added_after_remove(item):
    bar = item("pymacos")
    bar.remove()
    with pytest.raises(RuntimeError, match="removed"):
        bar.add("Late")
    with pytest.raises(RuntimeError, match="removed"):
        bar.separator()
    bar.remove()  # again: nothing happens


def test_remove_from_another_thread(item):
    bar = item("pymacos")
    entry = bar.add("Act", lambda: None)
    worker = threading.Thread(target=bar.remove)
    worker.start()
    worker.join()
    # Queued for the main thread, but no entry may be added in the meantime.
    with pytest.raises(RuntimeError, match="removed"):
        bar.add("Too late")
    assert not bar._removed and entry._tag in menubar._actions
    macos.menubar.run(timeout=0.2)
    assert bar._removed and entry._native is None and entry._tag not in menubar._actions
