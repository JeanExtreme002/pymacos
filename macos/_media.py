# -*- coding: utf-8 -*-

"""
Internal helpers for editing video and audio with AVFoundation: time values,
compositions, and exporting them to a file.
"""

import ctypes
import math
import os
from pathlib import Path
from functools import lru_cache
from typing import Optional, Union

from . import _files, _objc
from ._system import framework
from .errors import MacOSError, WaitTimeoutError

TIMESCALE = 600  # the usual movie timescale: exact for 24, 25, 30 and 60 fps
_VALID = 1  # kCMTimeFlags_Valid

FILE_TYPES = {
    ".mov": "com.apple.quicktime-movie",
    ".mp4": "public.mpeg-4",
    ".m4v": "com.apple.m4v-video",
    ".m4a": "com.apple.m4a-audio",
}

_COMPLETED, _FAILED, _CANCELLED = 3, 4, 5  # AVAssetExportSessionStatus

# The track types editable() keeps the playback settings of: pictures, sounds, subtitles and captions.
_KINDS = ("vide", "soun", "sbtl", "text", "clcp")


class CMTime(ctypes.Structure):
    _fields_ = [("value", ctypes.c_int64), ("timescale", ctypes.c_int32), ("flags", ctypes.c_uint32), ("epoch", ctypes.c_int64)]


class CMTimeRange(ctypes.Structure):
    _fields_ = [("start", CMTime), ("duration", CMTime)]


def time(seconds: float) -> CMTime:
    # ctypes would wrap a value past the 64-bit field without a word, and NaN or infinity fail cryptically.
    if not math.isfinite(seconds) or abs(round(seconds * TIMESCALE)) >= 2**63:
        raise ValueError("time must be a finite number of seconds, not {}".format(seconds))
    return CMTime(round(seconds * TIMESCALE), TIMESCALE, _VALID, 0)


def seconds(value: CMTime) -> float:
    return value.value / value.timescale if value.flags & _VALID and value.timescale else 0.0


def time_range(start: float, duration: float) -> CMTimeRange:
    return CMTimeRange(time(start), time(duration))


def load() -> None:
    framework("AVFoundation")
    framework("CoreMedia")


def source(path: Union[str, "os.PathLike[str]"], kind: str = "video or sound") -> Path:
    """
    ``path`` made absolute, checked before any tool or framework reads it: ``FileNotFoundError`` when nothing's
    there, ``PermissionError`` when it can't be read, ``ValueError`` when it isn't a file (a folder, a FIFO).

    ``avconvert`` and ``afconvert`` would only say they couldn't open it, and AVFoundation waits on a
    FIFO for a writer that never comes.
    """
    found = _files.existing(path)
    if not found.is_file():
        raise ValueError("{} is not a {} macOS can play".format(found, kind))
    open(str(found), "rb").close()  # PermissionError: the file's mode, or no Files and Folders access
    return found


def asset(path: Path, kind: str = "video or sound") -> int:
    """An autoreleased ``AVURLAsset`` for a media file, ``kind`` naming it in the error. Call inside an autorelease pool."""
    if os.path.exists(path) and not os.path.isfile(path):
        # A FIFO: AVFoundation would wait for a writer before answering isPlayable. A folder isn't media either.
        raise ValueError("{} is not a {} macOS can play".format(path, kind))
    load()
    found = _objc.send(
        _objc.cls("AVURLAsset"), "URLAssetWithURL:options:", _objc.file_url(path), None, argtypes=(_objc.id, _objc.id)
    )
    if not found or not _objc.send(found, "isPlayable", restype=_objc.BOOL):
        # A file that can't be read isn't playable either: Python's own PermissionError says so, as image and
        # pdf do, not that its format is wrong. open(), not os.access(): the folders privacy protects
        # (Desktop, Documents...) pass the permission bits.
        if os.path.isfile(path):
            open(path, "rb").close()
        raise ValueError("{} is not a {} macOS can play".format(path, kind))
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
        raise MacOSError("could not edit the track: {}".format(_objc.error_message(error)))


