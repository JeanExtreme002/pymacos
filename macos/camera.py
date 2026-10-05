# -*- coding: utf-8 -*-

"""
List the cameras, take photos and record videos with the webcam.

::

    [camera.name for camera in macos.camera.devices()]   # ['FaceTime HD Camera']
    macos.camera.photo("me.jpg")
    macos.camera.record("clip.mov", seconds=5)

Uses AVFoundation, like Photo Booth. Taking photos and videos needs the
*Camera* permission for the app running Python (your terminal or IDE), and
recording sound with a video the *Microphone* one: macOS asks for each the
first time. The camera's green light is on while it works.
"""

import ctypes
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from . import _capture, _files, _objc
from ._system import framework
from .errors import MacOSError

__all__ = ["Camera", "devices", "photo", "record", "has_permission", "request_permission"]

PathLike = Union[str, "os.PathLike[str]"]

_WARM_UP = 1.0  # seconds for the camera to settle its exposure before a photo
_TIMEOUT = 15.0  # seconds to wait for a photo or the end of a recording
_PHOTO_FORMATS = {".jpg", ".jpeg", ".png", ".heic", ".tiff"}


@dataclass(frozen=True)
class Camera:
    """A camera macOS can use: the built-in one, a USB webcam, an iPhone through Continuity..."""

    name: str
    """As shown in apps' camera menus, such as ``'FaceTime HD Camera'``."""
    id: str
    """A stable identifier for the camera."""
    is_default: bool
    """The camera apps use unless told otherwise."""


def has_permission() -> bool:
    """Whether this process may use the camera, without prompting the user."""
    return _capture.has_permission(_capture.VIDEO)


def request_permission() -> bool:
    """
    Ask for the Camera permission, showing the system prompt the first time; return whether it's granted.

    macOS asks only once: after that, the user must allow the app running
    Python (your terminal or IDE) in System Settings › Privacy & Security ›
    Camera, and restart it.
    """
    return _capture.request_permission(_capture.VIDEO)


def _handles(media: str = _capture.VIDEO) -> List[int]:
    """The ``AVCaptureDevice`` objects for ``media``. Call inside an autorelease pool."""
    framework("AVFoundation")
    found = _objc.send(_objc.cls("AVCaptureDevice"), "devicesWithMediaType:", _objc.nsstring(media), argtypes=(_objc.id,))
    return list(_objc.nsarray(found))


def _default_id(media: str = _capture.VIDEO) -> Optional[str]:
    framework("AVFoundation")
    default = _objc.send(
        _objc.cls("AVCaptureDevice"), "defaultDeviceWithMediaType:", _objc.nsstring(media), argtypes=(_objc.id,)
    )
    return _objc.pystring(_objc.send(default, "uniqueID")) if default else None


def devices() -> List[Camera]:
    """Return the connected cameras, the default one first. Needs no permission."""
    with _objc.autorelease_pool():
        default = _default_id()
        cameras = [
            Camera(
                name=_objc.pystring(_objc.send(handle, "localizedName")) or "",
                id=_objc.pystring(_objc.send(handle, "uniqueID")) or "",
                is_default=_objc.pystring(_objc.send(handle, "uniqueID")) == default,
            )
            for handle in _handles()
        ]
    return sorted(cameras, key=lambda camera: not camera.is_default)


def _device(camera: Union[str, Camera, None]) -> int:
    """The ``AVCaptureDevice`` for ``camera``: a Camera, an id, a full or unique partial name, or the default."""
    handles = _handles()
    if not handles:
        raise MacOSError("no camera is connected")
    if camera is None:
        default = _default_id()
        return next((handle for handle in handles if _objc.pystring(_objc.send(handle, "uniqueID")) == default), handles[0])
    wanted = camera.id if isinstance(camera, Camera) else camera
    named = [(handle, _objc.pystring(_objc.send(handle, "localizedName")) or "") for handle in handles]
    for handle, name in named:
        if wanted in (name, _objc.pystring(_objc.send(handle, "uniqueID"))):
            return handle
    loose = [handle for handle, name in named if wanted.casefold() in name.casefold()]
    if len(loose) == 1:
        return loose[0]
    names = ", ".join(repr(name) for _, name in named)
    if not loose:
        raise ValueError("no camera matches {!r}; connected: {}".format(wanted, names))
    raise ValueError("{!r} matches several cameras ({}); use the full name".format(wanted, names))


def _input(device: int) -> int:
    error = ctypes.c_void_p()
    source = _objc.send(
        _objc.cls("AVCaptureDeviceInput"),
        "deviceInputWithDevice:error:",
        device,
        ctypes.byref(error),
        argtypes=(_objc.id, ctypes.c_void_p),
    )
    if not source:
        name = _objc.pystring(_objc.send(device, "localizedName"))
        raise MacOSError("could not use {}: {}".format(name, _objc.error_message(error)))
    return source


