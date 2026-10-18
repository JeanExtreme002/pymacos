# -*- coding: utf-8 -*-

"""
List audio devices, switch the default output and input, and record the microphone.

::

    [device.name for device in macos.audio.outputs()]   # ['MacBook Pro Speakers', 'AirPods Pro']
    macos.audio.default_output()                          # Device(name='MacBook Pro Speakers', ...)
    macos.audio.set_output("AirPods Pro")
    macos.audio.set_input("MacBook Pro Microphone")
    macos.audio.mute_input()                              # mute the microphone
    macos.audio.record("memo.m4a", seconds=10)            # record it

Talks to CoreAudio directly, like the Sound settings do. Switching needs no
permission; recording needs the *Microphone* one, which macOS asks for the
first time.
"""

import array
import ctypes
import io
import math
import os
import struct
import sys
import tempfile
import time
import wave
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Sequence, Tuple, Union

from . import _capture, _cf, _files, _media, _objc
from ._system import framework, run as _run
from .errors import MacOSError, NotSupportedError

__all__ = [
    "Device",
    "devices",
    "outputs",
    "inputs",
    "default_output",
    "default_input",
    "set_output",
    "set_input",
    "input_volume",
    "set_input_volume",
    "input_muted",
    "mute_input",
    "record",
    "input_level",
    "has_permission",
    "request_permission",
    "AudioInfo",
    "info",
    "convert",
    "trim",
    "concat",
    "fade",
    "gain",
    "reverse",
    "speed",
    "classify",
    "record_until_silence",
]


def _code(text: str) -> int:
    """A CoreAudio four-character code, such as ``'dev#'``."""
    return int(struct.unpack(">I", text.encode("ascii"))[0])


_SYSTEM = 1  # kAudioObjectSystemObject
_GLOBAL, _OUTPUT, _INPUT = _code("glob"), _code("outp"), _code("inpt")
_MAIN_ELEMENT = 0

_TRANSPORTS = {
    "bltn": "builtin",
    "usb ": "usb",
    "blue": "bluetooth",
    "blea": "bluetooth",
    "hdmi": "hdmi",
    "dprt": "displayport",
    "airp": "airplay",
    "thun": "thunderbolt",
    "pci ": "pci",
    "virt": "virtual",
    "grup": "aggregate",
    "cont": "continuity",
    "avb ": "avb",
}


