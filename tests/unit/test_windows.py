"""Unit tests for :mod:`macos.windows`. They run on any platform."""

import macos


def test_set_fullscreen_asks_again_when_macos_drops_the_request(monkeypatch):
    class Window(macos.windows.Window):
        """A window whose first full screen request is dropped, as during an animation."""

        def __init__(self):
            self._element, self.app, self.pid = 0, "Test", 1
            self.state, self.requests = True, 0

        @property
        def fullscreen(self):
            return self.state

        def _set_flag(self, attribute, on, what):
            self.requests += 1
            if self.requests >= 2:
                self.state = on

    monkeypatch.setattr(macos.windows, "_FULL_SCREEN_RETRY", 0.05)
    monkeypatch.setattr(macos.windows, "_FULL_SCREEN_ANIMATION", 0)
    window = Window()

    window.set_fullscreen(False)

    assert window.fullscreen is False and window.requests == 2


def test_windows_wait_for(monkeypatch):
    windows = macos.windows
    answers = iter([[], [], ["the window"]])
    monkeypatch.setattr(windows, "list", lambda app=None, title=None: next(answers))
    monkeypatch.setattr(windows.time, "sleep", lambda seconds: None)

    assert windows.wait_for("TextEdit", title="Save") == "the window"
    monkeypatch.setattr(windows, "list", lambda app=None, title=None: [])
    assert windows.wait_for(title="Save", timeout=0) is None


def test_tile_grid():
    from macos.windows import _grid

    area = (0, 25, 1200, 800)
    assert _grid(1, area, None, 0) == [(0, 25, 1200, 800)]
    assert _grid(2, area, None, 0) == [(0, 25, 600, 800), (600, 25, 600, 800)]
    # Three windows: two on top, and the last one alone below, as wide as the display.
    assert _grid(3, area, None, 0) == [(0, 25, 600, 400), (600, 25, 600, 400), (0, 425, 1200, 400)]
    assert _grid(3, area, 3, 0) == [(0, 25, 400, 800), (400, 25, 400, 800), (800, 25, 400, 800)]
    assert _grid(2, area, 1, 10) == [(10, 35, 1180, 385), (10, 430, 1180, 385)]  # gaps around and between
    assert _grid(2, area, 5, 0) == _grid(2, area, None, 0)  # no more columns than windows
    assert _grid(0, area, None, 0) == []
    # Odd sizes: the rounded frames touch and end at the area's edge, never past it.
    frames = _grid(3, (0, 0, 1003, 801), 3, 0)
    assert [x + width for x, _, width, _ in frames] == [334, 669, 1003]
    assert [x for x, _, _, _ in frames] == [0, 334, 669]
    assert _grid(2, (0, 0, 1003, 801), 1, 0)[-1][1] + _grid(2, (0, 0, 1003, 801), 1, 0)[-1][3] == 801
    # An edge landing on .5 rounds the same way for both windows that share it: they touch, never overlap.
    row = _grid(26, (52, 0, 233, 200), None, 0)[:6]
    assert all(left + width == next_left for (left, _, width, _), (next_left, _, _, _) in zip(row, row[1:]))
    # A fractional area (the Dock's size is a float): the last row ends at the area's bottom, not a point under the Dock.
    _, top, _, height = _grid(4, (0, 24.5, 1440, 795.5), None, 0)[-1]
    assert top + height == 820


class _FakeWindow:
    def __init__(self, x, y):
        self.frame = (x, y, 300, 200)

    @property
    def position(self):
        return self.frame[:2]

    def set_frame(self, x, y, width, height):
        self.frame = (x, y, width, height)


def test_tile_keeps_each_display_and_the_order(monkeypatch):
    import pytest

    from macos import windows

    monkeypatch.setattr(windows, "_usable_areas", lambda: [(0, 25, 1000, 800), (1000, 0, 800, 600)])
    right, left, other = _FakeWindow(500, 100), _FakeWindow(20, 100), _FakeWindow(1100, 50)

    windows.tile([right, left, other])

    assert left.frame == (0, 25, 500, 800) and right.frame == (500, 25, 500, 800)  # by where they were
    lower = _FakeWindow(0, 600)
    windows.tile([lower, right, left], display=1)
    assert [window.frame[:2] for window in (left, right, lower)] == [(0, 25), (500, 25), (0, 425)]  # reading order
    assert other.frame == (1000, 0, 800, 600)  # alone on the second display

    windows.tile([right, left, other], display=2, gap=10)
    assert all(1000 <= window.frame[0] < 1800 for window in (right, left, other))

    with pytest.raises(ValueError, match="no display 3"):
        windows.tile([left], display=3)
    with pytest.raises(ValueError, match="columns must be at least 1"):
        windows.tile([left], columns=0)


