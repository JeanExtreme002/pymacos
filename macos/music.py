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
from .errors import MacOSError

__all__ = ["Track", "now_playing", "play", "pause", "play_pause", "next", "previous", "volume", "set_volume", "seek"]

PLAYERS = ("Music", "Spotify")
_SEPARATOR = "\x1f"  # ASCII unit separator: never in a song's title


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
    names = {app.name for app in apps.running()}
    return [player for player in PLAYERS if player in names]


def _state(app: str) -> str:
    return _osascript(app, 'tell application "{}" to player state as string'.format(app)).strip()


def _player(app: Optional[str]) -> str:
    """``app``, or the running player (the one playing, if both run), or Music."""
    if app is not None:
        if app not in PLAYERS:
            raise ValueError("app must be one of {}, not {!r}".format(", ".join(PLAYERS), app))
        return app
    running = _running()
    playing = [player for player in running if _state(player) == "playing"]
    return (playing or running or ["Music"])[0]


_TRACK = """
tell application "{app}"
    if player state is stopped then return ""
    set sep to ASCII character 31
    set song to current track
    return (name of song) & sep & (artist of song) & sep & (album of song) & sep & ¬
        (duration of song as string) & sep & (player position as string) & sep & (player state as string)
end tell
"""


def _number(text: str) -> Optional[float]:
    try:
        return float(text.strip().replace(",", "."))  # AppleScript writes reals in the user's locale
    except ValueError:
        return None


def now_playing(app: Optional[str] = None) -> Optional[Track]:
    """
    Return the song Music or Spotify is on (playing or paused), or ``None``.

    ``app`` is ``"Music"`` or ``"Spotify"``; by default, the one playing.
    This never opens a player: when none is running, it returns ``None``.
    """
    if app is not None and app not in PLAYERS:
        raise ValueError("app must be one of {}, not {!r}".format(", ".join(PLAYERS), app))
    candidates = [app] if app is not None else _running()
    candidates = [player for player in candidates if player in _running()]
    found: List[Track] = []
    for player in candidates:
        output = _osascript(player, _TRACK.format(app=player)).rstrip("\n")
        if not output:
            continue
        parts = output.split(_SEPARATOR)
        if len(parts) != 6:
            raise MacOSError("{} returned something unexpected: {!r}".format(player, output))
        title, artist, album, duration, position, state = parts
        seconds = _number(duration)
        if seconds is not None and player == "Spotify":
            seconds /= 1000  # Spotify counts milliseconds
        found.append(
            Track(
                title=title,
                artist=artist,
                album=album,
                duration=seconds if seconds else None,
                position=_number(position),
                playing=state.strip() == "playing",
                app=player,
            )
        )
    playing = [track for track in found if track.playing]
    if playing:
        return playing[0]
    return found[0] if found else None


def _command(command: str, app: Optional[str], *, may_open: bool = False) -> None:
    # Only play() may open a player: pausing or skipping in one that isn't running makes no sense.
    player = _player(app) if may_open else _running_player(app)
    _osascript(player, 'tell application "{}" to {}'.format(player, command))


def play(app: Optional[str] = None) -> None:
    """
    Play (or resume), in ``app`` (``"Music"`` or ``"Spotify"``) or the running player.

    With no player running, it opens Music.
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
    player = _player(app)
    if player not in _running():
        raise MacOSError("{} isn't running".format(player))
    return player


def volume(app: Optional[str] = None) -> int:
    """
    The player's own volume, from 0 to 100 (separate from the system volume, see :mod:`macos.volume`).

    ``app`` works as in :func:`play`. Raises :class:`~macos.errors.MacOSError`
    when the player isn't running.
    """
    player = _running_player(app)
    output = _osascript(player, 'tell application "{}" to sound volume'.format(player))
    level = _number(output)
    if level is None:
        raise MacOSError("{} returned something unexpected: {!r}".format(player, output))
    return int(round(level))


def set_volume(level: int, app: Optional[str] = None) -> None:
    """Set the player's own volume, from 0 to 100. ``app`` works as in :func:`volume`."""
    if not 0 <= level <= 100:
        raise ValueError("volume must be from 0 to 100, not {}".format(level))
    player = _running_player(app)
    _osascript(player, 'tell application "{}" to set sound volume to {}'.format(player, int(level)))


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
    _osascript(player, 'tell application "{}" to set player position to {}'.format(player, float(seconds)))
