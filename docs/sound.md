# Sound

{mod}`macos.sound` plays alert sounds and audio files.

```python
import macos

macos.sound.play("Glass")            # a system alert sound
macos.sound.play("done.mp3")         # an audio file
macos.sound.beep()                   # the alert sound chosen in System Settings
```

## Alert sounds

{func}`~macos.sound.names` lists the sounds you can play by name, the same ones
as in System Settings › Sound:

```python
macos.sound.names()   # ['Basso', 'Blow', 'Bottle', 'Frog', 'Funk', 'Glass', ...]
```

They come from `~/Library/Sounds`, `/Library/Sounds` and
`/System/Library/Sounds`, searched in that order: your own sound wins over a
system one of the same name, for `play` and `set_alert_sound` alike.

## Audio files

Any format macOS plays works: MP3, AAC/M4A, WAV, AIFF...

```python
macos.sound.play("~/Music/fanfare.m4a", volume=0.5)
```

`volume` goes from 0.0 to 1.0, relative to the system volume (see
[Volume](volume.md) to change that).

A `pathlib.Path` always means a file, even with no extension
(`Path("chime")`). Text means a file when it has a folder in it or an
extension (`"./chime"`, `"done.mp3"`), and a sound name otherwise; a name with
a dot in it, such as `"My.Sound"` from `My.Sound.aiff`, still plays when no
file of that name exists.

A file the app isn't allowed to read (its permissions, or a folder such as
Desktop without access) raises `PermissionError`, and one that isn't audio
`ValueError`.

## Waiting

{func}`~macos.sound.play` returns when the sound ends. Pass `wait=False` to
return right away while it plays:

```python
macos.sound.play("Submarine", wait=False)
start_long_task()
```

The sound plays in your script's process: if the script ends first, the sound
stops with it. Keep the default `wait=True` for a script's last sound.

## Sound settings

The alert sound, its volume and the interface's sound effects, as in System
Settings › Sound:

```python
macos.sound.set_alert_sound("Funk")      # one of names()
macos.sound.set_alert_volume(0.5)        # apart from music and videos
macos.sound.set_ui_sounds(False)         # no sound when emptying the Trash
```

`set_alert_sound(None)` goes back to macOS's own. Apps pick the alert sound
up when they're reopened.

## Reference

- {func}`macos.sound.play`
- {func}`macos.sound.beep`
- {func}`macos.sound.names`
- {func}`macos.sound.alert_sound`
- {func}`macos.sound.set_alert_sound`
- {func}`macos.sound.alert_volume`
- {func}`macos.sound.set_alert_volume`
- {func}`macos.sound.ui_sounds`
- {func}`macos.sound.set_ui_sounds`
