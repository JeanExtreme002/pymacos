"""Unit tests for :mod:`macos.pdf`. They run on any platform."""

import sys

import pytest

import macos


def test_pdf_argument_checks(tmp_path):
    with pytest.raises(ValueError, match="multiple of 90"):
        macos.pdf.rotate(__file__, 45, tmp_path / "out.pdf")
    with pytest.raises(ValueError, match="empty"):
        macos.pdf.encrypt(__file__, tmp_path / "out.pdf", "")
    with pytest.raises(ValueError, match="at least one"):
        macos.pdf.from_images([], "out.pdf")
    with pytest.raises(ValueError, match="empty"):
        macos.pdf.watermark(__file__, " ", tmp_path / "out.pdf")
    with pytest.raises(ValueError, match="opacity"):
        macos.pdf.watermark(__file__, "DRAFT", tmp_path / "out.pdf", opacity=0)
    with pytest.raises(ValueError, match="hex color"):
        macos.pdf.watermark(__file__, "DRAFT", tmp_path / "out.pdf", color="red")


@pytest.mark.skipif(sys.platform != "darwin", reason="reads and writes PDF forms with PDFKit")
def test_forms(tmp_path):
    from tests.helpers import pdf_form

    form = pdf_form(tmp_path / "form.pdf")
    fields = {field.name: field for field in macos.pdf.form_fields(form)}
    assert {name: (field.kind, field.value, field.options) for name, field in fields.items()} == {
        "Full name": ("text", None, ()),
        "Agree": ("checkbox", False, ()),
        "Plan": ("choice", None, ("Free", "Pro")),
        "Size": ("radio", None, ("Small", "Large")),
    }
    values = {"Full name": "Ana Souza", "Agree": True, "Plan": "Pro", "Size": "Large"}
    filled = macos.pdf.fill_form(form, values, tmp_path / "filled.pdf")
    assert {field.name: field.value for field in macos.pdf.form_fields(filled)} == {
        "Full name": "Ana Souza", "Agree": True, "Plan": "Pro", "Size": "Large"
    }
    refused = (
        ({"Nope": "x"}, "no field named 'Nope'"),
        ({"Agree": "yes"}, "pass True or False"),
        ({"Plan": "Gold"}, "offers Free, Pro"),
        ({"Full name": True}, "takes text"),
    )
    for wrong, message in refused:
        with pytest.raises(ValueError, match=message):
            macos.pdf.fill_form(form, wrong, tmp_path / "never.pdf")
    assert not (tmp_path / "never.pdf").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="draws PDF pages with PDFKit")
def test_sign(tmp_path):
    from tests.helpers import pdf_form, rgb_png

    form = macos.pdf.fill_form(pdf_form(tmp_path / "form.pdf"), {"Full name": "Ana Souza"}, tmp_path / "filled.pdf")
    signature = tmp_path / "signature.png"
    signature.write_bytes(rgb_png(300, 100, lambda x, y: (20, 40, 160)))
    signed = macos.pdf.sign(form, signature, tmp_path / "signed.pdf", width=150)
    assert macos.pdf.page_count(signed) == 1 and macos.pdf.form_fields(signed) == []  # flattened
    assert "Ana Souza" in macos.pdf.text(signed)  # the filled-in value is drawn in the page
    # The image is drawn where asked, at the size asked: look at the rendered page.
    assert _color_at(signed, tmp_path, (400, 632, 70, 28)) == "signature"   # bottom right, 36 points in
    assert _color_at(signed, tmp_path, (100, 400, 60, 60)) == "page"
    rotated = macos.pdf.sign(
        macos.pdf.rotate(form, 90, tmp_path / "rotated.pdf"), signature, tmp_path / "rotated-signed.pdf",
        position="top_left", width=120,
    )
    assert _color_at(rotated, tmp_path, (50, 40, 60, 20)) == "signature"      # upright, top left as it's seen
    assert _color_at(rotated, tmp_path, (560, 450, 60, 60)) == "page"
    with pytest.raises(ValueError, match="out of range"):
        macos.pdf.sign(form, signature, tmp_path / "never.pdf", page=2)
    with pytest.raises(ValueError, match="position must be one of"):
        macos.pdf.sign(form, signature, tmp_path / "never.pdf", position="middle")
    with pytest.raises(ValueError, match="width must be positive"):
        macos.pdf.sign(form, signature, tmp_path / "never.pdf", width=0)


