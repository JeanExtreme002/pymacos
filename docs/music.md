# Music

{mod}`macos.music` controls Apple Music and Spotify: play, pause, skip, and
what's playing.

```python
import macos

macos.music.now_playing()
# Track(title='Imagine', artist='John Lennon', album='Imagine', duration=183.0,
#       position=12.0, playing=True, app='Music')

macos.music.pause()
macos.music.next()
```

## What's playing

{func}`~macos.music.now_playing` returns the song Music or Spotify is on,
playing or paused, as a {class}`~macos.music.Track`, or `None`. When both run,
it prefers the one playing; `app="Spotify"` reads only that one. It never
opens a player: with none running, it returns `None`.

## Controlling the player

```python
macos.music.play()               # or resume
macos.music.pause()
macos.music.play_pause()         # like the play/pause key
macos.music.next()
macos.music.previous()
macos.music.play(app="Spotify")
```

Without `app`, they control the player that's playing, or the one running.
With none running, {func}`~macos.music.play` opens Music, and the others raise
{class}`~macos.MacOSError` instead of opening a player just to pause it.

## Volume and position

```python
macos.music.volume()        # 75: the player's own volume, from 0 to 100
macos.music.set_volume(40)
macos.music.seek(90)        # jump to 1:30 in the current song
```

The player's volume is separate from the system volume ({mod}`macos.volume`).
It takes an int: another number (`40.5`) is rounded down and warns
(`DeprecationWarning`), and pymacos 2.0 will raise `TypeError` instead, as
{func}`macos.volume.set` does.
These need the player running, and raise {class}`~macos.MacOSError`
otherwise.

The first time, macOS asks to allow the app running Python to control the
player (see [Permissions](permissions.md#automation)); if that's denied, the
calls raise {class}`~macos.PermissionDeniedError`.

## Reference

- {func}`macos.music.now_playing`
- {func}`macos.music.play`
- {func}`macos.music.pause`
- {func}`macos.music.play_pause`
- {func}`macos.music.next`
- {func}`macos.music.previous`
- {func}`macos.music.volume`
- {func}`macos.music.set_volume`
- {func}`macos.music.seek`
- {class}`macos.music.Track`
