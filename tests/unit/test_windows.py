"""Unit tests for :mod:`macos.windows`. They run on any platform."""

import contextlib
import gc

import pytest

import macos
from macos import windows as _windows


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

    scans = []
    monkeypatch.setattr(windows, "has_permission", lambda: True)
    monkeypatch.setattr(windows, "_targets", lambda app: scans.append(app) or [Quitting()])
    monkeypatch.setattr(windows, "_list", lambda targets, title: [])
    monkeypatch.setattr(windows.apps, "running", lambda **options: pytest.fail("the apps are scanned once, by _targets"))
    tiled = []
    monkeypatch.setattr(windows, "tile", lambda chosen, **options: tiled.append(chosen))

    assert windows.tile_all("Terminal") == [] and tiled == [[]] and scans == ["Terminal"]


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


def test_restarting_the_window_manager_waits_for_the_batch_to_end(commands):
    from macos import _system, windows

    with _system.batched_restarts():
        windows._restart_window_manager()
        windows._restart_window_manager()
        assert commands.calls == []  # put off until the block ends
    assert commands.calls == [["killall", "WindowManager"]]  # once


def test_request_permission_needs_the_prompt_option(monkeypatch):
    import ctypes

    import pytest

    from macos import windows

    monkeypatch.setattr(windows, "_accessibility", lambda: object())
    monkeypatch.setattr(ctypes.c_void_p, "in_dll", lambda library, name: ctypes.c_void_p(None), raising=False)
    with pytest.raises(macos.MacOSError, match="prompt option"):
        windows.request_permission()


def test_a_full_screen_change_that_never_happens_is_a_wait_timeout(monkeypatch):
    import pytest

    class Window(macos.windows.Window):
        """A window that never changes, however often it's asked."""

        def __init__(self):
            self._element, self.app, self.pid = 0, "Test", 1

        @property
        def fullscreen(self):
            return False

        def _set_flag(self, attribute, on, what):
            pass

    monkeypatch.setattr(macos.windows, "_FULL_SCREEN_TIMEOUT", 0.05)
    with pytest.raises(macos.WaitTimeoutError, match="within"):  # a MacOSError and a TimeoutError too
        Window().set_fullscreen()


# --- The Accessibility layer, against a fake AX API ---------------------------------------------------------------

_CANNOT_COMPLETE, _API_DISABLED, _ATTRIBUTE_UNSUPPORTED = -25204, -25211, -25205


class _FakeAX:
    """
    The AX functions :mod:`macos.windows` calls, and the CoreFoundation helpers that read their answers.

    Elements and values are integers, as the real ones are pointers: ``refs`` maps each to the Python value
    behind it. An app is a dict of attributes (``AXWindows``, ``AXFocusedWindow``), a window one too (``AXTitle``,
    ``AXPosition``...), and ``failing`` holds the AXError an app answers with instead.
    """

    def __init__(self):
        self.refs, self.attributes, self.failing, self.trusted = {}, {}, {}, True
        self.set, self.performed = [], []

    def ref(self, value):
        self.refs[len(self.refs) + 1] = value
        return len(self.refs)

    def element(self, **attributes):
        return self.ref(attributes)

    def app(self, pid, **attributes):
        self.attributes[pid] = attributes
        return pid

    # --- ApplicationServices ---

    def AXIsProcessTrusted(self):
        return self.trusted

    def AXUIElementCreateApplication(self, pid):
        return self.ref(self.attributes.get(pid, {})) if pid in self.attributes or pid not in self.failing else self.ref({})

    def AXUIElementSetMessagingTimeout(self, element, seconds):
        return 0

    def AXUIElementCopyAttributeValue(self, element, name, out):
        if not self.trusted:
            return _API_DISABLED
        holder = self.refs[element]
        for pid, status in self.failing.items():
            if holder is self.attributes.get(pid, None) or (pid not in self.attributes and holder == {}):
                return status
        if name not in holder:
            return _ATTRIBUTE_UNSUPPORTED
        value = holder[name]
        # An element held by another (a window, a close button) is handed out as itself, not as a copy.
        out._obj.value = value if type(value) is int and value in self.refs else self.ref(value)
        return 0

    def AXUIElementSetAttributeValue(self, element, name, value):
        self.set.append((element, name, self.refs[value]))
        self.refs[element][name] = self.refs[value]
        return 0

    def AXUIElementPerformAction(self, element, action):
        self.performed.append((element, action))
        return 0

    def AXValueCreate(self, kind, holder):
        point = holder._obj
        return self.ref((point.x, point.y) if kind == 1 else (point.width, point.height))

    def AXValueGetValue(self, value, kind, out):
        first, second = self.refs[value]
        if kind == 1:
            out._obj.x, out._obj.y = first, second
        else:
            out._obj.width, out._obj.height = first, second
        return True

    # --- CoreFoundation, as macos._cf wraps it ---

    def lib(self):
        return self

    def CFEqual(self, left, right):
        return self.refs[left] is self.refs[right]

    def string(self, text):
        return text

    def owned(self, ref):
        return contextlib.nullcontext(ref)

    def retain(self, ref):
        return ref

    def release(self, ref):
        pass

    def constant(self, library, name):
        return self.ref(name == "kCFBooleanTrue")

    def to_str(self, ref):
        return self.refs[ref] if isinstance(self.refs.get(ref), str) else None

    def to_bool(self, ref):
        return bool(self.refs.get(ref))

    def items(self, ref):
        return list(self.refs[ref])