def _color_at(pdf_path, folder, box):
    """Whether a box of the page, rendered 700 pixels tall or wide, is mostly the signature's blue or the page."""
    png = folder / "render.png"
    png.write_bytes(macos.pdf.render(pdf_path, 1, size=700))
    crop = macos.image.crop(png, folder / "crop.png", box)
    red, green, blue = (int(macos.image.dominant_colors(crop, 1)[0][index:index + 2], 16) for index in (1, 3, 5))
    return "signature" if blue > 120 and red < 80 else "page"


@pytest.mark.skipif(sys.platform != "darwin", reason="adds annotations with PDFKit")
def test_add_text(tmp_path):
    from macos import _objc
    from tests.helpers import rgb_png

    white = tmp_path / "white.png"
    white.write_bytes(rgb_png(612, 792, lambda x, y: (255, 255, 255)))
    page = macos.pdf.from_images([white], tmp_path / "page.pdf")
    stamped = macos.pdf.add_text(page, "Received", tmp_path / "one.pdf", size=20)
    stamped = macos.pdf.add_text(stamped, "Checked\nby Ana", tmp_path / "two.pdf", position="bottom_right", color="#c00000")

    with macos.pdf._open(stamped) as document:
        notes = _objc.nsarray(_objc.send(macos.pdf._page(document, 1), "annotations"))
        assert [(_objc.pystring(_objc.send(note, "type")), _objc.pystring(_objc.send(note, "contents"))) for note in notes] == [
            ("FreeText", "Received"),
            ("FreeText", "Checked\nby Ana"),
        ]
    assert stamped.read_bytes().count(b"/AP") >= 2  # appearances saved: other viewers show the text too
    assert _dominant(stamped, tmp_path, (36, 38, 60, 14)) != "#ffffff"  # the text, top left, 36 points in
    reddish = [
        (int(color[1:3], 16), int(color[3:5], 16)) for color in _dominant(stamped, tmp_path, (455, 640, 50, 28), count=2)
    ]
    assert any(red > 150 and green < 100 for red, green in reddish)  # the red text, bottom right
    assert _dominant(stamped, tmp_path, (250, 350, 80, 80)) == "#ffffff"  # the rest untouched
    for wrong, message in (({"size": 0}, "size must be positive"), ({"font": "NoSuchFont-Bold"}, "no font is named")):
        with pytest.raises(ValueError, match=message):
            macos.pdf.add_text(page, "x", tmp_path / "never.pdf", **wrong)
    with pytest.raises(ValueError, match="page 2 is out of range"):
        macos.pdf.add_text(page, "x", tmp_path / "never.pdf", page=2)


def _dominant(pdf_path, folder, box, count=1):
    """The main color (or colors) of a box of page 1, rendered 700 pixels tall or wide."""
    png = folder / "render.png"
    png.write_bytes(macos.pdf.render(pdf_path, 1, size=700))
    colors = macos.image.dominant_colors(macos.image.crop(png, folder / "crop.png", box), count)
    return colors if count > 1 else colors[0]


