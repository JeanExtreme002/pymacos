"""Unit tests for :mod:`macos.menubar`. They run on any platform and create no menu bar items."""

import os

import pytest

import macos
from macos import menubar


def test_item_needs_a_title_or_an_icon():
    with pytest.raises(ValueError, match="title, an icon, or both"):
        macos.menubar.Item()


@pytest.mark.parametrize("seconds", [0, -1, float("nan")])
def test_every_needs_a_positive_interval(seconds):
    with pytest.raises(ValueError, match="positive"):
        macos.menubar.every(seconds, lambda: None)


def _called(now):
    """The timers _pump would call at ``now``, each moved on as it does."""
    return [timer for timer in menubar._due_timers(now) if menubar._advance(timer, now)]


def test_timers_skip_missed_ticks_instead_of_bursting():
    timer = macos.menubar.every(1.0, lambda: None)
    try:
        assert timer._next is None  # not counting yet: run() hasn't started
        assert _called(9.0) == [] and timer._next == 10.0  # the first turn arms it, a full interval ahead
        assert _called(9.9) == []
        assert _called(10.0) == [timer]
        assert timer._next == 11.0
        # Busy for 5 s: one call now, the next a full interval later.
        assert _called(16.0) == [timer]
        assert timer._next == 17.0
        assert _called(16.1) == []  # not again at the next slice
        assert _called(17.0) == [timer]
        assert timer._next == 18.0
    finally:
        timer.cancel()
    assert timer not in menubar._timers
    assert menubar._due_timers(1e9) == []


def test_quit_stops_run_from_anywhere():
    import threading

    running = threading.Event()
    menubar._running.append(running)  # as run() does when it starts
    try:
        macos.menubar.quit()
        assert running.is_set()
    finally:
        menubar._running.remove(running)


def test_a_quit_while_nothing_runs_does_not_stop_the_next_run(monkeypatch):
    macos.menubar.quit()  # nothing runs: nothing to stop

    pumped = []
    monkeypatch.setattr(menubar, "_require_main_thread", lambda what: None)
    monkeypatch.setattr(menubar, "_application", lambda: 1)
    monkeypatch.setattr(menubar, "_pump", lambda app, wait: pumped.append(wait))
    menubar.run(timeout=0.05)
    assert pumped  # it ran until its timeout
    assert menubar._running == []

    def quit_from_an_action(app, wait):
        pumped.append(wait)
        macos.menubar.quit()

    pumped.clear()
    monkeypatch.setattr(menubar, "_pump", quit_from_an_action)
    menubar.run(timeout=5)
    assert len(pumped) == 1 and menubar._running == []


def test_changes_queued_off_the_main_thread_keep_only_a_setter_s_last_value(monkeypatch):
    import threading

    done = []
    monkeypatch.setattr(menubar, "_calls", menubar.OrderedDict())

    def from_a_worker():
        owner = object()
        for second in range(1000):  # a title updated every second while nothing runs
            menubar._on_main(lambda second=second: done.append(("title", second)), (owner, "setTitle:"))
        menubar._on_main(lambda: done.append("icon"))  # not a setter's value: never replaced
        menubar._on_main(lambda: done.append("icon again"))

    worker = threading.Thread(target=from_a_worker)
    worker.start()
    worker.join()
    assert len(menubar._calls) == 3

    monkeypatch.setattr(menubar._objc, "send", lambda *args, **kwargs: None)
    monkeypatch.setattr(menubar._objc, "nsstring", lambda text: text)
    monkeypatch.setattr(menubar._objc, "cls", lambda name: 1)  # no AppKit: these tests run on Linux too
    monkeypatch.setattr(menubar, "_due_timers", lambda now: [])

    class _Pool:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(menubar._objc, "autorelease_pool", _Pool)
    menubar._pump(1, 0)
    assert done == [("title", 999), "icon", "icon again"] and not menubar._calls