class _Address(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


@dataclass(frozen=True)
class Device:
    """An audio device: speakers, headphones, a microphone, a display's audio..."""

    id: int
    name: str
    """As shown in System Settings › Sound, in the system's language."""
    uid: str
    """A stable identifier that survives reconnecting the device."""
    transport: str
    """How it's connected: ``'builtin'``, ``'usb'``, ``'bluetooth'``, ``'hdmi'``, ``'airplay'``..."""
    is_output: bool
    is_input: bool


@lru_cache(maxsize=None)
def _core_audio() -> ctypes.CDLL:
    audio = framework("CoreAudio")
    address = ctypes.POINTER(_Address)
    size = ctypes.POINTER(ctypes.c_uint32)
    audio.AudioObjectGetPropertyDataSize.argtypes = (ctypes.c_uint32, address, ctypes.c_uint32, ctypes.c_void_p, size)
    audio.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
    audio.AudioObjectGetPropertyData.argtypes = (
        ctypes.c_uint32,
        address,
        ctypes.c_uint32,
        ctypes.c_void_p,
        size,
        ctypes.c_void_p,
    )
    audio.AudioObjectGetPropertyData.restype = ctypes.c_int32
    audio.AudioObjectSetPropertyData.argtypes = (
        ctypes.c_uint32,
        address,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    audio.AudioObjectSetPropertyData.restype = ctypes.c_int32
    return audio


def _property(target: int, selector: str, scope: int = _GLOBAL, element: int = _MAIN_ELEMENT) -> Optional[bytes]:
    """Raw bytes of a CoreAudio property, or ``None`` if the object doesn't have it."""
    audio = _core_audio()
    address = _Address(_code(selector), scope, element)
    size = ctypes.c_uint32()
    if audio.AudioObjectGetPropertyDataSize(target, ctypes.byref(address), 0, None, ctypes.byref(size)) != 0:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if audio.AudioObjectGetPropertyData(target, ctypes.byref(address), 0, None, ctypes.byref(size), buffer) != 0:
        return None
    return buffer.raw[: size.value]


def _string(target: int, selector: str) -> str:
    raw = _property(target, selector)
    if not raw:
        return ""
    # AudioHardwareBase.h, for kAudioObjectPropertyName and
    # kAudioDevicePropertyDeviceUID: "The caller is responsible for releasing
    # the returned CFObject", so the string is released once read.
    if len(raw) < ctypes.sizeof(ctypes.c_void_p):
        return ""  # not a CFStringRef: nothing to read, or to release
    with _cf.owned(ctypes.c_void_p.from_buffer_copy(raw).value) as ref:
        return _cf.to_str(ref) or ""


def _uint(target: int, selector: str, scope: int = _GLOBAL, element: int = _MAIN_ELEMENT) -> Optional[int]:
    raw = _property(target, selector, scope, element)
    return int(struct.unpack("I", raw[:4])[0]) if raw and len(raw) >= 4 else None


def _device(device_id: int) -> Device:
    transport = _uint(device_id, "tran")
    code = struct.pack(">I", transport).decode("ascii", "replace") if transport else ""
    return Device(
        id=device_id,
        name=_string(device_id, "lnam"),
        uid=_string(device_id, "uid "),
        transport=_TRANSPORTS.get(code, code.strip() or "unknown"),
        # A device plays (or records) when it has output (or input) streams.
        is_output=bool(_property(device_id, "stm#", _OUTPUT)),
        is_input=bool(_property(device_id, "stm#", _INPUT)),
    )


def devices() -> List[Device]:
    """Return every audio device, outputs and inputs."""
    raw = _property(_SYSTEM, "dev#") or b""
    ids = struct.unpack("{}I".format(len(raw) // 4), raw)
    return [_device(device_id) for device_id in ids]


def outputs() -> List[Device]:
    """Return the devices that play sound (speakers, headphones, displays...)."""
    return [device for device in devices() if device.is_output]


def inputs() -> List[Device]:
    """Return the devices that record sound (microphones...)."""
    return [device for device in devices() if device.is_input]


def _default(selector: str) -> Optional[Device]:
    device_id = _uint(_SYSTEM, selector)
    return _device(device_id) if device_id else None


def default_output() -> Optional[Device]:
    """Return the device sound currently plays through."""
    return _default("dOut")


def default_input() -> Optional[Device]:
    """Return the device currently used to record (the microphone apps get by default)."""
    return _default("dIn ")


def _find(target: Union[str, Device], candidates: List[Device], kind: str) -> Device:
    if isinstance(target, Device):
        target = target.uid
    if not isinstance(target, str):
        raise TypeError("device must be a Device or a str, not {}".format(type(target).__name__))
    # The uid first: it's unique, where two identical USB mics share their name.
    for device in candidates:
        if device.uid == target:
            return device
    exact = [device for device in candidates if device.name == target]
    if len(exact) == 1:
        return exact[0]
    wanted = target.casefold()
    loose = exact or [device for device in candidates if wanted in device.name.casefold()]
    if len(loose) == 1:
        return loose[0]
    if not loose:
        names = ", ".join(repr(device.name) for device in candidates)
        raise ValueError("no {} device matches {!r}; available: {}".format(kind, target, names))
    # Only the devices that match, each with its uid: the one way to tell apart devices of the same name.
    matches = ", ".join("{!r} (uid {!r})".format(device.name, device.uid) for device in loose)
    raise ValueError("{!r} matches several {} devices: {}; use the full name or the uid".format(target, kind, matches))


def _set_default(selector: str, device: Device) -> None:
    value = ctypes.c_uint32(device.id)
    address = _Address(_code(selector), _GLOBAL, _MAIN_ELEMENT)
    status = _core_audio().AudioObjectSetPropertyData(
        _SYSTEM, ctypes.byref(address), 0, None, ctypes.sizeof(value), ctypes.byref(value)
    )
    if status != 0:
        raise MacOSError("could not switch to {!r} (OSStatus {})".format(device.name, status))


def set_output(device: Union[str, Device]) -> Device:
    """
    Play sound through ``device`` and return it.

    ``device`` is a :class:`Device`, its full name, its uid, or part of its
    name when that matches only one device (``"AirPods"``). A name several
    devices share (two identical USB microphones) raises ``ValueError``,
    listing their uids: pass the uid or the :class:`Device` then.
    """
    chosen = _find(device, outputs(), "output")
    _set_default("dOut", chosen)
    return chosen


def set_input(device: Union[str, Device]) -> Device:
    """Record from ``device`` by default and return it. ``device`` works as in :func:`set_output`."""
    chosen = _find(device, inputs(), "input")
    _set_default("dIn ", chosen)
    return chosen


# The microphone's volume and mute, on the default input device or another one.


def _input_device(device: Union[str, Device, None]) -> Device:
    if device is None:
        current = default_input()
        if current is None:
            raise NotSupportedError("this Mac has no microphone")
        return current
    return _find(device, inputs(), "input")


def _input_channels(device: Device) -> int:
    """How many input channels the device has, from its stream configuration (an AudioBufferList)."""
    raw = _property(device.id, "slay", _INPUT) or b""
    if len(raw) < 4:
        return 0
    buffers = struct.unpack("I", raw[:4])[0]
    # Each AudioBuffer is 16 bytes (channels, byte size, data pointer), after 8 bytes of header.
    offsets = [8 + 16 * index for index in range(buffers) if len(raw) >= 24 + 16 * index]
    return sum(struct.unpack("I", raw[offset : offset + 4])[0] for offset in offsets)


def _elements(device: Device, selector: str) -> List[int]:
    """The elements that have ``selector`` on the input side: the main one, or each of the device's channels."""
    if _property(device.id, selector, _INPUT, 0) is not None:
        return [0]
    channels = range(1, _input_channels(device) + 1)
    return [channel for channel in channels if _property(device.id, selector, _INPUT, channel) is not None]


def _set_input(device: Device, selector: str, elements: List[int], value: ctypes._SimpleCData) -> None:
    audio = _core_audio()
    for element in elements:
        address = _Address(_code(selector), _INPUT, element)
        status = audio.AudioObjectSetPropertyData(
            device.id, ctypes.byref(address), 0, None, ctypes.sizeof(value), ctypes.byref(value)
        )
        if status != 0:
            raise MacOSError("could not change {!r} (OSStatus {})".format(device.name, status))


def input_volume(device: Union[str, Device, None] = None) -> float:
    """
    The microphone's input volume, from 0.0 to 1.0, as the slider in System Settings › Sound › Input.

    ``device`` works as in :func:`set_input`; by default, the default input.
    """
    chosen = _input_device(device)
    levels = [
        struct.unpack("f", raw[:4])[0]
        for raw in (_property(chosen.id, "volm", _INPUT, element) for element in _elements(chosen, "volm"))
        if raw and len(raw) >= 4
    ]
    if not levels:
        raise NotSupportedError("{!r} has no adjustable input volume".format(chosen.name))
    return round(sum(levels) / len(levels), 3)


def set_input_volume(value: float, *, device: Union[str, Device, None] = None) -> None:
    """Set the microphone's input volume, from 0.0 to 1.0. ``device`` works as in :func:`input_volume`."""
    if not 0.0 <= value <= 1.0:
        raise ValueError("volume must be from 0.0 to 1.0, not {}".format(value))
    chosen = _input_device(device)
    elements = _elements(chosen, "volm")
    if not elements:
        raise NotSupportedError("{!r} has no adjustable input volume".format(chosen.name))
    _set_input(chosen, "volm", elements, ctypes.c_float(value))


def input_muted(device: Union[str, Device, None] = None) -> bool:
    """Whether the microphone is muted. ``device`` works as in :func:`input_volume`."""
    chosen = _input_device(device)
    elements = _elements(chosen, "mute")
    if not elements:
        raise NotSupportedError("{!r} can't be muted; use set_input_volume(0.0)".format(chosen.name))
    return all(_uint(chosen.id, "mute", _INPUT, element) for element in elements)


def mute_input(on: bool = True, *, device: Union[str, Device, None] = None) -> None:
    """
    Mute the microphone (or unmute it with ``on=False``), for every app at once.

    Handy as a "mute me" shortcut in meetings. ``device`` works as in
    :func:`input_volume`. Devices without a mute switch raise
    :class:`~macos.errors.NotSupportedError`: set their volume to 0 instead.
    """
    chosen = _input_device(device)
    elements = _elements(chosen, "mute")
    if not elements:
        raise NotSupportedError("{!r} can't be muted; use set_input_volume(0.0)".format(chosen.name))
    _set_input(chosen, "mute", elements, ctypes.c_uint32(1 if on else 0))


# Recording the microphone, through AVFoundation's AVAudioRecorder.


def has_permission() -> bool:
    """Whether this process may record the microphone, without prompting the user."""
    return _capture.has_permission(_capture.AUDIO)


def request_permission() -> bool:
    """
    Ask for the Microphone permission, showing the system prompt the first time; return whether it's granted.

    macOS asks only once: after that, the user must allow the app running
    Python (your terminal or IDE) in System Settings › Privacy & Security ›
    Microphone, and restart it.
    """
    return _capture.request_permission(_capture.AUDIO)


# The format each extension records in: AAC for .m4a, uncompressed PCM for the others.
_RECORD_FORMATS = {
    ".m4a": {"AVFormatIDKey": _code("aac "), "AVEncoderAudioQualityKey": 96},  # AVAudioQualityHigh
    ".wav": {"AVFormatIDKey": _code("lpcm"), "AVLinearPCMBitDepthKey": 16, "AVLinearPCMIsBigEndianKey": 0},
    ".aiff": {"AVFormatIDKey": _code("lpcm"), "AVLinearPCMBitDepthKey": 16, "AVLinearPCMIsBigEndianKey": 1},
    ".aif": {"AVFormatIDKey": _code("lpcm"), "AVLinearPCMBitDepthKey": 16, "AVLinearPCMIsBigEndianKey": 1},
    ".caf": {"AVFormatIDKey": _code("lpcm"), "AVLinearPCMBitDepthKey": 16, "AVLinearPCMIsBigEndianKey": 0},
}


def _recorder(target: Path, channels: int, metering: bool = False) -> int:
    """An autoreleased, prepared ``AVAudioRecorder`` writing to ``target``. Call inside an autorelease pool."""
    framework("AVFoundation")
    settings = dict(_RECORD_FORMATS[target.suffix.lower()], AVSampleRateKey=44100, AVNumberOfChannelsKey=channels)
    dictionary = _objc.nsdictionary_of({key: _objc.nsnumber(value) for key, value in settings.items()})
    error = ctypes.c_void_p()
    recorder = _objc.send(
        _objc.send(_objc.cls("AVAudioRecorder"), "alloc"),
        "initWithURL:settings:error:",
        _objc.file_url(target),
        dictionary,
        ctypes.byref(error),
        argtypes=(_objc.id, _objc.id, ctypes.c_void_p),
    )
    if not recorder:
        raise MacOSError("could not record to {}: {}".format(target, _objc.error_message(error)))
    _objc.send(recorder, "autorelease")
    _objc.send(recorder, "setMeteringEnabled:", metering, argtypes=(_objc.BOOL,), restype=None)
    if not _objc.send(recorder, "prepareToRecord", restype=_objc.BOOL):
        raise MacOSError("the microphone could not be prepared")
    return recorder


def record(path: Union[str, "os.PathLike[str]"], seconds: float, *, channels: int = 1) -> Path:
    """
    Record the microphone for ``seconds`` into ``path``, and return it when the recording ends.

    ``path``'s extension sets the format: ``.m4a`` (AAC, small), ``.wav``,
    ``.aiff`` or ``.caf`` (uncompressed). ``channels`` is 1 (mono) or 2
    (stereo). It records the default input: switch it first with
    :func:`set_input`. Needs the Microphone permission, which macOS asks for
    the first time::

        macos.audio.record("memo.m4a", 30)

    Ctrl-C stops the recording early and keeps what was recorded until then.
    If the recording fails, a file already at ``path`` stays as it was.
    """
    if not _positive(seconds):
        raise ValueError("seconds must be positive, not {}".format(seconds))
    if channels not in (1, 2):
        raise ValueError("channels must be 1 or 2, not {}".format(channels))
    target = Path(path).expanduser().absolute()
    if target.suffix.lower() not in _RECORD_FORMATS:
        raise ValueError(
            "can't record {!r} files; use one of {}".format(target.suffix, ", ".join(sorted(_RECORD_FORMATS)))
        )
    _capture.require_permission(_capture.AUDIO)
    # Recorded beside the target and moved over it once saved: prepareToRecord
    # empties the file it's given, so a recording that fails would otherwise
    # destroy the one that was there, or leave it to pass for the new one.
    interrupted: List[BaseException] = []
    with _files.replacing(target) as temporary, _objc.autorelease_pool():
        recorder = _recorder(temporary, channels)
        if not _objc.send(recorder, "record", restype=_objc.BOOL):
            raise MacOSError("the microphone could not start recording")
        # Not recordForDuration: its stop is a run loop timer, which a
        # script never turns. Stop it ourselves, even on Ctrl-C.
        heard = 0.0
        try:
            time.sleep(seconds)
        except KeyboardInterrupt as error:
            interrupted.append(error)  # stopped on purpose: what was recorded is kept, then Ctrl-C goes on
        finally:
            heard = _recorded_seconds(recorder)  # before stop(), which resets it
            _objc.send(recorder, "stop", restype=None)
        # No sound recorded (the file holds prepareToRecord's header at most): never over the old file.
        if not temporary.exists() or heard <= 0:
            if interrupted:
                raise interrupted[0]  # stopped before anything was saved: the Ctrl-C, not a failure of ours
            raise MacOSError("the recording wasn't saved")
    if interrupted:
        raise interrupted[0]
    return target


def _positive(value: float) -> bool:
    """Whether ``value`` is a number of seconds to wait or keep: above 0, and neither infinite nor NaN."""
    return math.isfinite(value) and value > 0


def _recorded_seconds(recorder: int) -> float:
    """How long a recorder still recording has recorded: 0 when it has no sound yet, only the file's header."""
    return float(_objc.send(recorder, "currentTime", restype=ctypes.c_double) or 0)


def input_level(seconds: float = 0.3) -> float:
    """
    How loud the microphone hears it right now, from 0.0 (silence) to 1.0 (the loudest it takes).

    Listens for ``seconds`` and returns the average level: about 0.01 in a
    quiet room, 0.1 to 0.3 for someone talking nearby. Handy to tell whether
    someone is speaking, or to wait for quiet::

        while macos.audio.input_level() > 0.05:
            time.sleep(1)

    Needs the Microphone permission, like :func:`record`. Nothing is kept.
    """
    if not _positive(seconds):
        raise ValueError("seconds must be positive, not {}".format(seconds))
    _capture.require_permission(_capture.AUDIO)
    handle, name = tempfile.mkstemp(suffix=".caf")
    os.close(handle)
    scratch = Path(name)
    levels: List[float] = []
    try:
        with _objc.autorelease_pool():
            recorder = _recorder(scratch, 1, metering=True)
            if not _objc.send(recorder, "record", restype=_objc.BOOL):
                raise MacOSError("the microphone could not start listening")
            try:
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    time.sleep(0.05)
                    _objc.send(recorder, "updateMeters", restype=None)
                    power = _objc.send(
                        recorder, "averagePowerForChannel:", 0, argtypes=(_objc.NSUInteger,), restype=ctypes.c_float
                    )
                    levels.append(10 ** (float(power) / 20))  # decibels to a 0-1 amplitude
            finally:
                _objc.send(recorder, "stop", restype=None)
    finally:
        scratch.unlink(missing_ok=True)
    level = sum(levels) / len(levels) if levels else 0.0
    return round(min(max(level, 0.0), 1.0), 4) if not math.isnan(level) else 0.0


# Audio files: read with AVFoundation, converted with afconvert (which ships
# with macOS), and edited as 16-bit samples in Python.

PathLike = Union[str, "os.PathLike[str]"]

_CODECS = {"aac ": "aac", "alac": "alac", "lpcm": "pcm", ".mp3": "mp3", "opus": "opus", "flac": "flac", "ac-3": "ac3"}
_QUALITY = {"high": 127, "medium": 90, "low": 50}  # AAC variable-bit-rate quality, 0 to 127
_WRITE = {".m4a", ".wav", ".aiff", ".aif", ".caf"}


@dataclass(frozen=True)
class AudioInfo:
    """What an audio file contains."""

    duration: float
    """In seconds."""
    sample_rate: int
    """Samples per second, such as 44100 or 48000."""
    channels: int
    """1 (mono), 2 (stereo)..."""
    codec: str
    """``'aac'``, ``'alac'``, ``'pcm'`` (uncompressed), ``'mp3'``... or the codec's four-character code for others."""
    bitrate: Optional[int]
    """In kilobits per second, when the file says."""


class _StreamDescription(ctypes.Structure):
    # AudioStreamBasicDescription
    _fields_ = [
        ("sample_rate", ctypes.c_double),
        ("format_id", ctypes.c_uint32),
        ("format_flags", ctypes.c_uint32),
        ("bytes_per_packet", ctypes.c_uint32),
        ("frames_per_packet", ctypes.c_uint32),
        ("bytes_per_frame", ctypes.c_uint32),
        ("channels", ctypes.c_uint32),
        ("bits_per_channel", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


def _existing(path: PathLike) -> Path:
    """``path`` made absolute; ``FileNotFoundError`` when nothing's there, ``PermissionError`` when it can't be read.

    Checked here, not left to ``afconvert``, which says only "Couldn't open input file (-54)".
    """
    found = _files.existing(path)
    _objc._readable(str(found))
    return found


@lru_cache(maxsize=None)
def _core_media() -> ctypes.CDLL:
    media = framework("CoreMedia")
    pointer = ctypes.c_void_p
    signatures = {
        "CMAudioFormatDescriptionGetStreamBasicDescription": ((pointer,), ctypes.POINTER(_StreamDescription)),
        "CMSampleBufferGetDataBuffer": ((pointer,), pointer),
        "CMBlockBufferGetDataLength": ((pointer,), ctypes.c_size_t),
        "CMBlockBufferCopyDataBytes": ((pointer, ctypes.c_size_t, ctypes.c_size_t, pointer), ctypes.c_int32),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(media, name)
        function.argtypes = argtypes
        function.restype = restype
    return media


def info(path: PathLike) -> AudioInfo:
    """Return the duration, sample rate, channels, codec and bitrate of an audio (or video) file's sound."""
    source = _existing(path)
    framework("AVFoundation")
    media = _core_media()
    with _objc.autorelease_pool():
        asset = _media.asset(source)  # "not a video or sound": an audio file isn't a video
        tracks = _media.tracks(asset, "soun")
        if not tracks:
            raise ValueError("{} has no sound".format(source))
        formats = list(_objc.nsarray(_objc.send(tracks[0], "formatDescriptions")))
        description = media.CMAudioFormatDescriptionGetStreamBasicDescription(formats[0]) if formats else None
        if not description:
            raise MacOSError("could not read the sound's format in {}".format(source))
        stream = description.contents
        rate = float(_objc.send(tracks[0], "estimatedDataRate", restype=ctypes.c_float))
        code = struct.pack(">I", stream.format_id).decode("latin-1")
        return AudioInfo(
            duration=round(_media.seconds(_objc.send(tracks[0], "timeRange", restype=_media.CMTimeRange).duration), 3),
            sample_rate=int(round(stream.sample_rate)),
            channels=int(stream.channels),
            codec=_CODECS.get(code, code.strip()),
            bitrate=int(round(rate / 1000)) if rate > 0 else None,
        )


def _encoding(target: Path, quality: str, lossless: bool) -> List[str]:
    """afconvert's options to write ``target``'s format."""
    extension = target.suffix.lower()
    if extension not in _WRITE:
        raise ValueError("can't write {!r} audio; use one of {}".format(target.suffix, ", ".join(sorted(_WRITE))))
    if quality not in _QUALITY:
        raise ValueError("quality must be 'high', 'medium' or 'low', not {!r}".format(quality))
    if extension == ".m4a":
        if lossless:
            return ["-f", "m4af", "-d", "alac"]
        return ["-f", "m4af", "-d", "aac", "-s", "3", "-ue", "vbrq", str(_QUALITY[quality])]
    if lossless:
        raise ValueError("lossless=True is for .m4a files (Apple Lossless); {} is lossless already".format(extension))
    return {
        ".wav": ["-f", "WAVE", "-d", "LEI16"],
        ".aiff": ["-f", "AIFF", "-d", "BEI16"],
        ".aif": ["-f", "AIFF", "-d", "BEI16"],
        ".caf": ["-f", "caff", "-d", "LEI16"],
    }[extension]


def _afconvert(source: Path, target: Path, options: List[str]) -> Path:
    """Convert with afconvert through a temporary file next to ``target``, so the source may be the target."""
    return _files.write_atomically(target, lambda name: _run(["afconvert", *options, str(source), name]))


def convert(source: PathLike, output: PathLike, *, quality: str = "high", lossless: bool = False) -> Path:
    """
    Convert an audio file to the format of ``output``'s extension, and return ``output``.

    Writes ``.m4a`` (AAC, or Apple Lossless with ``lossless=True``), ``.wav``,
    ``.aiff`` and ``.caf`` (16-bit PCM); reads anything macOS plays, MP3 and the sound of
    videos included. ``quality`` (``"high"``, ``"medium"`` or ``"low"``)
    sets the AAC quality: lower is smaller::

        macos.audio.convert("podcast.wav", "podcast.m4a", quality="medium")
        macos.audio.convert("song.mp3", "song.m4a", lossless=True)
    """
    original = _existing(source)
    target = Path(output).expanduser().absolute()
    return _afconvert(original, target, _encoding(target, quality, lossless))


# Editing: decode to 16-bit PCM, change the samples, encode to the output's format. The samples go
# through a WAV file on each side, read and written a piece at a time (trim, concat, fade, gain, reverse),
# so a long recording isn't held in memory whole, let alone several times over.

_CHUNK_FRAMES = 1 << 16  # frames edited at a time: 256 KiB of 16-bit stereo
_WAVE_PCM, _WAVE_EXTENSIBLE = 1, 0xFFFE  # WAVE_FORMAT_PCM, WAVE_FORMAT_EXTENSIBLE: the integer samples asked for


def _wav_layout(stream: io.BufferedIOBase) -> Tuple[int, int, int, int]:
    """``(channels, sample rate, where the samples start, their size in bytes)`` of a 16-bit WAV file."""
    stream.seek(0, os.SEEK_END)
    end = stream.tell()
    stream.seek(0)
    head = stream.read(12)
    if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise MacOSError("afconvert didn't write a WAV file")
    channels = rate = 0
    start = size = 0
    offset = 12
    while offset + 8 <= end:
        stream.seek(offset)
        header = stream.read(8)
        kind, length = header[:4], struct.unpack("<I", header[4:8])[0]
        if kind == b"fmt ":
            fields = stream.read(16)
            if length < 16 or len(fields) < 16:
                raise MacOSError("afconvert wrote a WAV file whose format is cut short")
            tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", fields)
            if tag not in (_WAVE_PCM, _WAVE_EXTENSIBLE) or bits != 16:
                raise MacOSError("afconvert wrote a WAV file of another kind than 16-bit PCM")
        elif kind == b"data":
            start, size = offset + 8, min(length, end - offset - 8)
        offset += 8 + length + (length & 1)  # chunks are padded to an even size
    if not channels or not rate:
        raise MacOSError("afconvert wrote a WAV file without a format")
    return channels, rate, start, size - size % 2


def _read_wav(data: bytes) -> Tuple[int, int, bytes]:
    """``(channels, sample rate, sample bytes)`` of a 16-bit WAV file, the extensible variant included."""
    channels, rate, start, size = _wav_layout(io.BytesIO(data))
    return channels, rate, data[start : start + size]


class _Samples:
    """The 16-bit samples of a WAV file, read a piece at a time, in frames (one sample per channel)."""

    def __init__(self, stream: io.BufferedIOBase) -> None:
        self.stream = stream
        self.channels, self.rate, self.start, size = _wav_layout(stream)
        self.frames = size // (2 * self.channels)
        self.seek(0)

    def seek(self, frame: int) -> None:
        self.position = max(0, min(frame, self.frames))
        self.stream.seek(self.start + self.position * 2 * self.channels)

    def read(self, frames: int) -> "array.array[int]":
        """The next ``frames`` frames (fewer at the end), read straight into the array: no copy in between."""
        # Never past the data chunk: other chunks (LIST metadata...) may follow it, and aren't sound.
        frames = max(0, min(frames, self.frames - self.position))
        samples = array.array("h", [0]) * (frames * self.channels)
        count = (self.stream.readinto(memoryview(samples).cast("B")) or 0) // 2 if frames else 0
        del samples[count - count % self.channels :]  # whole frames only
        self.position += len(samples) // self.channels
        if sys.byteorder == "big":
            samples.byteswap()  # WAV is little-endian
        return samples


@contextmanager
def _decoded(path: Path, rate: Optional[int] = None, channels: Optional[int] = None) -> Iterator[_Samples]:
    """The samples of an audio file, decoded by afconvert (optionally resampled and remixed), to read."""
    with tempfile.TemporaryDirectory() as folder:
        decoded = Path(folder) / "decoded.wav"
        options = ["-f", "WAVE", "-d", "LEI16" + ("@{}".format(rate) if rate else "")]
        if channels:
            options += ["-c", str(channels)]
        _run(["afconvert", *options, str(path), str(decoded)])
        with open(str(decoded), "rb") as stream:
            yield _Samples(stream)


@contextmanager
def _encoding_to(
    output: PathLike, channels: int, rate: int, quality: str, lossless: bool
) -> Iterator[Callable[["array.array[int]"], None]]:
    """
    A function to write samples with, a piece at a time; at the end, they're encoded into ``output``.

    Through a WAV file, which afconvert then turns into ``output``'s format.
    """
    target = Path(output).expanduser().absolute()
    options = _encoding(target, quality, lossless)
    with tempfile.TemporaryDirectory() as folder:
        plain = Path(folder) / "edited.wav"
        with wave.open(str(plain), "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(2)
            writer.setframerate(rate)

            def write(samples: "array.array[int]") -> None:
                if sys.byteorder == "big":
                    samples = array.array("h", samples)
                    samples.byteswap()  # WAV is little-endian
                writer.writeframesraw(samples)  # its bytes, as they are: no copy

            yield write
        _afconvert(plain, target, options)


def _clip(value: float) -> int:
    return -32768 if value < -32768 else 32767 if value > 32767 else int(value)


def trim(
    source: PathLike,
    output: PathLike,
    start: float = 0.0,
    duration: Optional[float] = None,
    *,
    quality: str = "high",
    lossless: bool = False,
) -> Path:
    """
    Keep ``duration`` seconds of an audio file from ``start`` (to the end by default), and return ``output``.

    ``output``'s extension sets the format, and ``quality`` and ``lossless``
    work as in :func:`convert`::

        macos.audio.trim("interview.m4a", "answer.m4a", start=95, duration=30)
    """
    if not (math.isfinite(start) and start >= 0) or (duration is not None and not _positive(duration)):
        raise ValueError("start must not be negative and duration must be positive")
    _encoding(Path(output).expanduser().absolute(), quality, lossless)  # check the output before the work
    with _decoded(_existing(source)) as samples:
        first = int(start * samples.rate)
        if first >= samples.frames:
            raise ValueError("start={} is past the end of the audio".format(start))
        last = samples.frames if duration is None else min(samples.frames, first + int(duration * samples.rate))
        with _encoding_to(output, samples.channels, samples.rate, quality, lossless) as write:
            # Only the part kept is read, a piece at a time.
            samples.seek(first)
            for at in range(first, last, _CHUNK_FRAMES):
                write(samples.read(min(_CHUNK_FRAMES, last - at)))
    return Path(output).expanduser().absolute()


def concat(
    files: Sequence[PathLike], output: PathLike, *, quality: str = "high", lossless: bool = False
) -> Path:
    """
    Join audio files one after another into ``output``, and return it.

    The files may differ in format, sample rate and channels: they're all
    converted to the first one's. ``quality`` and ``lossless`` work as in
    :func:`convert`::

        macos.audio.concat(["intro.m4a", "episode.wav", "outro.m4a"], "podcast.m4a")
    """
    if not files:
        raise ValueError("concat() needs at least one file")
    _encoding(Path(output).expanduser().absolute(), quality, lossless)  # check the output before the work
    paths = [_existing(path) for path in files]
    with _decoded(paths[0]) as first:
        channels, rate = first.channels, first.rate
        with _encoding_to(output, channels, rate, quality, lossless) as write:
            # File after file, a piece at a time: only one file's samples are decoded at once, on disk.
            _copy_samples(first, write)
            for path in paths[1:]:
                with _decoded(path, rate, channels) as samples:
                    _copy_samples(samples, write)
    return Path(output).expanduser().absolute()


def _copy_samples(samples: _Samples, write: Callable[["array.array[int]"], None]) -> None:
    """Write every frame of ``samples``, from where it is, a piece at a time."""
    while samples.position < samples.frames:
        write(samples.read(_CHUNK_FRAMES))


def fade(
    source: PathLike,
    output: PathLike,
    *,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    quality: str = "high",
    lossless: bool = False,
) -> Path:
    """
    Raise the volume from silence over ``fade_in`` seconds and lower it to silence over the last ``fade_out``.

    Returns ``output``. ``quality`` and ``lossless`` work as in :func:`convert`::

        macos.audio.fade("song.m4a", "song-faded.m4a", fade_in=2, fade_out=5)
    """
    if not all(math.isfinite(length) and length >= 0 for length in (fade_in, fade_out)):
        raise ValueError("fade_in and fade_out must not be negative")
    _encoding(Path(output).expanduser().absolute(), quality, lossless)  # check the output before the work
    with _decoded(_existing(source)) as samples:
        channels, frames = samples.channels, samples.frames
        rising, falling = min(frames, int(fade_in * samples.rate)), min(frames, int(fade_out * samples.rate))
        with _encoding_to(output, channels, samples.rate, quality, lossless) as write:
            # A piece at a time, as gain() does: only the frames inside a fade are touched.
            for first in range(0, frames, _CHUNK_FRAMES):
                chunk = samples.read(_CHUNK_FRAMES)
                end = first + len(chunk) // channels
                fades = (
                    (range(first, min(end, rising)), lambda frame: frame / rising),
                    (range(max(first, frames - falling), end), lambda frame: (frames - 1 - frame) / falling),
                )
                for span, factor_at in fades:
                    for frame in span:
                        factor = factor_at(frame)
                        for index in range((frame - first) * channels, (frame - first + 1) * channels):
                            chunk[index] = int(chunk[index] * factor)
                write(chunk)
    return Path(output).expanduser().absolute()


def _gain_table(factor: float) -> List[int]:
    """
    What each 16-bit sample becomes, ``factor`` times louder and clipped, indexed by the sample itself.

    The negative samples come last, so that ``table[sample]`` finds them as
    Python indexes a list from its end: -1 is the last entry.
    """
    return [_clip(value * factor) for value in range(32768)] + [_clip(value * factor) for value in range(-32768, 0)]


def gain(
    source: PathLike, output: PathLike, decibels: float, *, quality: str = "high", lossless: bool = False
) -> Path:
    """
    Make an audio file louder (positive ``decibels``) or quieter (negative), and return ``output``.

    +6 dB is about twice as loud, -6 dB half. Loud parts pushed past the
    maximum are clipped. ``quality`` and ``lossless`` work as in :func:`convert`.
    """
    if not math.isfinite(decibels):
        raise ValueError("decibels must be a finite number, not {}".format(decibels))
    _encoding(Path(output).expanduser().absolute(), quality, lossless)  # check the output before the work
    # 65536 possible samples: work each one out once, then look them up, which runs in C, chunk by chunk.
    # Past +200 dB (ten billion times louder) every sample but silence clips just the same, and the
    # factor of a few thousand decibels would overflow a float.
    table = _gain_table(10 ** (min(decibels, 200.0) / 20))
    with _decoded(_existing(source)) as samples:
        with _encoding_to(output, samples.channels, samples.rate, quality, lossless) as write:
            for _ in range(0, samples.frames, _CHUNK_FRAMES):
                write(array.array("h", map(table.__getitem__, samples.read(_CHUNK_FRAMES))))
    return Path(output).expanduser().absolute()


def reverse(source: PathLike, output: PathLike, *, quality: str = "high", lossless: bool = False) -> Path:
    """
    Save an audio file played backwards to ``output``, and return it.

    ``quality`` and ``lossless`` work as in :func:`convert`.
    """
    _encoding(Path(output).expanduser().absolute(), quality, lossless)  # check the output before the work
    with _decoded(_existing(source)) as samples:
        channels = samples.channels
        with _encoding_to(output, channels, samples.rate, quality, lossless) as write:
            # From the end, a piece at a time: each piece's frames reversed, keeping each frame's channels in order.
            for end in range(samples.frames, 0, -_CHUNK_FRAMES):
                samples.seek(max(0, end - _CHUNK_FRAMES))
                piece = samples.read(end - samples.position)
                backwards = array.array("h", piece)
                for channel in range(channels):
                    backwards[channel::channels] = piece[channel::channels][::-1]
                write(backwards)
    return Path(output).expanduser().absolute()


def speed(
    source: PathLike,
    output: PathLike,
    factor: float,
    *,
    keep_pitch: bool = True,
    quality: str = "high",
    lossless: bool = False,
) -> Path:
    """
    Play an audio file ``factor`` times faster (1.5) or slower (0.75), and return ``output``.

    By default the pitch stays the same, to listen to a lecture or a podcast
    faster without the chipmunk voices; ``keep_pitch=False`` changes it with
    the speed, like a record played faster. ``quality`` and ``lossless`` work
    as in :func:`convert`::

        macos.audio.speed("lecture.m4a", "lecture-fast.m4a", 1.5)
    """
    if not _positive(factor):
        raise ValueError("factor must be positive, not {}".format(factor))
    target = Path(output).expanduser().absolute()
    _encoding(target, quality, lossless)  # check the output before the work
    original = _existing(source)
    details = info(original)
    channels = 1 if details.channels == 1 else 2
    with tempfile.TemporaryDirectory() as folder, _encoding_to(
        target, channels, details.sample_rate, quality, lossless
    ) as write, _objc.autorelease_pool():
        edited = _media.editable(_media.asset(original), keep_state=False)  # re-encoded: every track in the mix
        length = _media.duration(edited)
        # A second of silence after the sound, in each of its tracks, stretched along with it: the
        # time-pitch algorithm holds back the last stretch before the end of what it stretches, which
        # cut up to a tenth of a second off a clip under about 3 s. It's the silence that's held back now.
        quiet = Path(folder) / "quiet.wav"
        with wave.open(str(quiet), "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(2)
            writer.setframerate(details.sample_rate)
            writer.writeframes(bytes(2 * channels * details.sample_rate))
        silence = _media.asset(quiet, "sound")
        quiet_track = _media.tracks(silence, "soun")[0]
        end = _objc.send(edited, "duration", restype=_media.CMTime)  # the exact end, not one rounded to 1/600 s
        for track in _media.tracks(edited, "soun"):
            error = ctypes.c_void_p()
            if not _objc.send(
                track,
                "insertTimeRange:ofTrack:atTime:error:",
                _objc.send(quiet_track, "timeRange", restype=_media.CMTimeRange),
                quiet_track,
                end,
                ctypes.byref(error),
                argtypes=(_media.CMTimeRange, _objc.id, _media.CMTime, ctypes.c_void_p),
                restype=_objc.BOOL,
            ):
                raise MacOSError("could not edit the sound: {}".format(_objc.error_message(error)))
        # The composition's own duration, not one rounded to 1/600 s: that would cut the last samples.
        padded = _objc.send(edited, "duration", restype=_media.CMTime)
        _objc.send(
            edited,
            "scaleTimeRange:toDuration:",
            _media.CMTimeRange(_media.time(0), padded),
            _stretched(padded, factor, details.sample_rate, sound=length),
            argtypes=(_media.CMTimeRange, _media.CMTime),
            restype=None,
        )
        # Read back as plain samples, stretched on the way, straight into the file to encode: nothing is
        # compressed until the output, once, in its own format. The exact length, too: no codec pads it,
        # and the silence after the sound isn't read.
        _read_samples(
            edited,
            write,
            rate=details.sample_rate,
            channels=channels,
            length=length / factor,
            time_pitch="Spectral" if keep_pitch else "Varispeed",
        )
    return target


def _stretched(length: "_media.CMTime", factor: float, rate: int, *, sound: float) -> "_media.CMTime":
    """
    ``length`` played ``factor`` times faster, to the sample at ``rate``: the speed() target duration.

    ``sound`` is how long the sound itself lasts, in seconds, without the silence after it.
    """
    # At least one tick per sample: a coarser timescale would round the end off, or past it.
    scale = max(1, -(-rate // length.timescale)) if length.timescale > 0 else 1
    ticks = length.value * scale / factor
    if not math.isfinite(ticks) or ticks >= 2**63:
        raise ValueError("factor {} is too small: the sound would last too long".format(factor))
    # The frames written are the sound's own, not the silence's: none of them left is an empty file.
    if round(ticks) <= 0 or round(sound / factor * rate) <= 0:
        raise ValueError("factor {} is too large: nothing of the sound would be left".format(factor))
    return _media.CMTime(round(ticks), length.timescale * scale, length.flags, length.epoch)


_READING, _READ, _READ_FAILED = 1, 2, 3  # AVAssetReaderStatus


def _read_samples(
    media: int,
    write: Callable[["array.array[int]"], None],
    *,
    rate: int,
    channels: int,
    length: float,
    time_pitch: str,
) -> None:
    """
    Decode the sound of an asset or a composition, its tracks mixed, as 16-bit samples given to ``write``.

    Its first ``length`` seconds, a buffer at a time, with ``time_pitch``
    (``"Spectral"``, ``"Varispeed"``) for the parts it plays faster or slower.
    Exactly that long: frames the reader holds back at the end come as silence.
    """
    framework("AVFoundation")
    error = ctypes.c_void_p()
    reader = _objc.send(
        _objc.send(_objc.cls("AVAssetReader"), "alloc"),
        "initWithAsset:error:",
        media,
        ctypes.byref(error),
        argtypes=(_objc.id, ctypes.c_void_p),
    )
    if not reader:
        raise MacOSError("could not read the sound: {}".format(_objc.error_message(error)))
    _objc.send(reader, "autorelease")
    settings = {
        "AVFormatIDKey": _code("lpcm"),
        "AVSampleRateKey": rate,
        "AVNumberOfChannelsKey": channels,
        "AVLinearPCMBitDepthKey": 16,
        "AVLinearPCMIsFloatKey": 0,
        "AVLinearPCMIsNonInterleaved": 0,
        "AVLinearPCMIsBigEndianKey": 1 if sys.byteorder == "big" else 0,  # this Mac's own order, as write() takes
    }
    dictionary = _objc.nsdictionary_of({key: _objc.nsnumber(value) for key, value in settings.items()})
    output = _objc.send(
        _objc.cls("AVAssetReaderAudioMixOutput"),
        "assetReaderAudioMixOutputWithAudioTracks:audioSettings:",
        _objc.nsarray_of(_media.tracks(media, "soun")),
        dictionary,
        argtypes=(_objc.id, _objc.id),
    )
    if not output or not _objc.send(reader, "canAddOutput:", output, argtypes=(_objc.id,), restype=_objc.BOOL):
        raise MacOSError("could not read the sound as samples")
    _objc.send(output, "setAudioTimePitchAlgorithm:", _objc.nsstring(time_pitch), argtypes=(_objc.id,), restype=None)
    _objc.send(reader, "addOutput:", output, argtypes=(_objc.id,), restype=None)
    # No time range: the reader would end the time-pitch algorithm there, before it gives the last stretch
    # out. Reading stops after ``length`` seconds below instead.
    if not _objc.send(reader, "startReading", restype=_objc.BOOL):
        failure = _objc.send(reader, "error")
        message = _objc.pystring(_objc.send(failure, "localizedDescription")) if failure else None
        raise MacOSError("could not read the sound: {}".format(message or "unknown error"))
    media_library = _core_media()
    remaining = int(round(length * rate))  # frames
    frame_size = 2 * channels
    while remaining > 0:
        with _objc.autorelease_pool():
            buffer = _objc.send(output, "copyNextSampleBuffer", restype=ctypes.c_void_p)
            if not buffer:
                break
            with _cf.owned(buffer):
                block = media_library.CMSampleBufferGetDataBuffer(buffer)
                frames = min(media_library.CMBlockBufferGetDataLength(block) // frame_size, remaining) if block else 0
                if not frames:
                    continue
                samples = array.array("h", [0]) * (frames * channels)
                address, _ = samples.buffer_info()
                if media_library.CMBlockBufferCopyDataBytes(block, 0, frames * frame_size, address) != 0:
                    raise MacOSError("could not read the sound's samples")
        write(samples)
        remaining -= frames
    status = _objc.send(reader, "status", restype=_objc.NSInteger)
    if status == _READ_FAILED:
        failure = _objc.send(reader, "error")
        message = _objc.pystring(_objc.send(failure, "localizedDescription")) if failure else None
        raise MacOSError("could not read the sound: {}".format(message or "unknown error"))
    if status == _READING:
        _objc.send(reader, "cancelReading", restype=None)  # what's left isn't wanted
    elif remaining > 0:
        write(array.array("h", [0]) * (remaining * channels))  # ended a little early: the length, as asked


# Sound classification, through SoundAnalysis.

_Produced = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_Failed = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_Completed = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_heard: dict = {}  # observer -> {"labels": {label: [confidence...]}, "error": ..., "analyzer": ...}


def _on_result(observer: int, _cmd: int, request: int, result: int) -> None:
    heard = _heard.setdefault(observer, {"labels": {}})
    if _cf.interrupted():
        # A Ctrl-C came while the analysis ran: stop it, rather than read the rest of the file first.
        analyzer = heard.get("analyzer")
        if analyzer:
            _objc.send(analyzer, "cancelAnalysis", restype=None)
        return
    labels = heard["labels"]
    try:
        for item in _objc.nsarray(_objc.send(result, "classifications")):
            label = _objc.pystring(_objc.send(item, "identifier")) or ""
            confidence = float(_objc.send(item, "confidence", restype=ctypes.c_double))
            labels.setdefault(label, []).append(confidence)
    except Exception as problem:  # an exception must not cross back into Objective-C: classify() raises it
        heard["error"] = "{} while reading a result".format(str(problem) or type(problem).__name__)
        analyzer = heard.get("analyzer")
        if analyzer:
            _objc.send(analyzer, "cancelAnalysis", restype=None)  # rather than read the rest of the file for nothing


def _on_failure(observer: int, _cmd: int, request: int, error: int) -> None:
    try:
        message = _objc.error_message(ctypes.c_void_p(error))
    except Exception as problem:  # an exception must not cross back into Objective-C: classify() raises it
        message = "{} while reading the error".format(str(problem) or type(problem).__name__)
    # The first error stays: cancelling the analysis after a Python error may be reported here too.
    _heard.setdefault(observer, {"labels": {}}).setdefault("error", message)


def _on_complete(observer: int, _cmd: int, request: int) -> None:
    _heard.setdefault(observer, {"labels": {}})["done"] = True


def classify(path: PathLike, *, limit: int = 5, min_confidence: float = 0.1) -> List[Tuple[str, float]]:
    """
    Tell what an audio (or video) file sounds like: ``[('speech', 0.97), ('music', 0.4), ...]``, most likely first.

    Apple's sound classifier knows more than 300 sounds: speech, laughter,
    music and instruments, dogs, birds, cars, sirens, applause, rain... It
    listens to the whole file, a few seconds at a time, and averages what it
    hears; sounds shorter than half a second are too short to tell. Runs
    offline, needs no permission, and needs macOS 12 or later::

        if dict(macos.audio.classify("clip.m4a")).get("dog_bark", 0) > 0.5:
            print("a dog!")

    ``limit`` and ``min_confidence`` work as in :func:`macos.vision.classify`.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1, not {}".format(limit))
    source = _existing(path)
    try:
        identifier = _cf.constant(framework("SoundAnalysis"), "SNClassifierIdentifierVersion1")
    except LookupError:
        raise NotSupportedError("classify() needs macOS 12 or later") from None
    _objc.define_class(
        "PymacosSoundObserver",
        {
            "request:didProduceResult:": ("v@:@@", _Produced, _on_result),
            "request:didFailWithError:": ("v@:@@", _Failed, _on_failure),
            "requestDidComplete:": ("v@:@", _Completed, _on_complete),
        },
        protocols=("SNResultsObserving",),
    )
    with _objc.autorelease_pool():
        error = ctypes.c_void_p()
        request = _objc.send(
            _objc.send(_objc.cls("SNClassifySoundRequest"), "alloc"),
            "initWithClassifierIdentifier:error:",
            identifier,
            ctypes.byref(error),
            argtypes=(_objc.id, ctypes.c_void_p),
        )
        if not request:
            raise MacOSError("the sound classifier isn't available: {}".format(_objc.error_message(error)))
        _objc.send(request, "autorelease")
        # It listens in 3-second windows, and says nothing about a shorter
        # file: use the file's own length then (it accepts 0.5 to 15 s).
        window = min(3.0, max(0.5, info(source).duration))
        _objc.send(request, "setWindowDuration:", _media.time(window), argtypes=(_media.CMTime,), restype=None)
        analyzer = _objc.send(
            _objc.send(_objc.cls("SNAudioFileAnalyzer"), "alloc"),
            "initWithURL:error:",
            _objc.file_url(source),
            ctypes.byref(error),
            argtypes=(_objc.id, ctypes.c_void_p),
        )
        if not analyzer:
            raise ValueError("{} has no sound macOS can read: {}".format(source, _objc.error_message(error, "unknown format")))
        _objc.send(analyzer, "autorelease")
        observer = _objc.new("PymacosSoundObserver")
        if not _objc.send(
            analyzer,
            "addRequest:withObserver:error:",
            request,
            observer,
            ctypes.byref(error),
            argtypes=(_objc.id, _objc.id, ctypes.c_void_p),
            restype=_objc.BOOL,
        ):
            raise MacOSError("could not analyze {}: {}".format(source, _objc.error_message(error)))
        _heard.setdefault(observer, {"labels": {}})["analyzer"] = analyzer  # for a Ctrl-C to cancel it
        try:
            with _cf.deferred_interrupt():  # a Ctrl-C meanwhile: the observer cancels the analysis, then it's raised
                _objc.send(analyzer, "analyze", restype=None)  # synchronous: the observer is called meanwhile
            heard = _heard.get(observer, {"labels": {}})
        finally:
            _heard.pop(observer, None)
    if heard.get("error"):
        raise MacOSError("could not analyze {}: {}".format(source, heard["error"]))
    windows = max((len(values) for values in heard["labels"].values()), default=0)
    averages = [(label, sum(values) / windows) for label, values in heard["labels"].items()] if windows else []
    ranked = sorted(((label, round(score, 3)) for label, score in averages if score >= min_confidence), key=lambda pair: -pair[1])
    return ranked[:limit]


def record_until_silence(
    path: PathLike,
    max_seconds: float = 60.0,
    *,
    silence: float = 1.5,
    threshold: float = 0.02,
    channels: int = 1,
) -> Path:
    """
    Record the microphone until the speaker stops talking, and return ``path``.

    It waits for sound (a level above ``threshold``, see :func:`input_level`),
    then stops after ``silence`` seconds of quiet, or after ``max_seconds``
    in any case. Made for voice notes and spoken commands::

        memo = macos.audio.record_until_silence("note.m4a")

    ``path`` and ``channels`` work as in :func:`record`. Needs the
    Microphone permission.
    """
    # max_seconds may be math.inf: no limit, only the silence ends it.
    if not (max_seconds > 0 and _positive(silence)):
        raise ValueError("max_seconds and silence must be positive")
    if not 0 < threshold < 1:
        raise ValueError("threshold must be between 0 and 1, not {}".format(threshold))
    if channels not in (1, 2):
        raise ValueError("channels must be 1 or 2, not {}".format(channels))
    target = Path(path).expanduser().absolute()
    if target.suffix.lower() not in _RECORD_FORMATS:
        raise ValueError(
            "can't record {!r} files; use one of {}".format(target.suffix, ", ".join(sorted(_RECORD_FORMATS)))
        )
    _capture.require_permission(_capture.AUDIO)
    # Beside the target, moved over it once saved, as in record().
    with _files.replacing(target) as temporary, _objc.autorelease_pool():
        recorder = _recorder(temporary, channels, metering=True)
        if not _objc.send(recorder, "record", restype=_objc.BOOL):
            raise MacOSError("the microphone could not start recording")
        interrupted: List[BaseException] = []
        heard = 0.0
        try:
            started = time.monotonic()
            heard_at: Optional[float] = None
            while True:
                time.sleep(0.05)
                now = time.monotonic()
                _objc.send(recorder, "updateMeters", restype=None)
                power = _objc.send(
                    recorder, "averagePowerForChannel:", 0, argtypes=(_objc.NSUInteger,), restype=ctypes.c_float
                )
                if 10 ** (float(power) / 20) > threshold:
                    heard_at = now
                if now - started >= max_seconds:
                    break
                if heard_at is not None and now - heard_at >= silence:
                    break
        except KeyboardInterrupt as error:
            interrupted.append(error)  # stopped on purpose, as in record(): what was recorded is kept
        finally:
            heard = _recorded_seconds(recorder)  # before stop(), which resets it
            _objc.send(recorder, "stop", restype=None)
        if not temporary.exists() or heard <= 0:  # no sound recorded, as in record()
            if interrupted:
                raise interrupted[0]  # stopped before anything was saved: the Ctrl-C, not a failure of ours
            raise MacOSError("the recording wasn't saved")
    if interrupted:
        raise interrupted[0]
    return target
