# -*- coding: utf-8 -*-

"""
Read, grab frames from and convert videos.

::

    macos.video.info("clip.mov")                 # VideoInfo(duration=12.5, width=1920, height=1080, ...)
    Path("cover.png").write_bytes(macos.video.frame("clip.mov", at=3.0))
    macos.video.convert("clip.mov", "small.mp4", quality="medium")
    macos.video.to_gif("screen.mov", "demo.gif", fps=10, width=480)

Uses AVFoundation, the framework behind QuickTime Player, and the
``avconvert`` command that ships with macOS: every format QuickTime opens
(MOV, MP4, M4V, HEVC, ProRes...) works, with no ffmpeg to install.
"""

import ctypes
import os
import re
import struct
import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Generator, Iterable, List, Optional, Sequence, Tuple, Union

from . import _cf, _files, _media, _objc
from ._system import framework, run as _run
from .errors import MacOSError

__all__ = [
    "VideoInfo",
    "info",
    "frame",
    "frames",
    "convert",
    "to_gif",
    "trim",
    "concat",
    "speed",
    "rotate",
    "crop",
    "reverse",
    "mute",
    "add_audio",
    "add_language_track",
    "from_images",
]

PathLike = Union[str, "os.PathLike[str]"]

_CODECS = {
    "avc1": "h264",
    "hvc1": "hevc",
    "hev1": "hevc",
    "ap4h": "prores",
    "ap4x": "prores",
    "apch": "prores",
    "apcn": "prores",
    "apcs": "prores",
    "apco": "prores",
    "jpeg": "mjpeg",
}

# What convert() writes for each output extension.
_EXTENSIONS = {".mov", ".mp4", ".m4v", ".m4a"}

# avconvert's presets: by quality, and by height for resizing.
_QUALITY = {"high": "PresetHighestQuality", "medium": "PresetMediumQuality", "low": "PresetLowQuality"}
_HEIGHTS = {480: "Preset640x480", 540: "Preset960x540", 720: "Preset1280x720", 1080: "Preset1920x1080", 2160: "Preset3840x2160"}
_HEVC_HEIGHTS = {1080: "PresetHEVC1920x1080", 2160: "PresetHEVC3840x2160"}


class _CMTime(ctypes.Structure):
    _fields_ = [("value", ctypes.c_int64), ("timescale", ctypes.c_int32), ("flags", ctypes.c_uint32), ("epoch", ctypes.c_int64)]


_VALID = 1  # kCMTimeFlags_Valid
_TIMESCALE = 600  # the usual movie timescale: exact for 24, 25, 30 and 60 fps


@dataclass(frozen=True)
class VideoInfo:
    """What a video file contains."""

    duration: float
    """In seconds."""
    width: int
    """In pixels, as it plays (turned upright, like a portrait phone video)."""
    height: int
    fps: Optional[float]
    """Frames per second, as the file declares it."""
    codec: Optional[str]
    """``'h264'``, ``'hevc'``, ``'prores'``... or the codec's four-character code for others."""
    has_audio: bool


def _load() -> None:
    framework("AVFoundation")
    framework("AppKit")


_existing = _files.existing


def _asset(path: Path) -> int:
    """An autoreleased ``AVURLAsset``. Call inside an autorelease pool."""
    asset = _objc.send(
        _objc.cls("AVURLAsset"), "URLAssetWithURL:options:", _objc.file_url(path), None, argtypes=(_objc.id, _objc.id)
    )
    if not asset or not _objc.send(asset, "isPlayable", restype=_objc.BOOL):
        raise ValueError("{} is not a video macOS can play".format(path))
    return asset


def _tracks(asset: int, kind: str) -> List[int]:
    return list(_objc.nsarray(_objc.send(asset, "tracksWithMediaType:", _objc.nsstring(kind), argtypes=(_objc.id,))))


def _seconds(time: _CMTime) -> float:
    return time.value / time.timescale if time.flags & _VALID and time.timescale else 0.0


@lru_cache(maxsize=None)
def _core_media() -> ctypes.CDLL:
    media = framework("CoreMedia")
    media.CMFormatDescriptionGetMediaSubType.argtypes = (ctypes.c_void_p,)
    media.CMFormatDescriptionGetMediaSubType.restype = ctypes.c_uint32
    return media


