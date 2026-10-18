"""Unit tests for :mod:`macos.video`. They run on any platform."""

import sys
from pathlib import Path

import pytest

import macos


@pytest.fixture
def avconvert(monkeypatch):
    """Stands in for avconvert: records each command and writes the file it was asked for."""
    calls = []

    def run(args, **kwargs):
        calls.append(list(args))
        if args[0] == "avconvert":
            Path(args[args.index("--output") + 1]).write_bytes(b"converted")
        return ""

    monkeypatch.setattr(macos.video, "_run", run)
    monkeypatch.setattr(macos.video, "_check_playable", lambda path: None)  # AVFoundation's: a test of its own
    return calls


@pytest.mark.skipif(sys.platform != "darwin", reason="asks AVFoundation")
def test_video_convert_refuses_a_file_that_isnt_a_video_before_avconvert(monkeypatch, tmp_path):
    monkeypatch.setattr(macos.video, "_run", lambda *args, **kwargs: pytest.fail("avconvert ran"))
    text = tmp_path / "notes.mov"
    text.write_text("not a video")
    with pytest.raises(ValueError, match="not a video"):
        macos.video.convert(text, tmp_path / "out.mp4")


def test_video_convert_command(avconvert, tmp_path):
    target = tmp_path / "out.mp4"
    assert macos.video.convert(__file__, target, quality="medium", start=5, duration=10.5) == target
    args = avconvert[-1]
    assert args[:-1] == [
        "avconvert",
        "--source",
        __file__,
        "--preset",
        "PresetMediumQuality",
        "--start",
        "5",
        "--duration",
        "10.5",
        "--output",
    ]
    # Written beside the target, under its own name, then moved over it: never --replace.
    assert Path(args[-1]).name == "out.mp4" and Path(args[-1]).parent.parent == tmp_path
    assert target.read_bytes() == b"converted" and [path.name for path in tmp_path.iterdir()] == ["out.mp4"]
    macos.video.convert(__file__, tmp_path / "out.mov", hevc=True, height=2160)
    assert avconvert[-1][4] == "PresetHEVC3840x2160"
    macos.video.convert(__file__, tmp_path / "out.m4v", height=720)
    assert avconvert[-1][4] == "Preset1280x720"


def test_convert_and_trim_may_write_over_their_source(avconvert, monkeypatch, tmp_path):
    monkeypatch.setattr(macos.video, "info", lambda path: macos.video.VideoInfo(10.0, 640, 480, 30.0, "h264", True))
    source = tmp_path / "clip.mov"
    source.write_bytes(b"not really a video")
    link = tmp_path / "link.mov"
    link.symlink_to(source)
    for output in (source, str(source), link):
        source.write_bytes(b"not really a video")
        macos.video.convert(source, output)
        assert source.read_bytes() == b"converted"  # read where it was, written elsewhere, then moved over
    source.write_bytes(b"not really a video")
    macos.video.trim(source, source, 1)
    assert source.read_bytes() == b"converted"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["clip.mov", "link.mov"]


def test_a_conversion_that_fails_leaves_the_old_output_alone(monkeypatch, tmp_path):
    def refuse(args, **kwargs):
        Path(args[args.index("--output") + 1]).write_bytes(b"half")
        raise macos.CommandError(args, 1, "no good")

    monkeypatch.setattr(macos.video, "_run", refuse)
    monkeypatch.setattr(macos.video, "_check_playable", lambda path: None)
    target = tmp_path / "out.mp4"
    target.write_bytes(b"yesterday")
    with pytest.raises(macos.CommandError):
        macos.video.convert(__file__, target)
    assert target.read_bytes() == b"yesterday" and [path.name for path in tmp_path.iterdir()] == ["out.mp4"]


