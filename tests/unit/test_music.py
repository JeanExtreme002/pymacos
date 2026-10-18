"""Unit tests for :mod:`macos.music`. They run on any platform."""

import re
import subprocess

import pytest

import macos
from macos import _system, music


class _FakePlayers:
    """Answers osascript for Music and Spotify, and records the commands."""

    def __init__(self, running, states, tracks):
        self.running, self.states, self.tracks = running, states, tracks
        self.volumes = {"Music": 100, "Spotify": 100}
        self.commands = []
        self.quit = set()  # players that quit after Python saw them running
        self.denied = set()  # players whose Automation permission is denied
        self.scripts = []

    def __call__(self, args, **kwargs):
        script = args[-1]
        self.scripts.append(script)
        app = "Spotify" if '"Spotify"' in script else "Music"
        if app in self.denied:
            return subprocess.CompletedProcess(args, 1, "", "Not authorized to send Apple events to {}. (-1743)".format(app))
        if "is running then" in script and app in self.quit:
            return subprocess.CompletedProcess(args, 0, music._NOT_RUNNING + "\n", "")
        told = re.search(r'tell application "\w+" to (.*)', script)
        if "current track" in script:
            output = self.tracks.get(app, "") + "\n"
        elif told and told.group(1) == "player state as string":
            output = self.states[app] + "\n"
        elif told and told.group(1) == "sound volume":
            output = "{}\n".format(self.volumes[app])
        else:
            assert told, script
            self.commands.append((app, told.group(1)))
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
        apps,
        "running",
        lambda: [apps.App(name, music._BUNDLE_IDS.get(name), 100 + index, None) for index, name in enumerate(fake.running)],
    )
    monkeypatch.setattr(apps, "_locate", lambda name: "/Applications/{}.app".format(name))  # both installed
    return fake


def test_now_playing_prefers_the_player_that_plays(players):
    track = macos.music.now_playing()

    # Spotify counts milliseconds; Music writes "183,5" in a Portuguese locale.
    assert track == macos.music.Track("Blue", "Eiffel 65", "Europop", 220.0, 30.0, True, "Spotify")
    assert macos.music.now_playing(app="Music") == macos.music.Track(
        "Imagine", "John Lennon", "Imagine", 183.5, 12.25, False, "Music"
    )


def test_players_are_found_by_bundle_identifier_in_any_language(players, monkeypatch):
    from macos import apps

    # A German Mac names Music "Musik": the name can't tell the player apart, its identifier can.
    monkeypatch.setattr(apps, "running", lambda: [apps.App("Musik", "com.apple.Music", 100, None)])
    track = macos.music.now_playing()

    assert track is not None and track.app == "Music" and track.title == "Imagine"
    macos.music.pause()
    assert players.commands == [("Music", "pause")]

    monkeypatch.setattr(apps, "running", lambda: [apps.App("Music", "com.example.not-music", 100, None)])
    assert macos.music.now_playing() is None


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

    monkeypatch.setattr(apps, "running", lambda: [apps.App("Music", "com.apple.Music", 1, None)])
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
    for level in (True, False, "50", None):
        with pytest.raises(TypeError, match="must be a number"):
            macos.music.set_volume(level)


def test_set_volume_rounds_a_fraction_as_volume_reads_it(players):
    macos.music.set_volume(49.9)
    macos.music.set_volume(0.4, app="Music")

    assert players.commands == [("Spotify", "set sound volume to 50"), ("Music", "set sound volume to 0")]


def test_a_track_with_missing_fields_reads_as_empty_text(players):
    # The script turns a missing name, artist or album into "": an empty title reaches the Track as such.
    players.tracks["Spotify"] = "\x1f".join(["", "", "Radio", "missing value", "3.5", "playing"])

    assert macos.music.now_playing() == macos.music.Track("", "", "Radio", None, 3.5, True, "Spotify")
    script = players.scripts[-1]
    for field in ("trackName", "trackArtist", "trackAlbum"):
        assert "if {} is missing value then set {} to \"\"".format(field, field) in script
    assert 'return "" & trackName' in script


def test_a_track_that_isnt_text_is_refused(players):
    # What "missing value" & text used to give: a list, printed with ", " between its items.
    players.tracks["Music"] = "missing value, \x1f, missing value, \x1f, Al, \x1f, 183\x1f12\x1fpaused, "

    with pytest.raises(macos.MacOSError, match="unexpected"):
        macos.music.now_playing(app="Music")


def test_a_player_that_cant_be_asked_is_passed_over(players):
    players.denied = {"Music"}  # Music runs, but its Automation permission is denied; Spotify plays

    assert macos.music.now_playing().app == "Spotify"
    macos.music.pause()
    assert macos.music.volume() == 100
    assert players.commands == [("Spotify", "pause")]

    # Named, the player that can't be asked still raises.
    with pytest.raises(macos.PermissionDeniedError, match="Music"):
        macos.music.now_playing(app="Music")
    with pytest.raises(macos.PermissionDeniedError, match="Music"):
        macos.music.pause(app="Music")


def test_when_every_player_fails_the_error_is_raised(players):
    players.denied = {"Music", "Spotify"}

    for call in (macos.music.now_playing, macos.music.pause, macos.music.volume, macos.music.play):
        with pytest.raises(macos.PermissionDeniedError, match="Music"):
            call()

    players.running = ["Music"]
    with pytest.raises(macos.PermissionDeniedError):
        macos.music.now_playing()


def test_play_says_when_the_player_isnt_installed(players, monkeypatch):
    from macos import apps
    from macos.errors import AppNotFoundError

    def missing(name):
        raise AppNotFoundError("unable to find application {!r}".format(name))

    players.running = ["Music"]
    monkeypatch.setattr(apps, "_locate", missing)
    with pytest.raises(AppNotFoundError, match="Spotify isn't installed"):
        macos.music.play(app="Spotify")
    assert players.scripts == []  # no "Where is Spotify?" chooser
    macos.music.play(app="Music")  # running: no need to look it up
    assert players.commands == [("Music", "play")]


def test_a_player_that_quits_meanwhile_isnt_reopened(players):
    # NSWorkspace still lists both, but they quit before the script ran: each script asks first.
    players.quit = {"Music", "Spotify"}

    assert macos.music.now_playing() is None
    for control in (macos.music.pause, macos.music.next, macos.music.volume, lambda: macos.music.seek(5)):
        with pytest.raises(macos.MacOSError, match="isn't running"):
            control()
    with pytest.raises(macos.MacOSError, match="isn't running"):
        macos.music.set_volume(20, app="Spotify")
    assert players.commands == []
    assert all('if application id "com.' in script for script in players.scripts)

    macos.music.play()  # play may open a player: it doesn't ask
    assert players.commands == [("Music", "play")]


def test_player_commands_read_the_running_players_once(players, monkeypatch):
    from macos import music

    reads = []
    real = music._running
    monkeypatch.setattr(music, "_running", lambda: reads.append(1) or real())
    macos.music.now_playing()
    macos.music.pause()
    macos.music.volume()
    assert len(reads) == 3  # one read per call, not one per helper on the way
