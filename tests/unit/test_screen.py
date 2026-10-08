"""Unit tests for :mod:`macos.screen`. They run on any platform."""

import subprocess
import sys
from pathlib import Path

import pytest

import macos
from macos import _system, screen


@pytest.fixture
def capture(fake_run, monkeypatch):
    """``fake_run``, also writing a few bytes where ``screencapture`` saves its image, as it does."""

    def run(args, **kwargs):
        result = fake_run(args, **kwargs)
        if args[0] == "screencapture" and fake_run.returncode == 0:
            with open(args[-1], "wb") as image:
                image.write(b"\x89PNG")
        return result

    monkeypatch.setattr(_system.subprocess, "run", run)
    return fake_run


def test_screenshot_arguments(capture, tmp_path):
    fake_run = capture
    target = macos.screenshot(tmp_path / "shot.JPG", region=(1, 2, 30, 40), display=2, cursor=True, check_permission=False)

    assert target == (tmp_path / "shot.JPG").resolve()
    assert fake_run.args[:-1] == ["screencapture", "-x", "-t", "jpg", "-C", "-R1,2,30,40", "-D2"]
    # Captured beside the output, under its name, then moved over it.
    staged = fake_run.args[-1]
    assert staged != str(target) and staged.endswith("/shot.JPG") and str(target.parent) in staged
    assert target.read_bytes() == b"\x89PNG" and list(tmp_path.iterdir()) == [target]


def test_screenshot_defaults_to_a_temporary_png(capture):
    fake_run = capture
    target = macos.screenshot(check_permission=False)
    try:
        assert target.suffix == ".png"
        assert fake_run.args[-1] == str(target)
    finally:
        target.unlink()


def test_screenshot_rejects_unknown_format(fake_run, tmp_path):
    with pytest.raises(ValueError, match="unsupported image format"):
        macos.screenshot(tmp_path / "shot.bmp", check_permission=False)


def test_screenshot_raises_without_permission(fake_run, monkeypatch, tmp_path):
    monkeypatch.setattr(screen, "has_permission", lambda: False)

    with pytest.raises(macos.PermissionDeniedError, match="Screen Recording"):
        macos.screenshot(tmp_path / "shot.png")
    assert fake_run.calls == []


def test_failed_screenshot_removes_its_temporary_file(fake_run, monkeypatch, tmp_path):
    fake_run.returncode = 1
    monkeypatch.setattr(screen.tempfile, "tempdir", str(tmp_path))

    with pytest.raises(macos.CommandError):
        macos.screenshot(display=9, check_permission=False)

    assert list(tmp_path.iterdir()) == []


