"""Unit tests for :mod:`macos.video`. They run on any platform."""

import pytest

import macos


def test_video_convert_command(commands, tmp_path):
    macos.video.convert(__file__, tmp_path / "out.mp4", quality="medium", start=5, duration=10.5)
    assert commands.calls[-1] == [
        "avconvert",
        "--source",
        __file__,
        "--output",
        str(tmp_path / "out.mp4"),
        "--preset",
        "PresetMediumQuality",
        "--replace",
        "--start",
        "5",
        "--duration",
        "10.5",
    ]
    macos.video.convert(__file__, tmp_path / "out.mov", hevc=True, height=2160)
    assert commands.calls[-1][6] == "PresetHEVC3840x2160"
    macos.video.convert(__file__, tmp_path / "out.m4v", height=720)
    assert commands.calls[-1][6] == "Preset1280x720"


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


def test_convert_refuses_to_write_over_its_source(commands, tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not really a video")
    link = tmp_path / "link.mp4"
    link.symlink_to(source)
    for output in (source, str(source), link):
        with pytest.raises(ValueError, match="can't write over its source"):
            macos.video.convert(source, output)
    assert commands.calls == [] and source.read_bytes() == b"not really a video"


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
