"""Unit tests for :mod:`macos.video`. They run on any platform."""

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
    return calls


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


def test_an_interrupted_export_is_cancelled(monkeypatch, tmp_path):
    from contextlib import nullcontext

    from macos import _media

    sent = []

    def send(receiver, selector, *args, **kwargs):
        sent.append(selector)
        return 0 if selector == "status" else 1

    def interrupted(done, timeout):
        raise KeyboardInterrupt

    monkeypatch.setattr(_media._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(_media._objc, "send", send)
    monkeypatch.setattr(_media._objc, "cls", lambda name: 1)
    monkeypatch.setattr(_media._objc, "nsstring", lambda text: 2)
    monkeypatch.setattr(_media._objc, "file_url", lambda path: 3)
    monkeypatch.setattr(_media, "ignore_completion", lambda: 4)
    monkeypatch.setattr(_media._objc, "run_until", interrupted)
    target = tmp_path / "out.mov"
    with pytest.raises(KeyboardInterrupt):
        _media.export(5, target)
    # The session is stopped, not left encoding into the temporary folder, which is gone.
    assert sent[-1] == "cancelExport"
    assert list(tmp_path.iterdir()) == []


def test_editing_keeps_the_videos_turn(monkeypatch):
    """insertTimeRange:ofAsset: gives the composition's tracks an identity transform: the source's are copied over."""
    from contextlib import nullcontext

    from macos import _media, _objc

    media, edited = 1, 2
    source_a, source_b, copy_a, copy_b, segment_a, segment_b = 11, 12, 21, 22, 31, 32
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
            return {copy_a: [segment_a], copy_b: [segment_b]}[receiver]
        if selector == "sourceTrackID":
            return {segment_a: source_a, segment_b: source_b}[receiver]
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

    def send(receiver, selector, *args, **kwargs):
        if selector == "duration":
            return video._media.time(7 / 24)  # a 7-frame clip at 24 fps: 0.2917 s, which info() gives as 0.292
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

    assert video.frame("clip.mov", at=0.292) == b"png"
    assert asked[-1] == pytest.approx(7 / 24 - 0.001, abs=0.002)  # a millisecond before the end, as frames() reads it
    assert video.frame("clip.mov", at=0.1) == b"png" and asked[-1] == pytest.approx(0.1, abs=0.002)
    with pytest.raises(ValueError, match="past the end"):
        video.frame("clip.mov", at=0.293)
