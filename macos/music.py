# -*- coding: utf-8 -*-

"""
Control Apple Music and Spotify: play, pause, skip, and see what's playing.

::

    macos.music.now_playing()      # Track(title='Imagine', artist='John Lennon', ..., playing=True, app='Music')
    macos.music.pause()
    macos.music.next()
    macos.music.play(app="Spotify")

Goes through AppleScript, like the media keys' equivalents in Shortcuts, so
the first time macOS asks to allow the app running Python (your terminal or
IDE) to control the player; if that's denied,
:class:`~macos.errors.PermissionDeniedError` is raised.
"""

import math
from dataclasses import dataclass
from typing import List, Optional

from . import apps
from ._system import applescript
from .errors import AppNotFoundError, MacOSError

__all__ = ["Track", "now_playing", "play", "pause", "play_pause", "next", "previous", "volume", "set_volume", "seek"]

# How a running player is recognized: its name is localized ("Musik", "Música"...), while
# AppleScript's `tell application "Music"` finds it by the names below in every language.
_BUNDLE_IDS = {"Music": "com.apple.Music", "Spotify": "com.spotify.client"}
PLAYERS = tuple(_BUNDLE_IDS)
_SEPARATOR = "\x1f"  # ASCII unit separator: never in a song's title
# What a script answers when its player quit after Python saw it running: telling a player that
# isn't running anything opens it, so the scripts that mustn't open one ask first.
_NOT_RUNNING = "pymacos: not running"
# Every player state of Music's and Spotify's dictionaries, as `player state as string` writes them.
_STATES = ("playing", "paused", "stopped", "fast forwarding", "rewinding")


@dataclass(frozen=True)
class Track:
    """The song a player is on."""

    title: str
    artist: str
    album: str
    duration: Optional[float]
    """In seconds, when the player knows it (not for live radio)."""
    position: Optional[float]
    """How far into the song, in seconds."""
    playing: bool
    """``False`` when paused."""
    app: str
    """``'Music'`` or ``'Spotify'``."""


def _osascript(app: str, script: str) -> str:
    return applescript(app, script)


def _running() -> List[str]:
    identifiers = {app.bundle_id for app in apps.running()}
    return [player for player in PLAYERS if _BUNDLE_IDS[player] in identifiers]


def _if_running(app: str, script: str) -> str:
    """``script`` (it tells ``app`` something), run only if ``app`` still runs: else it returns ``_NOT_RUNNING``."""
    return 'if application id "{}" is running then\n{}\nelse\n    return "{}"\nend if'.format(
        _BUNDLE_IDS[app], script.strip("\n"), _NOT_RUNNING
    )


def _tell(app: str, command: str) -> str:
    """Tell a running ``app`` ``command``, and return its answer; raises :class:`MacOSError` if it quit meanwhile."""
    output = _osascript(app, _if_running(app, 'tell application "{}" to {}'.format(app, command)))
    if output.strip() == _NOT_RUNNING:
        raise MacOSError("{} isn't running".format(app))
    return output


def _state(app: str) -> str:
    state = _osascript(app, _if_running(app, 'tell application "{}" to player state as string'.format(app))).strip()
    return "" if state == _NOT_RUNNING else state


def _check(app: Optional[str]) -> None:
    if app is not None and app not in PLAYERS:
        raise ValueError("app must be one of {}, not {!r}".format(", ".join(PLAYERS), app))


def _player(app: Optional[str], running: Optional[List[str]] = None) -> str:
    """
    ``app``, or the running player (the one playing, if both run), or Music. ``running``: when already known.

    A player that can't be asked (its Automation permission denied, say) is passed over for the
    other; only when every running player fails is the first error raised.
    """
    _check(app)
    if app is not None:
        return app
    if running is None:
        running = _running()
    answered: List[str] = []
    playing: List[str] = []
    errors: List[MacOSError] = []
    for player in running:
        try:
            state = _state(player)
        except MacOSError as error:
            errors.append(error)
            continue
        answered.append(player)
        if state == "playing":
            playing.append(player)
    if errors and not answered:
        raise errors[0]
    return (playing or answered or ["Music"])[0]


# Not "song": Music's dictionary has a constant of that name (a media kind), which can't be set,
# and the script wouldn't compile.
# A stream or an ad may have no name, artist or album: "missing value", which `&` would turn into a
# list (on its left) or the words "missing value" (on its right). Each becomes "" first, and the
# leading "" & keeps the whole a text.
_TRACK = """
tell application "{app}"
    if player state is stopped then return ""
    set sep to ASCII character 31
    set theTrack to current track
    set trackName to name of theTrack
    if trackName is missing value then set trackName to ""
    set trackArtist to artist of theTrack
    if trackArtist is missing value then set trackArtist to ""
    set trackAlbum to album of theTrack
    if trackAlbum is missing value then set trackAlbum to ""
    return "" & trackName & sep & trackArtist & sep & trackAlbum & sep & ¬
        (duration of theTrack as string) & sep & (player position as string) & sep & (player state as string)
end tell
"""


def _number(text: str) -> Optional[float]:
    try:
        return float(text.strip().replace(",", "."))  # AppleScript writes reals in the user's locale
    except ValueError:
        return None


