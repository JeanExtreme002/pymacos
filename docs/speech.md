# Speech

{func}`macos.say` speaks text out loud with the system voices.

```python
import macos

macos.say("Hello from Python")
```

Choose a voice and a speed in words per minute (about 175 to 200 is normal):

```python
macos.say("Hello, how are you?", voice="Samantha", rate=180)
```

`rate` must be a positive number (fractions such as `180.5` work); anything
else raises an error rather than being silently ignored by macOS.

By default `say` waits until the speech ends. Pass `wait=False` to return right
away while it plays:

```python
macos.say("Starting the backup", wait=False)
run_backup()
```

## Saving to a file

With `output`, nothing is played: the speech is saved to an audio file, and
its path is returned:

```python
macos.say("Welcome to the show", voice="Samantha", output="intro.m4a")
```

The format follows the extension: `.aiff`, `.m4a`, `.wav` or `.caf`.

## Voices

{func}`macos.speech.voices` lists the installed voices:

```python
for voice in macos.speech.voices():
    print(voice.name, voice.locale, voice.sample)
```

```text
Albert en_US Hello! My name is Albert.
Thomas fr_FR Bonjour, je m’appelle Thomas.
...
```

More voices can be downloaded in System Settings › Accessibility › Spoken
Content › System Voice › Manage Voices.

An unknown voice name is not an error: macOS falls back to the default voice.
Names are matched loosely, so `"samantha"` works too. The one exception is
`voice="?"`, which raises `ValueError`: the `say` command would list the voices
instead of speaking. Use {func}`macos.speech.voices` for that.

## Reference

- {func}`macos.say`
- {func}`macos.speech.voices`
- {class}`macos.speech.Voice`