@pytest.mark.parametrize("angle, corner", [(0, "top_left"), (90, "top_left"), (180, "bottom_right"), (270, "top_right")])
@pytest.mark.skipif(sys.platform != "darwin", reason="adds annotations with PDFKit")
def test_add_text_on_a_rotated_page(tmp_path, angle, corner):
    from tests.helpers import rgb_png

    white = tmp_path / "white.png"
    white.write_bytes(rgb_png(612, 792, lambda x, y: (255, 255, 255)))
    page = macos.pdf.from_images([white], tmp_path / "page.pdf")
    if angle:
        page = macos.pdf.rotate(page, angle, tmp_path / "rotated.pdf")
    stamped = macos.pdf.add_text(page, "Received", tmp_path / "stamped.pdf", position=corner, size=24)

    png = tmp_path / "render.png"
    png.write_bytes(macos.pdf.render(stamped, 1, size=700))
    width, height = macos.image.info(png).width, macos.image.info(png).height
    assert (width > height) == (angle % 180 == 90)  # rendered as it's seen

    def inked(horizontal, vertical):
        """Whether the corner of the rendered page has anything but white, as the page is seen."""
        box = (
            0 if horizontal == "left" else width - 180,
            0 if vertical == "top" else height - 70,
            180,
            70,
        )
        colors = macos.image.dominant_colors(macos.image.crop(png, tmp_path / "corner.png", box), 2)
        return any(color != "#ffffff" for color in colors)

    vertical, horizontal = corner.split("_")
    assert inked(horizontal, vertical)  # where asked, upright and whole
    opposite = ("right" if horizontal == "left" else "left", "bottom" if vertical == "top" else "top")
    assert not inked(*opposite)


@pytest.mark.skipif(sys.platform != "darwin", reason="reads and writes outlines with PDFKit")
def test_bookmarks(tmp_path):
    from tests.helpers import small_png

    picture = tmp_path / "page.png"
    picture.write_bytes(small_png(100, 100))
    book = macos.pdf.from_images([picture] * 3, tmp_path / "book.pdf")
    assert macos.pdf.bookmarks(book) == []
    contents = [("Intro", 1), ("Chapter 1", 2), ("1.1", 2, 1), ("1.1.1", 3, 2), ("Chapter 2", 3)]
    marked = macos.pdf.set_bookmarks(book, contents, tmp_path / "marked.pdf")
    assert [(mark.title, mark.page, mark.level) for mark in macos.pdf.bookmarks(marked)] == [
        ("Intro", 1, 0), ("Chapter 1", 2, 0), ("1.1", 2, 1), ("1.1.1", 3, 2), ("Chapter 2", 3, 0)
    ]  # fmt: skip
    assert macos.pdf.bookmarks(macos.pdf.set_bookmarks(marked, [], tmp_path / "cleared.pdf")) == []
    for wrong, message in (([("Deep", 1, 1)], "deeper than"), ([("x", 9)], "out of range"), ([(" ", 1)], "must not be empty")):
        with pytest.raises(ValueError, match=message):
            macos.pdf.set_bookmarks(book, wrong, tmp_path / "never.pdf")


@pytest.mark.skipif(sys.platform != "darwin", reason="reads PDFs with CoreGraphics")
def test_images(tmp_path):
    from tests.helpers import rgb_png

    stripes = tmp_path / "stripes.png"
    stripes.write_bytes(rgb_png(120, 80, lambda x, y: (200, 30, 30) if x < 60 else (30, 30, 200)))
    photo = macos.image.convert(stripes, tmp_path / "photo.jpg")
    document = macos.pdf.from_images([photo, stripes, photo], tmp_path / "pictures.pdf")

    found = macos.pdf.images(document, tmp_path / "out")
    assert [path.name for path in found] == ["page1-1.jpg", "page2-1.png"]  # the photo used twice, saved once
    assert found[0].read_bytes()[:2] == b"\xff\xd8"  # the JPEG as embedded
    for path in found:
        assert (macos.image.info(path).width, macos.image.info(path).height) == (120, 80)
    assert [path.name for path in macos.pdf.images(document, tmp_path / "two", pages=[2])] == ["page2-1.png"]
    with pytest.raises(ValueError, match="out of range"):
        macos.pdf.images(document, tmp_path / "never", pages=[4])