class _Pool:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _fake_appkit(monkeypatch, on_main=True):
    """No AppKit: record what would be sent, as ``(receiver, selector, args)``; changes run now on the "main" thread."""
    sent = []
    monkeypatch.setattr(menubar, "_calls", menubar.OrderedDict())
    monkeypatch.setattr(menubar._files, "on_main_thread", lambda: on_main)
    monkeypatch.setattr(menubar._objc, "send", lambda receiver, selector, *args, **kw: sent.append((receiver, selector, args)))
    monkeypatch.setattr(menubar._objc, "nsstring", lambda text: text)
    monkeypatch.setattr(menubar._objc, "cls", lambda name: 1)
    monkeypatch.setattr(menubar._objc, "autorelease_pool", _Pool)
    return sent


def _from_a_worker(function):
    import threading

    errors = []

    def work():
        try:
            function()
        except BaseException as e:  # raised on the worker: handed back to the test
            errors.append(e)

    worker = threading.Thread(target=work)
    worker.start()
    worker.join()
    if errors:
        raise errors[0]


def test_a_change_on_the_main_thread_drops_an_older_one_still_queued(monkeypatch):
    sent = _fake_appkit(monkeypatch)
    entry = menubar.MenuItem(5, 1, "Sync", None, True, False)
    main = menubar._files.on_main_thread

    monkeypatch.setattr(menubar._files, "on_main_thread", lambda: False)
    _from_a_worker(lambda: (entry.set_title("Syncing…"), entry.set_checked(True)))
    assert len(menubar._calls) == 2

    monkeypatch.setattr(menubar._files, "on_main_thread", main)
    entry.set_title("Done")  # newer, on the main thread: shown at once
    entry.set_checked(False)
    assert not menubar._calls  # the worker's older changes would have undone these
    menubar._pump(1, 0)
    assert [(s, a) for _, s, a in sent if s in ("setTitle:", "setState:")] == [("setTitle:", ("Done",)), ("setState:", (0,))]
    assert entry.title == "Done" and entry.checked is False


def test_a_text_utf8_cannot_hold_fails_at_the_call_and_keeps_the_old_one(monkeypatch):
    _fake_appkit(monkeypatch, on_main=False)
    entry = menubar.MenuItem(5, 1, "Mail", None, True, False)
    item = object.__new__(menubar.Item)
    item._title, item._tooltip = "Mail", None

    with pytest.raises(UnicodeEncodeError):
        _from_a_worker(lambda: entry.set_title("Mail \udc80"))
    with pytest.raises(UnicodeEncodeError):
        _from_a_worker(lambda: item.set_title("Mail \udc80"))
    with pytest.raises(UnicodeEncodeError):
        _from_a_worker(lambda: item.set_tooltip("\udc80"))
    assert entry.title == "Mail" and item.title == "Mail" and item.tooltip is None
    assert not menubar._calls  # nothing left to fail later inside run()


@pytest.mark.parametrize(
    "kwargs", [{"title": "Mail \udc80"}, {"title": "Mail", "tooltip": "\udc80"}, {"title": "Mail", "quit": "\udc80"}]
)
def test_an_item_with_a_bad_text_fails_before_anything_is_in_the_menu_bar(monkeypatch, kwargs):
    monkeypatch.setattr(menubar, "_require_main_thread", lambda what: None)

    def no_appkit():
        raise AssertionError("nothing native may be made")

    monkeypatch.setattr(menubar, "_application", no_appkit)
    monkeypatch.setattr(menubar, "_image", lambda icon, template: no_appkit())
    with pytest.raises(UnicodeEncodeError):
        menubar.Item(icon=b"png", **kwargs)


def test_icons_set_from_a_worker_keep_one_image_waiting(monkeypatch):
    sent = _fake_appkit(monkeypatch, on_main=False)
    item = object.__new__(menubar.Item)
    item._button, item._removed = 7, False
    item._next_icon, item._icon_waiting = None, False

    def spin():
        for image in (101, 102, 103):  # a spinner, while run() isn't turning
            item._show_icon(image)

    _from_a_worker(spin)
    assert len(menubar._calls) == 1
    assert sent == [(101, "release", ()), (102, "release", ())]  # never shown: released at once
    sent.clear()
    menubar._pump(1, 0)
    assert [(r, s, a) for r, s, a in sent if s in ("setImage:", "release")] == [
        (7, "setImage:", (103,)),
        (103, "release", ()),
    ]

    # On the main thread, set_icon(None) drops a worker's icon still waiting, and releases it.
    sent.clear()
    _from_a_worker(lambda: item._show_icon(104))
    monkeypatch.setattr(menubar._files, "on_main_thread", lambda: True)
    item._show_icon(None)
    assert sent == [(104, "release", ()), (7, "setImage:", (None,))] and not menubar._calls