def test_video_argument_checks(tmp_path):
    with pytest.raises(ValueError, match="negative"):
        macos.video.frame(__file__, at=-1)
    with pytest.raises(ValueError, match="can't write"):
        macos.video.convert(__file__, tmp_path / "out.avi")
    with pytest.raises(ValueError, match="quality"):
        macos.video.convert(__file__, tmp_path / "out.mp4", quality="best")
    with pytest.raises(ValueError, match="height must be one of"):
        macos.video.convert(__file__, tmp_path / "out.mp4", height=333)
    with pytest.raises(ValueError, match="with hevc=True"):
        macos.video.convert(__file__, tmp_path / "out.mp4", hevc=True, height=720)
    with pytest.raises(ValueError, match="only has the 'high' quality"):
        macos.video.convert(__file__, tmp_path / "out.mp4", hevc=True, quality="low")
    with pytest.raises(ValueError, match="duration"):
        macos.video.convert(__file__, tmp_path / "out.mp4", duration=0)
    with pytest.raises(ValueError, match="fps"):
        macos.video.to_gif(__file__, tmp_path / "out.gif", fps=0)
    with pytest.raises(ValueError, match="width"):
        macos.video.to_gif(__file__, tmp_path / "out.gif", width=0)
    with pytest.raises(ValueError, match="duration"):
        macos.video.to_gif(__file__, tmp_path / "out.gif", duration=0)
    with pytest.raises(ValueError, match=".gif"):
        macos.video.to_gif(__file__, tmp_path / "out.mp4")
    with pytest.raises(ValueError, match="can't write '.avi'"):
        macos.video.trim(__file__, tmp_path / "out.avi", 1)
    with pytest.raises(ValueError, match="at least one"):
        macos.video.concat([], tmp_path / "out.mov")
    with pytest.raises(ValueError, match="positive"):
        macos.video.speed(__file__, tmp_path / "out.mov", -1)
    with pytest.raises(ValueError, match="multiple of 90"):
        macos.video.rotate(__file__, tmp_path / "out.mov", 45)
    for degrees in ("90", "%d", "90%", b"%d", bytearray(b"%d"), None):
        with pytest.raises(TypeError, match="must be a number"):
            macos.video.rotate(__file__, tmp_path / "out.mov", degrees)
    with pytest.raises(ValueError, match="at least 2 x 2"):
        macos.video.crop(__file__, tmp_path / "out.mov", (0, 0, 0, 10))
    with pytest.raises(ValueError, match="at least 2 x 2"):
        macos.video.crop(__file__, tmp_path / "out.mov", (0, 0, 1, 10))
    with pytest.raises(ValueError, match="volume"):
        macos.video.add_audio(__file__, __file__, tmp_path / "out.mov", volume=2)
    with pytest.raises(ValueError, match="negative"):
        macos.video.add_audio(__file__, __file__, tmp_path / "out.mov", at=-1)
    with pytest.raises(ValueError, match="language tag"):
        macos.video.add_language_track(__file__, __file__, tmp_path / "out.mov", "english")
    with pytest.raises(ValueError, match="tag"):
        macos.video.add_language_track(__file__, __file__, tmp_path / "out.mov", "en", original_language="pt_BR")
    with pytest.raises(ValueError, match="at least one"):
        macos.video.from_images([], tmp_path / "out.mov")
    with pytest.raises(ValueError, match="fps"):
        macos.video.from_images([__file__], tmp_path / "out.mov", fps=0)
    with pytest.raises(ValueError, match="every"):
        macos.video.frames(__file__, every=0)


@pytest.fixture
def fake_frames(monkeypatch):
    """Stands in for AVFoundation's frame reader: a frame is its time, and what's released is recorded."""
    reads, released = [], []

    def frames_at(source, times, width=None, tolerance=0.0):
        reads.append(list(times))
        return [int(moment * 100) + 1 for moment in times]

    monkeypatch.setattr(macos.video, "_frames_at", frames_at)
    monkeypatch.setattr(macos.video._cf, "release", released.append)
    return reads, released


