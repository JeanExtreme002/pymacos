"""Unit tests for :mod:`macos.sound`. They run on any platform."""

from pathlib import Path

import pytest

import macos


def test_sound_argument_checks():
    with pytest.raises(ValueError):
        macos.sound.play("Glass", volume=2)


def test_play_drains_what_it_autoreleases(monkeypatch):
    from contextlib import contextmanager

    events = []

    @contextmanager
    def pool():
        events.append("push")
        yield
        events.append("pop")

    def send(receiver, selector, *args, **kwargs):
        events.append(selector)
        return 0.0 if selector == "duration" else True

    monkeypatch.setattr(macos.sound, "_load", lambda sound: events.append("load") or 42)
    monkeypatch.setattr(macos.sound._objc, "autorelease_pool", pool)
    monkeypatch.setattr(macos.sound._objc, "send", send)
    monkeypatch.setattr(macos.sound.time, "sleep", lambda seconds: None)

    macos.sound.play("Glass")

    assert events == ["push", "load", "setVolume:", "duration", "play", "pop", "release"]  # released after


def test_ctrl_c_while_waiting_stops_the_sound_and_releases_it(monkeypatch):
    from contextlib import nullcontext

    events = []

    def send(receiver, selector, *args, **kwargs):
        events.append(selector)
        return 3.0 if selector == "duration" else True

    def interrupted(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(macos.sound, "_load", lambda sound: 42)
    monkeypatch.setattr(macos.sound._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(macos.sound._objc, "send", send)
    monkeypatch.setattr(macos.sound.time, "sleep", interrupted)

    with pytest.raises(KeyboardInterrupt):
        macos.sound.play("Glass")

    assert events[-2:] == ["stop", "release"]  # not left playing, nor retained for good


def test_a_named_sound_is_played_from_a_copy(monkeypatch):
    sent = []

    def send(receiver, selector, *args, **kwargs):
        sent.append(selector)
        return 7

    monkeypatch.setattr(macos.sound, "_appkit", lambda: None)
    monkeypatch.setattr(macos.sound._objc, "send", send)
    monkeypatch.setattr(macos.sound._objc, "cls", lambda name: 1)
    monkeypatch.setattr(macos.sound._objc, "nsstring", lambda text: 2)

    macos.sound._load("Glass")

    # The shared instance soundNamed: returns may be playing already.
    assert sent == ["soundNamed:", "copy"]


def _fake_player(monkeypatch):
    """Record what ``_load`` sends, as (selector, args), with nothing to play."""
    sent = []

    def send(receiver, selector, *args, **kwargs):
        sent.append((selector, args))
        return 7

    monkeypatch.setattr(macos.sound, "_appkit", lambda: None)
    monkeypatch.setattr(macos.sound._objc, "send", send)
    monkeypatch.setattr(macos.sound._objc, "cls", lambda name: 1)
    monkeypatch.setattr(macos.sound._objc, "nsstring", lambda text: text)
    return sent


def _sound_folders(monkeypatch, tmp_path, *folders):
    """Point the alert sound folders at ``folders`` under ``tmp_path``, made empty."""
    paths = tuple(tmp_path / folder for folder in folders)
    for path in paths:
        path.mkdir(parents=True)
    monkeypatch.setattr(macos.sound, "_SOUND_FOLDERS", paths)
    monkeypatch.setattr(macos.sound, "require_macos", lambda: None)
    return paths


def test_a_listed_name_with_a_dot_is_played_from_its_file(monkeypatch, tmp_path):
    (user,) = _sound_folders(monkeypatch, tmp_path, "user")
    (user / "My.Sound.aiff").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    sent = _fake_player(monkeypatch)

    assert "My.Sound" in macos.sound.names()
    macos.sound._load("My.Sound")

    assert sent[-1] == ("initWithContentsOfFile:byReference:", (str(user / "My.Sound.aiff"), False))


def test_a_missing_file_with_an_extension_is_still_file_not_found(monkeypatch, tmp_path):
    _sound_folders(monkeypatch, tmp_path, "user")
    monkeypatch.chdir(tmp_path)
    _fake_player(monkeypatch)

    with pytest.raises(FileNotFoundError):
        macos.sound._load("done.mp3")


def test_a_path_object_always_means_a_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    sent = _fake_player(monkeypatch)

    with pytest.raises(FileNotFoundError):
        macos.sound._load(Path("Glass"))  # not the alert sound
    (tmp_path / "chime").write_bytes(b"")
    macos.sound._load(Path("chime"))

    assert [selector for selector, args in sent] == ["alloc", "initWithContentsOfFile:byReference:"]


def test_set_alert_sound_picks_the_file_play_would(monkeypatch, tmp_path):
    user, system = _sound_folders(monkeypatch, tmp_path, "user", "system")
    (system / "Glass.aiff").write_bytes(b"")
    (user / "Glass.aiff").write_bytes(b"")
    written = []
    monkeypatch.setattr(macos.sound.defaults, "write", lambda domain, key, value: written.append(value))

    macos.sound.set_alert_sound("Glass")

    assert written == [str(user / "Glass.aiff")]  # soundNamed: looks in ~/Library/Sounds first


def test_the_user_sound_folder_comes_first():
    assert macos.sound._SOUND_FOLDERS[0] == Path("~/Library/Sounds").expanduser()
    assert macos.sound._SOUND_FOLDERS[-1] == Path("/System/Library/Sounds")


@pytest.mark.parametrize("value", [5, b"/System/Library/Sounds/Glass.aiff", ["Glass"], ""])
def test_a_hand_edited_alert_sound_reads_as_macos_own(monkeypatch, value):
    monkeypatch.setattr(macos.sound.defaults, "read", lambda *args, **kwargs: value)

    assert macos.sound.alert_sound() is None


@pytest.mark.parametrize(
    "value, on",
    [(1, True), (0, False), ("0", False), ("1", True), (True, True), ("x", True), ("NO", False), ("false", False),
     ("YES", True), (False, False)],
)
def test_ui_sounds_reads_a_hand_edited_value(monkeypatch, value, on):
    monkeypatch.setattr(macos.sound.defaults, "read", lambda *args, **kwargs: value)

    assert macos.sound.ui_sounds() is on


def test_an_unreadable_file_is_a_permission_error(monkeypatch, tmp_path):
    """NSSound just answers nil: a file that can't be read was said to be no audio file, a ValueError."""
    import os

    monkeypatch.setattr(macos.sound._objc, "send", lambda receiver, selector, *args, **kwargs: None)
    monkeypatch.setattr(macos.sound._objc, "cls", lambda name: 1)
    monkeypatch.setattr(macos.sound._objc, "nsstring", lambda text: text)
    locked = tmp_path / "done.mp3"
    locked.write_bytes(b"ID3")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("this user reads any file (root)")
        with pytest.raises(PermissionError) as raised:
            macos.sound._load_file(locked)
        assert not isinstance(raised.value, macos.MacOSError)  # Python's own, as image, pdf and video raise
    finally:
        locked.chmod(0o600)
    with pytest.raises(ValueError, match="not an audio file"):
        macos.sound._load_file(locked)
    with pytest.raises(ValueError, match="not an audio file"):
        macos.sound._load_file(tmp_path)
