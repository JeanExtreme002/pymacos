# -*- coding: utf-8 -*-

"""
Internal helpers for editing video and audio with AVFoundation: time values,
compositions, and exporting them to a file.
"""

import ctypes
from pathlib import Path
from functools import lru_cache
from typing import Optional

from . import _files, _objc
from ._system import framework
from .errors import MacOSError

TIMESCALE = 600  # the usual movie timescale: exact for 24, 25, 30 and 60 fps
_VALID = 1  # kCMTimeFlags_Valid

FILE_TYPES = {
    ".mov": "com.apple.quicktime-movie",
    ".mp4": "public.mpeg-4",
    ".m4v": "com.apple.m4v-video",
    ".m4a": "com.apple.m4a-audio",
}

_COMPLETED, _FAILED, _CANCELLED = 3, 4, 5  # AVAssetExportSessionStatus


class CMTime(ctypes.Structure):
    _fields_ = [("value", ctypes.c_int64), ("timescale", ctypes.c_int32), ("flags", ctypes.c_uint32), ("epoch", ctypes.c_int64)]


class CMTimeRange(ctypes.Structure):
    _fields_ = [("start", CMTime), ("duration", CMTime)]


def time(seconds: float) -> CMTime:
    return CMTime(round(seconds * TIMESCALE), TIMESCALE, _VALID, 0)


def seconds(value: CMTime) -> float:
    return value.value / value.timescale if value.flags & _VALID and value.timescale else 0.0


def time_range(start: float, duration: float) -> CMTimeRange:
    return CMTimeRange(time(start), time(duration))


def load() -> None:
    framework("AVFoundation")
    framework("CoreMedia")


def asset(path: Path) -> int:
    """An autoreleased ``AVURLAsset`` for a media file. Call inside an autorelease pool."""
    load()
    found = _objc.send(
        _objc.cls("AVURLAsset"), "URLAssetWithURL:options:", _objc.file_url(path), None, argtypes=(_objc.id, _objc.id)
    )
    if not found or not _objc.send(found, "isPlayable", restype=_objc.BOOL):
        raise ValueError("{} is not a video or sound macOS can play".format(path))
    return found


def duration(media: int) -> float:
    return seconds(_objc.send(media, "duration", restype=CMTime))


def tracks(media: int, kind: str) -> list:
    """The ``"vide"`` or ``"soun"`` tracks of an asset or a composition."""
    return list(_objc.nsarray(_objc.send(media, "tracksWithMediaType:", _objc.nsstring(kind), argtypes=(_objc.id,))))


def composition() -> int:
    """An empty, autoreleased ``AVMutableComposition``."""
    load()
    return _objc.send(_objc.cls("AVMutableComposition"), "composition")


def add_track(target: int, kind: str) -> int:
    """A new track of ``kind`` (``"vide"``, ``"soun"``) in a composition."""
    return _objc.send(
        target,
        "addMutableTrackWithMediaType:preferredTrackID:",
        _objc.nsstring(kind),
        0,  # kCMPersistentTrackID_Invalid: let it choose
        argtypes=(_objc.id, ctypes.c_int32),
    )


def insert(track: int, source_track: int, start: float, length: float, at: float) -> None:
    """Copy ``length`` seconds of ``source_track`` from ``start`` into ``track`` at ``at`` seconds."""
    error = ctypes.c_void_p()
    ok = _objc.send(
        track,
        "insertTimeRange:ofTrack:atTime:error:",
        time_range(start, length),
        source_track,
        time(at),
        ctypes.byref(error),
        argtypes=(CMTimeRange, _objc.id, CMTime, ctypes.c_void_p),
        restype=_objc.BOOL,
    )
    if not ok:
        raise MacOSError("could not edit the track: {}".format(_objc.error_message(error) or "unknown error"))


def copy_track(target: int, track: int, kind: str, until: float) -> int:
    """
    Add a copy of ``track`` to the composition ``target``, cut at ``until`` seconds, and return the copy.

    The track keeps its place on the timeline: a sound that starts late
    still does, and one that ends early isn't stretched to ``until``.
    """
    span = _core_media().CMTimeRangeGetIntersection(_objc.send(track, "timeRange", restype=CMTimeRange), time_range(0, until))
    copy = add_track(target, kind)
    if seconds(span.duration) > 0:
        error = ctypes.c_void_p()
        ok = _objc.send(
            copy,
            "insertTimeRange:ofTrack:atTime:error:",
            span,
            track,
            span.start,
            ctypes.byref(error),
            argtypes=(CMTimeRange, _objc.id, CMTime, ctypes.c_void_p),
            restype=_objc.BOOL,
        )
        if not ok:
            raise MacOSError("could not edit the track: {}".format(_objc.error_message(error) or "unknown error"))
    return copy


