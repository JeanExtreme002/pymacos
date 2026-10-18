"""Tests of :mod:`macos.vision` against the real system. Skipped outside macOS."""

import platform
from pathlib import Path

import pytest

import macos
from tests.helpers import WALLPAPER_MOVIE, pdf_with_text, png_size, rgb_png


def test_ocr_reads_a_quick_look_preview(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("PYMACOS OCR TEST 12345\nsecond line here\n")

    image = macos.finder.thumbnail(note, size=800)
    assert image.startswith(b"\x89PNG")

    lines = macos.vision.lines(image, languages=["en-US"])
    texts = [line.text for line in lines]
    assert "PYMACOS OCR TEST 12345" in texts
    assert texts.index("PYMACOS OCR TEST 12345") < texts.index("second line here")  # top to bottom
    assert all(0 <= line.confidence <= 1 for line in lines)
    assert all(0 <= value <= 1 for line in lines for value in line.box)


def test_ocr_languages_and_errors(tmp_path):
    assert "en-US" in macos.vision.languages()
    with pytest.raises(FileNotFoundError):
        macos.vision.text(tmp_path / "missing.png")
    # Not an image: the same errors as scan_document's, not Vision's own message.
    for call in (macos.vision.text, macos.vision.classify, macos.vision.scan_document):
        with pytest.raises(ValueError, match="not an image macOS can read"):
            call(b"not an image")
        with pytest.raises(IsADirectoryError):
            call(tmp_path)
    with pytest.raises(TypeError):
        macos.vision.text(b"not an image", languages="en-US")


@pytest.mark.skipif(
    int(platform.mac_ver()[0].split(".")[0] or 0) < 13,
    reason="Vision detects the language on macOS 13 or later",
)
def test_ocr_detects_a_language_it_isnt_given(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("你好世界 欢迎光临北京\n", encoding="utf-8")

    assert "你好世界" in macos.vision.text(macos.finder.thumbnail(note, size=800))


def test_pdfs_are_refused_and_read_once_rendered(tmp_path):
    document = tmp_path / "scan.pdf"
    document.write_bytes(pdf_with_text([("INVOICE 2026 TOTAL 42.00", 72, 700)]))

    for call in (macos.vision.text, macos.vision.faces, macos.vision.scan_document):
        with pytest.raises(ValueError, match="macos.pdf.render"):
            call(document)
    with pytest.raises(ValueError, match="macos.pdf.render"):
        macos.vision.lines(document.read_bytes())
    # The documented way: draw the page, then read it.
    assert "INVOICE 2026 TOTAL 42.00" in macos.vision.text(macos.pdf.render(document, page=1, size=2048))


def test_qr_code_round_trip():
    url = "https://github.com/JeanExtreme002/pymacos"
    image = macos.image.qr_code(url, size=300)

    found = macos.vision.barcodes(image)
    assert [(code.payload, code.kind) for code in found] == [(url, "QR")]
    assert macos.vision.faces(image) == []


def test_classify_returns_ranked_labels():
    labels = macos.vision.classify(macos.image.qr_code("pymacos"), min_confidence=0.0, limit=3)

    assert len(labels) <= 3
    assert [confidence for _, confidence in labels] == sorted((c for _, c in labels), reverse=True)


def _paper_photo(angle=12):
    """A 300x420 sheet with lines of "text", turned by ``angle`` degrees, on a dark desk."""
    import math

    cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def pixel(x, y):
        # (u, v): the point in the sheet's own coordinates, from its centre.
        u = (x - 240) * cos + (y - 320) * sin
        v = -(x - 240) * sin + (y - 320) * cos
        if abs(u) < 150 and abs(v) < 210:
            is_text = -120 < u < 110 and v < 150 and int(v + 180) % 30 < 8
            return (40, 40, 40) if is_text else (245, 245, 240)
        return (70, 45, 30)

    return rgb_png(480, 640, pixel)


def test_scan_document():
    scan = macos.vision.scan_document(_paper_photo())

    assert scan is not None
    width, height = png_size(scan)
    assert abs(width - 300) < 15 and abs(height - 420) < 15  # the sheet alone, straightened
    assert macos.vision.scan_document(macos.image.qr_code("not a sheet of paper")) is None


def test_smart_crop():
    photo = _paper_photo()

    assert png_size(macos.vision.smart_crop(photo, 200, 100)) == (200, 100)
    assert png_size(macos.vision.smart_crop(photo, 100, 300)) == (100, 300)
    # Never scaled up: the largest 2:1 crop of a 480x640 image is 480x240.
    assert png_size(macos.vision.smart_crop(photo, 2000, 1000)) == (480, 240)


def test_image_distance_and_duplicates(tmp_path):
    # Feature prints need real, detailed photos: use the wallpapers.
    pictures = sorted(Path("/System/Library/Desktop Pictures").glob("*.heic"))
    if len(pictures) < 2:
        pytest.skip("the desktop pictures aren't installed")
    first, other = pictures[0], pictures[-1]
    copy = macos.image.resize(first, tmp_path / "copy.jpg", width=1200)

    assert macos.vision.image_distance(first, copy) < 0.3 < macos.vision.image_distance(first, other)
    assert macos.vision.duplicates([first, other, copy]) == [[first, copy]]


_PARROT = Path("/Library/User Pictures/Animals/Parrot.heic")


def test_remove_background():
    import struct

    if not _PARROT.exists():
        pytest.skip("the sample user pictures aren't installed")
    try:
        cutout = macos.vision.remove_background(_PARROT)
    except macos.NotSupportedError:
        pytest.skip("needs macOS 14")

    width, height, _, color_type = struct.unpack(">IIBB", cutout[16:26])
    assert color_type == 6  # RGBA: the background is transparent
    cropped = macos.vision.remove_background(_PARROT, crop=True)
    cropped_width, cropped_height = struct.unpack(">II", cropped[16:24])
    assert cropped_width <= width and cropped_height <= height
    assert macos.vision.remove_background(macos.image.qr_code("no subject here")) is None


def test_animals_without_any():
    assert macos.vision.animals(macos.image.qr_code("no pets")) == []


@pytest.fixture
def wallpaper_movie():
    if not WALLPAPER_MOVIE.exists():
        pytest.skip("the video wallpapers aren't installed")
    return WALLPAPER_MOVIE


def test_horizon_and_straighten(wallpaper_movie, tmp_path):
    frame = tmp_path / "sunrise.png"
    frame.write_bytes(macos.video.frame(wallpaper_movie, at=20))
    tilt = macos.vision.horizon(frame)
    if tilt is None:
        pytest.skip("Vision doesn't see this frame's horizon here")

    level = macos.image.straighten(frame, tmp_path / "level.png")

    assert macos.vision.horizon(level) is None  # level now
    original, fixed = macos.image.info(frame), macos.image.info(level)
    assert fixed.width < original.width  # cropped, so no empty corners
    assert abs(fixed.width / fixed.height - original.width / original.height) < 0.01
    assert macos.vision.horizon(macos.image.qr_code("no horizon")) is None


def test_vision_poses_and_aesthetics(tmp_path):
    nobody = macos.image.qr_code("nobody here")
    assert macos.vision.body_pose(nobody) == []
    assert macos.vision.hand_pose(nobody) == []
    try:
        score = macos.vision.aesthetics(nobody)
    except macos.NotSupportedError:
        pytest.skip("needs macOS 15")
    assert -1.0 <= score.score <= 1.0 and isinstance(score.utility, bool)