def test_screenshot_that_saved_nothing_is_an_error(fake_run, monkeypatch, tmp_path):
    # screencapture exited 0 but wrote nothing: the empty temporary file isn't returned, and is removed.
    monkeypatch.setattr(screen.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(macos.MacOSError, match="didn't save a screenshot"):
        macos.screenshot(check_permission=False)
    assert list(tmp_path.iterdir()) == []

    # Into a given path: nothing there afterwards is an error too.
    with pytest.raises(macos.MacOSError, match="didn't save a screenshot"):
        macos.screenshot(tmp_path / "shot.png", check_permission=False)
    assert fake_run.calls[-1]["timeout"] > 0  # a hung screencapture is stopped
    assert list(tmp_path.iterdir()) == []


def test_an_earlier_image_cant_pass_for_a_screenshot_that_saved_nothing(fake_run, tmp_path):
    target = tmp_path / "shot.png"
    target.write_bytes(b"the earlier screenshot")

    with pytest.raises(macos.MacOSError, match="didn't save a screenshot"):
        macos.screenshot(target, check_permission=False)
    assert target.read_bytes() == b"the earlier screenshot"  # left as it was
    assert list(tmp_path.iterdir()) == [target]


def test_start_screensaver(fake_run):
    macos.screen.start_screensaver()

    assert fake_run.args == ["open", "-a", "ScreenSaverEngine"]


def test_lock(monkeypatch):
    from types import SimpleNamespace

    calls = []

    def lock_now():
        calls.append("lock")
        return login.status

    login = SimpleNamespace(status=0, SACLockScreenImmediate=lock_now)
    monkeypatch.setattr(macos.screen, "private_framework", lambda name: login)

    macos.screen.lock()
    assert calls == ["lock"]

    login.status = 1
    with pytest.raises(macos.MacOSError, match="could not lock"):
        macos.screen.lock()


@pytest.mark.skipif(sys.platform != "darwin", reason="builds real Core Foundation dictionaries")
@pytest.mark.parametrize(
    "session, locked", [({"kCGSSessionOnConsoleKey": True}, False), ({"CGSSessionScreenIsLocked": True}, True)]
)
def test_is_locked_reads_the_session(monkeypatch, session, locked):
    from types import SimpleNamespace

    from macos import _cf

    graphics = SimpleNamespace(CGSessionCopyCurrentDictionary=lambda: _cf.from_python(session))
    monkeypatch.setattr(macos.screen, "framework", lambda name: graphics)

    assert macos.screen.is_locked() is locked


class _FakeRecording:
    """``subprocess.Popen`` for screencapture: ``record(args, timeout)`` plays what it does while recording."""

    def __init__(self, record, stuck_finishing=False, interrupted_again=False, exit_status=0):
        self.record = record
        self.stuck_finishing = stuck_finishing  # after Ctrl-C, it doesn't finish the movie in time
        self.interrupted_again = interrupted_again
        self.exit_status = exit_status  # how it ends after Ctrl-C
        self.made = []

    def __call__(self, args, **kwargs):
        assert not kwargs.get("start_new_session")  # in Python's group: it ends with it, never left recording
        recording = self

        class Process:
            returncode = None
            signals = []
            calls = []

            def communicate(self, timeout=None):
                Process.calls.append(timeout)
                if len(Process.calls) == 1:
                    recording.record(args, timeout)
                elif len(Process.calls) == 2 and recording.stuck_finishing:
                    raise subprocess.TimeoutExpired(args, timeout)
                elif len(Process.calls) == 2 and recording.interrupted_again:
                    raise KeyboardInterrupt  # Ctrl-C a second time, while it finishes
                self.returncode = recording.exit_status if len(Process.calls) == 2 else 0
                return None, b""

            def poll(self):
                return self.returncode

            def send_signal(self, number):
                Process.signals.append(number)

            def kill(self):
                Process.signals.append("kill")

        self.made.append((list(args), Process))
        return Process()


def test_screen_record_command(fake_run, monkeypatch, tmp_path):
    target = tmp_path / "demo.mov"
    monkeypatch.setattr(macos.screen, "has_permission", lambda: True)
    recording = _FakeRecording(lambda args, timeout: Path(args[-1]).write_bytes(b"movie"))
    monkeypatch.setattr(_system.subprocess, "Popen", recording)

    assert macos.screen.record(target, 2.4, region=(0, 0, 800, 600), display=2, audio=True, clicks=True) == target
    args = recording.made[0][0]
    assert args[:-1] == ["screencapture", "-x", "-v", "-V2", "-R0,0,800,600", "-D2", "-g", "-k"]
    # Recorded beside the target, then moved over it.
    assert Path(args[-1]).name == "demo.mov" and Path(args[-1]).parent.parent == tmp_path
    assert target.read_bytes() == b"movie"
    assert [path.name for path in tmp_path.iterdir()] == ["demo.mov"]


def test_a_screen_recording_that_saves_nothing_leaves_the_old_one(fake_run, monkeypatch, tmp_path):
    target = tmp_path / "demo.mov"
    target.write_bytes(b"yesterday")
    monkeypatch.setattr(macos.screen, "has_permission", lambda: True)
    monkeypatch.setattr(_system.subprocess, "Popen", _FakeRecording(lambda args, timeout: None))

    # screencapture exited 0 without writing: the old recording can't pass for the new one.
    with pytest.raises(macos.MacOSError, match="wasn't saved"):
        macos.screen.record(target, 1)
    assert target.read_bytes() == b"yesterday"
    assert [path.name for path in tmp_path.iterdir()] == ["demo.mov"]


def test_screen_record_gives_up_on_a_stuck_screencapture(fake_run, monkeypatch, tmp_path):
    def stuck(args, timeout):
        assert timeout == 62  # the recording's seconds, and a minute to save it
        raise subprocess.TimeoutExpired(args, timeout)

    recording = _FakeRecording(stuck)
    monkeypatch.setattr(_system.subprocess, "Popen", recording)
    monkeypatch.setattr(macos.screen, "has_permission", lambda: True)
    with pytest.raises(macos.MacOSError, match="didn't finish recording"):
        macos.screen.record(tmp_path / "clip.mov", 2)
    assert recording.made[0][1].signals == ["kill"]


@pytest.mark.parametrize("finished", [True, False])
def test_ctrl_c_lets_screencapture_finish_the_movie_and_keeps_it(fake_run, monkeypatch, tmp_path, finished):
    import signal

    target = tmp_path / "demo.mov"
    target.write_bytes(b"yesterday")

    def interrupted(args, timeout):
        if finished:  # told to stop, screencapture ends the movie
            Path(args[-1]).write_bytes(b"movie so far")
        raise KeyboardInterrupt

    recording = _FakeRecording(interrupted)
    monkeypatch.setattr(macos.screen, "has_permission", lambda: True)
    monkeypatch.setattr(_system.subprocess, "Popen", recording)
    monkeypatch.setattr(_system, "_terminal_interrupted_us", lambda: False)  # no terminal sent it one
    with pytest.raises(KeyboardInterrupt):  # the script still stops, as asked
        macos.screen.record(target, 60)
    process = recording.made[0][1]
    # Asked to stop, then waited for to finish the file, never killed: subprocess.run would kill it at once.
    assert process.signals == [signal.SIGINT] and process.calls[1] == macos.screen._FINISH_GRACE
    assert target.read_bytes() == (b"movie so far" if finished else b"yesterday")
    assert [path.name for path in tmp_path.iterdir()] == ["demo.mov"]


def test_a_ctrl_c_from_the_terminal_isnt_sent_to_screencapture_twice(fake_run, monkeypatch, tmp_path):
    def interrupted(args, timeout):
        Path(args[-1]).write_bytes(b"movie so far")
        raise KeyboardInterrupt

    recording = _FakeRecording(interrupted)
    monkeypatch.setattr(macos.screen, "has_permission", lambda: True)
    monkeypatch.setattr(_system.subprocess, "Popen", recording)
    monkeypatch.setattr(_system, "_terminal_interrupted_us", lambda: True)  # it got the terminal's SIGINT too
    with pytest.raises(KeyboardInterrupt):
        macos.screen.record(tmp_path / "demo.mov", 60)
    assert recording.made[0][1].signals == []  # only waited for: a second SIGINT may cut its finishing short


@pytest.mark.parametrize(
    "how", [{"stuck_finishing": True}, {"interrupted_again": True}, {"exit_status": 1}], ids=["slow", "twice", "failed"]
)
def test_a_movie_screencapture_couldnt_finish_doesnt_replace_the_old_one(fake_run, monkeypatch, tmp_path, how):
    target = tmp_path / "demo.mov"
    target.write_bytes(b"yesterday")

    def interrupted(args, timeout):
        Path(args[-1]).write_bytes(b"half a movie")
        raise KeyboardInterrupt

    recording = _FakeRecording(interrupted, **how)
    monkeypatch.setattr(macos.screen, "has_permission", lambda: True)
    monkeypatch.setattr(_system.subprocess, "Popen", recording)
    with pytest.raises(KeyboardInterrupt):  # still the Ctrl-C
        macos.screen.record(target, 60)
    if "exit_status" not in how:
        assert recording.made[0][1].signals[-1] == "kill"  # stopped for good, not left running
    assert target.read_bytes() == b"yesterday"  # an unfinished movie is dropped
    assert [path.name for path in tmp_path.iterdir()] == ["demo.mov"]


def test_screen_record_needs_the_permission(fake_run, monkeypatch, tmp_path):
    monkeypatch.setattr(macos.screen, "has_permission", lambda: False)

    with pytest.raises(macos.PermissionDeniedError, match="Screen Recording"):
        macos.screen.record(tmp_path / "demo.mov", 1)


def test_screen_argument_checks(tmp_path):
    with pytest.raises(ValueError, match="0.0 to 1.0"):
        macos.screen.set_brightness(1.5)
    with pytest.raises(ValueError, match="positive"):
        macos.screen.record(tmp_path / "out.mov", 0)
    with pytest.raises(ValueError, match=".mov"):
        macos.screen.record(tmp_path / "out.mp4", 1)


def test_find_text_maps_the_boxes_to_the_screen(monkeypatch, tmp_path):
    from macos import vision

    shot = tmp_path / "shot.png"
    shot.write_bytes(b"png")
    main = screen.Display(1, "Main", 1000, 800, 0, 0, 2000, 1600, 2.0, 60.0, True, False)
    side = screen.Display(2, "Side", 500, 400, 1000, -100, 500, 400, 1.0, 60.0, False, False)
    monkeypatch.setattr(screen, "displays", lambda: [main, side])

    def capture(**kwargs):
        shot.write_bytes(b"png")
        return shot

    monkeypatch.setattr(screen, "screenshot", capture)
    boxes = [("Click Submit below", (0.5, 0.25, 0.1, 0.05))]
    monkeypatch.setattr(vision, "_occurrences", lambda image, text, languages: boxes)

    match = screen.find_text("submit")[0]
    assert (match.text, match.x, match.y, match.width, match.height) == ("Click Submit below", 500, 200, 100, 40)
    assert match.center == (550, 220)
    assert not shot.exists()  # the capture is deleted
    on_side = screen.find_text("x", display=2)[0]
    assert (on_side.x, on_side.y) == (1250, 0)  # the side display starts at (1000, -100)
    in_region = screen.find_text("x", region=(100, 100, 200, 100))[0]
    assert (in_region.x, in_region.y) == (200, 125)
    with pytest.raises(ValueError, match="no display 3"):
        screen.find_text("x", display=3)
    with pytest.raises(ValueError, match="no display 0"):  # displays count from 1
        screen.find_text("x", display=0)


def test_wait_for_text(monkeypatch):
    results = iter([[], [], [screen.TextMatch("OK", 1, 2, 3, 4)]])
    monkeypatch.setattr(screen, "find_text", lambda *args, **kwargs: next(results))
    monkeypatch.setattr(screen.time, "sleep", lambda seconds: None)

    assert screen.wait_for_text("ok") == screen.TextMatch("OK", 1, 2, 3, 4)
    monkeypatch.setattr(screen, "find_text", lambda *args, **kwargs: [])
    assert screen.wait_for_text("ok", timeout=0) is None

    # A timeout shorter than the interval still gets a last look, when it ends.
    clock, scans = {"now": 0.0}, []
    monkeypatch.setattr(screen.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(screen.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds))
    monkeypatch.setattr(screen, "find_text", lambda *args, **kwargs: scans.append(clock["now"]) or [])
    assert screen.wait_for_text("ok", timeout=0.4, interval=0.5) is None
    assert scans == [0.0, 0.4]


def test_find_text_argument_checks():
    with pytest.raises(ValueError, match="empty"):
        screen.find_text("  ")
    with pytest.raises(ValueError, match="interval"):
        screen.wait_for_text("ok", interval=0)


def test_screenshot_settings(monkeypatch, tmp_path):
    from macos import defaults

    store, applied = {}, []
    monkeypatch.setattr(defaults, "read", lambda domain, key=None, default=None: store.get(key, default))
    monkeypatch.setattr(defaults, "write", lambda domain, key, value: store.__setitem__(key, value))
    monkeypatch.setattr(screen, "_apply_capture_settings", lambda: applied.append(1))

    assert screen.screenshot_format() == "png" and screen.screenshot_shadow() is True
    screen.set_screenshot_folder(tmp_path)
    screen.set_screenshot_format(".JPEG")
    screen.set_screenshot_shadow(False)
    assert store == {"location": str(tmp_path.resolve()), "type": "jpg", "disable-shadow": True}
    assert screen.screenshot_folder() == tmp_path.resolve()
    assert (screen.screenshot_format(), screen.screenshot_shadow()) == ("jpg", False)
    assert len(applied) == 3
    with pytest.raises(ValueError, match="format must be one of"):
        screen.set_screenshot_format("webp")
    with pytest.raises(NotADirectoryError):
        screen.set_screenshot_folder(tmp_path / "missing")


def test_a_display_change_that_fails_is_cancelled(monkeypatch):
    from types import SimpleNamespace

    calls = []

    def begin(pointer):
        pointer._obj.value = 99
        return 0

    cg = SimpleNamespace(
        CGBeginDisplayConfiguration=begin,
        CGCancelDisplayConfiguration=lambda handle: calls.append(("cancel", handle)),
        CGCompleteDisplayConfiguration=lambda handle, option: calls.append(("complete", handle)),
    )
    monkeypatch.setattr(screen, "_arrangement_api", lambda: cg)

    def change(api, handle):
        raise ValueError("no such display")

    with pytest.raises(ValueError, match="no such display"):
        screen._configure(change)
    assert calls == [("cancel", 99)]