def _track(player: str) -> Optional[Track]:
    output = _osascript(player, _if_running(player, _TRACK.format(app=player))).rstrip("\n")
    if not output or output.strip() == _NOT_RUNNING:
        return None
    parts = output.split(_SEPARATOR)
    # The state is checked too: a field that isn't text would leave the count right and the state wrong.
    if len(parts) != 6 or parts[5].strip() not in _STATES:
        raise MacOSError("{} returned something unexpected: {!r}".format(player, output))
    title, artist, album, duration, position, state = parts
    seconds = _number(duration)
    if seconds is not None and player == "Spotify":
        seconds /= 1000  # Spotify counts milliseconds
    return Track(
        title=title,
        artist=artist,
        album=album,
        duration=seconds if seconds else None,
        position=_number(position),
        playing=state.strip() == "playing",
        app=player,
    )


def now_playing(app: Optional[str] = None) -> Optional[Track]:
    """
    Return the song Music or Spotify is on (playing or paused), or ``None``.

    ``app`` is ``"Music"`` or ``"Spotify"``; by default, the one playing.
    This never opens a player: when none is running, it returns ``None``.
    Without ``app``, a player that can't be read (its Automation permission
    denied, say) is passed over; only when every running one fails is the
    error raised.
    """
    _check(app)
    running = _running()
    candidates = [player for player in ([app] if app is not None else running) if player in running]
    found: List[Track] = []
    errors: List[MacOSError] = []
    for player in candidates:
        try:
            track = _track(player)
        except MacOSError as error:
            if app is not None:
                raise
            errors.append(error)
            continue
        if track is not None:
            found.append(track)
    if errors and len(errors) == len(candidates):
        raise errors[0]
    playing = [track for track in found if track.playing]
    if playing:
        return playing[0]
    return found[0] if found else None


def _command(command: str, app: Optional[str], *, may_open: bool = False) -> None:
    # Only play() may open a player: pausing or skipping in one that isn't running makes no sense.
    if not may_open:
        _tell(_running_player(app), command)
        return
    _check(app)
    running = _running()
    player = _player(app, running)
    if player not in running:
        # Told to play, a player that isn't installed has AppleScript ask "Where is Spotify?"
        # and wait for an answer: say so instead.
        try:
            apps._locate(_BUNDLE_IDS[player])
        except AppNotFoundError:
            raise AppNotFoundError("{} isn't installed".format(player)) from None
    _osascript(player, 'tell application "{}" to {}'.format(player, command))


def play(app: Optional[str] = None) -> None:
    """
    Play (or resume), in ``app`` (``"Music"`` or ``"Spotify"``) or the running player.

    With no player running, it opens Music. Raises
    :class:`~macos.errors.AppNotFoundError` when the player isn't installed.
    """
    _command("play", app, may_open=True)


def pause(app: Optional[str] = None) -> None:
    """
    Pause the player that is playing, or ``app``.

    Like the other controls but :func:`play`, it never opens a player:
    with none running, it raises :class:`~macos.errors.MacOSError`.
    """
    _command("pause", app)


def play_pause(app: Optional[str] = None) -> None:
    """Play if paused, pause if playing, like the play/pause key."""
    _command("playpause", app)


def next(app: Optional[str] = None) -> None:
    """Skip to the next song."""
    _command("next track", app)


def previous(app: Optional[str] = None) -> None:
    """Go back to the previous song (or the start of this one, as the player decides)."""
    _command("previous track", app)


def _running_player(app: Optional[str]) -> str:
    """Like ``_player``, but never opens a player: reading or tuning one that isn't running makes no sense."""
    running = _running()  # read once: _player would read it again
    player = _player(app, running)
    if player not in running:
        raise MacOSError("{} isn't running".format(player))
    return player


def volume(app: Optional[str] = None) -> int:
    """
    The player's own volume, from 0 to 100 (separate from the system volume, see :mod:`macos.volume`).

    ``app`` works as in :func:`play`. Raises :class:`~macos.errors.MacOSError`
    when the player isn't running.
    """
    player = _running_player(app)
    output = _tell(player, "sound volume")
    level = _number(output)
    if level is None:
        raise MacOSError("{} returned something unexpected: {!r}".format(player, output))
    return int(round(level))


def set_volume(level: int, app: Optional[str] = None) -> None:
    """
    Set the player's own volume, from 0 to 100. ``app`` works as in :func:`volume`.

    A fraction is rounded, as :func:`volume` reads it; anything but a number
    (``True`` too) raises :class:`TypeError`.
    """
    if isinstance(level, bool) or not isinstance(level, (int, float)):
        raise TypeError("volume must be a number, not {!r}".format(level))
    if not 0 <= level <= 100:
        raise ValueError("volume must be from 0 to 100, not {}".format(level))
    player = _running_player(app)
    _tell(player, "set sound volume to {}".format(int(round(level))))


def seek(seconds: float, app: Optional[str] = None) -> None:
    """
    Jump to ``seconds`` into the current song, like dragging the progress bar.

    ``app`` works as in :func:`volume`. Past the end, the player moves on to the next song.
    """
    # NaN passes "< 0", and inf or nan would reach the script as the words "inf"/"nan".
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("seconds must be a number, zero or more, not {}".format(seconds))
    player = _running_player(app)
    # A plain decimal point, whatever the user's locale: AppleScript reads numbers in code that way.
    _tell(player, "set player position to {}".format(float(seconds)))
