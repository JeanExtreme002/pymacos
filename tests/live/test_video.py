"""Tests of :mod:`macos.video` against the real system. Skipped outside macOS."""

import ctypes

import pytest

import macos
from macos import _media, _objc
from tests.helpers import WALLPAPER_MOVIE, rgb_png


@pytest.fixture(scope="module")
def movie(tmp_path_factory):
    """A video wallpaper, or else a short screen recording (CI runners have no video wallpapers)."""
    if WALLPAPER_MOVIE.exists():
        return WALLPAPER_MOVIE
    if not macos.screen.has_permission():
        pytest.skip("no video wallpaper, and no Screen Recording permission to make a video")
    # Recorded once for the module: each recording is a few seconds, and screencapture has hung on CI.
    try:
        return macos.screen.record(tmp_path_factory.mktemp("movie") / "screen.mov", 3, region=(0, 0, 320, 200))
    except macos.MacOSError as error:
        pytest.skip("no video to test with: {}".format(error))  # these test video, not screen recording


def test_video_info_frame_and_convert(movie, tmp_path):
    import struct

    details = macos.video.info(movie)
    assert details.duration > 2 and details.width > details.height > 0 and details.codec

    thumbnail = macos.video.frame(movie, at=2.0, size=320)
    assert max(struct.unpack(">II", thumbnail[16:24])) == 320
    with pytest.raises(ValueError, match="past the end"):
        macos.video.frame(movie, at=details.duration + 10)

    clip = macos.video.convert(movie, tmp_path / "clip.mp4", height=480, duration=1)
    small = macos.video.info(clip)
    assert (small.codec, round(small.duration)) == ("h264", 1)
    assert small.width <= 640 and small.height <= 480
    with pytest.raises(ValueError, match="no sound"):
        macos.video.convert(clip, tmp_path / "sound.m4a")


def test_video_convert_keeps_only_the_sound(tmp_path):
    import subprocess

    speech = tmp_path / "speech.aiff"
    subprocess.run(["say", "-o", str(speech), "hello"], check=True)

    sound = macos.video.convert(speech, tmp_path / "speech.m4a")

    details = macos.video.info(sound)
    assert details.has_audio and details.width == 0 and details.duration > 0


def test_video_to_gif(movie, tmp_path):
    from macos import _cf

    gif = macos.video.to_gif(movie, tmp_path / "clip.gif", fps=5, width=160, duration=2)

    details = macos.image.info(gif)
    assert (details.format, details.width) == ("gif", 160)
    io = macos.image._io()
    with _cf.owned(macos.image._source(gif)) as source:
        assert io.CGImageSourceGetCount(source) == 10  # 2 seconds at 5 fps
        with _cf.owned(io.CGImageSourceCopyPropertiesAtIndex(source, 3, None)) as frame:
            assert _cf.to_python(frame)["{GIF}"]["DelayTime"] == pytest.approx(0.2)
    # It loops through the NETSCAPE2.0 block; without it, viewers play it once.
    assert b"NETSCAPE2.0" in gif.read_bytes()
    once = macos.video.to_gif(movie, tmp_path / "once.gif", fps=5, width=160, duration=1, loop=False)
    assert b"NETSCAPE2.0" not in once.read_bytes()


def _brightening_clip(tmp_path, frames=24):
    """A 320x160 clip: red, blue, green and white quarters, with a gray square brightening frame after frame."""
    colors = [(255, 0, 0), (0, 0, 255), (0, 255, 0), (255, 255, 255)]
    images = []
    for index in range(frames):

        def pixel(x, y, index=index):
            if 140 <= x < 180 and 10 <= y < 40:
                return (index * 10,) * 3
            return colors[(x >= 160) + 2 * (y >= 80)]

        image = tmp_path / "frame-{:02}.png".format(index)
        image.write_bytes(rgb_png(320, 160, pixel))
        images.append(image)
    return macos.video.from_images(images, tmp_path / "clip.mp4", fps=24)


def _frame_colors(path, tmp_path, at=0.5):
    """The main color of each corner of the frame at ``at`` seconds, and the frame's size."""
    shot = tmp_path / "shot.png"
    shot.write_bytes(macos.video.frame(path, at=at))
    details = macos.image.info(shot)
    width, height = details.width, details.height
    corners = []
    for x, y in ((5, 5), (width - 25, 5), (5, height - 25), (width - 25, height - 25)):
        corner = macos.image.crop(shot, tmp_path / "corner.png", (x, y, 20, 20))
        corners.append(macos.image.dominant_colors(corner, count=1)[0])
    return (width, height), corners


