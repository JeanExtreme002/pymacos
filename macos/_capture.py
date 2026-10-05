# -*- coding: utf-8 -*-

"""
Internal helpers for :mod:`macos.camera` and the microphone in :mod:`macos.audio`:
the Camera and Microphone permissions, through AVFoundation.
"""

import ctypes
import threading
from typing import Dict, List

from . import _objc
from ._system import framework
from .errors import PermissionDeniedError, PromptTimeoutError

VIDEO, AUDIO = "vide", "soun"  # AVMediaTypeVideo, AVMediaTypeAudio

_NOT_DETERMINED, _RESTRICTED, _DENIED, _AUTHORIZED = 0, 1, 2, 3
_NAMES = {VIDEO: "Camera", AUDIO: "Microphone"}


def _status(media: str) -> int:
    framework("AVFoundation")
    with _objc.autorelease_pool():
        return int(
            _objc.send(
                _objc.cls("AVCaptureDevice"),
                "authorizationStatusForMediaType:",
                _objc.nsstring(media),
                argtypes=(_objc.id,),
                restype=_objc.NSInteger,
            )
        )


def has_permission(media: str) -> bool:
    return _status(media) == _AUTHORIZED


# The calls waiting for the answer to each media's prompt: one answer settles them all.
_lock = threading.Lock()
_waiting: Dict[str, List["_Answer"]] = {VIDEO: [], AUDIO: []}
_handlers: Dict[str, int] = {}


class _Answer:
    def __init__(self) -> None:
        self.granted = False
        self.done = threading.Event()


def _handler(media: str) -> int:
    """
    The completion block for ``media``'s prompt, made once: a block lives as long as the process.

    It answers every call waiting at the time, so it needs no context of its own.
    """
    with _lock:
        if media not in _handlers:

            def answered(granted: bool) -> None:
                with _lock:
                    waiting, _waiting[media] = _waiting[media], []
                for answer in waiting:
                    answer.granted = bool(granted)
                    answer.done.set()

            _handlers[media] = _objc.block(answered, b"v@?B", ctypes.c_bool)
        return _handlers[media]


def request_permission(media: str, timeout: float = 120.0) -> bool:
    """
    Show the system prompt if the user hasn't answered yet, and wait for the answer.

    ``False`` when it's denied, or still unanswered after ``timeout`` seconds.
    """
    status = _status(media)
    if status != _NOT_DETERMINED:
        return status == _AUTHORIZED
    handler = _handler(media)
    answer = _Answer()
    with _lock:
        _waiting[media].append(answer)
    try:
        with _objc.autorelease_pool():
            _objc.send(
                _objc.cls("AVCaptureDevice"),
                "requestAccessForMediaType:completionHandler:",
                _objc.nsstring(media),
                handler,
                argtypes=(_objc.id, ctypes.c_void_p),
                restype=None,
            )
        _objc.run_until(answer.done.is_set, timeout)
    finally:
        with _lock:
            if answer in _waiting[media]:
                _waiting[media].remove(answer)
    return answer.granted


def require_permission(media: str) -> None:
    """Ask for the permission the first time; raise when it's denied, or the prompt goes unanswered."""
    if request_permission(media):
        return
    name = _NAMES[media]
    if _status(media) == _NOT_DETERMINED:
        raise PromptTimeoutError(
            "no answer to the {} permission prompt: run it again and click Allow, or allow the app running "
            "Python (your terminal or IDE) in System Settings › Privacy & Security › {}".format(name, name)
        )
    raise PermissionDeniedError(
        "{} permission is missing: allow the app running Python (your terminal or IDE) in System Settings › "
        "Privacy & Security › {}, then restart it".format(name, name)
    )