@pytest.mark.skipif(sys.platform != "darwin", reason="reads PDFs with CoreGraphics")
def test_images_in_calibrated_colors_and_inverted(tmp_path):
    from tests.helpers import pdf_with_images

    document = tmp_path / "raw.pdf"
    document.write_bytes(pdf_with_images([
        ("[/CalGray << /WhitePoint [0.95 1 1.09] >>]", "[1 0]", 4, 4, bytes([0]) * 16),   # black, inverted: white
        ("[/CalRGB << /WhitePoint [0.95 1 1.09] >>]", None, 4, 4, bytes([200, 30, 30]) * 16),
        ("/DeviceGray", "[0 0.5]", 4, 4, bytes([128]) * 16),   # a mapping it can't draw: skipped
    ]))  # fmt: skip
    found = macos.pdf.images(document, tmp_path / "out")
    assert [path.name for path in found] == ["page1-1.png", "page1-2.png"]
    assert macos.image.dominant_colors(found[0], 1) == ["#ffffff"]
    assert macos.image.dominant_colors(found[1], 1) == ["#c81e1e"]


@pytest.mark.skipif(sys.platform != "darwin", reason="reads PDFs with CoreGraphics")
def test_images_come_in_name_order(tmp_path):
    from tests.helpers import pdf_with_images

    # Twelve pictures, each redder than the last, named Im0 to Im11: the dictionary's own order isn't fixed.
    document = tmp_path / "twelve.pdf"
    document.write_bytes(pdf_with_images([("/DeviceRGB", None, 2, 2, bytes([index * 20, 0, 0]) * 4) for index in range(12)]))
    found = macos.pdf.images(document, tmp_path / "out")
    assert [path.name for path in found] == ["page1-{}.png".format(number) for number in range(1, 13)]
    assert [int(macos.image.dominant_colors(path, 1)[0][1:3], 16) for path in found] == [index * 20 for index in range(12)]
    assert macos.pdf._natural(b"Im10") > macos.pdf._natural(b"Im2")


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_seen_and_unrotated_are_inverses(rotation):
    box = (72.0, 200.0, 120.0, 40.0)
    assert macos.pdf._unrotated(macos.pdf._seen(box, 612, 792, rotation), 612, 792, rotation) == box


def test_next_to():
    anchor = (72.0, 200.0, 90.0, 20.0)  # a word as the page is seen
    assert macos.pdf._next_to(anchor, 100, 40, "right", 8) == (170.0, 190.0)  # centered on the line
    assert macos.pdf._next_to(anchor, 100, 40, "left", 8) == (-36.0, 190.0)
    assert macos.pdf._next_to(anchor, 100, 40, "above", 8) == (72.0, 228.0)
    assert macos.pdf._next_to(anchor, 100, 40, "below", 8) == (72.0, 152.0)