def _session(inputs: List[int], output: int) -> int:
    """A running ``AVCaptureSession`` from ``inputs`` to ``output`` (autoreleased)."""
    session = _objc.new("AVCaptureSession")
    for source in inputs + [output]:
        adder = "addOutput:" if source == output else "addInput:"
        checker = "canAddOutput:" if source == output else "canAddInput:"
        if not _objc.send(session, checker, source, argtypes=(_objc.id,), restype=_objc.BOOL):
            raise MacOSError("the camera can't be used that way")
        _objc.send(session, adder, source, argtypes=(_objc.id,), restype=None)
    _objc.send(session, "startRunning", restype=None)
    return session


# The delegates AVFoundation calls back, keyed by the delegate object: what each capture got. Only the
# delegates still waited for take results: one that timed out is forgotten, and a callback arriving late
# for it is dropped, or it would stay here for good, and be read by the next delegate given the same
# address.
_results: Dict[int, Dict[str, Any]] = {}
_waiting: set = set()  # delegates whose capture is under way
_started: set = set()  # movie delegates whose recording has begun
_lock = threading.Lock()


def _store(delegate: int, result: Dict[str, Any]) -> None:
    with _lock:
        if delegate in _waiting:
            _results[delegate] = result


def _forget(delegate: int) -> None:
    with _lock:
        _waiting.discard(delegate)
        _started.discard(delegate)
        _results.pop(delegate, None)


_PhotoDone = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_MovieStarted = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_MovieDone = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)


def _photo_done(delegate: int, _cmd: int, output: int, photo: int, error: int) -> None:
    result: Dict[str, Any] = {"done": True}
    if error:
        result["error"] = _objc.error_message(ctypes.c_void_p(error))
    else:
        result["data"] = _objc.pybytes(_objc.send(photo, "fileDataRepresentation"))
    _store(delegate, result)


def _movie_started(delegate: int, _cmd: int, output: int, url: int, connections: int) -> None:
    with _lock:
        if delegate in _waiting:
            _started.add(delegate)


def _movie_done(delegate: int, _cmd: int, output: int, url: int, connections: int, error: int) -> None:
    result: Dict[str, Any] = {"done": True}
    if error:
        # "Recording stopped" is how a normal stop is reported: the file is fine then.
        info = _objc.send(error, "userInfo")
        finished = _objc.send(
            info, "objectForKey:", _objc.nsstring("AVErrorRecordingSuccessfullyFinishedKey"), argtypes=(_objc.id,)
        )
        if not (finished and _objc.send(finished, "boolValue", restype=_objc.BOOL)):
            result["error"] = _objc.error_message(ctypes.c_void_p(error))
    _store(delegate, result)


def _delegate(kind: str) -> int:
    """A new delegate object (autoreleased) whose callback lands in ``_results``, until :func:`_forget`."""
    if kind == "photo":
        name = "PymacosPhotoDelegate"
        _objc.define_class(
            name,
            {"captureOutput:didFinishProcessingPhoto:error:": ("v@:@@@", _PhotoDone, _photo_done)},
            protocols=("AVCapturePhotoCaptureDelegate",),
        )
    else:
        name = "PymacosMovieDelegate"
        _objc.define_class(
            name,
            {
                "captureOutput:didStartRecordingToOutputFileAtURL:fromConnections:": (
                    "v@:@@@",
                    _MovieStarted,
                    _movie_started,
                ),
                "captureOutput:didFinishRecordingToOutputFileAtURL:fromConnections:error:": (
                    "v@:@@@@",
                    _MovieDone,
                    _movie_done,
                ),
            },
            protocols=("AVCaptureFileOutputRecordingDelegate",),
        )
    delegate = _objc.new(name)
    with _lock:
        _waiting.add(delegate)
    return delegate


def _wait(delegate: int, what: str) -> Dict[str, Any]:
    # The callbacks come on the main queue: turn the run loop while waiting (on the main thread, which
    # photo() and record() check first: another thread's run loop never gets them).
    try:
        if not _objc.run_until(lambda: delegate in _results, _TIMEOUT):
            raise MacOSError("the camera didn't finish the {} within {} seconds".format(what, _TIMEOUT))
        with _lock:
            result = _results[delegate]
    finally:
        _forget(delegate)
    if "error" in result:
        raise MacOSError("the camera couldn't take the {}: {}".format(what, result["error"]))
    return result


def _output_path(path: Optional[PathLike], default_suffix: str, allowed: Any) -> Tuple[Path, bool]:
    """The target path, and whether it's a temporary file made here."""
    if path is None:
        handle, name = tempfile.mkstemp(prefix="camera-", suffix=default_suffix)
        os.close(handle)
        return Path(name), True
    target = Path(path).expanduser().absolute()
    if target.suffix.lower() not in allowed:
        raise ValueError("can't save {!r} files; use one of {}".format(target.suffix, ", ".join(sorted(allowed))))
    return target, False