@pytest.fixture
def fake_ax(monkeypatch):
    fake = _FakeAX()
    monkeypatch.setattr(_windows, "_accessibility", lambda: fake)
    monkeypatch.setattr(_windows, "_cf", fake)
    yield fake
    # A Window releases its element when it goes: with the real CFRelease, once the fake is gone, a fake
    # element would crash the process. Every window left (a failed test's traceback keeps them) gives its up.
    gc.collect()
    for window in [obj for obj in gc.get_objects() if isinstance(obj, _windows.Window)]:
        window._element = 0


def _two_windows(fake):
    """Terminal (pid 7) with two windows, the second minimized."""
    front = fake.element(AXTitle="Notes", AXPosition=(10.0, 25.0), AXSize=(640.0, 480.0), AXMinimized=False)
    back = fake.element(AXTitle="Scratch", AXPosition=(300.0, 200.0), AXSize=(400.0, 300.0), AXMinimized=True)
    fake.app(7, AXWindows=[front, back], AXFocusedWindow=front)
    return macos.apps.App("Terminal", "com.apple.Terminal", 7, "/System/Applications/Utilities/Terminal.app")


def test_windows_of_an_app_read_their_titles_frames_and_state(fake_ax):
    terminal = _two_windows(fake_ax)
    found = macos.windows.list(terminal)

    assert [window.title for window in found] == ["Notes", "Scratch"]
    assert [window.frame for window in found] == [(10, 25, 640, 480), (300, 200, 400, 300)]
    assert [window.minimized for window in found] == [False, True]
    assert all((window.app, window.pid) == ("Terminal", 7) for window in found)
    assert found[0] == macos.windows.list(terminal)[0] and found[0] != found[1]  # the same window, listed again
    assert repr(found[0]) == "Window(app='Terminal', title='Notes', frame=(10, 25, 640, 480))"
    assert [window.title for window in macos.windows.list(terminal, title="scr")] == ["Scratch"]
    assert macos.windows.list(terminal, title="Nothing") == []


def test_windows_of_an_app_found_by_name(fake_ax, monkeypatch):
    terminal = _two_windows(fake_ax)
    monkeypatch.setattr(macos.apps, "get", lambda name: terminal if name == "Terminal" else None)

    assert [window.title for window in macos.windows.list("Terminal")] == ["Notes", "Scratch"]
    assert macos.windows.list("Typo") == []  # not running by that name: as documented, no windows


def test_an_app_that_does_not_answer_counts_as_having_no_windows(fake_ax):
    busy = macos.apps.App("Busy", "com.example.busy", 9, "/Applications/Busy.app")
    fake_ax.failing[9] = _CANNOT_COMPLETE

    assert macos.windows.list(busy) == []
    assert macos.windows.list(macos.apps.App("Idle", None, 10, None)) == []  # answers, with no windows


def test_the_missing_accessibility_permission_is_said(fake_ax, monkeypatch):
    fake_ax.trusted = False
    terminal = _two_windows(fake_ax)
    monkeypatch.setattr(macos.apps, "frontmost", lambda: terminal)

    assert macos.windows.has_permission() is False
    with pytest.raises(macos.PermissionDeniedError, match="Accessibility permission is missing"):
        macos.windows.list(terminal)
    with pytest.raises(macos.PermissionDeniedError):
        macos.windows.focused()
    fake_ax.trusted = True
    assert macos.windows.focused().title == "Notes"
    # Trusted when asked, refused when the windows are read: the same error, not an empty list.
    monkeypatch.setattr(_windows, "has_permission", lambda: True)
    fake_ax.trusted = False
    with pytest.raises(macos.PermissionDeniedError):
        macos.windows.list(terminal)


def test_focused_window(fake_ax, monkeypatch):
    terminal = _two_windows(fake_ax)
    monkeypatch.setattr(macos.apps, "frontmost", lambda: terminal)
    assert macos.windows.focused().title == "Notes"

    fake_ax.app(8)  # the app in front has no window focused
    monkeypatch.setattr(macos.apps, "frontmost", lambda: macos.apps.App("Empty", None, 8, None))
    assert macos.windows.focused() is None
    monkeypatch.setattr(macos.apps, "frontmost", lambda: None)
    assert macos.windows.focused() is None


def test_window_actions_reach_the_right_element(fake_ax):
    front, back = macos.windows.list(_two_windows(fake_ax))

    front.minimize()
    assert fake_ax.set[-1] == (front._element, "AXMinimized", True) and front.minimized
    front.restore()
    assert fake_ax.set[-1] == (front._element, "AXMinimized", False)
    front.move(50, 60)
    front.resize(800, 600)
    assert front.frame == (50, 60, 800, 600)
    back.set_frame(0, 25, 1280, 800)
    assert back.frame == (0, 25, 1280, 800)
    with pytest.raises(ValueError, match="positive"):
        front.resize(0, 10)

    with pytest.raises(macos.MacOSError, match="no close button"):
        front.close()
    button = fake_ax.element()
    fake_ax.refs[front._element]["AXCloseButton"] = button
    front.close()
    assert fake_ax.performed[-1][1] == "AXPress" and fake_ax.refs[fake_ax.performed[-1][0]] is fake_ax.refs[button]
