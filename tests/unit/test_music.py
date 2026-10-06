"""Unit tests for :mod:`macos.music`. They run on any platform."""

import subprocess

import pytest

import macos
from macos import _system


class _FakePlayers:
    """Answers osascript for Music and Spotify, and records the commands."""

    def __init__(self, running, states, tracks):
        self.running, self.states, self.tracks = running, states, tracks
        self.volumes = {"Music": 100, "Spotify": 100}
        self.commands = []

    def __call__(self, args, **kwargs):
        script = args[-1]
        app = "Spotify" if '"Spotify"' in script else "Music"
        if "player state as string" in script and "current track" not in script:
            output = self.states[app] + "\n"
        elif script.endswith("to sound volume"):
            output = "{}\n".format(self.volumes[app])
        elif "current track" in script:
            output = self.tracks.get(app, "") + "\n"
        else:
            self.commands.append((app, script.split(" to ", 1)[1]))
            output = ""
        return subprocess.CompletedProcess(args, 0, output, "")


@pytest.fixture
def players(monkeypatch):
    from macos import apps

    fake = _FakePlayers(
        running=["Music", "Spotify"],
        states={"Music": "paused", "Spotify": "playing"},
        tracks={
            "Music": "\x1f".join(["Imagine", "John Lennon", "Imagine", "183,5", "12,25", "paused"]),
            "Spotify": "\x1f".join(["Blue", "Eiffel 65", "Europop", "220000", "30.0", "playing"]),
        },
    )
    monkeypatch.setattr(_system.sys, "platform", "darwin")
    monkeypatch.setattr(_system.subprocess, "run", fake)
    monkeypatch.setattr(
        apps, "running", lambda: [apps.App(name, None, 100 + index, None) for index, name in enumerate(fake.running)]
    )
    return fake


def test_now_playing_prefers_the_player_that_plays(players):
    track = macos.music.now_playing()

    # Spotify counts milliseconds; Music writes "183,5" in a Portuguese locale.
    assert track == macos.music.Track("Blue", "Eiffel 65", "Europop", 220.0, 30.0, True, "Spotify")
    assert macos.music.now_playing(app="Music") == macos.music.Track(
        "Imagine", "John Lennon", "Imagine", 183.5, 12.25, False, "Music"
    )


def test_now_playing_never_opens_a_player(players):
    players.running = []

    assert macos.music.now_playing() is None
    assert macos.music.now_playing(app="Music") is None


def test_player_commands_go_to_the_right_app(players):
    macos.music.pause()
    macos.music.next(app="Music")
    players.running = []
    macos.music.play()  # nothing runs: Music opens

    assert players.commands == [("Spotify", "pause"), ("Music", "next track"), ("Music", "play")]


def test_music_without_the_automation_permission(fake_run, monkeypatch):
    from macos import apps

    monkeypatch.setattr(apps, "running", lambda: [apps.App("Music", None, 1, None)])
    fake_run.returncode = 1
    fake_run.stderr = "Not authorized to send Apple events to Music. (-1743)"

    with pytest.raises(macos.PermissionDeniedError, match="Automation"):
        macos.music.play(app="Music")


def test_player_volume_and_seek(players):
    players.volumes = {"Music": 40, "Spotify": 75}

    assert macos.music.volume() == 75  # Spotify plays
    assert macos.music.volume(app="Music") == 40
    macos.music.set_volume(30)
    macos.music.seek(62.5, app="Music")

    assert players.commands == [("Spotify", "set sound volume to 30"), ("Music", "set player position to 62.5")]


def test_player_controls_never_open_a_player(players):
    players.running = []

    for control in (macos.music.pause, macos.music.play_pause, macos.music.next, macos.music.previous):
        with pytest.raises(macos.MacOSError, match="isn't running"):
            control()
    assert players.commands == []  # nothing was sent: Music stays closed


def test_player_volume_needs_a_running_player(players):
    players.running = ["Music"]

    with pytest.raises(macos.MacOSError, match="Spotify isn't running"):
        macos.music.volume(app="Spotify")
    with pytest.raises(macos.MacOSError, match="Spotify isn't running"):
        macos.music.seek(10, app="Spotify")


def test_music_argument_checks():
    with pytest.raises(ValueError, match="app must be one of"):
        macos.music.play(app="Winamp")
    with pytest.raises(ValueError, match="app must be one of"):
        macos.music.now_playing(app="Winamp")
    with pytest.raises(ValueError, match="0 to 100"):
        macos.music.set_volume(101)
    for seconds in (-1, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="zero or more"):
            macos.music.seek(seconds)
    with pytest.raises(ValueError, match="0 to 100"):
        macos.music.set_volume(float("nan"))
