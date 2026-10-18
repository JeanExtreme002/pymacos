"""Unit tests for :mod:`macos._media`. They run on any platform."""

import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import macos
from macos import _media


@pytest.fixture
def objc(monkeypatch):
    """Fakes the Objective-C bridge: ``answers`` maps a selector to what it returns (a callable gets the receiver)."""
    answers = {}
    sent = []

    def send(receiver, selector, *args, **kwargs):
        sent.append((receiver, selector) + args)
        answer = answers.get(selector)
        return answer(receiver, *args) if callable(answer) else answer

    monkeypatch.setattr(_media, "load", lambda: None)
    monkeypatch.setattr(_media._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(_media._objc, "send", send)
    monkeypatch.setattr(_media._objc, "cls", lambda name: 0)
    monkeypatch.setattr(_media._objc, "nsstring", lambda text: text)
    monkeypatch.setattr(_media._objc, "file_url", lambda path: 3)
    monkeypatch.setattr(_media._objc, "nsarray", lambda items: iter(items or []))
    return SimpleNamespace(answers=answers, sent=sent)


def test_time_rejects_what_it_cant_hold():
    """NaN and infinity named the argument nowhere, and a value past 64 bits wrapped around silently."""
    for bad in (float("nan"), float("inf"), -float("inf"), 1e17, -1e17):
        with pytest.raises(ValueError, match="finite number of seconds"):
            _media.time(bad)
    assert (_media.time(0).value, _media.time(0).timescale) == (0, 600)
    assert _media.time(1e9).value == 600 * 10**9  # a long time is fine: the limit is half a billion years


def test_an_unreadable_file_is_a_permission_error(objc, tmp_path):
    """A file that can't be opened isn't said to be in a format macOS can't play."""
    objc.answers.update({"URLAssetWithURL:options:": 1, "isPlayable": False})
    locked = tmp_path / "song.wav"
    locked.write_bytes(b"RIFF")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("this user reads any file (root)")
        with pytest.raises(PermissionError) as raised:
            _media.asset(locked)
        # Python's own, as image and pdf raise: PermissionDeniedError is for a privacy permission.
        assert not isinstance(raised.value, macos.MacOSError)
    finally:
        locked.chmod(0o600)
    # One that opens but isn't media, or a folder, is still a ValueError.
    with pytest.raises(ValueError, match="not a video or sound"):
        _media.asset(locked)
    with pytest.raises(ValueError, match="not a video or sound"):
        _media.asset(tmp_path)


def _flags(sent, track):
    return [entry[1:] for entry in sent if entry[0] == track and entry[1].startswith("set")]


def test_editing_keeps_every_tracks_language_group_and_state(objc):
    """insertTimeRange:ofAsset: makes every track on, in no language: a dubbed film would play both sounds."""
    media, edited = 1, 2
    kinds = {}
    spanish, english, copy_spanish, copy_english, segment_spanish, segment_english = 11, 12, 21, 22, 31, 32
    exact = _media.CMTime(44130, 44100, 1, 0)  # not a whole number of 1/600 s
    kinds.update({(media, "soun"): [spanish, english], (edited, "soun"): [copy_english, copy_spanish]})
    objc.answers.update(
        {
            "composition": edited,
            "insertTimeRange:ofAsset:atTime:error:": True,
            "duration": exact,
            "tracksWithMediaType:": lambda receiver, kind: kinds.get((receiver, kind), []),
            "trackID": lambda track, *args: track,
            "segments": lambda copy, *args: {copy_spanish: [segment_spanish], copy_english: [segment_english]}[copy],
            "isEmpty": False,
            "sourceTrackID": lambda segment, *args: {segment_spanish: spanish, segment_english: english}[segment],
            "isEnabled": lambda track, *args: track == spanish,
            "alternateGroupID": 1,
            "extendedLanguageTag": lambda track, *args: {spanish: "es", english: None}[track],
            "languageCode": lambda track, *args: {spanish: "spa", english: "eng"}[track],
            "canonicalLanguageIdentifierFromString:": lambda locale, code: {"eng": "en"}[code],
        }
    )
    assert _media.editable(media) == edited
    # Matched by the segment, not by the order: the tag when there's one, the tag of the old three-letter code otherwise.
    assert _flags(objc.sent, copy_spanish) == [
        ("setEnabled:", True),
        ("setAlternateGroupID:", 1),
        ("setExtendedLanguageTag:", "es"),
    ]
    assert _flags(objc.sent, copy_english) == [
        ("setEnabled:", False),
        ("setAlternateGroupID:", 1),
        ("setExtendedLanguageTag:", "en"),
    ]
    # The asset's own length is inserted, not one rounded to 1/600 s that drops its last samples.
    inserted = next(entry for entry in objc.sent if entry[1] == "insertTimeRange:ofAsset:atTime:error:")[2]
    assert (inserted.duration.value, inserted.duration.timescale) == (44130, 44100)


def test_editing_media_of_no_known_length_fails(objc):
    objc.answers["duration"] = _media.CMTime(0, 0, 0, 0)  # flags without kCMTimeFlags_Valid
    objc.answers["insertTimeRange:ofAsset:atTime:error:"] = lambda *args: pytest.fail("inserted media of no known length")
    with pytest.raises(macos.MacOSError, match="could not read the media: it has no known length"):
        _media.editable(1)


def test_a_copied_track_keeps_its_language_group_and_state(objc, monkeypatch):
    track, copy = 11, 21
    span = _media.time_range(0, 2)
    monkeypatch.setattr(_media, "_core_media", lambda: SimpleNamespace(CMTimeRangeGetIntersection=lambda a, b: span))
    objc.answers.update(
        {
            "addMutableTrackWithMediaType:preferredTrackID:": copy,
            "insertTimeRange:ofTrack:atTime:error:": True,
            "isEnabled": False,
            "alternateGroupID": 3,
            "extendedLanguageTag": "fr-CA",
        }
    )
    assert _media.copy_track(5, track, "soun", 2) == copy
    assert _flags(objc.sent, copy) == [("setEnabled:", False), ("setAlternateGroupID:", 3), ("setExtendedLanguageTag:", "fr-CA")]


def test_a_copy_of_an_old_track_never_keeps_its_three_letter_code(objc, monkeypatch):
    """A code ("eng") left on the copy would outlive the tag add_language_track relabels it with ("es")."""
    track, copy = 11, 21
    span = _media.time_range(0, 2)
    monkeypatch.setattr(_media, "_core_media", lambda: SimpleNamespace(CMTimeRangeGetIntersection=lambda a, b: span))
    objc.answers.update(
        {
            "addMutableTrackWithMediaType:preferredTrackID:": copy,
            "insertTimeRange:ofTrack:atTime:error:": True,
            "isEnabled": True,
            "alternateGroupID": 0,
            "extendedLanguageTag": None,
            "languageCode": "eng",
            "canonicalLanguageIdentifierFromString:": lambda locale, code: {"eng": "en"}[code],
        }
    )
    _media.copy_track(5, track, "soun", 2)
    assert ("setLanguageCode:", "eng") not in _flags(objc.sent, copy)
    assert _flags(objc.sent, copy)[-1] == ("setExtendedLanguageTag:", "en")


def test_export_keeps_the_sources_metadata(objc, monkeypatch, tmp_path):
    """A composition has no metadata: the date and place a video was shot come from the asset it was made of."""
    objc.answers.update(
        {"exportSessionWithAsset:presetName:": 7, "metadata": lambda asset, *args: "metadata of {}".format(asset), "status": 3}
    )
    written = []
    monkeypatch.setattr(_media._objc, "file_url", written.append)
    monkeypatch.setattr(_media._objc, "run_until", lambda done, timeout: written[-1].write_bytes(b"movie") > 0)
    monkeypatch.setattr(_media, "ignore_completion", lambda: 4)
    _media.export(5, tmp_path / "out.mov", source=9)
    assert (7, "setMetadata:", "metadata of 9") in objc.sent
    objc.sent.clear()
    _media.export(5, tmp_path / "out.mov")
    assert not [entry for entry in objc.sent if entry[1] == "setMetadata:"]


def test_editing_for_a_re_encode_leaves_every_track_on(objc):
    """The re-encoding exporter leaves a track that's off out: speed() and crop() dropped a video's second language."""
    media, edited, french, copy_french, segment = 1, 2, 11, 21, 31
    kinds = {(media, "soun"): [french], (edited, "soun"): [copy_french]}
    objc.answers.update(
        {
            "composition": edited,
            "insertTimeRange:ofAsset:atTime:error:": True,
            "duration": _media.time(2),
            "tracksWithMediaType:": lambda receiver, kind: kinds.get((receiver, kind), []),
            "trackID": lambda track, *args: track,
            "segments": [segment],
            "isEmpty": False,
            "sourceTrackID": french,
            "isEnabled": False,
            "alternateGroupID": 1,
            "extendedLanguageTag": "fr",
        }
    )
    assert _media.editable(media, keep_state=False) == edited
    assert _flags(objc.sent, copy_french) == [("setExtendedLanguageTag:", "fr")]  # the language only
    objc.sent.clear()
    _media.editable(media)
    assert _flags(objc.sent, copy_french)[:2] == [("setEnabled:", False), ("setAlternateGroupID:", 1)]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
def test_a_fifo_is_not_media_and_doesnt_wait_for_a_writer(objc, tmp_path):
    """AVFoundation's isPlayable, and open(), wait on a FIFO for a writer: it must be refused before either."""
    import threading

    objc.answers["URLAssetWithURL:options:"] = lambda *args: pytest.fail("AVFoundation was asked about a FIFO")
    fifo = tmp_path / "pipe"
    os.mkfifo(str(fifo))
    raised = []

    def read():
        try:
            _media.asset(fifo)
        except ValueError as error:
            raised.append(error)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(5)
    if reader.is_alive():
        os.close(os.open(str(fifo), os.O_WRONLY | os.O_NONBLOCK))  # let the stuck open() return
        reader.join(5)
        pytest.fail("asset() waited on the FIFO for a writer")
    assert raised and "not a video or sound" in str(raised[0])
    with pytest.raises(ValueError, match="not a sound"):
        _media.source(fifo, "sound")  # what audio and video check their sources with, before afconvert or avconvert


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_source_checks_a_file_before_a_tool_reads_it(tmp_path):
    with pytest.raises(FileNotFoundError):
        _media.source(tmp_path / "missing.mov")
    with pytest.raises(ValueError, match="not a video"):
        _media.source(tmp_path, "video")  # a folder isn't media
    locked = tmp_path / "clip.mov"
    locked.write_bytes(b"moov")
    locked.chmod(0)
    try:
        with pytest.raises(PermissionError):
            _media.source(locked, "video")
    finally:
        locked.chmod(0o600)
    assert _media.source(locked, "video") == locked