def test_frames_are_read_a_batch_at_a_time_forwards(fake_frames):
    reads, released = fake_frames
    backwards = [0.5, 0.4, 0.3, 0.2, 0.1]
    stream = macos.video._frame_stream("clip.mov", backwards, batch=2)
    assert next(stream) == 51 and reads == [[0.4, 0.5]] and released == []  # read forwards, handed out backwards
    assert list(stream) == [41, 31, 21, 11]
    assert reads == [[0.4, 0.5], [0.2, 0.3], [0.1]]
    assert sorted(released) == [11, 21, 31, 41, 51]  # each batch released once done with: never all at once

    stream = macos.video._frame_stream("clip.mov", [0.0, 0.1, 0.2], batch=2)
    next(stream)
    stream.close()  # stopped early, by an error writing the video: its batch goes too
    assert sorted(released[5:]) == [1, 11]


def test_batches_hold_about_256_mb_of_frames():
    assert macos.video._batch(3840, 2160) == 8  # 4K: 33 MB a frame
    assert macos.video._batch(320, 160) == 64
    assert macos.video._batch(100000, 100000) == 1


def test_a_frame_that_cant_be_encoded_cancels_the_writer(monkeypatch, tmp_path):
    from contextlib import nullcontext

    from macos import video

    sent = []

    def send(receiver, selector, *args, **kwargs):
        sent.append(selector)
        return True if selector in ("startWriting", "isReadyForMoreMediaData") else 1

    monkeypatch.setattr(video, "_load", lambda: None)
    monkeypatch.setattr(video._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(video._objc, "send", send)
    monkeypatch.setattr(video._objc, "cls", lambda name: 1)
    monkeypatch.setattr(video._objc, "nsstring", lambda text: 2)
    monkeypatch.setattr(video._objc, "nsarray_of", lambda items: 3)
    monkeypatch.setattr(video._objc, "file_url", lambda path: 4)
    monkeypatch.setattr(video._media, "time", lambda seconds: 0)

    def bad_frame(picture, width, height):
        raise macos.MacOSError("could not make a video frame")

    monkeypatch.setattr(video, "_pixel_buffer", bad_frame)
    target = tmp_path / "out.mov"
    with pytest.raises(macos.MacOSError, match="video frame"):
        video._write_frames([11, 12], target, 30, 100, 100)
    # The writer is told to stop, not left to be found by the pool, and nothing is left at the target.
    assert sent[-1] == "cancelWriting" and "startWriting" in sent
    assert not target.exists() and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("stop", ["interrupted", "timed out"])
def test_an_interrupted_export_is_cancelled(monkeypatch, tmp_path, stop):
    from contextlib import nullcontext

    from macos import _media

    sent = []

    def send(receiver, selector, *args, **kwargs):
        sent.append(selector)
        return 0 if selector == "status" else 1

    def interrupted(done, timeout):
        if stop == "timed out":
            return False
        raise KeyboardInterrupt

    monkeypatch.setattr(_media._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(_media._objc, "send", send)
    monkeypatch.setattr(_media._objc, "cls", lambda name: 1)
    monkeypatch.setattr(_media._objc, "nsstring", lambda text: 2)
    monkeypatch.setattr(_media._objc, "file_url", lambda path: 3)
    monkeypatch.setattr(_media, "ignore_completion", lambda: 4)
    monkeypatch.setattr(_media._objc, "run_until", interrupted)
    target = tmp_path / "out.mov"
    # A wait that ran out raises a TimeoutError, as every other does (and still a MacOSError, as it did).
    expected = macos.WaitTimeoutError if stop == "timed out" else KeyboardInterrupt
    with pytest.raises(expected):
        _media.export(5, target)
    # The session is stopped, not left encoding into the temporary folder, which is gone.
    assert sent[-1] == "cancelExport"
    assert list(tmp_path.iterdir()) == []


def test_editing_keeps_the_videos_turn(monkeypatch):
    """insertTimeRange:ofAsset: gives the composition's tracks an identity transform: the source's are copied over."""
    from contextlib import nullcontext

    from macos import _media, _objc

    media, edited = 1, 2
    source_a, source_b, copy_a, copy_b, segment_a, segment_b, gap = 11, 12, 21, 22, 31, 32, 33
    turns = {source_a: _objc.CGAffineTransform(0, 1, -1, 0, 480, 0), source_b: _objc.CGAffineTransform(-1, 0, 0, -1, 640, 480)}
    set_on = []

    def send(receiver, selector, *args, **kwargs):
        if selector == "composition":
            return edited
        if selector == "insertTimeRange:ofAsset:atTime:error:":
            return True
        if selector == "duration":
            return _media.time(2)
        if selector == "tracksWithMediaType:":
            # The composition's video tracks, not in the source's order: matched by where their segment came from.
            return {(media, "vide"): [source_a, source_b], (edited, "vide"): [copy_b, copy_a]}.get((receiver, args[0]), [])
        if selector == "trackID":
            return receiver
        if selector == "preferredTransform":
            return turns[receiver]
        if selector == "segments":
            return {copy_a: [gap, segment_a], copy_b: [segment_b]}[receiver]  # an empty edit first: no source
        if selector == "isEmpty":
            return receiver == gap
        if selector == "sourceTrackID":
            return {gap: 0, segment_a: source_a, segment_b: source_b}[receiver]
        if selector == "setPreferredTransform:":
            set_on.append((receiver, (args[0].a, args[0].b, args[0].c, args[0].d, args[0].tx, args[0].ty)))
        return None

    monkeypatch.setattr(_media, "load", lambda: None)
    monkeypatch.setattr(_media._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(_media._objc, "send", send)
    monkeypatch.setattr(_media._objc, "cls", lambda name: 0)
    monkeypatch.setattr(_media._objc, "nsstring", lambda text: text)
    monkeypatch.setattr(_media._objc, "nsarray", lambda items: iter(items or []))

    assert _media.editable(media) == edited
    assert set_on == [(copy_b, (-1, 0, 0, -1, 640, 480)), (copy_a, (0, 1, -1, 0, 480, 0))]


def test_frame_at_the_end_reads_the_last_frame(monkeypatch):
    """info() rounds the duration to the millisecond: a frame asked at that time is the last one, not past the end."""
    from contextlib import nullcontext

    from macos import video

    asked = []
    picture = [7 / 24]  # where the picture ends: with the sound, by default

    def send(receiver, selector, *args, **kwargs):
        if selector == "duration":
            return video._media.time(7 / 24)  # a 7-frame clip at 24 fps: 0.2917 s, which info() gives as 0.292
        if selector == "tracksWithMediaType:":
            return ["picture"]
        if selector == "timeRange":
            return video._media.time_range(0, picture[0])
        if selector == "copyCGImageAtTime:actualTime:error:":
            asked.append(video._media.seconds(args[0]))
        return 1

    monkeypatch.setattr(video, "_load", lambda: None)
    monkeypatch.setattr(video, "_existing", lambda path: Path(path))
    monkeypatch.setattr(video, "_asset", lambda path: 1)
    monkeypatch.setattr(video._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(video._objc, "send", send)
    monkeypatch.setattr(video._objc, "cls", lambda name: 1)
    monkeypatch.setattr(video._objc, "cgimage_png", lambda image: b"png")
    monkeypatch.setattr(video._objc, "nsstring", lambda text: text)
    monkeypatch.setattr(video._objc, "nsarray", lambda items: iter(items))

    assert video.frame("clip.mov", at=0.292) == b"png"
    assert asked[-1] == pytest.approx(7 / 24 - 0.001, abs=0.002)  # a millisecond before the end, as frames() reads it
    assert video.frame("clip.mov", at=0.1) == b"png" and asked[-1] == pytest.approx(0.1, abs=0.002)
    with pytest.raises(ValueError, match="past the end"):
        video.frame("clip.mov", at=0.293)

    # The sound goes on after the picture: past its last frame, that frame is the one read.
    picture[0] = 0.125
    assert video.frame("clip.mov", at=0.25) == b"png" and asked[-1] == pytest.approx(0.124, abs=0.002)
    assert video.frame("clip.mov", at=0.1) == b"png" and asked[-1] == pytest.approx(0.1, abs=0.002)


@pytest.fixture
def fake_writer(monkeypatch):
    """Stands in for AVAssetWriter: records each selector, with the time it was given, if any."""
    from contextlib import nullcontext

    from macos import video

    sent, files = [], []

    def send(receiver, selector, *args, **kwargs):
        if selector == "finishWritingWithCompletionHandler:":
            Path(files[-1]).write_bytes(b"video")
        moment = next((video._media.seconds(arg) for arg in args if isinstance(arg, video._media.CMTime)), None)
        sent.append((selector, moment))
        if selector == "status":
            return video._WRITTEN
        return True if selector in ("startWriting", "isReadyForMoreMediaData", "appendPixelBuffer:withPresentationTime:") else 1

    monkeypatch.setattr(video, "_load", lambda: None)
    monkeypatch.setattr(video._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(video._objc, "send", send)
    monkeypatch.setattr(video._objc, "cls", lambda name: 1)
    monkeypatch.setattr(video._objc, "nsstring", lambda text: 2)
    monkeypatch.setattr(video._objc, "file_url", lambda path: files.append(path) or 4)
    monkeypatch.setattr(video._objc, "run_until", lambda done, timeout: done())
    monkeypatch.setattr(video._media, "ignore_completion", lambda: 5)
    monkeypatch.setattr(video, "_pixel_buffer", lambda picture, width, height: 6)
    monkeypatch.setattr(video._cf, "release", lambda value: None)
    return sent


def test_a_lone_frame_lasts_a_frame(fake_writer, tmp_path):
    """Without an end, the writer makes a single frame last about 1/15 s, not 1/fps."""
    macos.video._write_frames([11], tmp_path / "still.mov", 1, 100, 100)
    selectors = [selector for selector, _ in fake_writer]
    assert selectors.index("endSessionAtSourceTime:") < selectors.index("markAsFinished")
    assert dict(fake_writer)["endSessionAtSourceTime:"] == pytest.approx(1.0)


def test_frames_are_timed_exactly_at_any_fps(fake_writer, tmp_path):
    """1/600 s units rounded slow slideshows: fps=1/7 showed each image 6.977 s, fps=0.003 for 300 s."""
    for fps, step in ((1 / 7, 7.0), (0.003, 1 / 0.003), (29.97, 1 / 29.97), (1 / 3600, 3600.0)):
        del fake_writer[:]
        macos.video._write_frames([11, 12, 13], tmp_path / "slow.mov", fps, 100, 100)
        shown = [moment for selector, moment in fake_writer if selector == "appendPixelBuffer:withPresentationTime:"]
        assert shown == [pytest.approx(index * step, abs=1e-5) for index in range(3)]
        assert dict(fake_writer)["endSessionAtSourceTime:"] == pytest.approx(3 * step, abs=1e-5)


def test_a_stalled_writer_raises_a_timeout(fake_writer, monkeypatch, tmp_path):
    from macos import video

    monkeypatch.setattr(video._objc, "run_until", lambda done, timeout: False)
    with pytest.raises(macos.WaitTimeoutError, match="finish writing"):
        video._write_frames([11], tmp_path / "out.mov", 1, 100, 100)
    # The encoder not taking a frame is one too: still a MacOSError, and now a TimeoutError as well.
    monkeypatch.setattr(video, "_WRITER_PATIENCE", -1.0)
    send = video._objc.send
    monkeypatch.setattr(
        video._objc,
        "send",
        lambda receiver, selector, *args, **kwargs: (
            False if selector == "isReadyForMoreMediaData" else
            video._WRITING if selector == "status" else send(receiver, selector, *args, **kwargs)
        ),
    )
    with pytest.raises(macos.WaitTimeoutError, match="didn't take a frame"):
        video._write_frames([11], tmp_path / "out.mov", 1, 100, 100)
    assert issubclass(macos.WaitTimeoutError, TimeoutError) and issubclass(macos.WaitTimeoutError, macos.MacOSError)


def test_a_one_pixel_wide_image_makes_a_video_two_pixels_wide(fake_writer, monkeypatch, tmp_path):
    """Rounded to an even width, 1 pixel was 0: the writer threw an Objective-C exception, which aborted Python."""
    from types import SimpleNamespace

    from macos import image, video

    monkeypatch.setattr(image, "info", lambda path: SimpleNamespace(width=1, height=40, orientation=1))
    monkeypatch.setattr(video, "_load_image", lambda path, longest: 7)
    sizes = []
    write = video._write_frames

    def write_frames(pictures, target, fps, width, height):
        sizes.append((width, height))
        return write(pictures, target, fps, width, height)

    monkeypatch.setattr(video, "_write_frames", write_frames)
    video.from_images([__file__], tmp_path / "line.mov", fps=1)
    assert sizes == [(2, 80)]
    # And nothing reaches the writer with an empty size.
    with pytest.raises(ValueError, match="at least 2 x 2"):
        write([11], tmp_path / "out.mov", 1, 1, 40)
    assert not any(selector == "assetWriterInputWithMediaType:outputSettings:" for selector, _ in fake_writer[-3:])


def test_from_images_checks_fps(tmp_path):
    for fps in (float("nan"), float("inf"), 1001, -1):
        with pytest.raises(ValueError, match="fps"):
            macos.video.from_images([__file__], tmp_path / "out.mov", fps=fps)


def test_language_tags_are_checked_whole(tmp_path):
    for tag in ("en\n", "fr-CA\n"):
        with pytest.raises(ValueError, match="language tag"):
            macos.video.add_language_track(__file__, __file__, tmp_path / "out.mov", tag)
        with pytest.raises(ValueError, match="language tag"):
            macos.video.add_language_track(__file__, __file__, tmp_path / "out.mov", "en", original_language=tag)
    with pytest.raises(TypeError, match="language tag"):
        macos.video.add_language_track(__file__, __file__, tmp_path / "out.mov", 42)
    assert macos.video._LANGUAGE_TAG.fullmatch("es-419")


@pytest.fixture
def fake_edit(monkeypatch):
    """Stands in for the editing path: an asset of ``length`` seconds with one video track of ``rate`` fps."""
    from contextlib import nullcontext

    from macos import video

    clip = {"length": 1.0, "rate": 30.0}
    sent = []

    def send(receiver, selector, *args, **kwargs):
        sent.append((selector, args))
        if selector == "nominalFrameRate":
            return clip["rate"]
        if selector == "preferredTransform":
            return video._objc.CGAffineTransform(1, 0, 0, 1, 0, 0)
        if selector == "naturalSize":
            return video._objc.CGSize(640, 480)
        return 1

    monkeypatch.setattr(video._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(video._objc, "send", send)
    monkeypatch.setattr(video._objc, "cls", lambda name: 1)
    monkeypatch.setattr(video._objc, "new", lambda name: 1)
    monkeypatch.setattr(video._objc, "nsarray_of", lambda items: 3)
    monkeypatch.setattr(video, "_existing", lambda path: Path(path))
    monkeypatch.setattr(video, "_concat_transforms", lambda first, second: second)
    monkeypatch.setattr(video._media, "asset", lambda path: 1)
    monkeypatch.setattr(video._media, "editable", lambda media, **options: sent.append(("editable", options)) or 2)
    monkeypatch.setattr(video._media, "duration", lambda media: clip["length"])
    monkeypatch.setattr(video._media, "tracks", lambda media, kind: [9])
    monkeypatch.setattr(video._media, "export", lambda media, target, **options: target)
    return clip, sent


@pytest.mark.parametrize("rate", [48.0, 120.0, 23.976, 30.0])
def test_crop_keeps_the_frame_rate(fake_edit, tmp_path, rate):
    """600 // 48 made 48 fps 50, and a 60 fps cap halved 120 fps slow motion."""
    clip, sent = fake_edit
    clip["rate"] = rate
    macos.video.crop("clip.mov", tmp_path / "out.mov", (0, 0, 320, 240))
    (duration,) = [args[0] for selector, args in sent if selector == "setFrameDuration:"]
    assert duration.timescale / duration.value == pytest.approx(rate, abs=0.001)


def test_speed_refuses_a_factor_that_leaves_no_time(fake_edit, tmp_path):
    """Rounded to 0, the new length did nothing: the export copied the clip at its own speed, and said it worked."""
    clip, sent = fake_edit
    with pytest.raises(ValueError, match="too large"):
        macos.video.speed("clip.mov", tmp_path / "out.mov", 1e6)
    assert not any(selector == "scaleTimeRange:toDuration:" for selector, _ in sent)
    for factor in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="factor"):
            macos.video.speed("clip.mov", tmp_path / "out.mov", factor)
    assert macos.video.speed("clip.mov", tmp_path / "out.mov", 100) == tmp_path / "out.mov"


def test_frames_gif_and_reverse_stop_at_the_pictures_end(monkeypatch, tmp_path):
    """The duration counts a sound that goes on after the picture: past its last frame there was nothing to read."""
    from macos import video

    asked = []

    def stream(source, times, **options):
        asked.append(list(times))
        yield from (1 for _ in times)

    monkeypatch.setattr(video, "info", lambda path: video.VideoInfo(4.2, 640, 480, 10.0, "h264", False))
    monkeypatch.setattr(video, "_existing", lambda path: Path(path))
    monkeypatch.setattr(video, "_load", lambda: None)
    monkeypatch.setattr(video, "_last_moment", lambda path: 0.999)  # a 1-second picture
    monkeypatch.setattr(video, "_frame_stream", stream)
    monkeypatch.setattr(video._objc, "cgimage_png", lambda picture: b"png")
    monkeypatch.setattr(video._cf, "retain", lambda picture: picture)

    assert len(video.frames("clip.mov")) == 5
    assert asked[-1] == [0.0, 0.999, 0.999, 0.999, 0.999]  # as many frames, the last one held

    monkeypatch.setattr(video, "_write_frames", lambda pictures, target, fps, width, height: list(pictures) and target)
    video.reverse("clip.mov", tmp_path / "back.mov")
    assert max(asked[-1]) == 0.999 and len(asked[-1]) == 42 and asked[-1][-1] == pytest.approx(0.05)

    from macos import image

    from types import SimpleNamespace

    nothing = lambda *args: None  # noqa: E731
    monkeypatch.setattr(
        image, "_io", lambda: SimpleNamespace(CGImageDestinationAddImage=nothing, CGImageDestinationSetProperties=nothing)
    )
    monkeypatch.setattr(image, "_write", lambda target, kind, add, count: add(0) or target)
    monkeypatch.setattr(video._cf, "from_python", lambda value: None)  # the loop count: Core Foundation
    video.to_gif("clip.mov", tmp_path / "clip.gif", start=0.5, duration=1.0)
    assert asked[-1][:5] == [pytest.approx(moment) for moment in (0.5, 0.6, 0.7, 0.8, 0.9)]
    assert asked[-1][5:] == [0.999] * 5


def test_edits_keep_the_sources_metadata(fake_edit, monkeypatch, tmp_path):
    """A composition has no metadata: without the source asset, the date and place a clip was shot were dropped."""
    from types import SimpleNamespace

    from macos import video

    exported = []
    monkeypatch.setattr(video._media, "export", lambda media, target, **options: exported.append(options) or target)
    monkeypatch.setattr(video._media, "composition", lambda: 4)
    monkeypatch.setattr(video._media, "add_track", lambda media, kind: 5)
    monkeypatch.setattr(video._media, "insert", lambda *args: None)
    copied = []
    monkeypatch.setattr(video._media, "copy_track", lambda *args, **options: copied.append(options) or 6)
    send = video._objc.send
    monkeypatch.setattr(
        video._objc,
        "send",
        lambda receiver, selector, *args, **kwargs: (
            video._media.time_range(0, 1.0) if selector == "timeRange" else send(receiver, selector, *args, **kwargs)
        ),
    )
    monkeypatch.setattr(video, "_upright_size", lambda track: (640, 480))
    monkeypatch.setattr(video, "_copy_picture", lambda source, target, length: None)
    out = tmp_path / "out.mov"
    video.rotate("clip.mov", out, 90)
    video.mute("clip.mov", out)
    video.crop("clip.mov", out, (0, 0, 320, 240))
    video.speed("clip.mov", out, 2)
    monkeypatch.setattr(video._objc, "nsstring", lambda text: 8)
    monkeypatch.setattr("macos.audio.info", lambda path: SimpleNamespace(codec="aac"))
    video.add_audio("clip.mov", "sound.m4a", out)
    assert copied[-1] == {"keep_state": False}  # re-encoded with the mix: a second language left off would be lost
    video.add_language_track("clip.mov", "sound.m4a", out, "en")
    # Each clip its own asset: concat must keep the first one's, not any other's.
    monkeypatch.setattr(video._media, "asset", lambda path: {"clip.mov": 1, "other.mov": 7}[str(path)])
    video.concat(["clip.mov", "other.mov"], out)
    assert [options.get("source") for options in exported] == [1] * 7  # the source's asset, never the edit


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_times_must_be_finite(avconvert, monkeypatch, tmp_path, bad):
    """NaN passed every `< 0` check: avconvert was handed "nan", and frame() failed with a vague message."""
    monkeypatch.setattr(macos.video, "info", lambda path: macos.video.VideoInfo(10.0, 640, 480, 30.0, "h264", True))
    out = tmp_path / "out.mov"
    with pytest.raises(ValueError, match="at must"):
        macos.video.frame(__file__, at=bad)
    with pytest.raises(ValueError, match="at must"):
        macos.video.add_audio(__file__, __file__, out, at=bad)
    with pytest.raises(ValueError, match="every must"):
        macos.video.frames(__file__, every=bad)
    for label in ("start", "duration"):
        with pytest.raises(ValueError, match=label + " must"):
            macos.video.trim(__file__, out, **{label: bad})
        with pytest.raises(ValueError, match=label + " must"):
            macos.video.convert(__file__, out, **{label: bad})
        with pytest.raises(ValueError, match=label + " must"):
            macos.video.to_gif(__file__, tmp_path / "out.gif", **{label: bad})
    assert not avconvert


def test_re_encoding_edits_leave_every_track_on(fake_edit, monkeypatch, tmp_path):
    """The re-encoding exporter leaves a track that's off out: speed() and crop() dropped a dubbed video's second language."""
    from macos import video

    clip, sent = fake_edit
    monkeypatch.setattr(video, "_upright_size", lambda track: (640, 480))
    video.speed("clip.mov", tmp_path / "out.mov", 2)
    video.crop("clip.mov", tmp_path / "out.mov", (0, 0, 320, 240))
    video.rotate("clip.mov", tmp_path / "out.mov", 90)  # passthrough: the on/off state and groups survive it
    assert [args for selector, args in sent if selector == "editable"] == [{"keep_state": False}, {"keep_state": False}, {}]
