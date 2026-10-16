"""Unit tests for :mod:`macos.vision`. They run on any platform."""

import sys
import warnings

import pytest

import macos


def test_best_shot_picks_the_best_faces(monkeypatch):
    scores = {"blurry.jpg": 0.2, "none.jpg": None, "sharp.jpg": 0.7, "also-sharp.jpg": 0.7}
    monkeypatch.setattr(macos.vision, "_load", lambda: None)
    monkeypatch.setattr(macos.vision, "_face_quality", lambda image: scores[image])

    assert macos.vision.best_shot(["blurry.jpg", "none.jpg", "sharp.jpg", "also-sharp.jpg"]) == "sharp.jpg"
    assert macos.vision.best_shot(["none.jpg"]) is None
    with pytest.raises(ValueError):
        macos.vision.best_shot([])


def test_duplicates_groups_through_chains_in_the_given_order(monkeypatch):
    # Feature prints are stood in by numbers; their distance is the difference.
    monkeypatch.setattr(macos.vision, "_load", lambda: None)
    monkeypatch.setattr(macos.vision, "_feature_print", lambda image: image)
    monkeypatch.setattr(macos.vision, "_distance", lambda first, second: abs(first - second))
    monkeypatch.setattr(macos.vision._objc, "send", lambda *args, **kwargs: None)

    # 1.0 ~ 1.2 ~ 1.4 chain into one group, though 1.0 and 1.4 are far apart.
    groups = macos.vision.duplicates([5.0, 1.0, 9.0, 1.2, 5.1, 1.4], threshold=0.3)

    assert groups == [[5.0, 5.1], [1.0, 1.2, 1.4]]


def test_joint_names_are_readable():
    assert macos.vision._snake("LeftShoulder") == "left_shoulder"
    assert macos.vision._snake("ThumbCMC") == "thumb_cmc"
    assert macos.vision._snake("IndexTip") == "index_tip"
    assert len(macos.vision._BODY_JOINTS) == 19 and len(macos.vision._HAND_JOINTS) == 21


def test_vision_argument_checks(monkeypatch):
    with pytest.raises(ValueError):
        macos.vision.classify(b"image", limit=0)
    from contextlib import nullcontext

    monkeypatch.setattr(macos.vision, "_load", lambda: None)
    monkeypatch.setattr(macos.vision._objc, "autorelease_pool", nullcontext)  # no Objective-C: runs on Linux too
    monkeypatch.setattr(macos.vision._objc, "new", lambda name: 0)  # the request isn't made: nothing is classified
    monkeypatch.setattr(macos.vision, "_perform", lambda image, request: [])
    for bad in (1.5, -0.1, True, float("nan"), 10**400):  # 1.5 finds nothing, quietly; True reads as 1.0
        with pytest.warns(DeprecationWarning, match="min_confidence from 0.0 to 1.0, not "):
            assert macos.vision.classify(b"image", min_confidence=bad) == []
    from decimal import Decimal
    from fractions import Fraction

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for fine in (Fraction(1, 2), Decimal("0.5"), 0, 1):  # any number in range: no warning
            assert macos.vision.classify(b"image", min_confidence=fine) == []
        for odd in ("0.5", None):  # can't be compared: nothing said here, the filtering fails on them as before
            macos.vision.classify(b"image", min_confidence=odd)  # nothing found by the fake, so nothing to filter
    with pytest.raises(ValueError, match="threshold"):
        macos.vision.duplicates([b"image"], threshold=0)
    with pytest.raises(ValueError, match="positive"):
        macos.vision.smart_crop(b"image", 0, 100)
    with pytest.raises(ValueError, match="max_hands"):
        macos.vision.hand_pose(b"image", max_hands=0)


def test_text_spans_ignore_case_whatever_the_length():
    from macos.vision import _spans

    assert _spans("Click Submit, then submit", "SUBMIT") == [(6, 12), (19, 25)]
    assert _spans("Straße STRASSE", "strasse") == [(0, 6), (7, 14)]  # "ß" folds to "ss"
    assert _spans("ßA", "a") == [(1, 2)]
    assert _spans("anything", "") == []


def test_a_word_vision_cant_place_keeps_its_lines_box(monkeypatch):
    from macos import _objc, vision

    # One line, "pay 42": Vision places "pay", but not "42". The fakes stand in for the observations.
    line = _objc.CGRect(_objc.CGPoint(0.1, 0.5), _objc.CGSize(0.8, 0.1))
    box = _objc.CGRect(_objc.CGPoint(0.1, 0.5), _objc.CGSize(0.2, 0.1))

    def send(receiver, selector, *args, **kwargs):
        if selector == "topCandidates:":
            return ["candidate"]
        if selector == "string":
            return "pay 42"
        if selector == "boundingBoxForRange:error:":
            return "part" if args[0].location == 0 else None
        if selector == "boundingBox":
            return box if receiver == "part" else line
        raise AssertionError(selector)

    monkeypatch.setattr(vision._objc, "send", send)
    monkeypatch.setattr(vision._objc, "nsarray", lambda value: value)
    monkeypatch.setattr(vision._objc, "pystring", lambda value: value)
    words = vision._words_of(["observation"])
    assert [word for word, _ in words] == ["pay", "42"]  # not dropped: OCR would lose it from the PDF
    assert [tuple(round(part, 2) for part in place) for _, place in words] == [(0.1, 0.4, 0.2, 0.1), (0.1, 0.4, 0.8, 0.1)]


def test_pdfs_are_refused_before_vision_sees_a_blank_image(tmp_path):
    from macos.vision import _refuse_pdf

    document = tmp_path / "scan.png"  # the name doesn't matter, the bytes do
    document.write_bytes(b"%PDF-1.7\n...")
    for image in (b"%PDF-1.4\n...", bytearray(b"\r\n%PDF-1.4\n..."), document, str(document)):
        with pytest.raises(ValueError, match="macos.pdf.render"):
            _refuse_pdf(image)
        with pytest.raises(ValueError, match="macos.pdf.render"):
            macos.vision.smart_crop(image, 100, 100)

    _refuse_pdf(b"\x89PNG\r\n\x1a\n")
    # An image may mention a PDF in its metadata: only a header that opens the file counts.
    _refuse_pdf(b"\x89PNG\r\n\x1a\n...tEXtComment\x00%PDF-1.4 exported")
    _refuse_pdf(b"%PDF-but no version")
    _refuse_pdf(tmp_path / "missing.png")  # left to the usual FileNotFoundError


def test_scan_document_says_it_needs_macos_12_where_vision_cant(monkeypatch):
    from macos import _cf, _objc, vision

    def cls(name):
        raise _cf.Unavailable("Objective-C class {!r} is not loaded".format(name))

    monkeypatch.setattr(vision, "_load", lambda: None)
    monkeypatch.setattr(_objc, "cls", cls)
    with pytest.raises(macos.NotSupportedError, match=r"scan_document\(\) needs macOS 12 or later"):
        macos.vision.scan_document(b"\x89PNG\r\n\x1a\n")


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision checks the file: outside macOS, the platform comes first")
def test_classify_reports_a_missing_file_whatever_min_confidence_is(tmp_path):
    from decimal import Decimal

    # A value whose comparison raises (a Decimal NaN) fails in the filtering, as it always did: never before
    # the file's own error.
    with pytest.raises(FileNotFoundError):
        macos.vision.classify(tmp_path / "missing.png", min_confidence=Decimal("NaN"))
