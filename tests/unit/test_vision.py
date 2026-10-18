"""Unit tests for :mod:`macos.vision`. They run on any platform."""

import os

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


def test_vision_argument_checks():
    with pytest.raises(ValueError):
        macos.vision.classify(b"image", limit=0)
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


def test_a_fifo_is_refused_before_anything_waits_for_its_writer(tmp_path):
    from macos.vision import _refuse_pdf

    fifo = tmp_path / "pipe.png"
    os.mkfifo(str(fifo))
    # Opened, it'd block this test forever: refused, it can't.
    with pytest.raises(ValueError, match="not an image macOS can read"):
        _refuse_pdf(fifo)
    _refuse_pdf(tmp_path)  # a folder: left to IsADirectoryError, as ciimage raises


def test_scan_document_says_it_needs_macos_12_where_vision_cant(monkeypatch):
    from macos import _cf, _objc, vision

    def cls(name):
        raise _cf.Unavailable("Objective-C class {!r} is not loaded".format(name))

    monkeypatch.setattr(vision, "_load", lambda: None)
    monkeypatch.setattr(_objc, "cls", cls)
    with pytest.raises(macos.NotSupportedError, match=r"scan_document\(\) needs macOS 12 or later"):
        macos.vision.scan_document(b"\x89PNG\r\n\x1a\n")


def _recording_send(monkeypatch, responds=True):
    """Fake ``_objc.send`` for :func:`macos.vision._request`: records each selector and the value sent with it."""
    from macos import vision

    sent = []

    def send(receiver, selector, *args, **kwargs):
        sent.append((selector, args))
        return responds if selector == "respondsToSelector:" else "request"

    monkeypatch.setattr(vision._objc, "send", send)
    monkeypatch.setattr(vision._objc, "cls", lambda name: name)
    monkeypatch.setattr(vision._objc, "sel", lambda name: name)
    monkeypatch.setattr(vision._objc, "nsstring", lambda value: value)
    monkeypatch.setattr(vision._objc, "nsarray_of", lambda values: values)
    return sent


def test_text_recognition_detects_the_language_unless_told(monkeypatch):
    from macos import vision

    sent = _recording_send(monkeypatch)
    vision._request(None, False)
    assert ("setAutomaticallyDetectsLanguage:", (True,)) in sent  # off by default: CJK would read as English

    sent = _recording_send(monkeypatch)
    vision._request(["zh-Hans"], False)
    assert ("setRecognitionLanguages:", (["zh-Hans"],)) in sent
    assert "setAutomaticallyDetectsLanguage:" not in [selector for selector, _ in sent]  # the caller's list holds

    sent = _recording_send(monkeypatch, responds=False)  # macOS 12: no such property
    vision._request(None, False)
    assert "setAutomaticallyDetectsLanguage:" not in [selector for selector, _ in sent]


def test_languages_as_a_string_is_refused(monkeypatch):
    from macos import vision

    sent = _recording_send(monkeypatch)
    with pytest.raises(TypeError, match=r"\['zh-Hans'\]"):
        vision._request("zh-Hans", False)  # not seven one-letter codes Vision would ignore
    monkeypatch.setattr(vision, "_load", lambda: None)
    with pytest.raises(TypeError):
        macos.vision.text(b"image", languages="en-US")
    assert sent == []


def test_image_distance_releases_the_first_print_when_the_second_fails(monkeypatch):
    from macos import vision

    released = []

    def feature_print(image):
        if image == "missing.png":
            raise FileNotFoundError(image)
        return "print of " + image

    monkeypatch.setattr(vision, "_load", lambda: None)
    monkeypatch.setattr(vision, "_feature_print", feature_print)
    monkeypatch.setattr(vision, "_distance", lambda first, second: 0.5)
    monkeypatch.setattr(vision._objc, "send", lambda receiver, selector, **kwargs: released.append(receiver))

    with pytest.raises(FileNotFoundError):
        vision.image_distance("photo.jpg", "missing.png")
    assert released == ["print of photo.jpg"]

    released.clear()
    with pytest.raises(FileNotFoundError):
        vision.image_distance("missing.png", "photo.jpg")
    assert released == []  # nothing was made

    released.clear()
    assert vision.image_distance("photo.jpg", "copy.jpg") == 0.5
    assert sorted(released) == ["print of copy.jpg", "print of photo.jpg"]


def test_an_input_that_isnt_an_image_raises_value_error(monkeypatch, tmp_path):
    import ctypes

    from macos import vision

    def failure(domain, code, message="CRImage Reader Detector was given zero-dimensioned image (0 x 0)"):
        answers = {"domain": domain, "code": code, "localizedDescription": message}
        monkeypatch.setattr(vision._objc, "send", lambda receiver, selector, **kwargs: answers[selector])
        monkeypatch.setattr(vision._objc, "pystring", lambda value: value)
        return ctypes.c_void_p(1)

    def ciimage(image):
        # Stands for _objc.ciimage: only b"png" and the folder's own files decode.
        if image == b"png":
            return 1
        path = str(image)
        if os.path.isdir(path):
            raise IsADirectoryError(path)
        label = "the image" if isinstance(image, bytes) else path
        raise ValueError("{} is not an image macOS can read".format(label))

    monkeypatch.setattr(vision._objc, "ciimage", ciimage)

    # What Vision answers for empty bytes, a text file or a folder: the same errors as scan_document's.
    error = failure("com.apple.Vision", 13)
    with pytest.raises(ValueError, match="the image is not an image macOS can read"):
        raise vision._read_error(b"", error)
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    with pytest.raises(ValueError, match="notes.txt is not an image macOS can read"):
        raise vision._read_error(str(text), error)
    with pytest.raises(IsADirectoryError):
        raise vision._read_error(tmp_path, error)

    # Vision gives the same code to a real image too small to analyze: that one keeps Vision's message.
    small = "The image is too small in at least one dimension 600 x 2 (each dimension has to be more than 2 pixels)"
    error = failure("com.apple.Vision", 13, small)
    with pytest.raises(macos.MacOSError, match="the image could not be read: The image is too small"):
        raise vision._read_error(b"png", error)

    # Any other failure is Vision's own: still MacOSError, with its message.
    error = failure("com.apple.Vision", 9, "internal error")
    with pytest.raises(macos.MacOSError, match="the image could not be read: internal error"):
        raise vision._read_error(b"image", error)
    with pytest.raises(macos.MacOSError, match="the image could not be read"):
        raise vision._read_error(b"image", ctypes.c_void_p())