@lru_cache(maxsize=None)
def _core_media() -> ctypes.CDLL:
    media = framework("CoreMedia")
    media.CMTimeRangeGetIntersection.argtypes = (CMTimeRange, CMTimeRange)
    media.CMTimeRangeGetIntersection.restype = CMTimeRange
    return media


@lru_cache(maxsize=None)
def ignore_completion() -> int:
    """
    A completion handler block that does nothing, for APIs that require one.

    Callers poll the status instead: blocks live as long as the process, so
    this single one serves every export.
    """
    return _objc.block(lambda: None, b"v@?")


def editable(media: int) -> int:
    """An autoreleased ``AVMutableComposition`` with every track of an asset, to edit."""
    edited = composition()
    error = ctypes.c_void_p()
    ok = _objc.send(
        edited,
        "insertTimeRange:ofAsset:atTime:error:",
        time_range(0, duration(media)),
        media,
        time(0),
        ctypes.byref(error),
        argtypes=(CMTimeRange, _objc.id, CMTime, ctypes.c_void_p),
        restype=_objc.BOOL,
    )
    if not ok:
        raise MacOSError("could not read the media: {}".format(_objc.error_message(error) or "unknown error"))
    return edited


def export(
    media: int,
    output: Path,
    *,
    preset: str = "AVAssetExportPresetHighestQuality",
    audio_mix: Optional[int] = None,
    video_composition: Optional[int] = None,
    time_pitch: Optional[str] = None,
    length: Optional[float] = None,
    timeout: float = 3600.0,
) -> Path:
    """
    Export an asset or composition to ``output`` (its extension picks the file type), and return ``output``.

    Writes to a temporary file next to it first, so the output may be one of
    the inputs, and a failure leaves nothing half-written. ``length`` keeps
    only the first seconds: the time stretcher pads the sound with silence.
    """
    extension = output.suffix.lower()
    if extension not in FILE_TYPES:
        raise ValueError("can't write {!r} files; use one of {}".format(output.suffix, ", ".join(sorted(FILE_TYPES))))
    # Beside the output, at a path where nothing is yet: the exporter refuses to replace a file.
    with _files.replacing(output) as temporary, _objc.autorelease_pool():
        session = _objc.send(
            _objc.cls("AVAssetExportSession"),
            "exportSessionWithAsset:presetName:",
            media,
            _objc.nsstring(preset),
            argtypes=(_objc.id, _objc.id),
        )
        if not session:
            raise MacOSError("this media can't be exported that way")
        _objc.send(session, "setOutputURL:", _objc.file_url(temporary), argtypes=(_objc.id,), restype=None)
        _objc.send(
            session, "setOutputFileType:", _objc.nsstring(FILE_TYPES[extension]), argtypes=(_objc.id,), restype=None
        )
        if audio_mix:
            _objc.send(session, "setAudioMix:", audio_mix, argtypes=(_objc.id,), restype=None)
        if video_composition:
            _objc.send(session, "setVideoComposition:", video_composition, argtypes=(_objc.id,), restype=None)
        if length is not None:
            _objc.send(session, "setTimeRange:", time_range(0, length), argtypes=(CMTimeRange,), restype=None)
        if time_pitch:
            _objc.send(
                session, "setAudioTimePitchAlgorithm:", _objc.nsstring(time_pitch), argtypes=(_objc.id,), restype=None
            )
        _objc.send(
            session,
            "exportAsynchronouslyWithCompletionHandler:",
            ignore_completion(),
            argtypes=(ctypes.c_void_p,),
            restype=None,
        )
        done = lambda: _objc.send(session, "status", restype=_objc.NSInteger) >= _COMPLETED  # noqa: E731
        if not _objc.run_until(done, timeout):
            _objc.send(session, "cancelExport", restype=None)
            raise MacOSError("the export didn't finish within {} seconds".format(timeout))
        status = _objc.send(session, "status", restype=_objc.NSInteger)
        if status != _COMPLETED:
            error = _objc.send(session, "error")
            message = _objc.pystring(_objc.send(error, "localizedDescription")) if error else "unknown error"
            raise MacOSError("the export failed: {}".format(message))
    return output