@pytest.mark.skipif(sys.platform != "darwin", reason="finds text and draws with PDFKit")
def test_sign_and_add_text_near_a_text(tmp_path):
    from macos import _objc
    from tests.helpers import pdf_with_text, rgb_png

    form = tmp_path / "form.pdf"
    form.write_bytes(pdf_with_text([("Name:", 72, 700), ("Signature:", 72, 200)]))
    signature = tmp_path / "signature.png"
    signature.write_bytes(rgb_png(300, 100, lambda x, y: (20, 40, 160)))

    signed = macos.pdf.sign(form, signature, tmp_path / "signed.pdf", near="signature:", width=120)  # any case
    # "Signature:" ends near x=155 points, its line centered near y=206: the picture (120 x 40 points) sits just
    # right of it, which the 700-pixel render (0.884 pixels a point) shows around pixels 145-250 by 500-535.
    assert _color_at(signed, tmp_path, (180, 505, 40, 20)) == "signature"
    assert _color_at(signed, tmp_path, (160, 440, 40, 20)) == "page"  # not on the line above

    named = macos.pdf.add_text(form, "Ana Souza", tmp_path / "named.pdf", near="Name:")
    with macos.pdf._open(named) as document:
        note = list(_objc.nsarray(_objc.send(macos.pdf._page(document, 1), "annotations")))[0]
        bounds = _objc.send(note, "bounds", restype=_objc.CGRect)
    assert 115 < bounds.origin.x < 135 and 690 < bounds.origin.y < 710  # right after "Name:", on its line

    below = macos.pdf.add_text(form, "Ana Souza", tmp_path / "below.pdf", near="Name:", side="below")
    with macos.pdf._open(below) as document:
        note = list(_objc.nsarray(_objc.send(macos.pdf._page(document, 1), "annotations")))[0]
        bounds = _objc.send(note, "bounds", restype=_objc.CGRect)
    assert 70 <= bounds.origin.x < 75 and bounds.origin.y + bounds.size.height < 700  # under it

    with pytest.raises(ValueError, match="isn't on the PDF"):
        macos.pdf.sign(form, signature, tmp_path / "never.pdf", near="Witness:")
    with pytest.raises(ValueError, match="isn't on page 1"):
        macos.pdf.add_text(form, "x", tmp_path / "never.pdf", near="Witness:", page=1)
    with pytest.raises(ValueError, match="position or near, not both"):
        macos.pdf.add_text(form, "x", tmp_path / "never.pdf", near="Name:", position="top_left")
    with pytest.raises(ValueError, match="side must be one of"):
        macos.pdf.sign(form, signature, tmp_path / "never.pdf", near="Name:", side="up")