@lru_cache(maxsize=None)
def _core_video() -> ctypes.CDLL:
    video_library = framework("CoreVideo")
    pointer = ctypes.c_void_p
    signatures = {
        "CVPixelBufferCreate": (
            (pointer, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint32, pointer, ctypes.POINTER(pointer)),
            ctypes.c_int32,
        ),
        "CVPixelBufferLockBaseAddress": ((pointer, ctypes.c_uint64), ctypes.c_int32),
        "CVPixelBufferUnlockBaseAddress": ((pointer, ctypes.c_uint64), ctypes.c_int32),
        "CVPixelBufferGetBaseAddress": ((pointer,), pointer),
        "CVPixelBufferGetBytesPerRow": ((pointer,), ctypes.c_size_t),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(video_library, name)
        function.argtypes = argtypes
        function.restype = restype
    return video_library


@lru_cache(maxsize=None)
def _graphics() -> ctypes.CDLL:
    graphics = framework("CoreGraphics")
    pointer = ctypes.c_void_p
    signatures = {
        "CGBitmapContextCreate": (
            (pointer, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, pointer, ctypes.c_uint32),
            pointer,
        ),
        "CGContextSetRGBFillColor": ((pointer, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double), None),
        "CGContextFillRect": ((pointer, _objc.CGRect), None),
        "CGContextDrawImage": ((pointer, _objc.CGRect, pointer), None),
        "CGContextRelease": ((pointer,), None),
        "CGImageGetWidth": ((pointer,), ctypes.c_size_t),
        "CGImageGetHeight": ((pointer,), ctypes.c_size_t),
        "CGAffineTransformConcat": ((_objc.CGAffineTransform, _objc.CGAffineTransform), _objc.CGAffineTransform),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(graphics, name)
        function.argtypes = argtypes
        function.restype = restype
    return graphics


def _upright_size(track: int) -> Tuple[int, int]:
    size = _objc.send(track, "naturalSize", restype=_objc.CGSize)
    transform = _objc.send(track, "preferredTransform", restype=_objc.CGAffineTransform)
    width, height = abs(round(size.width)), abs(round(size.height))
    # A quarter turn (a portrait phone video) swaps the sides.
    return (height, width) if abs(transform.b) > 0.5 and abs(transform.c) > 0.5 else (width, height)


def info(path: PathLike) -> VideoInfo:
    """Return the duration, size, frame rate and codec of a video file, and whether it has sound."""
    _load()
    source = _existing(path)
    with _objc.autorelease_pool():
        asset = _asset(source)
        duration = _seconds(_objc.send(asset, "duration", restype=_CMTime))
        videos = _tracks(asset, "vide")
        width = height = 0
        fps: Optional[float] = None
        codec: Optional[str] = None
        if videos:
            width, height = _upright_size(videos[0])
            rate = float(_objc.send(videos[0], "nominalFrameRate", restype=ctypes.c_float))
            fps = round(rate, 3) if rate > 0 else None
            formats = list(_objc.nsarray(_objc.send(videos[0], "formatDescriptions")))
            if formats:
                code = struct.pack(">I", _core_media().CMFormatDescriptionGetMediaSubType(formats[0])).decode("latin-1")
                codec = _CODECS.get(code, code.strip())
        return VideoInfo(
            duration=round(duration, 3),
            width=width,
            height=height,
            fps=fps,
            codec=codec,
            has_audio=bool(_tracks(asset, "soun")),
        )


def frame(path: PathLike, at: float = 0.0, *, size: Optional[int] = None) -> bytes:
    """
    Return the frame shown ``at`` seconds into a video, as PNG bytes.

    ``size`` limits the longest side, in pixels, for thumbnails::

        Path("thumb.png").write_bytes(macos.video.frame("clip.mov", at=5, size=320))

    The frame is turned upright, like the video plays.
    """
    if at < 0:
        raise ValueError("at must not be negative, not {}".format(at))
    if size is not None and size <= 0:
        raise ValueError("size must be positive, not {}".format(size))
    _load()
    source = _existing(path)
    with _objc.autorelease_pool():
        asset = _asset(source)
        duration = _seconds(_objc.send(asset, "duration", restype=_CMTime))
        if at > duration:
            raise ValueError("at={} is past the end of the {:.3f}-second video".format(at, duration))
        generator = _objc.send(
            _objc.cls("AVAssetImageGenerator"), "assetImageGeneratorWithAsset:", asset, argtypes=(_objc.id,)
        )
        _objc.send(generator, "setAppliesPreferredTrackTransform:", True, argtypes=(_objc.BOOL,), restype=None)
        # The exact frame, not the nearest keyframe.
        exact = _CMTime(0, 1, _VALID, 0)
        for selector in ("setRequestedTimeToleranceBefore:", "setRequestedTimeToleranceAfter:"):
            _objc.send(generator, selector, exact, argtypes=(_CMTime,), restype=None)
        if size is not None:
            _objc.send(
                generator, "setMaximumSize:", _objc.CGSize(size, size), argtypes=(_objc.CGSize,), restype=None
            )
        actual = _CMTime()
        error = ctypes.c_void_p()
        image = _objc.send(
            generator,
            "copyCGImageAtTime:actualTime:error:",
            _CMTime(round(at * _TIMESCALE), _TIMESCALE, _VALID, 0),
            ctypes.byref(actual),
            ctypes.byref(error),
            argtypes=(_CMTime, ctypes.c_void_p, ctypes.c_void_p),
            restype=ctypes.c_void_p,
        )
        if not image:
            raise MacOSError("could not read the frame at {}s: {}".format(at, _objc.error_message(error) or "no image"))
        return _objc.cgimage_png(image)


def convert(
    source: PathLike,
    output: PathLike,
    *,
    quality: str = "high",
    hevc: bool = False,
    height: Optional[int] = None,
    start: Optional[float] = None,
    duration: Optional[float] = None,
) -> Path:
    """
    Convert, compress, resize or trim a video, and return ``output``.

    ``output``'s extension sets the container: ``.mp4``, ``.mov`` or ``.m4v``;
    ``.m4a`` keeps only the sound. ``quality`` is ``"high"``, ``"medium"`` or
    ``"low"`` (a small preview, about 224 pixels wide). ``hevc=True`` encodes
    in HEVC (H.265), smaller than H.264 at the same quality. ``height``
    resizes it to fit 640×480, 960×540, 1280×720, 1920×1080 or 3840×2160
    (``height=480`` to ``2160``; only 1080 and 2160 with HEVC), keeping its
    proportions: a 16:9 video at ``height=480`` becomes 640×360 (``quality``
    is then ignored). ``start``
    and ``duration``, in seconds, keep only part of it::

        macos.video.convert("screen.mov", "share.mp4", quality="medium")
        macos.video.convert("talk.mov", "talk.m4a")                        # the sound only
        macos.video.convert("clip.mov", "intro.mp4", start=0, duration=10)

    Replaces ``output`` if it exists. Uses ``avconvert``, which ships with macOS.
    """
    original = _existing(source)
    target = Path(output).expanduser().absolute()
    extension = target.suffix.lower()
    if extension not in _EXTENSIONS:
        raise ValueError("can't write {!r} videos; use one of {}".format(target.suffix, ", ".join(sorted(_EXTENSIONS))))
    if quality not in _QUALITY:
        raise ValueError("quality must be 'high', 'medium' or 'low', not {!r}".format(quality))
    for label, value in (("start", start), ("duration", duration)):
        if value is not None and (value < 0 or (label == "duration" and value == 0)):
            raise ValueError("{} must be positive, not {}".format(label, value))
    if extension == ".m4a":
        if not info(original).has_audio:
            raise ValueError("{} has no sound to keep".format(original))
        preset = "PresetAppleM4A"
    elif height is not None:
        heights = _HEVC_HEIGHTS if hevc else _HEIGHTS
        if height not in heights:
            raise ValueError(
                "height must be one of {}{}, not {}".format(
                    ", ".join(str(value) for value in sorted(heights)), " with hevc=True" if hevc else "", height
                )
            )
        preset = heights[height]
    else:
        preset = "PresetHEVCHighestQuality" if hevc and quality == "high" else _QUALITY[quality]
        if hevc and quality != "high":
            raise ValueError("hevc=True only has the 'high' quality; pass height= to make it smaller")
    if _same_file(original, target):
        # avconvert --replace would delete the source before reading it.
        raise ValueError("convert() can't write over its source; pick another output")
    target.parent.mkdir(parents=True, exist_ok=True)
    args = ["avconvert", "--source", str(original), "--output", str(target), "--preset", preset, "--replace"]
    if start is not None:
        args += ["--start", str(start)]
    if duration is not None:
        args += ["--duration", str(duration)]
    _run(args)
    return target


def _same_file(first: Path, second: Path) -> bool:
    """Whether two paths are the same file (through a link or another spelling, too)."""
    try:
        return first == second or os.path.samefile(str(first), str(second))
    except OSError:  # one of them doesn't exist
        return False


def _frames_at(
    source: Path, times: Sequence[float], *, width: Optional[int] = None, tolerance: float = 0.0
) -> List[int]:
    """
    The frames shown at ``times`` (in seconds), upright, as owned ``CGImage`` objects: release each one.

    ``width`` scales them down; ``tolerance`` lets it take the nearest frame
    within that many seconds, which is much faster than the exact one.
    """
    pictures: List[int] = []
    try:
        with _objc.autorelease_pool():
            media = _asset(source)
            generator = _objc.send(
                _objc.cls("AVAssetImageGenerator"), "assetImageGeneratorWithAsset:", media, argtypes=(_objc.id,)
            )
            _objc.send(generator, "setAppliesPreferredTrackTransform:", True, argtypes=(_objc.BOOL,), restype=None)
            leeway = _CMTime(round(tolerance * _TIMESCALE), _TIMESCALE, _VALID, 0)
            for selector in ("setRequestedTimeToleranceBefore:", "setRequestedTimeToleranceAfter:"):
                _objc.send(generator, selector, leeway, argtypes=(_CMTime,), restype=None)
            if width:
                # A tall limit: only the width matters, the height follows the proportions.
                _objc.send(
                    generator, "setMaximumSize:", _objc.CGSize(width, 100000), argtypes=(_objc.CGSize,), restype=None
                )
            for moment in times:
                error = ctypes.c_void_p()
                picture = _objc.send(
                    generator,
                    "copyCGImageAtTime:actualTime:error:",
                    _CMTime(round(moment * _TIMESCALE), _TIMESCALE, _VALID, 0),
                    None,
                    ctypes.byref(error),
                    argtypes=(_CMTime, ctypes.c_void_p, ctypes.c_void_p),
                    restype=ctypes.c_void_p,
                )
                if not picture:
                    raise MacOSError(
                        "could not read the frame at {:.2f}s: {}".format(moment, _objc.error_message(error) or "no image")
                    )
                pictures.append(picture)
    except BaseException:
        for picture in pictures:
            _cf.release(picture)
        raise
    return pictures


_FRAME_BUDGET = 256 * 1024 * 1024  # bytes of decoded frames held at once while streaming them


def _batch(width: int, height: int) -> int:
    """How many frames of ``width`` x ``height`` pixels to read at once: about 256 MB of them, 1 to 64."""
    return max(1, min(64, _FRAME_BUDGET // max(1, width * height * 4)))


def _frame_stream(
    source: Path, times: Sequence[float], *, batch: int, width: Optional[int] = None, tolerance: float = 0.0
) -> Generator[int, None, None]:
    """
    The frames shown at ``times``, in that order, like :func:`_frames_at`, but ``batch`` at a time.

    Each ``CGImage`` is lent: it's released once the batch it came in is
    done, so at most ``batch`` frames are in memory, however long the video.
    Within a batch the frames are read in the video's order, which is how the
    decoder goes fast, then handed out in the order asked: a batch of
    ``times`` going backwards is read forwards and given reversed.
    """
    for begin in range(0, len(times), batch):
        wanted = list(times[begin : begin + batch])
        order = sorted(range(len(wanted)), key=wanted.__getitem__)
        pictures = _frames_at(source, [wanted[index] for index in order], width=width, tolerance=tolerance)
        try:
            by_index = dict(zip(order, pictures))
            for index in range(len(wanted)):
                yield by_index[index]
        finally:
            for picture in pictures:
                _cf.release(picture)


def to_gif(
    source: PathLike,
    output: PathLike,
    *,
    fps: float = 10.0,
    width: int = 480,
    start: Optional[float] = None,
    duration: Optional[float] = None,
    loop: bool = True,
) -> Path:
    """
    Turn a video (or part of it) into an animated GIF, and return ``output``.

    Made for screen recordings you put in a README, an issue or a chat::

        macos.screen.record("demo.mov", 8, region=(0, 0, 1280, 800))
        macos.video.to_gif("demo.mov", "demo.gif", fps=10, width=640)

    ``fps`` is the frames per second of the GIF and ``width`` its width in
    pixels (never wider than the video), keeping the proportions. ``start``
    and ``duration``, in seconds, keep only part of the video. The GIF
    loops forever; ``loop=False`` plays it once. GIFs get big fast: a few
    seconds at 10 fps and 480 pixels is a good size.
    """
    from . import image

    if not 0 < fps <= 50:
        raise ValueError("fps must be above 0 and at most 50, not {}".format(fps))
    if width <= 0:
        raise ValueError("width must be positive, not {}".format(width))
    for label, value in (("start", start), ("duration", duration)):
        if value is not None and (value < 0 or (label == "duration" and value == 0)):
            raise ValueError("{} must be positive, not {}".format(label, value))
    target = Path(output).expanduser().absolute()
    if target.suffix.lower() != ".gif":
        raise ValueError("the output must be a .gif, not {!r}".format(target.suffix))
    details = info(source)
    begin = start or 0.0
    if begin >= details.duration:
        raise ValueError("start={} is past the end of the {:.3f}-second video".format(begin, details.duration))
    end = min(details.duration, begin + duration) if duration is not None else details.duration
    step = 1.0 / fps
    times = [begin + index * step for index in range(max(1, int((end - begin) * fps)))]

    original = _existing(source)
    io = image._io()
    scaled = width if width < details.width else None
    high = round(details.height * scaled / details.width) if scaled and details.width else details.height
    # Half a frame either way: close enough, and much faster than exact frames. A batch at a time: the GIF
    # encoder keeps what it needs of each frame, so every frame needn't be held decoded at once.
    pictures = _frame_stream(original, times, batch=_batch(scaled or details.width, high), width=scaled, tolerance=step / 2)

    delay = round(step, 2)  # GIF delays are in hundredths of a second
    # LoopCount 0 loops forever. Without it, ImageIO writes no loop block
    # at all, and viewers play the GIF once.
    repeat = _cf.from_python({"{GIF}": {"LoopCount": 0}}) if loop else None
    timing = _cf.from_python({"{GIF}": {"DelayTime": delay, "UnclampedDelayTime": delay}})

    def add(destination: int) -> None:
        if repeat:
            io.CGImageDestinationSetProperties(destination, repeat)
        for picture in pictures:
            io.CGImageDestinationAddImage(destination, picture, timing)

    try:
        with _cf.owned(repeat), _cf.owned(timing):
            return image._write(target, "com.compuserve.gif", add, len(times))
    finally:
        pictures.close()  # releases the batch being read if writing failed


def frames(path: PathLike, every: float = 1.0, *, size: Optional[int] = None) -> List[bytes]:
    """
    Return a frame every ``every`` seconds (from the start), as PNG bytes, turned upright.

    ``size`` limits the longest side, in pixels. Long videos give many frames:
    a 10-minute video at the default gives 600::

        for index, png in enumerate(macos.video.frames("clip.mov", every=5, size=640)):
            Path("frame-{:03}.png".format(index)).write_bytes(png)
    """
    if every <= 0:
        raise ValueError("every must be positive, not {}".format(every))
    if size is not None and size <= 0:
        raise ValueError("size must be positive, not {}".format(size))
    details = info(path)
    count = max(1, int(details.duration / every) + (1 if details.duration % every else 0))
    times = [min(index * every, max(details.duration - 0.001, 0)) for index in range(count)]
    width = None
    if size is not None and details.width and details.height:
        width = size if details.width >= details.height else max(1, round(size * details.width / details.height))
    _load()
    high = round(details.height * width / details.width) if width and details.width else details.height
    pictures = _frame_stream(
        _existing(path), times, batch=_batch(width or details.width, high), width=width, tolerance=min(every / 2, 0.5)
    )
    try:
        # Encoded as they come, a batch of frames at a time: only the PNGs pile up.
        return [_objc.cgimage_png(_cf.retain(picture)) for picture in pictures]
    finally:
        pictures.close()


def _target(output: PathLike, allowed: Sequence[str] = (".mov", ".mp4", ".m4v")) -> Path:
    target = Path(output).expanduser().absolute()
    if target.suffix.lower() not in allowed:
        raise ValueError("can't write {!r} videos; use one of {}".format(target.suffix, ", ".join(sorted(allowed))))
    return target


def trim(source: PathLike, output: PathLike, start: float = 0.0, duration: Optional[float] = None) -> Path:
    """
    Keep ``duration`` seconds of a video from ``start`` (to the end by default), without re-encoding it.

    Fast, and without any loss: the frames are copied as they are. The cut
    lands on the nearest keyframe, so it may start a fraction of a second
    early; for a cut exact to the frame, use :func:`convert` with ``start``
    and ``duration``, which re-encodes::

        macos.video.trim("lecture.mov", "question.mov", start=1800, duration=90)
    """
    if start < 0 or (duration is not None and duration <= 0):
        raise ValueError("start must not be negative and duration must be positive")
    original = _existing(source)
    target = _target(output)
    length = info(original).duration
    if start >= length:
        raise ValueError("start={} is past the end of the {:.3f}-second video".format(start, length))
    args = ["avconvert", "--source", str(original), "--output", str(target), "--preset", "PresetPassthrough", "--replace"]
    args += ["--start", str(start), "--duration", str(min(duration, length - start) if duration else length - start)]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target == original:
        raise ValueError("trim() can't write over its source; pick another output")
    _run(args)
    return target


def concat(videos: Sequence[PathLike], output: PathLike) -> Path:
    """
    Join videos one after another into ``output``, sound included, and return it.

    Made for clips of the same size and orientation, like parts of one
    recording; clips of another size keep their own size in the first one's
    frame. Re-encodes at the highest quality::

        macos.video.concat(["intro.mov", "talk.mov", "outro.mov"], "full.mp4")
    """
    if not videos:
        raise ValueError("concat() needs at least one video")
    target = _target(output)
    sources = [_existing(video) for video in videos]
    with _objc.autorelease_pool():
        # One video track and one sound track for all the clips: the exporter
        # only plays the first video track, and clips from different
        # encoders would otherwise each get their own.
        joined = _media.composition()
        picture = _media.add_track(joined, "vide")
        sound: Optional[int] = None
        at = 0.0
        for index, source in enumerate(sources):
            media = _media.asset(source)
            length = _media.duration(media)
            videos_in = _media.tracks(media, "vide")
            if not videos_in:
                raise ValueError("{} has no video".format(source))
            _media.insert(picture, videos_in[0], 0, length, at)
            if index == 0:
                transform = _objc.send(videos_in[0], "preferredTransform", restype=_objc.CGAffineTransform)
                _objc.send(picture, "setPreferredTransform:", transform, argtypes=(_objc.CGAffineTransform,), restype=None)
            sounds = _media.tracks(media, "soun")
            if sounds:
                if sound is None:
                    sound = _media.add_track(joined, "soun")
                sound_length = _media.seconds(_objc.send(sounds[0], "timeRange", restype=_media.CMTimeRange).duration)
                _media.insert(sound, sounds[0], 0, min(length, sound_length), at)
            at += length
        return _media.export(joined, target, length=at)


def speed(source: PathLike, output: PathLike, factor: float) -> Path:
    """
    Play a video ``factor`` times faster (2.0) or slower (0.5), and return ``output``.

    The sound follows, at the same pitch: voices don't turn into chipmunks.
    Re-encodes at the highest quality::

        macos.video.speed("walk.mov", "timelapse.mp4", 8)
    """
    if factor <= 0:
        raise ValueError("factor must be positive, not {}".format(factor))
    target = _target(output)
    with _objc.autorelease_pool():
        edited = _media.editable(_media.asset(_existing(source)))
        length = _media.duration(edited)
        _objc.send(
            edited,
            "scaleTimeRange:toDuration:",
            _media.time_range(0, length),
            _media.time(length / factor),
            argtypes=(_media.CMTimeRange, _media.CMTime),
            restype=None,
        )
        return _media.export(edited, target, time_pitch="Spectral", length=length / factor)


def _concat_transforms(first: _objc.CGAffineTransform, second: _objc.CGAffineTransform) -> _objc.CGAffineTransform:
    return _graphics().CGAffineTransformConcat(first, second)


def rotate(source: PathLike, output: PathLike, degrees: int) -> Path:
    """
    Turn a video clockwise by ``degrees`` (90, 180 or 270; negative turns counter-clockwise), and return ``output``.

    The frames aren't re-encoded: the video is marked to play turned, as
    phones do, so it's fast and lossless.
    """
    if degrees % 90:
        raise ValueError("degrees must be a multiple of 90, not {}".format(degrees))
    target = _target(output)
    turns = (degrees // 90) % 4
    with _objc.autorelease_pool():
        media = _media.asset(_existing(source))
        edited = _media.editable(media)
        videos = _media.tracks(edited, "vide")
        if not videos:
            raise ValueError("{} has no video to turn".format(source))
        width, height = _upright_size(_media.tracks(media, "vide")[0])
        # A clockwise turn of the upright picture (y points down in video coordinates).
        turn = {
            0: _objc.CGAffineTransform(1, 0, 0, 1, 0, 0),
            1: _objc.CGAffineTransform(0, 1, -1, 0, height, 0),
            2: _objc.CGAffineTransform(-1, 0, 0, -1, width, height),
            3: _objc.CGAffineTransform(0, -1, 1, 0, 0, width),
        }[turns]
        for track in videos:
            current = _objc.send(track, "preferredTransform", restype=_objc.CGAffineTransform)
            _objc.send(
                track,
                "setPreferredTransform:",
                _concat_transforms(current, turn),
                argtypes=(_objc.CGAffineTransform,),
                restype=None,
            )
        return _media.export(edited, target, preset="AVAssetExportPresetPassthrough")


def crop(source: PathLike, output: PathLike, box: Tuple[int, int, int, int]) -> Path:
    """
    Keep the part of a video inside ``box``, ``(x, y, width, height)`` in pixels from the top-left corner.

    The box is measured on the upright picture, as it plays. Video encoders
    need even sizes, so an odd width or height loses its last pixel.
    Re-encodes at the highest quality, sound included::

        macos.video.crop("screen.mov", "window.mov", (100, 80, 1280, 720))
    """
    x, y, width, height = box
    if width < 2 or height < 2 or x < 0 or y < 0:
        raise ValueError("the box needs a size of at least 2 x 2 and no negative corner, not {}".format(box))
    target = _target(output)
    with _objc.autorelease_pool():
        media = _media.asset(_existing(source))
        edited = _media.editable(media)
        videos = _media.tracks(edited, "vide")
        if not videos:
            raise ValueError("{} has no video to crop".format(source))
        full_width, full_height = _upright_size(_media.tracks(media, "vide")[0])
        if x + width > full_width or y + height > full_height:
            raise ValueError("the box {} doesn't fit in the {} x {} video".format(box, full_width, full_height))
        # Even sizes: video encoders need them.
        render = _objc.CGSize(width - width % 2, height - height % 2)
        layer = _objc.send(
            _objc.cls("AVMutableVideoCompositionLayerInstruction"),
            "videoCompositionLayerInstructionWithAssetTrack:",
            videos[0],
            argtypes=(_objc.id,),
        )
        upright = _objc.send(videos[0], "preferredTransform", restype=_objc.CGAffineTransform)
        moved = _concat_transforms(upright, _objc.CGAffineTransform(1, 0, 0, 1, -x, -y))
        _objc.send(
            layer,
            "setTransform:atTime:",
            moved,
            _media.time(0),
            argtypes=(_objc.CGAffineTransform, _media.CMTime),
            restype=None,
        )
        instruction = _objc.new("AVMutableVideoCompositionInstruction")
        _objc.send(
            instruction,
            "setTimeRange:",
            _media.time_range(0, _media.duration(edited)),
            argtypes=(_media.CMTimeRange,),
            restype=None,
        )
        _objc.send(instruction, "setLayerInstructions:", _objc.nsarray_of([layer]), argtypes=(_objc.id,), restype=None)
        composition = _objc.new("AVMutableVideoComposition")
        _objc.send(composition, "setRenderSize:", render, argtypes=(_objc.CGSize,), restype=None)
        rate = float(_objc.send(videos[0], "nominalFrameRate", restype=ctypes.c_float)) or 30.0
        _objc.send(
            composition,
            "setFrameDuration:",
            _media.CMTime(_media.TIMESCALE // max(1, min(int(round(rate)), 60)), _media.TIMESCALE, 1, 0),
            argtypes=(_media.CMTime,),
            restype=None,
        )
        _objc.send(composition, "setInstructions:", _objc.nsarray_of([instruction]), argtypes=(_objc.id,), restype=None)
        return _media.export(edited, target, video_composition=composition)


def mute(source: PathLike, output: PathLike) -> Path:
    """Save a video without its sound, and return ``output``. Fast and lossless: nothing is re-encoded."""
    target = _target(output)
    with _objc.autorelease_pool():
        media = _media.asset(_existing(source))
        silent = _media.composition()
        videos = _media.tracks(media, "vide")
        if not videos:
            raise ValueError("{} has no video".format(source))
        length = _media.duration(media)
        for track in videos:
            copy = _media.add_track(silent, "vide")
            _media.insert(copy, track, 0, length, 0)
            transform = _objc.send(track, "preferredTransform", restype=_objc.CGAffineTransform)
            _objc.send(copy, "setPreferredTransform:", transform, argtypes=(_objc.CGAffineTransform,), restype=None)
        return _media.export(silent, target, preset="AVAssetExportPresetPassthrough")


def add_audio(
    video: PathLike,
    audio: PathLike,
    output: PathLike,
    *,
    at: float = 0.0,
    replace: bool = False,
    volume: float = 1.0,
) -> Path:
    """
    Add a sound (music, a voice-over...) to a video, from ``at`` seconds into it, and return ``output``.

    By default it plays over the video's own sound; ``replace=True`` drops
    the original sound instead. ``volume`` (0.0 to 1.0) sets the added
    sound's loudness. A sound longer than the video is cut at its end; to use
    part of it, :func:`macos.audio.trim` it first::

        macos.video.add_audio("timelapse.mov", "music.m4a", "timelapse-music.mp4", volume=0.5)
        macos.video.add_audio("talk.mov", "dub.m4a", "dubbed.mov", replace=True)
    """
    if at < 0:
        raise ValueError("at must not be negative, not {}".format(at))
    if not 0.0 <= volume <= 1.0:
        raise ValueError("volume must be from 0.0 to 1.0, not {}".format(volume))
    target = _target(output)
    with _objc.autorelease_pool():
        picture = _media.asset(_existing(video))
        sound = _media.asset(_existing(audio))
        length = _media.duration(picture)
        if at >= length:
            raise ValueError("at={} is past the end of the {:.3f}-second video".format(at, length))
        mixed = _media.composition()
        _copy_picture(picture, mixed, length)
        if not replace:
            for track in _media.tracks(picture, "soun"):
                _media.copy_track(mixed, track, "soun", length)
        added_tracks = _media.tracks(sound, "soun")
        if not added_tracks:
            raise ValueError("{} has no sound".format(audio))
        added = _media.add_track(mixed, "soun")
        _media.insert(added, added_tracks[0], 0, min(_media.duration(sound), length - at), at)
        parameters = _objc.send(
            _objc.cls("AVMutableAudioMixInputParameters"), "audioMixInputParametersWithTrack:", added, argtypes=(_objc.id,)
        )
        _objc.send(
            parameters,
            "setVolume:atTime:",
            ctypes.c_float(volume),
            _media.time(0),
            argtypes=(ctypes.c_float, _media.CMTime),
            restype=None,
        )
        mix = _objc.new("AVMutableAudioMix")
        _objc.send(mix, "setInputParameters:", _objc.nsarray_of([parameters]), argtypes=(_objc.id,), restype=None)
        return _media.export(mixed, target, audio_mix=mix)


def _copy_picture(source: int, target: int, length: float) -> None:
    """Copy the video tracks of the asset ``source`` into the composition ``target``, upright."""
    for track in _media.tracks(source, "vide"):
        copy = _media.copy_track(target, track, "vide", length)
        transform = _objc.send(track, "preferredTransform", restype=_objc.CGAffineTransform)
        _objc.send(copy, "setPreferredTransform:", transform, argtypes=(_objc.CGAffineTransform,), restype=None)


def _pixel_buffer(picture: int, width: int, height: int) -> int:
    """An owned ``CVPixelBuffer`` of ``width`` x ``height``: ``picture`` fitted in, on black."""
    from .image import _srgb

    video_library, graphics = _core_video(), _graphics()
    buffer = ctypes.c_void_p()
    status = video_library.CVPixelBufferCreate(None, width, height, _BGRA, None, ctypes.byref(buffer))
    if status != 0 or not buffer:
        raise MacOSError("could not make a video frame (CVReturn {})".format(status))
    try:
        video_library.CVPixelBufferLockBaseAddress(buffer, 0)
        try:
            context = graphics.CGBitmapContextCreate(
                video_library.CVPixelBufferGetBaseAddress(buffer),
                width,
                height,
                8,
                video_library.CVPixelBufferGetBytesPerRow(buffer),
                _srgb(),
                2 | (2 << 12),  # kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Little: BGRA
            )
            if not context:
                raise MacOSError("could not draw a video frame of {} x {} pixels".format(width, height))
            try:
                graphics.CGContextSetRGBFillColor(context, 0, 0, 0, 1)
                graphics.CGContextFillRect(context, _objc.CGRect(_objc.CGPoint(0, 0), _objc.CGSize(width, height)))
                source_width, source_height = graphics.CGImageGetWidth(picture), graphics.CGImageGetHeight(picture)
                scale = min(width / max(source_width, 1), height / max(source_height, 1))
                drawn_width, drawn_height = source_width * scale, source_height * scale
                area = _objc.CGRect(
                    _objc.CGPoint((width - drawn_width) / 2, (height - drawn_height) / 2),
                    _objc.CGSize(drawn_width, drawn_height),
                )
                graphics.CGContextDrawImage(context, area, picture)
            finally:
                graphics.CGContextRelease(context)
        finally:
            video_library.CVPixelBufferUnlockBaseAddress(buffer, 0)
    except BaseException:
        _cf.release(buffer.value)
        raise
    return int(buffer.value or 0)


_BGRA = int.from_bytes(b"BGRA", "big")  # kCVPixelFormatType_32BGRA


_WRITING, _WRITTEN, _WRITE_FAILED = 1, 2, 3  # AVAssetWriterStatus
_WRITER_PATIENCE = 60.0  # seconds to wait for the encoder to take the next frame


def _writer_failure(writer: int) -> str:
    failure = _objc.send(writer, "error")
    return (_objc.pystring(_objc.send(failure, "localizedDescription")) if failure else None) or "unknown error"


def _write_frames(pictures: Iterable[int], target: Path, fps: float, width: int, height: int) -> Path:
    """
    Encode ``pictures`` (``CGImage`` objects), one every 1/``fps`` seconds, into an H.264 video.

    ``pictures`` is read one at a time, so a generator keeps only one image in memory.
    """
    _load()
    width, height = width - width % 2, height - height % 2  # encoders need even sizes
    # Beside the target, at a path where nothing is yet: the writer refuses to replace a file.
    with _files.replacing(target) as temporary:
        name = str(temporary)
        with _objc.autorelease_pool():
            error = ctypes.c_void_p()
            writer = _objc.send(
                _objc.cls("AVAssetWriter"),
                "assetWriterWithURL:fileType:error:",
                _objc.file_url(name),
                _objc.nsstring(_media.FILE_TYPES[target.suffix.lower()]),
                ctypes.byref(error),
                argtypes=(_objc.id, _objc.id, ctypes.c_void_p),
            )
            if not writer:
                raise MacOSError("could not write {}: {}".format(target, _objc.error_message(error)))
            number = lambda value: _objc.send(  # noqa: E731
                _objc.cls("NSNumber"), "numberWithDouble:", float(value), argtypes=(ctypes.c_double,)
            )
            settings = _objc.send(
                _objc.cls("NSDictionary"),
                "dictionaryWithObjects:forKeys:",
                _objc.nsarray_of([_objc.nsstring("avc1"), number(width), number(height)]),
                _objc.nsarray_of([_objc.nsstring(key) for key in ("AVVideoCodecKey", "AVVideoWidthKey", "AVVideoHeightKey")]),
                argtypes=(_objc.id, _objc.id),
            )
            writer_input = _objc.send(
                _objc.cls("AVAssetWriterInput"),
                "assetWriterInputWithMediaType:outputSettings:",
                _objc.nsstring("vide"),
                settings,
                argtypes=(_objc.id, _objc.id),
            )
            adaptor = _objc.send(
                _objc.cls("AVAssetWriterInputPixelBufferAdaptor"),
                "assetWriterInputPixelBufferAdaptorWithAssetWriterInput:sourcePixelBufferAttributes:",
                writer_input,
                None,
                argtypes=(_objc.id, _objc.id),
            )
            _objc.send(writer, "addInput:", writer_input, argtypes=(_objc.id,), restype=None)
            if not _objc.send(writer, "startWriting", restype=_objc.BOOL):
                raise MacOSError("could not start writing {}".format(target))
            _objc.send(writer, "startSessionAtSourceTime:", _media.time(0), argtypes=(_media.CMTime,), restype=None)
            for index, picture in enumerate(pictures):
                deadline = time.monotonic() + _WRITER_PATIENCE
                while not _objc.send(writer_input, "isReadyForMoreMediaData", restype=_objc.BOOL):
                    if _objc.send(writer, "status", restype=_objc.NSInteger) != _WRITING:
                        raise MacOSError("could not write the video: {}".format(_writer_failure(writer)))
                    if time.monotonic() > deadline:
                        _objc.send(writer, "cancelWriting", restype=None)
                        raise MacOSError("the video encoder stopped taking frames")
                    time.sleep(0.005)
                buffer = _pixel_buffer(picture, width, height)
                try:
                    # index / fps seconds, exactly: value index * 600, timescale fps * 600.
                    moment = _media.CMTime(index * 600, int(round(fps * 600)), 1, 0)
                    appended = _objc.send(
                        adaptor,
                        "appendPixelBuffer:withPresentationTime:",
                        buffer,
                        moment,
                        argtypes=(ctypes.c_void_p, _media.CMTime),
                        restype=_objc.BOOL,
                    )
                finally:
                    _cf.release(buffer)
                if not appended:
                    raise MacOSError("could not add frame {} to the video".format(index + 1))
            _objc.send(writer_input, "markAsFinished", restype=None)
            _objc.send(
                writer,
                "finishWritingWithCompletionHandler:",
                _media.ignore_completion(),
                argtypes=(ctypes.c_void_p,),
                restype=None,
            )
            status = lambda: _objc.send(writer, "status", restype=_objc.NSInteger)  # noqa: E731
            if not _objc.run_until(lambda: status() != _WRITING, 600):
                raise MacOSError("the video didn't finish writing")
            if status() != _WRITTEN:
                raise MacOSError("could not write the video: {}".format(_writer_failure(writer)))
    return target


def _load_image(path: Path, longest: Optional[int]) -> int:
    """An owned, upright ``CGImage`` of an image file, scaled down to ``longest`` pixels if given."""
    from . import image

    io = image._io()
    with _cf.owned(image._source(path)) as source:
        details = image._describe(source)
        options = image._options(
            {
                "kCGImageSourceCreateThumbnailFromImageAlways": True,
                "kCGImageSourceCreateThumbnailWithTransform": True,
                "kCGImageSourceThumbnailMaxPixelSize": longest or max(details.width, details.height),
            }
        )
        with _cf.owned(options):
            picture = io.CGImageSourceCreateThumbnailAtIndex(source, 0, options)
    if not picture:
        raise ValueError("{} is not an image macOS can read".format(path))
    return int(picture)


def from_images(
    images: Sequence[PathLike], output: PathLike, fps: float = 24.0, *, width: Optional[int] = None
) -> Path:
    """
    Make a video from images, one after another, ``fps`` of them per second, and return ``output``.

    For timelapses and slideshows: at ``fps=1`` each image shows for a
    second. The video takes the first image's size (or ``width``, keeping its
    proportions); images of other shapes are fitted in, on black::

        photos = sorted(Path("~/Pictures/Garden").expanduser().glob("*.jpg"))
        macos.video.from_images(photos, "garden.mp4", fps=12, width=1280)
    """
    if not images:
        raise ValueError("from_images() needs at least one image")
    if fps <= 0:
        raise ValueError("fps must be positive, not {}".format(fps))
    if width is not None and width < 2:
        raise ValueError("width must be at least 2, not {}".format(width))
    target = _target(output)
    sources = [_existing(image) for image in images]
    from . import image as image_module

    first = image_module.info(sources[0])
    first_width, first_height = first.width, first.height
    if first.orientation in (5, 6, 7, 8):
        first_width, first_height = first_height, first_width
    frame_width = width or first_width
    frame_height = max(2, round(frame_width * first_height / first_width))
    longest = max(frame_width, frame_height)

    def one_at_a_time() -> Generator[int, None, None]:
        for source in sources:
            picture = _load_image(source, longest)
            try:
                yield picture
            finally:
                _cf.release(picture)

    pictures = one_at_a_time()
    try:
        return _write_frames(pictures, target, fps, frame_width, frame_height)
    finally:
        pictures.close()  # releases the image being encoded if writing failed


def reverse(source: PathLike, output: PathLike) -> Path:
    """
    Save a video played backwards, sound included, and return ``output``.

    Every frame is read and written again, so it's slow on long or large
    videos: a few seconds of clip is the sweet spot.
    """
    from . import audio

    original = _existing(source)
    target = _target(output)
    details = info(original)
    rate = min(details.fps or 30.0, 60.0)
    count = max(1, int(details.duration * rate))
    times = [max(0.0, details.duration - (index + 0.5) / rate) for index in range(count)]
    # From the end, a batch at a time, each read forwards and handed out backwards: never more than about
    # 256 MB of frames decoded at once, where reading them all first would hold the whole video (some 20 GB
    # for ten seconds of 4K at 60 fps).
    pictures = _frame_stream(original, times, batch=_batch(details.width, details.height), tolerance=0.5 / rate)
    if not details.has_audio:
        try:
            return _write_frames(pictures, target, rate, details.width, details.height)
        finally:
            pictures.close()  # releases the batch being encoded if writing failed
    target.parent.mkdir(parents=True, exist_ok=True)
    # Beside the output, and cleaned up whatever fails.
    with tempfile.TemporaryDirectory(dir=str(target.parent), prefix=".reverse-") as folder:
        silent = Path(folder) / ("frames" + target.suffix)
        try:
            _write_frames(pictures, silent, rate, details.width, details.height)
        finally:
            pictures.close()
        backwards = audio.reverse(original, Path(folder) / "backwards.m4a")
        return add_audio(silent, backwards, target, replace=True)


_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")  # "en", "fr-CA", "es-419"...


def _set_language(track: int, tag: str) -> None:
    # The exporter fills the three-letter code (eng, por...) from the tag.
    _objc.send(track, "setExtendedLanguageTag:", _objc.nsstring(tag), argtypes=(_objc.id,), restype=None)


def add_language_track(
    video: PathLike,
    audio: PathLike,
    output: PathLike,
    language: str,
    *,
    original_language: Optional[str] = None,
) -> Path:
    """
    Add a sound in another language as an alternative track, and return ``output``.

    Players that support it (QuickTime Player, the TV app, VLC...) offer the
    languages in their audio menu; the video's own sound stays the default.
    ``language`` and ``original_language`` are language tags such as ``"en"``,
    ``"fr-CA"`` or ``"es-419"``; ``original_language`` labels the sound that's
    already there. Nothing is re-encoded but the added sound, turned into AAC
    if it isn't already::

        macos.video.add_language_track("film.mov", "film-english.m4a", "film-dual.mov", "en", original_language="es")

    A sound longer than the video is cut at its end. To mix a sound into the
    video instead, see :func:`add_audio`.
    """
    from . import audio as audio_module

    for label, tag in (("language", language), ("original_language", original_language)):
        if tag is not None and not _LANGUAGE_TAG.match(tag):
            raise ValueError("{} must be a language tag such as 'en' or 'fr-CA', not {!r}".format(label, tag))
    target = _target(output)
    sound_path = _existing(audio)
    with tempfile.TemporaryDirectory() as folder:
        # Copied as it is into the video: make it AAC, which every player reads.
        if audio_module.info(sound_path).codec != "aac":
            sound_path = audio_module.convert(sound_path, Path(folder) / "sound.m4a")
        with _objc.autorelease_pool():
            picture = _media.asset(_existing(video))
            sound = _media.asset(sound_path)
            length = _media.duration(picture)
            dubbed = _media.composition()
            _copy_picture(picture, dubbed, length)
            # One alternate group for every sound track: players offer one at a time.
            group = 1
            originals = _media.tracks(picture, "soun")
            for track in originals:
                copy = _media.copy_track(dubbed, track, "soun", length)
                _objc.send(copy, "setAlternateGroupID:", group, argtypes=(ctypes.c_int32,), restype=None)
                if original_language:
                    _set_language(copy, original_language)
            added_tracks = _media.tracks(sound, "soun")
            if not added_tracks:
                raise ValueError("{} has no sound".format(audio))
            added = _media.add_track(dubbed, "soun")
            _media.insert(added, added_tracks[0], 0, min(_media.duration(sound), length), 0)
            _objc.send(added, "setAlternateGroupID:", group, argtypes=(ctypes.c_int32,), restype=None)
            _set_language(added, language)
            # Off by default when there's an original to play; the only sound otherwise.
            _objc.send(added, "setEnabled:", not originals, argtypes=(_objc.BOOL,), restype=None)
            return _media.export(dubbed, target, preset="AVAssetExportPresetPassthrough")