def test_tile_all_ignores_an_app_that_quits(monkeypatch):
    from macos import windows

    class Quitting:
        pid = 1

        @property
        def is_hidden(self):
            raise macos.AppNotFoundError("gone")

    monkeypatch.setattr(windows.apps, "running", lambda include_background=False: [Quitting()])
    monkeypatch.setattr(windows, "list", lambda app=None, title=None: [])
    tiled = []
    monkeypatch.setattr(windows, "tile", lambda chosen, **options: tiled.append(chosen))

    assert windows.tile_all() == [] and tiled == [[]]


def test_tile_with_too_large_a_gap_moves_nothing(monkeypatch):
    import pytest

    from macos import windows

    with pytest.raises(ValueError, match="gap of 400 points leaves no room"):
        windows._grid(2, (0, 0, 1000, 800), None, 400)
    monkeypatch.setattr(windows, "_usable_areas", lambda: [(0, 25, 1000, 800), (1000, 0, 400, 300)])
    first, second = _FakeWindow(10, 100), _FakeWindow(1100, 50)
    with pytest.raises(ValueError, match="no room"):
        windows.tile([first, second], gap=160)  # fits the first display, not the second
    assert first.frame == (10, 100, 300, 200) and second.frame == (1100, 50, 300, 200)  # neither moved


def test_center_keeps_clear_of_the_menu_bar_and_the_dock(monkeypatch):
    from macos import windows

    class Window(windows.Window):
        def __init__(self, frame):
            self._element, self.app, self.pid = 0, "Test", 1
            self._frame = frame

        @property
        def frame(self):
            return self._frame

        def move(self, x, y):
            self._frame = (x, y) + self._frame[2:]

    # A display 1000 x 800 whose menu bar takes 25 points at the top and the Dock 75 at the bottom.
    monkeypatch.setattr(windows, "_usable_areas", lambda: [(0, 25, 1000, 700), (1000, 0, 800, 600)])
    window = Window((0, 0, 400, 300))
    window.center()
    assert window.frame == (300, 225, 400, 300)
    tall = Window((1100, 0, 400, 900))
    tall.center()
    assert tall.frame == (1200, 0, 400, 900)  # on its own display, its top edge kept on it


def test_set_fullscreen_tells_a_window_that_cannot_go_full_screen(monkeypatch):
    import pytest

    from macos import windows

    class Window(windows.Window):
        def __init__(self, status):
            self._element, self.app, self.pid = 0, "Test", 1
            self.status = status

        def _set_flag(self, attribute, on, what):
            windows._check(self.status, what)

    with pytest.raises(macos.MacOSError, match="can't go full screen: its app doesn't allow it"):
        Window(-25200).set_fullscreen()  # kAXErrorFailure
    with pytest.raises(macos.MacOSError, match="the window is gone"):
        Window(-25202).set_fullscreen()


def test_restarting_the_window_manager_only_ignores_it_not_running(commands):
    import pytest

    from macos import windows

    commands.answers["WindowManager"] = (1, "", "No matching processes belonging to you were found")
    windows._restart_window_manager()  # not running: it reads the settings when it starts
    commands.answers["WindowManager"] = (2, "", "killall: unknown signal")
    with pytest.raises(macos.CommandError, match="unknown signal"):
        windows._restart_window_manager()


def test_request_permission_needs_the_prompt_option(monkeypatch):
    import ctypes

    import pytest

    from macos import windows

    monkeypatch.setattr(windows, "_accessibility", lambda: object())
    monkeypatch.setattr(ctypes.c_void_p, "in_dll", lambda library, name: ctypes.c_void_p(None), raising=False)
    with pytest.raises(macos.MacOSError, match="prompt option"):
        windows.request_permission()