def test_redact_targets():
    import re

    from macos.pdf import _patterns, _scrub, _utf16_offsets

    (label, words), (_, cpf) = _patterns(["Ana  Souza", re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")])
    assert label == "Ana  Souza"
    assert words.search("assinado por ANA\nsouza") and not words.search("Anasouza")  # any case and spacing
    ana = _patterns("Ana")[0][1]
    assert [m.group() for m in ana.finditer("Ana, Banana, Anapolis, ANA.")] == ["Ana", "ANA"]  # whole words only
    assert _patterns("-00")[0][1].search("789-00")  # an edge that isn't a letter or digit needs no word around it
    assert _patterns("Jose")[0][1].search("José") is None and _patterns("José")[0][1].search("JOSÉ.")
    counts = [0, 0]
    assert _scrub("Contrato de Ana Souza, CPF 123.456.789-00", [("", words), ("", cpf)], counts) == (
        "Contrato de " + "█" * 9 + ", CPF " + "█" * 14
    )
    assert counts == [1, 1]
    # Overlapping targets: each is searched in the original, so the longer one is covered whole.
    counts = [0, 0]
    both = _patterns(["Ana", "Ana Souza"])
    assert _scrub("Report on Ana Souza", both, counts) == "Report on " + "█" * 9 and counts == [1, 1]
    counts = [0, 0]  # the other order too: the shorter target is still found inside the longer one
    assert _scrub("Report on Ana Souza", _patterns(["Ana Souza", "Souza"]), counts) == "Report on " + "█" * 9
    assert counts == [1, 1]
    # A pattern that only matches between characters never counts as found: it would black out nothing.
    counts = [0]
    assert _scrub("secret plan", [("", re.compile(r"(?=secret)"))], counts) == "secret plan" and counts == [0]
    assert _patterns("a.b")[0][1].search("a.b") and not _patterns("a.b")[0][1].search("axb")  # literal, not a pattern
    assert _utf16_offsets("💡 CPF") == [0, 2, 3, 4, 5, 6]  # PDFKit counts an emoji as two
    text = "Ação 💡 relatório 𝒜 fim"
    assert _utf16_offsets(text) == [len(text[:index].encode("utf-16-le")) // 2 for index in range(len(text) + 1)]

    with pytest.raises(ValueError, match="is for bytes"):
        _patterns([re.compile(b"secret")])
    with pytest.raises(ValueError, match="each target once: 'Ana' is given more than once"):
        _patterns(["Ana", re.compile("Ana")])  # a text and a pattern with the same source count as one
    with pytest.raises(ValueError, match="each target once"):
        _patterns(["Souza", "Souza"])
    for bad, message in [([], "at least one"), (["  "], "takes texts"), ([3], "takes texts"), ([re.compile("x*")], "empty text")]:
        with pytest.raises(ValueError, match=message):
            _patterns(bad)


def _is_encrypted(path):
    from macos import _objc

    with macos.pdf._open(path) as document:  # opens without a password: no user password left
        return bool(_objc.send(document, "isEncrypted", restype=_objc.BOOL))


@pytest.fixture
def locked_book(tmp_path):
    """An encrypted, two-page PDF (password "s3cret") with a title and bookmarks."""
    from tests.helpers import pdf_with_text

    from macos import _objc

    plain = tmp_path / "plain.pdf"
    plain.write_bytes(pdf_with_text([("Contract of Jane Doe", 72, 700)]))
    two = macos.pdf.merge([plain, plain], tmp_path / "two.pdf")
    marked = macos.pdf.set_bookmarks(two, [("Start", 1), ("Annex", 2), ("Detail", 2, 1)], tmp_path / "marked.pdf")
    with macos.pdf._open(marked) as document:
        title = _objc.send(
            _objc.cls("NSDictionary"),
            "dictionaryWithObject:forKey:",
            _objc.nsstring("The contract"),
            _objc.nsstring("Title"),
            argtypes=(_objc.id, _objc.id),
        )
        _objc.send(document, "setDocumentAttributes:", title, argtypes=(_objc.id,), restype=None)
        macos.pdf._save(document, marked)
    locked = macos.pdf.encrypt(marked, tmp_path / "locked.pdf", "s3cret")
    assert macos.pdf.metadata(locked, password="s3cret").title == "The contract"
    return locked


@pytest.mark.skipif(sys.platform != "darwin", reason="reads and writes PDFs with PDFKit")
def test_edits_of_an_encrypted_pdf_are_not_encrypted(locked_book, tmp_path):
    assert macos.pdf.page_count(locked_book, password="s3cret") == 2
    with pytest.raises(macos.PermissionDeniedError):
        macos.pdf.text(locked_book)
    rotated = macos.pdf.rotate(locked_book, 90, tmp_path / "rotated.pdf", password="s3cret")
    redacted = macos.pdf.redact(locked_book, ["Jane Doe"], tmp_path / "redacted.pdf", password="s3cret").path
    stamped = macos.pdf.add_text(locked_book, "Seen", tmp_path / "stamped.pdf", password="s3cret")
    marked = macos.pdf.set_bookmarks(locked_book, [("Only", 2)], tmp_path / "marked-again.pdf", password="s3cret")
    for result in (rotated, redacted, stamped, marked):
        assert not _is_encrypted(result), result.name
        assert macos.pdf.page_count(result) == 2
    # What the copy carries over: the pages as edited, the metadata and the bookmarks, pointing to its own pages.
    assert macos.pdf.text(rotated, [2]) == "Contract of Jane Doe"
    assert macos.pdf.metadata(rotated).title == "The contract"
    assert [(mark.title, mark.page, mark.level) for mark in macos.pdf.bookmarks(rotated)] == [
        ("Start", 1, 0), ("Annex", 2, 0), ("Detail", 2, 1)
    ]  # fmt: skip
    assert [(mark.title, mark.page) for mark in macos.pdf.bookmarks(marked)] == [("Only", 2)]
    assert "Jane Doe" not in macos.pdf.text(redacted) and macos.pdf.metadata(redacted).title == "The contract"


@pytest.mark.skipif(sys.platform != "darwin", reason="reads and writes PDF forms with PDFKit")
def test_filling_an_encrypted_form_gives_an_unencrypted_one(tmp_path):
    from tests.helpers import pdf_form

    locked = macos.pdf.encrypt(pdf_form(tmp_path / "form.pdf"), tmp_path / "locked.pdf", "s3cret")
    filled = macos.pdf.fill_form(locked, {"Full name": "Ana Souza", "Agree": True}, tmp_path / "filled.pdf", password="s3cret")
    assert not _is_encrypted(filled)
    values = {field.name: field.value for field in macos.pdf.form_fields(filled)}
    assert values["Full name"] == "Ana Souza" and values["Agree"] is True


@pytest.mark.skipif(sys.platform != "darwin", reason="writes PDFs with PDFKit")
def test_outputs_get_the_usual_permissions(tmp_path):
    import os
    import stat

    from tests.helpers import pdf_with_text

    old = os.umask(0o022)
    try:
        source = tmp_path / "source.pdf"
        source.write_bytes(pdf_with_text([("Hello", 72, 700)]))
        target = tmp_path / "not" / "yet" / "there" / "rotated.pdf"  # its folders are made, beside it
        macos.pdf.rotate(source, 90, target)
        assert stat.S_IMODE(target.stat().st_mode) == 0o644  # not a temporary file's 0o600
        os.chmod(str(target), 0o664)
        macos.pdf.watermark(target, "DRAFT", target)  # rewritten in place: it keeps its permissions
        assert stat.S_IMODE(target.stat().st_mode) == 0o664
        assert sorted(os.listdir(str(target.parent))) == ["rotated.pdf"]
    finally:
        os.umask(old)


@pytest.mark.skipif(sys.platform != "darwin", reason="writes PDFs with PDFKit")
def test_compress_of_an_encrypted_pdf_keeps_the_smaller_one(tmp_path, monkeypatch):
    from tests.helpers import pdf_with_text

    source = tmp_path / "text.pdf"
    source.write_bytes(pdf_with_text([("Only some text", 72, 700)]))
    locked = macos.pdf.encrypt(source, tmp_path / "locked.pdf", "s3cret")
    written = []
    real = macos.pdf._write_pdf

    def write(document, name, options=None):
        done = real(document, name, options)
        if options:  # the filtered one: make it the bigger of the two
            with open(name, "ab") as file:
                file.write(b"%" + b" " * 50000 + b"\n")
        written.append((name, options is not None))
        return done

    monkeypatch.setattr(macos.pdf, "_write_pdf", write)
    result = macos.pdf.compress(locked, tmp_path / "small.pdf", password="s3cret")
    assert [filtered for _, filtered in written] == [True, False]  # filtered, then the plain copy to compare
    assert result.stat().st_size < 50000 and not _is_encrypted(result)
    assert macos.pdf.text(result) == "Only some text"


@pytest.mark.skipif(sys.platform != "darwin", reason="writes PDFs with PDFKit")
def test_encrypt_with_an_owner_password(tmp_path):
    from tests.helpers import pdf_with_text

    source = tmp_path / "text.pdf"
    source.write_bytes(pdf_with_text([("Private", 72, 700)]))
    locked = macos.pdf.encrypt(source, tmp_path / "locked.pdf", "user-pw", owner_password="owner-pw")
    assert macos.pdf.text(locked, password="user-pw") == "Private"
    assert macos.pdf.text(locked, password="owner-pw") == "Private"  # the owner's opens it too
    with pytest.raises(macos.PermissionDeniedError):
        macos.pdf.text(locked)
    with pytest.raises(ValueError, match="owner password"):
        macos.pdf.encrypt(source, tmp_path / "never.pdf", "user-pw", owner_password="")


@pytest.mark.skipif(sys.platform != "darwin", reason="reads PDFs and runs Vision")
def test_ocr_opens_the_pdf_once_and_hands_vision_the_drawn_page(tmp_path, monkeypatch):
    from tests.helpers import pdf_with_text

    source = tmp_path / "text.pdf"
    source.write_bytes(pdf_with_text([("Invoice number 4821", 72, 700)]))
    scan = macos.pdf.from_images([macos.pdf.render(source, size=1700)], tmp_path / "scan.pdf")
    opened, read = [], []
    real_open, real_words = macos.pdf._open, macos.vision._picture_words
    monkeypatch.setattr(macos.pdf, "_open", lambda *args: opened.append(args) or real_open(*args))
    monkeypatch.setattr(macos.pdf, "render", lambda *args, **kwargs: pytest.fail("no PNG round trip"))
    monkeypatch.setattr(
        macos.vision, "_picture_words", lambda picture, languages: read.append(1) or real_words(picture, languages)
    )
    searchable = macos.pdf.ocr(scan, tmp_path / "searchable.pdf", languages=["en-US"])
    assert len(opened) == 1 and read == [1]
    monkeypatch.setattr(macos.pdf, "_open", real_open)
    assert "Invoice number 4821" in macos.pdf.text(searchable)


def test_inverting_samples_flips_every_byte():
    assert bytes([0, 1, 128, 254, 255]).translate(macos.pdf._INVERTED) == bytes([255, 254, 127, 1, 0])


def test_hex_colors_are_read_by_one_parser():
    assert macos.pdf._color is macos.image._hex_color
    assert macos.pdf._color("#FF8000") == (1.0, 128 / 255, 0.0)


@pytest.mark.skipif(sys.platform != "darwin", reason="draws PDF pages with PDFKit")
def test_redrawn_pages_keep_the_crop_box(tmp_path):
    import struct

    from tests.helpers import pdf_with_text, rgb_png

    # A Letter page cropped to its bottom-left 300 x 300 points: SECRET is drawn, but cropped away.
    cropped = tmp_path / "cropped.pdf"
    cropped.write_bytes(pdf_with_text([("VISIBLE", 72, 72), ("SECRET", 400, 700)], crop=(0, 0, 300, 300)))
    signature = tmp_path / "signature.png"
    signature.write_bytes(rgb_png(30, 10, lambda x, y: (20, 40, 160)))
    made = [
        macos.pdf.watermark(cropped, "DRAFT", tmp_path / "watermarked.pdf"),
        macos.pdf.sign(cropped, signature, tmp_path / "signed.pdf", width=30),
        macos.pdf.add_text(cropped, "Approved", tmp_path / "noted.pdf"),
    ]

    def size(png):
        return struct.unpack(">II", png[16:24])

    assert size(macos.pdf.render(cropped, size=300)) == (300, 300)  # the crop box, not the Letter page
    for pdf in made:
        # The new page is the part that showed, nothing more.
        assert size(macos.pdf.render(pdf, size=300)) == (300, 300), pdf.name
        assert "VISIBLE" in macos.pdf.text(pdf), pdf.name


@pytest.mark.skipif(sys.platform != "darwin", reason="reads and writes outlines with PDFKit")
@pytest.mark.parametrize(
    "rotate, corner",
    # The corner, in the page's own coordinates, that shows at the top-left once the page is turned.
    [(0, (100, 400)), (90, (100, 100)), (180, (400, 100)), (270, (400, 400))],
)
def test_bookmarks_open_at_the_top_of_the_visible_part(tmp_path, rotate, corner):
    import ctypes

    from macos import _objc
    from tests.helpers import pdf_with_text

    cropped = tmp_path / "cropped.pdf"
    cropped.write_bytes(pdf_with_text([("VISIBLE", 150, 150)], rotate=rotate, crop=(100, 100, 400, 400)))
    marked = macos.pdf.set_bookmarks(cropped, [("Start", 1)], tmp_path / "marked.pdf")

    with macos.pdf._open(marked, None) as document:
        child = _objc.send(_objc.send(document, "outlineRoot"), "childAtIndex:", 0, argtypes=(ctypes.c_ulong,))
        point = _objc.send(_objc.send(child, "destination"), "point", restype=_objc.CGPoint)
    assert (point.x, point.y) == corner  # of the crop box as it shows, not the Letter page's (0, 792)