def photo(path: Optional[PathLike] = None, *, camera: Union[str, Camera, None] = None) -> Path:
    """
    Take a photo with the webcam and return its path.

    ``path``'s extension sets the format (``.jpg``, ``.png``, ``.heic``,
    ``.tiff``); without ``path``, a temporary ``.jpg`` is made, and deleting
    it is up to you. ``camera`` is a :class:`Camera`, its id, or its name
    (or part of it); by default, the default camera.

    The camera turns on for about a second first, so the exposure settles.
    Needs the Camera permission, which macOS asks for the first time::

        macos.camera.photo("~/Desktop/me.jpg")
    """
    target, temporary = _output_path(path, ".jpg", _PHOTO_FORMATS)
    try:
        _files.require_main_thread("macos.camera.photo()")
        _capture.require_permission(_capture.VIDEO)
        with _objc.autorelease_pool():
            device = _device(camera)
            output = _objc.new("AVCapturePhotoOutput")
            session = _session([_input(device)], output)
            delegate = _delegate("photo")
            try:
                _objc.run_until(lambda: False, _WARM_UP)
                settings = _objc.send(_objc.cls("AVCapturePhotoSettings"), "photoSettings")
                _objc.send(
                    output,
                    "capturePhotoWithSettings:delegate:",
                    settings,
                    delegate,
                    argtypes=(_objc.id, _objc.id),
                    restype=None,
                )
                data = _wait(delegate, "photo").get("data")
            finally:
                _forget(delegate)
                _objc.send(session, "stopRunning", restype=None)
        if not data:
            raise MacOSError("the camera returned no photo")
        if target.suffix.lower() in (".jpg", ".jpeg"):
            _files.write_atomically(target, lambda name: Path(name).write_bytes(data))
        else:
            from . import image

            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as shot:
                shot.write(data)
            try:
                image.convert(shot.name, target)
            finally:
                os.unlink(shot.name)
        return target
    except BaseException:
        if temporary:
            target.unlink(missing_ok=True)
        raise


def record(
    path: PathLike, seconds: float, *, camera: Union[str, Camera, None] = None, audio: bool = True
) -> Path:
    """
    Record a video with the webcam for ``seconds`` into a ``.mov`` file, and return its path when it ends.

    ``camera`` works as in :func:`photo`. ``audio=True`` also records the
    default microphone, which needs the Microphone permission too. To make it
    an ``.mp4`` or smaller, see :func:`macos.video.convert`::

        macos.camera.record("hello.mov", 5)
        macos.video.convert("hello.mov", "hello.mp4", quality="medium")
    """
    if seconds <= 0:
        raise ValueError("seconds must be positive, not {}".format(seconds))
    target = Path(path).expanduser().absolute()
    if target.suffix.lower() != ".mov":
        raise ValueError("webcam videos are .mov files, not {!r}".format(target.suffix))
    _files.require_main_thread("macos.camera.record()")
    _capture.require_permission(_capture.VIDEO)
    if audio:
        _capture.require_permission(_capture.AUDIO)
    # Recorded beside the target, at a path where nothing is yet (the recorder refuses to replace a file),
    # and moved over it once saved: a recording that fails leaves the file that was there as it was.
    with _files.replacing(target) as temporary:
        _record(temporary, seconds, camera, audio)
    return target


def _record(target: Path, seconds: float, camera: Union[str, Camera, None], audio: bool) -> None:
    with _objc.autorelease_pool():
        inputs = [_input(_device(camera))]
        if audio:
            microphones = _handles(_capture.AUDIO)
            if not microphones:
                raise MacOSError("no microphone to record the sound with; pass audio=False")
            default = _default_id(_capture.AUDIO)
            microphone = next(
                (handle for handle in microphones if _objc.pystring(_objc.send(handle, "uniqueID")) == default),
                microphones[0],
            )
            inputs.append(_input(microphone))
        output = _objc.new("AVCaptureMovieFileOutput")
        session = _session(inputs, output)
        delegate = _delegate("movie")
        try:
            _objc.send(
                output,
                "startRecordingToOutputFileURL:recordingDelegate:",
                _objc.file_url(target),
                delegate,
                argtypes=(_objc.id, _objc.id),
                restype=None,
            )
            try:
                # The recording begins a moment after it's asked for (about a
                # second): count the seconds from then, or the video comes out
                # short, and stopping before it began fails ("Cannot Record").
                if not _objc.run_until(lambda: delegate in _started or delegate in _results, _TIMEOUT):
                    raise MacOSError("the camera didn't start recording within {} seconds".format(_TIMEOUT))
                end = time.monotonic() + seconds
                _objc.run_until(lambda: time.monotonic() >= end or delegate in _results, seconds + 1)
            finally:
                _objc.send(output, "stopRecording", restype=None)
            _wait(delegate, "video")
        finally:
            _forget(delegate)
            _objc.send(session, "stopRunning", restype=None)
    if not target.exists():
        raise MacOSError("the video wasn't saved")