def test_run_rejects_a_nan_timeout_before_it_starts(monkeypatch):
    monkeypatch.setattr(menubar, "_application", lambda: pytest.fail("run() started"))
    with pytest.raises(ValueError, match="timeout"):
        menubar.run(timeout=float("nan"))


def test_timers_pause_between_runs(monkeypatch):
    monkeypatch.setattr(menubar, "_timers", [])
    hourly = macos.menubar.every(3600, lambda: None)
    assert _called(0.0) == [] and hourly._next == 3600.0
    menubar._pause_timers(10.0)  # run() returned 10 s in
    assert hourly._next is None and hourly._left == 3590.0
    assert _called(50000.0) == []  # an hour of other work later, the next run() starts: not due yet
    assert hourly._next == 53590.0
    assert _called(53590.0) == [hourly]

    # run() pauses them when it returns.
    hourly._next = hourly._left = None  # not yet armed, on the real clock
    monkeypatch.setattr(menubar, "_require_main_thread", lambda what: None)
    monkeypatch.setattr(menubar, "_application", lambda: 1)
    monkeypatch.setattr(menubar, "_pump", lambda app, wait: menubar._due_timers(menubar.time.monotonic()))
    menubar.run(timeout=0.05)
    assert hourly._next is None and 0 < hourly._left <= 3600


def test_a_timer_that_raises_leaves_the_others_due(monkeypatch):
    _fake_appkit(monkeypatch)
    monkeypatch.setattr(menubar, "_timers", [])
    called = []

    def failing():
        called.append("a")
        raise OSError("offline")

    a = macos.menubar.every(1, failing)
    b = macos.menubar.every(1, lambda: called.append("b"))
    clock = [0.0]
    monkeypatch.setattr(menubar.time, "monotonic", lambda: clock[0])
    menubar._pump(1, 0)  # arms both
    clock[0] = 1.0
    with pytest.raises(OSError):
        menubar._pump(1, 0)
    assert called == ["a"] and b._next == 1.0  # b wasn't called: still due
    menubar._pump(1, 0)
    assert called == ["a", "b"] and a._next == b._next == 2.0


@pytest.mark.parametrize("seconds", [float("inf"), float("-inf")])
def test_every_needs_a_finite_interval(seconds):
    with pytest.raises(ValueError, match="positive"):
        macos.menubar.every(seconds, lambda: None)


def test_every_needs_a_callable():
    with pytest.raises(TypeError, match="callable"):
        macos.menubar.every(1, "tick")
    assert not menubar._timers


def test_add_needs_a_callable_or_none():
    item = object.__new__(menubar.Item)  # never reaches AppKit: the check comes first
    with pytest.raises(TypeError, match="callable or None"):
        menubar.Item.add(item, "Refresh", "refresh")


def test_icon_paths_fail_as_open_would(tmp_path):
    with pytest.raises(FileNotFoundError):
        menubar._image(tmp_path / "missing.png", True)
    with pytest.raises(IsADirectoryError):
        menubar._image(tmp_path, True)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
def test_an_icon_path_to_a_fifo_is_no_image(tmp_path):
    fifo = tmp_path / "pipe"
    os.mkfifo(str(fifo))
    with pytest.raises(ValueError, match="not an image"):
        menubar._image(fifo, True)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root reads any file")
def test_an_unreadable_icon_file_raises_permission_error(tmp_path):
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\x89PNG")
    icon.chmod(0)
    try:
        with pytest.raises(PermissionError):
            menubar._image(icon, True)
    finally:
        icon.chmod(0o644)
