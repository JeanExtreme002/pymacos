# Audio Files

{mod}`macos.audio` also reads, converts and edits audio files, and recognizes
the sounds in them, with no ffmpeg. For the audio devices and the microphone,
see [Audio](audio.md).

## Reading and converting

{func}`~macos.audio.info` tells what an audio file (or a video's sound)
contains, and {func}`~macos.audio.convert` converts it:

```python
macos.audio.info("song.mp3")
# AudioInfo(duration=215.3, sample_rate=44100, channels=2, codec='mp3', bitrate=192)

macos.audio.convert("podcast.wav", "podcast.m4a", quality="medium")
macos.audio.convert("song.mp3", "song.m4a", lossless=True)   # Apple Lossless
```

It reads anything macOS plays (MP3, AAC, WAV, AIFF, FLAC...) and writes
`.m4a` (AAC, or Apple Lossless with `lossless=True`), `.wav`, `.aiff` and
`.caf`, the last three as 16-bit PCM. `quality` (`"high"`, `"medium"` or
`"low"`) sets the AAC quality; `lossless=True` is only for `.m4a`.
It uses the `afconvert` command that ships with macOS.

## Editing

```python
macos.audio.trim("interview.m4a", "answer.m4a", start=95, duration=30)
macos.audio.concat(["intro.m4a", "episode.wav", "outro.m4a"], "podcast.m4a")
macos.audio.fade("song.m4a", "song-faded.m4a", fade_in=2, fade_out=5)
macos.audio.gain("quiet.m4a", "louder.m4a", 6)        # +6 dB, about twice as loud
macos.audio.reverse("word.wav", "drow.wav")
macos.audio.speed("lecture.m4a", "lecture-fast.m4a", 1.5)
```

- {func}`~macos.audio.concat` accepts files of different formats, sample
  rates and channels: they're all converted to the first one's.
- {func}`~macos.audio.gain` clips the loudest parts if pushed past the maximum.
- {func}`~macos.audio.speed` keeps the pitch by default, so voices don't turn
  into chipmunks; `keep_pitch=False` changes it with the speed. The sound is
  compressed once, into the output's format: a `.wav` output loses nothing
  more than the stretching itself.
- {func}`~macos.audio.trim` and {func}`~macos.audio.gain` go through the file
  a piece at a time, so long recordings don't fill the memory.

The output's extension sets the format, and `quality` and `lossless` work as
for {func}`~macos.audio.convert`. The edits work on 16-bit samples: a 16-bit
`.wav` edited into a `.wav` loses nothing, but a 24-bit one comes out 16-bit.

## What's in a recording

{func}`~macos.audio.classify` tells what an audio (or video) file sounds
like, with Apple's classifier of more than 300 sounds: speech, laughter,
music and instruments, dogs, birds, cars, sirens, applause, rain...

```python
macos.audio.classify("clip.m4a")
# [('speech', 0.88), ('laughter', 0.31), ('music', 0.12)]
```

It listens to the whole file, a few seconds at a time, and averages what it
hears, most likely first. Sounds shorter than half a second are too short to
tell. It runs offline and needs no permission. `limit`
and `min_confidence` work as for {func}`macos.vision.classify`.

## Reference

- {func}`macos.audio.info`
- {func}`macos.audio.convert`
- {func}`macos.audio.trim`
- {func}`macos.audio.concat`
- {func}`macos.audio.fade`
- {func}`macos.audio.gain`
- {func}`macos.audio.reverse`
- {func}`macos.audio.speed`
- {func}`macos.audio.classify`
- {class}`macos.audio.AudioInfo`