def copy_track(target: int, track: int, kind: str, until: float, keep_state: bool = True) -> int:
    """
    Add a copy of ``track`` to the composition ``target``, cut at ``until`` seconds, and return the copy.

    The track keeps its place on the timeline: a sound that starts late
    still does, and one that ends early isn't stretched to ``until``. It
    keeps how it plays, too: see :func:`keep_settings`, which ``keep_state`` is passed to.
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
            raise MacOSError("could not edit the track: {}".format(_objc.error_message(error)))
    keep_settings(copy, track, keep_state)
    return copy


def keep_settings(copy: int, track: int, state: bool = True) -> None:
    """
    Give the composition track ``copy`` the language, alternate group and on/off state of ``track``.

    A new track is on, in no language and no group: a film's second
    language (or its commentary) would otherwise play over the first.
    ``state=False`` copies the language only, leaving every track on and in
    no group: for an export that re-encodes, which would leave a track
    that's off out of the file.
    """
    if state:
        _objc.send(
            copy, "setEnabled:", _objc.send(track, "isEnabled", restype=_objc.BOOL), argtypes=(_objc.BOOL,), restype=None
        )
        _objc.send(
            copy,
            "setAlternateGroupID:",
            _objc.send(track, "alternateGroupID", restype=ctypes.c_int32),
            argtypes=(ctypes.c_int32,),
            restype=None,
        )
    # Only ever the tag ("fr-CA"): the exporter fills the three-letter code from it. A code copied onto the
    # track would outlive a tag a caller sets later, and an English code on a track relabelled Spanish
    # makes players that go by the code call it English. An older file with only a code ("eng") gets
    # the tag that code stands for ("en").
    tag = _objc.send(track, "extendedLanguageTag")
    if not tag:
        code = _objc.send(track, "languageCode")
        if code:
            tag = _objc.send(_objc.cls("NSLocale"), "canonicalLanguageIdentifierFromString:", code, argtypes=(_objc.id,))
    if tag:
        _objc.send(copy, "setExtendedLanguageTag:", tag, argtypes=(_objc.id,), restype=None)


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


def editable(media: int, keep_state: bool = True) -> int:
    """
    An autoreleased ``AVMutableComposition`` with every track of an asset, to edit.

    The video tracks keep the asset's ``preferredTransform``: a video marked
    to play turned (a portrait phone video, :func:`macos.video.rotate`'s
    output) still does, and what's done to the composition composes with it.
    Every track keeps its language, and the whole length is kept, to the
    sample. Each keeps its alternate group and on/off state too, unless
    ``keep_state`` is false: pass that for an export that re-encodes, which
    would drop a track that's off (a second language).
    """
    # The asset's own duration, not one rounded to the 1/600 s TIMESCALE: that would cut the last samples.
    length = _objc.send(media, "duration", restype=CMTime)
    if not length.flags & _VALID:
        raise MacOSError("could not read the media: it has no known length")
    edited = composition()
    error = ctypes.c_void_p()
    ok = _objc.send(
        edited,
        "insertTimeRange:ofAsset:atTime:error:",
        CMTimeRange(time(0), length),
        media,
        time(0),
        ctypes.byref(error),
        argtypes=(CMTimeRange, _objc.id, CMTime, ctypes.c_void_p),
        restype=_objc.BOOL,
    )
    if not ok:
        raise MacOSError("could not read the media: {}".format(_objc.error_message(error)))
    # The new tracks get an identity transform, whatever the source's, and are all on, in no language:
    # copied over, each from the track its segment came from (the order isn't promised to match).
    for kind in _KINDS:
        sources = {_objc.send(track, "trackID", restype=ctypes.c_int32): track for track in tracks(media, kind)}
        if not sources:
            continue
        for copy in tracks(edited, kind):
            segments = [
                segment
                for segment in _objc.nsarray(_objc.send(copy, "segments"))
                if not _objc.send(segment, "isEmpty", restype=_objc.BOOL)  # an empty edit (a gap) has no source track
            ]
            source = sources.get(_objc.send(segments[0], "sourceTrackID", restype=ctypes.c_int32) if segments else None)
            if source is None:
                continue
            if kind == "vide":
                turn = _objc.send(source, "preferredTransform", restype=_objc.CGAffineTransform)
                _objc.send(copy, "setPreferredTransform:", turn, argtypes=(_objc.CGAffineTransform,), restype=None)
            keep_settings(copy, source, keep_state)
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
    source: Optional[int] = None,
    timeout: float = 3600.0,
) -> Path:
    """
    Export an asset or composition to ``output`` (its extension picks the file type), and return ``output``.

    Writes to a temporary file next to it first, so the output may be one of
    the inputs, and a failure leaves nothing half-written. ``length`` keeps
    only the first seconds: the time stretcher pads the sound with silence.
    ``source`` is the asset a composition was made from: the output keeps
    its metadata (the date it was shot, where, the camera...), which a
    composition has none of. All of it in the source's own kind of file;
    from a .mov to an .mp4 or back, only what the output can hold (the date
    and place, mostly). Keep it alive until this returns.
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
        if source:
            _objc.send(session, "setMetadata:", _objc.send(source, "metadata"), argtypes=(_objc.id,), restype=None)
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
        try:
            finished = _objc.run_until(done, timeout)
        except BaseException:
            # Ctrl-C (or a callback's error) while it exports: stop the session, or it would keep
            # encoding in the background into a folder that's about to be deleted.
            _objc.send(session, "cancelExport", restype=None)
            raise
        if not finished:
            _objc.send(session, "cancelExport", restype=None)
            raise WaitTimeoutError("the export didn't finish within {} seconds".format(timeout))
        status = _objc.send(session, "status", restype=_objc.NSInteger)
        if status != _COMPLETED:
            error = _objc.send(session, "error")
            message = _objc.pystring(_objc.send(error, "localizedDescription")) if error else "unknown error"
            raise MacOSError("the export failed: {}".format(message))
    return output