def _is(color, target):
    # Loose: H.264 shifts colors a little (pure green comes back as #43fb00).
    return all(abs(int(color[index : index + 2], 16) - target[index // 2]) < 90 for index in (1, 3, 5))


def test_video_editing(speech, tmp_path):
    video = macos.video
    red, blue, green, white = (255, 0, 0), (0, 0, 255), (0, 255, 0), (255, 255, 255)
    clip = _brightening_clip(tmp_path)
    details = video.info(clip)
    assert (details.width, details.height, details.duration, details.has_audio) == (320, 160, 1.0, False)
    size, corners = _frame_colors(clip, tmp_path)
    assert size == (320, 160) and [_is(c, t) for c, t in zip(corners, (red, blue, green, white))] == [True] * 4

    assert len(video.frames(clip, every=0.25)) == 4
    voiced = video.add_audio(clip, speech, tmp_path / "voiced.mov")
    assert video.info(voiced).has_audio and video.info(voiced).duration == 1.0
    assert not video.info(video.mute(voiced, tmp_path / "muted.mov")).has_audio
    assert abs(video.info(video.trim(voiced, tmp_path / "trimmed.mov", 0.25, 0.5)).duration - 0.5) < 0.15
    assert video.info(video.concat([voiced, clip, voiced], tmp_path / "joined.mp4")).duration == 3.0
    assert video.info(video.speed(voiced, tmp_path / "fast.mov", 2)).duration == 0.5

    size, corners = _frame_colors(video.rotate(clip, tmp_path / "turned.mov", 90), tmp_path)
    assert size == (160, 320)  # a quarter turn clockwise: the bottom-left (green) goes to the top-left
    assert [_is(c, t) for c, t in zip(corners, (green, red, white, blue))] == [True] * 4
    size, corners = _frame_colors(video.crop(clip, tmp_path / "cropped.mov", (200, 80, 120, 80)), tmp_path)
    assert size == (120, 80) and all(_is(c, white) for c in corners)  # the bottom-right quarter

    def square(path, at):
        shot = tmp_path / "square.png"
        shot.write_bytes(video.frame(path, at=at))
        return int(macos.image.dominant_colors(macos.image.crop(shot, tmp_path / "s.png", (150, 15, 20, 15)), 1)[0][1:3], 16)

    backwards = video.reverse(voiced, tmp_path / "backwards.mov")
    assert video.info(backwards).has_audio
    assert square(clip, 0.1) < square(clip, 0.9) and square(backwards, 0.1) > square(backwards, 0.9)

    dual = video.add_language_track(voiced, speech, tmp_path / "dual.mp4", "en", original_language="pt-BR")
    with _objc.autorelease_pool():
        sounds = _media.tracks(_media.asset(dual), "soun")
        languages = [_objc.pystring(_objc.send(track, "languageCode")) for track in sounds]
        enabled = [bool(_objc.send(track, "isEnabled", restype=_objc.BOOL)) for track in sounds]
        groups = {_objc.send(track, "alternateGroupID", restype=ctypes.c_int32) for track in sounds}
    assert (languages, enabled, len(groups)) == (["por", "eng"], [True, False], 1)
    assert video.info(dual).duration == 1.0


def test_reverse_reads_the_frames_a_few_at_a_time(tmp_path, monkeypatch):
    clip = _brightening_clip(tmp_path)
    monkeypatch.setattr(macos.video, "_FRAME_BUDGET", 320 * 160 * 4 * 5)  # five frames a batch
    backwards = macos.video.reverse(clip, tmp_path / "backwards.mov")  # no sound: written straight to it
    assert not macos.video.info(backwards).has_audio

    def square(at):
        shot = tmp_path / "square.png"
        shot.write_bytes(macos.video.frame(backwards, at=at))
        crop = macos.image.crop(shot, tmp_path / "s.png", (150, 15, 20, 15))
        return int(macos.image.dominant_colors(crop, 1)[0][1:3], 16)

    levels = [square(at) for at in (0.05, 0.3, 0.55, 0.8, 0.95)]
    assert levels == sorted(levels, reverse=True) and levels[0] - levels[-1] > 150  # darker and darker, across batches
    assert len(macos.video.frames(clip, every=0.125)) == 8  # across batches too
