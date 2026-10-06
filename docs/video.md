# Video

{mod}`macos.video` reads videos, grabs their frames and converts them, with
AVFoundation, the framework behind QuickTime Player. Any format QuickTime opens
works (MOV, MP4, M4V, HEVC, ProRes...), with no ffmpeg to install.

```python
import macos

macos.video.info("clip.mov")
# VideoInfo(duration=12.5, width=1920, height=1080, fps=30.0, codec='h264', has_audio=True)

macos.video.convert("clip.mov", "clip.mp4", quality="medium")
```

## Frames

{func}`~macos.video.frame` returns the frame shown at a time, in seconds, as
PNG bytes, turned upright like the video plays:

```python
from pathlib import Path

Path("cover.png").write_bytes(macos.video.frame("clip.mov", at=3.0))
Path("thumb.png").write_bytes(macos.video.frame("clip.mov", at=3.0, size=320))
```

`size` limits the longest side, for thumbnails.

## Converting

{func}`~macos.video.convert` converts, compresses, resizes and trims:

```python
macos.video.convert("screen.mov", "share.mp4", quality="medium")   # smaller
macos.video.convert("clip.mov", "clip.mp4", hevc=True)             # HEVC (H.265)
macos.video.convert("4k.mov", "hd.mp4", height=1080)               # resized
macos.video.convert("talk.mov", "intro.mp4", start=0, duration=10) # the first 10 s
macos.video.convert("talk.mov", "talk.m4a")                        # the sound only
```

- The output's extension sets the container: `.mp4`, `.mov`, `.m4v`, or `.m4a`
  for the sound only.
- `quality` is `"high"` (the default), `"medium"` or `"low"`, a small preview.
- `height` fits the video in 640×480, 960×540, 1280×720, 1920×1080 or
  3840×2160 (`height=480` to `2160`), keeping its proportions: a 16:9 video at
  `height=480` becomes 640×360. With `height`, `quality` is ignored.
- `hevc=True` encodes in HEVC, smaller than H.264 at the same quality, at the
  high quality or at `height=1080` or `2160`.

It uses the `avconvert` command that ships with macOS, and replaces the output
if it exists; the output can't be the source itself (it raises `ValueError`).
To record the screen, see {func}`macos.screen.record`.

## Animated GIFs

{func}`~macos.video.to_gif` turns a video, or part of it, into a GIF that
loops, for a README, an issue or a chat:

```python
macos.screen.record("demo.mov", 8, region=(0, 0, 1280, 800))
macos.video.to_gif("demo.mov", "demo.gif", fps=10, width=640)
macos.video.to_gif("talk.mov", "moment.gif", start=42, duration=3)
```

`fps` (10 by default) and `width` (480 pixels, never wider than the video)
set its smoothness and size. The GIF loops forever; `loop=False` plays it
once. GIFs get big fast: a few seconds at 10 fps and
480 pixels is a good size.

## Editing

```python
macos.video.trim("lecture.mov", "question.mov", start=1800, duration=90)
macos.video.concat(["intro.mov", "talk.mov", "outro.mov"], "full.mp4")
macos.video.speed("walk.mov", "timelapse.mp4", 8)
macos.video.rotate("sideways.mov", "upright.mov", 90)        # clockwise
macos.video.crop("screen.mov", "window.mov", (100, 80, 1280, 720))
macos.video.mute("clip.mov", "silent.mov")
macos.video.reverse("jump.mov", "jump-backwards.mov")
```

- {func}`~macos.video.trim`, {func}`~macos.video.rotate` and
  {func}`~macos.video.mute` don't re-encode: they're fast and lossless. The
  trim lands on the nearest keyframe, so it may start a fraction of a second
  early; {func}`~macos.video.convert` with `start` and `duration` is exact to
  the frame.
- {func}`~macos.video.concat` is made for clips of the same size, like parts
  of one recording.
- {func}`~macos.video.speed` keeps the sound's pitch.
- {func}`~macos.video.crop` measures the box on the upright picture, in
  pixels from the top-left corner.
- {func}`~macos.video.reverse` plays the sound backwards too. It reads every
  frame, so it's best for short clips; it reads them a few at a time (about
  256 MB of frames at once), so a long or 4K one takes time, not all the memory.

The others re-encode at the highest quality. The output can be a `.mov`,
`.mp4` or `.m4v`.

## Adding a soundtrack

{func}`~macos.video.add_audio` adds music or a voice-over to a video:

```python
macos.video.add_audio("trip.mov", "music.m4a", "trip-music.mp4", volume=0.4)   # under the original sound
macos.video.add_audio("talk.mov", "dub.m4a", "dubbed.mov", replace=True)       # instead of it
macos.video.add_audio("clip.mov", "sting.m4a", "clip-sting.mov", at=12.5)      # from 12.5 s
```

By default the sound plays over the video's own; `replace=True` drops the
original. `at` is where it starts, and a sound longer than the video is cut at
its end. To use part of a song, {func}`macos.audio.trim` it first.

{func}`~macos.video.add_language_track` adds a dub as a separate track
instead, which players offer in their audio menu, next to the original:

```python
macos.video.add_language_track("film.mov", "film-english.m4a", "film-dual.mov", "en", original_language="es")
```

Languages are tags such as `"en"`, `"fr-CA"` or `"es-419"`. The original
sound stays the default, and the video isn't re-encoded.

## Frames and timelapses

{func}`~macos.video.frames` takes a frame every few seconds, and
{func}`~macos.video.from_images` makes a video from images:

```python
for index, png in enumerate(macos.video.frames("talk.mov", every=30, size=640)):
    Path("frame-{:03}.png".format(index)).write_bytes(png)

photos = sorted(Path("~/Pictures/Garden").expanduser().glob("*.jpg"))
macos.video.from_images(photos, "garden.mp4", fps=12, width=1280)
```

The video takes the first image's size, or `width`; images of other shapes
are fitted in, on black. With {func}`macos.camera.photo` in a loop, it makes a
webcam timelapse, and {func}`macos.image.contact_sheet` puts the frames of a
video on one page.

## Reference

- {func}`macos.video.info`
- {func}`macos.video.frame`
- {func}`macos.video.convert`
- {func}`macos.video.to_gif`
- {func}`macos.video.frames`
- {func}`macos.video.trim`
- {func}`macos.video.concat`
- {func}`macos.video.speed`
- {func}`macos.video.rotate`
- {func}`macos.video.crop`
- {func}`macos.video.mute`
- {func}`macos.video.reverse`
- {func}`macos.video.add_audio`
- {func}`macos.video.add_language_track`
- {func}`macos.video.from_images`
- {class}`macos.video.VideoInfo`
