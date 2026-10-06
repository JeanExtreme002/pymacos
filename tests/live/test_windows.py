"""Tests of :mod:`macos.windows` against the real system. Skipped outside macOS."""

import os
import time

import pytest

import macos


def test_windows(test_window):
    window = test_window

    window.set_frame(60, 80, 420, 300)
    time.sleep(0.2)
    assert window.frame == (60, 80, 420, 300)
    window.move(100, 120)
    window.resize(360, 260)
    time.sleep(0.2)
    assert (window.position, window.size) == ((100, 120), (360, 260))

    window.center()
    time.sleep(0.2)
    # In the area the menu bar and the Dock leave, like snap().
    area_x, area_y, area_width, area_height = macos.windows._usable_areas()[0]
    x, y, width, height = window.frame
    assert (width, height) == (360, 260)  # the same size
    assert abs(x + width / 2 - (area_x + area_width / 2)) <= 1
    assert abs(y + height / 2 - (area_y + area_height / 2)) <= 1

    assert window.fullscreen is False
    if os.environ.get("CI"):  # it switches to a Space of its own: not on the user's Mac
        window.set_fullscreen()  # returns once the animation is done
        assert window.fullscreen
        window.set_fullscreen(False)
        assert not window.fullscreen

    window.minimize()
    time.sleep(0.8)
    assert window.minimized
    window.restore()
    time.sleep(0.8)
    assert not window.minimized

    window.focus()
    for _ in range(20):
        if macos.windows.focused() == window:
            break
        time.sleep(0.1)
    else:
        # The user (or another app) may have taken the focus meanwhile: the
        # window must at least be its app's main one.
        from macos import _cf

        main = window._read("AXMain")
        with _cf.owned(main):
            assert _cf.to_bool(main)
    assert window in macos.windows.list()

    window.close()
    time.sleep(0.5)
    with pytest.raises(macos.MacOSError):
        window.title


def test_window_screenshot_and_wait_for(test_window):
    if not macos.screen.has_permission():
        pytest.skip("no Screen Recording permission")
    test_window.set_frame(100, 100, 400, 250)
    time.sleep(0.5)

    shot = test_window.screenshot()
    try:
        details = macos.image.info(shot)
        scale = macos.screen.displays()[0].scale
        assert (details.width, details.height) == (round(400 * scale), round(250 * scale))  # no shadow
    finally:
        shot.unlink()
    assert macos.windows.wait_for(title=test_window.title, timeout=5) == test_window
    assert macos.windows.wait_for(title="no such window, surely", timeout=0.3) is None


def test_window_snap(test_window):
    from macos.windows import _usable_areas

    area_x, area_y, area_width, area_height = _usable_areas()[0]
    test_window.snap("left", display=1)
    time.sleep(0.3)
    x, y, width, height = test_window.frame
    assert (x, y) == (round(area_x), round(area_y)) and abs(width - area_width / 2) <= 2
    test_window.snap("bottom_right")
    time.sleep(0.3)
    x, y, width, height = test_window.frame
    assert abs(x - (area_x + area_width / 2)) <= 2 and abs(y + height - (area_y + area_height)) <= 2
    with pytest.raises(ValueError, match="layout must be one of"):
        test_window.snap("diagonal")


@pytest.fixture
def two_windows():
    """Two windows of our own, from two helper apps, to tile without touching the user's."""
    import subprocess
    import sys
    import uuid
    from pathlib import Path

    if not macos.windows.has_permission():
        pytest.skip("no Accessibility permission")
    helper = Path(__file__).with_name("_window_app.py")
    titles = ["pymacos tile {}".format(uuid.uuid4().hex[:8]) for _ in range(2)]
    processes = [
        subprocess.Popen([sys.executable, str(helper), title, "20"], stdout=subprocess.PIPE, text=True) for title in titles
    ]
    try:
        found = []
        for process, title in zip(processes, titles):
            process.stdout.readline()
            app = next(app for app in macos.apps.running(include_background=True) if app.pid == process.pid)
            for _ in range(20):
                windows = macos.windows.list(app, title=title)
                if windows:
                    break
                time.sleep(0.1)
            found.append((app, windows[0]))
        yield found
    finally:
        for process in processes:
            process.kill()
            process.wait()


def test_tile(two_windows):
    from macos.windows import _usable_areas

    area_x, area_y, area_width, area_height = _usable_areas()[0]
    (_, first), (second_app, second) = two_windows
    first.move(area_x + 10, area_y + 10)
    second.move(area_x + 400, area_y + 10)
    time.sleep(0.3)

    macos.windows.tile([second, first], display=1)
    time.sleep(0.3)
    assert abs(first.frame[0] - area_x) <= 2 and abs(second.frame[0] - (area_x + area_width / 2)) <= 2  # left to right
    for window in (first, second):
        x, y, width, height = window.frame
        assert abs(width - area_width / 2) <= 2
        # Inside the usable area and nearly as tall: macOS may still nudge a window by a few points
        # (seen on CI: 6 points lower and 10 shorter), which isn't the grid's doing.
        assert y >= area_y - 2 and y + height <= area_y + area_height + 2 and height >= area_height * 0.95

    tiled = macos.windows.tile_all(second_app, display=1, gap=20)  # only the helper's window
    time.sleep(0.3)
    assert tiled == [second]
    x, y, width, height = second.frame
    assert abs(x - (area_x + 20)) <= 2 and abs(width - (area_width - 40)) <= 2
