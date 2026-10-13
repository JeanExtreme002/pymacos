"""Tests of :mod:`macos.pdf` against the real system. Skipped outside macOS."""


import ctypes

import pytest

import macos
from macos import _objc
from tests.helpers import png_size, rgb_png, small_png


def _text_pdf(folder, pages):
    """A PDF with real text on each page, made by CUPS (every Mac has it)."""
    import subprocess

    source = folder / "pages.txt"
    source.write_text("\f".join(pages) + "\n")
    target = folder / "doc.pdf"
    with open(target, "wb") as output:
        result = subprocess.run(["cupsfilter", str(source)], stdout=output, stderr=subprocess.DEVNULL)
    if result.returncode != 0 or not target.stat().st_size:
        pytest.skip("cupsfilter can't make PDFs here")
    return target


def test_pdf_read_merge_extract_and_render(tmp_path):
    document = _text_pdf(tmp_path, ["Page one says hello", "Page two says ola"])

    assert macos.pdf.page_count(document) == 2
    assert macos.pdf.text(document, pages=[2]) == "Page two says ola"
    assert "Page one says hello" in macos.pdf.text(document)

    merged = macos.pdf.merge([document, document], tmp_path / "merged.pdf")
    assert macos.pdf.page_count(merged) == 4
    reordered = macos.pdf.extract(document, [2, 1], tmp_path / "reordered.pdf")
    assert macos.pdf.text(reordered).startswith("Page two")

    with pytest.raises(ValueError, match="out of range"):
        macos.pdf.text(document, pages=[3])

    page = macos.pdf.render(document, 1, size=2048)
    assert page.startswith(b"\x89PNG")
    assert "says hello" in macos.vision.text(page)  # macOS 15's Vision may drop the short "one"


def test_pdf_render_is_exact_and_follows_rotation(tmp_path):
    import ctypes
    import struct

    from macos import _objc

    document = _text_pdf(tmp_path, ["A portrait page"])
    for size in (1024, 2048):
        width, height = struct.unpack(">II", macos.pdf.render(document, size=size)[16:24])
        assert max(width, height) == size and height > width

    rotated = tmp_path / "rotated.pdf"
    with macos.pdf._open(document) as opened:
        _objc.send(macos.pdf._page(opened, 1), "setRotation:", 90, argtypes=(ctypes.c_long,), restype=None)
        macos.pdf._save(opened, rotated)
    width, height = struct.unpack(">II", macos.pdf.render(rotated, size=1024)[16:24])
    assert (max(width, height), width > height) == (1024, True)


def test_pdf_passwords(tmp_path):
    from macos import _objc

    document = _text_pdf(tmp_path, ["Secret page"])
    locked = tmp_path / "locked.pdf"
    with macos.pdf._open(document) as opened:
        # PDFKit only encrypts when both a user and an owner password are set.
        options = _objc.send(
            _objc.cls("NSDictionary"),
            "dictionaryWithObjects:forKeys:",
            _objc.nsarray_of([_objc.nsstring("1234"), _objc.nsstring("owner")]),
            _objc.nsarray_of(
                [_objc.nsstring("PDFDocumentUserPasswordOption"), _objc.nsstring("PDFDocumentOwnerPasswordOption")]
            ),
            argtypes=(_objc.id, _objc.id),
        )
        _objc.send(
            opened,
            "writeToFile:withOptions:",
            _objc.nsstring(str(locked)),
            options,
            argtypes=(_objc.id, _objc.id),
            restype=_objc.BOOL,
        )

    with pytest.raises(macos.PermissionDeniedError):
        macos.pdf.text(locked)
    with pytest.raises(macos.PermissionDeniedError, match="wrong password"):
        macos.pdf.text(locked, password="nope")
    assert macos.pdf.text(locked, password="1234") == "Secret page"

    merged = macos.pdf.merge([locked, document], tmp_path / "merged.pdf", password="1234")
    assert macos.pdf.page_count(merged) == 2
    assert macos.pdf.text(merged).startswith("Secret page")  # the result isn't encrypted


def test_pdf_from_images(tmp_path, capfd):
    import ctypes

    from macos import _cf

    photo = tmp_path / "photo.png"
    photo.write_bytes(small_png(40, 20))
    # The same picture, stored sideways with EXIF orientation 6, as phones do.
    portrait = tmp_path / "portrait.jpg"
    io = macos.image._io()
    with _cf.owned(macos.image._source(photo)) as source, _cf.owned(_cf.from_python({"Orientation": 6})) as options:
        macos.image._write(portrait, "public.jpeg", lambda d: io.CGImageDestinationAddImageFromSource(d, source, 0, options))
    url = "https://github.com/JeanExtreme002/pymacos"

    document = macos.pdf.from_images([photo, portrait, macos.image.qr_code(url, size=300)], tmp_path / "scan.pdf")

    assert macos.pdf.page_count(document) == 3
    with macos.pdf._open(document) as opened:
        sizes = []
        for number in (1, 2):
            bounds = _objc.send(
                macos.pdf._page(opened, number), "boundsForBox:", 0, argtypes=(ctypes.c_long,), restype=_objc.CGRect
            )
            sizes.append((bounds.size.width, bounds.size.height))
    assert sizes == [(40, 20), (20, 40)]  # each page is its picture, upright
    found = macos.vision.barcodes(macos.pdf.render(document, page=3))
    assert [code.payload for code in found] == [url]
    # PDFKit logged "CoreGraphics PDF has logged an error" for images without an orientation.
    assert "CoreGraphics" not in capfd.readouterr().err
    with pytest.raises(ValueError):
        macos.pdf.from_images([b"not an image"], tmp_path / "junk.pdf")
    assert not (tmp_path / "junk.pdf").exists()


def test_pdf_metadata_rotate_and_encrypt(tmp_path):
    import ctypes

    document = _text_pdf(tmp_path, ["Page one says hello", "Page two says ola"])

    details = macos.pdf.metadata(document)
    assert details.created is not None and details.created.tzinfo is not None
    assert details.keywords == []

    # Rotating in place is safe: the output replaces the input only once written.
    assert macos.pdf.rotate(document, 90, document, pages=[2]) == document
    macos.pdf.rotate(document, -180, document)
    with macos.pdf._open(document) as opened:
        rotations = [_objc.send(macos.pdf._page(opened, n), "rotation", restype=ctypes.c_long) for n in (1, 2)]
    assert rotations == [180, 270]

    locked = macos.pdf.encrypt(document, tmp_path / "locked.pdf", "s3cret")
    with pytest.raises(macos.PermissionDeniedError):
        macos.pdf.text(locked)
    assert macos.pdf.text(locked, password="s3cret", pages=[1]) == "Page one says hello"
    changed = macos.pdf.encrypt(locked, tmp_path / "changed.pdf", "other", current_password="s3cret")
    assert macos.pdf.page_count(changed, password="other") == 2


def test_pdf_redrawing_keeps_the_annotations(tmp_path):
    # A note added to the page, and the page redrawn by watermark(), ocr() and sign(): the note must still show.
    # Core Graphics draws a page without its annotations, which is how filled forms and notes once vanished.
    white = tmp_path / "white.png"
    white.write_bytes(rgb_png(300, 400, lambda x, y: (255, 255, 255)))
    noted = macos.pdf.add_text(macos.pdf.from_images([white], tmp_path / "page.pdf"), "Received", tmp_path / "noted.pdf", size=40)

    def inked(document):
        """Whether the top-left corner, where the note is, holds anything but white."""
        png = tmp_path / "render.png"
        png.write_bytes(macos.pdf.render(document, 1, size=700))
        crop = macos.image.crop(png, tmp_path / "crop.png", (36, 38, 160, 50))
        return macos.image.dominant_colors(crop, 2) != ["#ffffff"]

    assert inked(noted)
    assert inked(macos.pdf.watermark(noted, "x", tmp_path / "marked.pdf", opacity=0.01))
    assert inked(macos.pdf.ocr(noted, tmp_path / "searchable.pdf", redo=True))
    assert inked(macos.pdf.sign(noted, white, tmp_path / "signed.pdf"))


def test_pdf_watermark_and_compress(tmp_path):
    document = _text_pdf(tmp_path, ["Page one says hello", "Page two says ola"])
    macos.pdf.rotate(document, 90, document, pages=[2])

    marked = macos.pdf.watermark(document, "CONFIDENTIAL", tmp_path / "marked.pdf", color="#d00000")

    assert macos.pdf.page_count(marked) == 2
    assert macos.pdf.text(marked, pages=[1]).split("\n") == ["Page one says hello", "CONFIDENTIAL"]
    import struct

    width, height = struct.unpack(">II", macos.pdf.render(marked, page=2, size=400)[16:24])
    assert width > height  # the turned page still shows turned

    # Noise: what a scan or photo looks like to a compressor.
    noisy = tmp_path / "noise.png"
    noisy.write_bytes(rgb_png(800, 600, lambda x, y: ((x * 7919 + y * 104729) % 251, (x * y) % 247, (x + y * 31) % 241)))
    photos = macos.pdf.from_images([noisy], tmp_path / "photo.pdf")
    smaller = macos.pdf.compress(photos, tmp_path / "small.pdf")
    assert smaller.stat().st_size < photos.stat().st_size / 2
    assert macos.pdf.page_count(smaller) == 1

    # Only text: nothing to shrink, and rewriting it would make it bigger.
    original = document.read_bytes()
    text_only = macos.pdf.compress(document, tmp_path / "text.pdf")
    assert text_only.read_bytes() == original
    assert macos.pdf.compress(document, document).read_bytes() == original  # in place too
    in_place = tmp_path / "in-place.pdf"
    in_place.write_bytes(photos.read_bytes())
    macos.pdf.compress(in_place, in_place)
    assert in_place.stat().st_size < photos.stat().st_size / 2

    locked = macos.pdf.encrypt(photos, tmp_path / "locked.pdf", "s3cret")
    opened = macos.pdf.compress(locked, tmp_path / "opened.pdf", password="s3cret")
    assert macos.pdf.page_count(opened) == 1  # no password needed any more


def test_pdf_grayscale(tmp_path):
    colorful = tmp_path / "colorful.png"
    colorful.write_bytes(rgb_png(120, 80, lambda x, y: (230, 60, 30) if x < 60 else (20, 90, 220)))
    document = macos.pdf.from_images([colorful], tmp_path / "colorful.pdf")

    gray = macos.pdf.grayscale(document, tmp_path / "gray.pdf")

    page = tmp_path / "page.png"
    page.write_bytes(macos.pdf.render(gray, size=120))
    for color in macos.image.dominant_colors(page, count=3):
        red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
        assert max(red, green, blue) - min(red, green, blue) <= 3  # no color left


def test_ocr_makes_a_scan_searchable(tmp_path):
    source = _text_pdf(tmp_path, ["Invoice number 4821", "Second page about ocean waves"])
    pages = [macos.pdf.render(source, number, size=1700) for number in (1, 2)]
    scan = macos.pdf.from_images(pages, tmp_path / "scan.pdf")
    assert macos.pdf.text(scan).strip() == ""  # images only

    searchable = macos.pdf.ocr(scan, tmp_path / "searchable.pdf", languages=["en-US"])
    assert "Invoice number 4821" in macos.pdf.text(searchable, [1])  # the words keep their spaces
    assert "ocean waves" in macos.pdf.text(searchable, [2])
    kept = macos.pdf.ocr(source, tmp_path / "kept.pdf")  # pages with text stay as they are
    assert macos.pdf.text(kept) == macos.pdf.text(source)


def _raw_text(path):
    """Everything the file holds, its compressed streams inflated: where redacted text could still hide."""
    import re
    import zlib

    raw = path.read_bytes()
    found = [raw]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            found.append(zlib.decompress(match.group(1)))
        except zlib.error:
            pass
    return b"\n".join(found)


def test_redact_removes_the_text(tmp_path):
    import re

    from tests.helpers import pdf_with_text

    first, second = tmp_path / "1.pdf", tmp_path / "2.pdf"
    first.write_bytes(pdf_with_text([("Contrato de Ana", 72, 700), ("Souza, CPF 123.456.789-00", 72, 680)]))
    second.write_bytes(pdf_with_text([("Anexo sem dados", 72, 700)]))
    merged = macos.pdf.merge([first, second], tmp_path / "merged.pdf")
    source = macos.pdf.set_bookmarks(merged, [("Contrato de Ana Souza", 1), ("Anexo", 2)], tmp_path / "in.pdf")
    before = macos.pdf.render(source, 2)

    cpf = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")
    done = macos.pdf.redact(source, ["ana souza", cpf], tmp_path / "out.pdf")
    output = done.path

    assert done.matches == {"ana souza": 2, cpf.pattern: 1}  # the name: on the page, and in the bookmark
    assert done.pages == {1: 2}

    assert macos.pdf.page_count(output) == 2
    assert macos.pdf.text(output, [1]).strip() == ""  # the redacted page is a picture now
    assert macos.pdf.text(output, [2]) == "Anexo sem dados"  # the other page didn't change
    assert macos.pdf.render(output, 2) == before
    assert [(mark.title, mark.page) for mark in macos.pdf.bookmarks(output)] == [("Contrato de " + "█" * 9, 1), ("Anexo", 2)]
    raw = _raw_text(output)
    assert b"Souza" not in raw and b"123.456" not in raw and "Souza".encode("utf-16-be") not in raw

    assert png_size(macos.pdf.render(output, 1, size=792)) == (612, 792)  # the page keeps its size


def test_redact_writes_nothing_when_a_target_is_missing(tmp_path):
    from tests.helpers import pdf_with_text

    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_with_text([("Contrato de Ana Souza", 72, 700)]))
    with pytest.raises(ValueError, match="'Maria' isn't in the PDF, so nothing was written"):
        macos.pdf.redact(source, ["Ana Souza", "Maria"], tmp_path / "out.pdf")
    assert not (tmp_path / "out.pdf").exists()


def test_redact_a_rotated_page_and_a_form_field(tmp_path):
    from tests.helpers import pdf_form, pdf_with_text

    rotated = tmp_path / "rotated.pdf"
    rotated.write_bytes(pdf_with_text([("CPF 123.456.789-00", 72, 700)], rotate=90))
    output = macos.pdf.redact(rotated, "123.456.789-00", tmp_path / "rotated-out.pdf").path
    assert b"123.456" not in _raw_text(output)
    assert png_size(macos.pdf.render(output, 1, size=792)) == (792, 612)  # still turned as it was seen

    form = tmp_path / "form.pdf"
    pdf_form(form)
    filled = macos.pdf.fill_form(form, {"Full name": "Ana Souza"}, tmp_path / "filled.pdf")
    output = macos.pdf.redact(filled, "Ana Souza", tmp_path / "form-out.pdf").path
    assert macos.pdf.form_fields(output) == [] and b"Souza" not in _raw_text(output)


def _crop(path):
    from macos import pdf

    with pdf._open(path) as document:
        box = _objc.send(pdf._page(document, 1), "boundsForBox:", 1, argtypes=(ctypes.c_long,), restype=_objc.CGRect)
        return box.size.width, box.size.height


def test_redact_keeps_the_crop_and_drops_what_it_hides(tmp_path):
    from tests.helpers import pdf_with_text

    source = tmp_path / "cropped.pdf"
    source.write_bytes(pdf_with_text([("Ana Souza", 100, 500), ("Hidden margin note", 400, 50)], crop=(50, 300, 450, 700)))
    output = macos.pdf.redact(source, "Ana Souza", tmp_path / "out.pdf").path
    assert _crop(output) == _crop(source) == (400.0, 400.0)
    assert b"Hidden margin" not in _raw_text(output)


def test_redact_finds_a_target_only_in_the_metadata(tmp_path):
    from macos import pdf
    from tests.helpers import pdf_with_text

    plain = tmp_path / "plain.pdf"
    plain.write_bytes(pdf_with_text([("Nothing to hide here", 72, 700)]))
    source = tmp_path / "titled.pdf"
    with pdf._open(plain) as document:
        attributes = _objc.send(_objc.send(_objc.send(document, "documentAttributes"), "mutableCopy"), "autorelease")
        title, key = _objc.nsstring("Project Falcon report"), _objc.nsstring("Title")
        _objc.send(attributes, "setObject:forKey:", title, key, argtypes=(_objc.id, _objc.id), restype=None)
        _objc.send(document, "setDocumentAttributes:", attributes, argtypes=(_objc.id,), restype=None)
        pdf._save(document, source)

    done = macos.pdf.redact(source, "Project Falcon", tmp_path / "out.pdf")

    assert done.matches == {"Project Falcon": 1} and done.pages == {}  # no page to redraw
    assert macos.pdf.metadata(done.path).title == "\u2588" * 14 + " report"
    assert macos.pdf.text(done.path) == "Nothing to hide here" and b"Falcon" not in _raw_text(done.path)


def test_redact_keeps_the_other_annotations_in_the_picture(tmp_path):
    from tests.helpers import pdf_with_text

    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_with_text([("Signed by Ana Souza", 72, 700)]))
    stamped = macos.pdf.add_text(source, "APPROVED", tmp_path / "stamped.pdf", page=1, position=(72, 400), size=36)

    output = macos.pdf.redact(stamped, "Ana Souza", tmp_path / "out.pdf").path

    seen = macos.vision.text(macos.pdf.render(output, 1, size=1600))
    assert "APPROVED" in seen and "Signed by" in seen and "Souza" not in seen


def test_redact_removes_hidden_text_and_counts_every_match(tmp_path, monkeypatch):
    from macos import pdf
    from tests.helpers import pdf_with_text

    # Invisible text, as OCR adds: still text to extract, so it must go.
    source = tmp_path / "hidden.pdf"
    source.write_bytes(pdf_with_text([("Visible line", 72, 700), ("Ana Souza", 72, 600)], invisible=[1]))
    assert "Ana Souza" in macos.pdf.text(source)
    done = macos.pdf.redact(source, "Ana Souza", tmp_path / "out.pdf")
    assert done.pages == {1: 1} and b"Souza" not in _raw_text(done.path)

    # A match with no box to draw still has its page redrawn: that's what removes the text.
    found = pdf._redactions
    monkeypatch.setattr(pdf, "_redactions", lambda *args: (found(*args)[0], []))
    done = macos.pdf.redact(source, "Ana Souza", tmp_path / "boxless.pdf")
    assert done.pages == {1: 1} and b"Souza" not in _raw_text(done.path)
    monkeypatch.undo()

    # A comment holding a target twice counts twice.
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(pdf_with_text([("Signed by Ana Souza", 72, 700)]))
    noted = macos.pdf.add_text(plain, "Ana Souza, Ana Souza", tmp_path / "noted.pdf", page=1, position=(72, 400))
    done = macos.pdf.redact(noted, "Ana Souza", tmp_path / "noted-out.pdf")
    assert done.matches == {"Ana Souza": 3} and done.pages == {1: 3}


def test_redact_doesnt_join_an_annotations_properties(tmp_path):
    from macos import pdf
    from tests.helpers import pdf_form

    form = tmp_path / "form.pdf"
    pdf_form(form)
    filled = macos.pdf.fill_form(form, {"Full name": "Souza"}, tmp_path / "filled.pdf")
    source = tmp_path / "noted.pdf"
    with pdf._open(filled) as document:
        for _, widget in pdf._widgets(document):
            if _objc.pystring(_objc.send(widget, "fieldName")) == "Full name":
                _objc.send(widget, "setContents:", _objc.nsstring("Ana"), argtypes=(_objc.id,), restype=None)
        pdf._save(document, source)

    # "Ana" is the field's comment and "Souza" its value: "Ana Souza" is in neither.
    with pytest.raises(ValueError, match="'Ana Souza' isn't in the PDF"):
        macos.pdf.redact(source, "Ana Souza", tmp_path / "out.pdf")
    assert macos.pdf.redact(source, "Souza", tmp_path / "out.pdf").matches == {"Souza": 1}


def test_redact_searches_every_text_an_annotation_holds(tmp_path):
    from macos import pdf
    from macos._objc import CGPoint, CGRect, CGSize
    from tests.helpers import pdf_form, pdf_with_text

    # A choice option and a radio state, nowhere in the page's text.
    form = tmp_path / "form.pdf"
    pdf_form(form)
    done = macos.pdf.redact(form, "Large", tmp_path / "form-out.pdf")
    assert done.pages == {1: 1} and b"Large" not in _raw_text(done.path)

    # A comment whose author is the name, on a page that doesn't show it, while another page does.
    first, second = tmp_path / "1.pdf", tmp_path / "2.pdf"
    first.write_bytes(pdf_with_text([("Signed by Ana Souza", 72, 700)]))
    second.write_bytes(pdf_with_text([("Reviewed", 72, 700)]))
    merged = macos.pdf.merge([first, second], tmp_path / "merged.pdf")
    source = tmp_path / "noted.pdf"
    with pdf._open(merged) as document:
        note = _objc.send(
            _objc.send(_objc.cls("PDFAnnotation"), "alloc"),
            "initWithBounds:forType:withProperties:",
            CGRect(CGPoint(72, 600), CGSize(20, 20)),
            _objc.nsstring("Text"),
            None,
            argtypes=(CGRect, _objc.id, _objc.id),
        )
        _objc.send(note, "autorelease")
        _objc.send(note, "setContents:", _objc.nsstring("Looks fine"), argtypes=(_objc.id,), restype=None)
        _objc.send(note, "setUserName:", _objc.nsstring("Ana Souza"), argtypes=(_objc.id,), restype=None)
        _objc.send(pdf._page(document, 2), "addAnnotation:", note, argtypes=(_objc.id,), restype=None)
        pdf._save(document, source)

    done = macos.pdf.redact(source, "Ana Souza", tmp_path / "out.pdf")
    assert done.pages == {1: 1, 2: 1} and b"Souza" not in _raw_text(done.path)


def test_redact_reads_the_whole_annotation_dictionary(tmp_path):
    from tests.helpers import pdf_with_text

    # The name only in a comment's subject (/Subj), on a page that doesn't show it, while another page does.
    first, second = tmp_path / "1.pdf", tmp_path / "2.pdf"
    first.write_bytes(
        pdf_with_text([("Report", 72, 700)], annotations=["/Subtype /Text /Rect [72 600 92 620] /Subj (Ana Souza review)"])
    )
    second.write_bytes(pdf_with_text([("Signed by Ana Souza", 72, 700)]))
    merged = macos.pdf.merge([first, second], tmp_path / "merged.pdf")
    done = macos.pdf.redact(merged, "Ana Souza", tmp_path / "out.pdf")
    assert done.pages == {1: 1, 2: 1} and b"Souza" not in _raw_text(done.path)

    # Rich-text contents (/RC), which PDFKit doesn't read: on a page left as it is, they must not stay behind.
    # PDFKit doesn't write them back; should a macOS keep them, this fails, and they need reading.
    # The name is found only in the title, so the page itself is left as it is.
    rich = tmp_path / "rich.pdf"
    rich.write_bytes(
        pdf_with_text(
            [("Report", 72, 700)],
            annotations=["/Subtype /Text /Rect [72 400 92 420] /Contents (Fine) /RC (<body><p>Ask Ana Souza</p></body>)"],
            title="Ana Souza report",
        )
    )
    assert b"Ask Ana Souza" in rich.read_bytes() and macos.pdf.metadata(rich).title == "Ana Souza report"
    done = macos.pdf.redact(rich, "Ana Souza", tmp_path / "rich-out.pdf")
    assert done.matches == {"Ana Souza": 1} and done.pages == {}
    assert b"Ask Ana" not in _raw_text(done.path) and b"Souza" not in _raw_text(done.path)


def _pdf_with_extras(page_text, xmp_creator=None, bookmark_link=None):
    """A one-page PDF, written by hand, with an XMP packet naming its creator and a bookmark leading to a link."""
    drawing = "BT /F1 18 Tf 72 700 Td ({}) Tj ET".format(page_text)
    objects = [
        "<< /Type /Catalog /Pages 2 0 R{}{} >>".format(
            " /Metadata 6 0 R" if xmp_creator else "", " /Outlines 7 0 R" if bookmark_link else ""
        ),
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        "<< /Length {} >>\nstream\n{}\nendstream".format(len(drawing), drawing),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    xmp = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:creator><rdf:Seq><rdf:li>{}</rdf:li></rdf:Seq></dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>"
    ).format(xmp_creator or "")
    objects.append("<< /Type /Metadata /Subtype /XML /Length {} >>\nstream\n{}\nendstream".format(len(xmp), xmp))
    objects.append("<< /Type /Outlines /First 8 0 R /Last 8 0 R /Count 1 >>")
    objects.append("<< /Title (Profile) /Parent 7 0 R /A << /S /URI /URI ({}) >> >>".format(bookmark_link or ""))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += "{} 0 obj\n{}\nendobj\n".format(number, body).encode("latin-1")
    table = len(out)
    out += "xref\n0 {}\n0000000000 65535 f \n".format(len(objects) + 1).encode()
    out += b"".join("{:010d} 00000 n \n".format(offset).encode() for offset in offsets)
    out += "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n".format(len(objects) + 1, table).encode()
    return bytes(out)


def test_redact_drops_an_xmp_packet_that_holds_a_target(tmp_path):
    source = tmp_path / "in.pdf"
    source.write_bytes(_pdf_with_extras("Contract of Ana Souza", xmp_creator="Ana Souza"))
    done = macos.pdf.redact(source, "Ana Souza", tmp_path / "out.pdf")
    assert done.matches == {"Ana Souza": 1} and done.pages == {1: 1}  # the packet goes, but only the page counts
    assert b"Souza" not in _raw_text(done.path)

    # Found only in the packet (here, as a date macOS could have written there itself), a target isn't found.
    import re

    dated = tmp_path / "dated.pdf"
    dated.write_bytes(_pdf_with_extras("Contract of Ana Souza", xmp_creator="2026-10-13"))
    with pytest.raises(ValueError, match="isn't in the PDF"):
        macos.pdf.redact(dated, re.compile(r"\d{4}-\d{2}-\d{2}"), tmp_path / "dated-out.pdf")
    assert not (tmp_path / "dated-out.pdf").exists()

    # One that doesn't hold a target stays, as everything else that doesn't.
    kept = tmp_path / "kept.pdf"
    kept.write_bytes(_pdf_with_extras("Contract of Ana Souza", xmp_creator="Legal team"))
    done = macos.pdf.redact(kept, "Ana Souza", tmp_path / "kept-out.pdf")
    assert done.matches == {"Ana Souza": 1} and b"Legal team" in _raw_text(done.path)


def test_redact_drops_a_bookmark_link_that_holds_a_target(tmp_path):
    source = tmp_path / "in.pdf"
    source.write_bytes(_pdf_with_extras("Contract of Ana Souza", bookmark_link="https://example.com/?q=Ana Souza"))
    done = macos.pdf.redact(source, "Ana Souza", tmp_path / "out.pdf")
    assert done.matches == {"Ana Souza": 2}  # the address, read as PDFKit gives it (Ana%20Souza), counts
    assert [mark.title for mark in macos.pdf.bookmarks(done.path)] == ["Profile"]  # the bookmark stays, without its link
    raw = _raw_text(done.path)
    assert b"Souza" not in raw and b"example.com" not in raw


def test_redact_removes_a_target_only_in_the_cropped_away_part(tmp_path):
    from tests.helpers import pdf_with_text

    source = tmp_path / "cropped.pdf"
    source.write_bytes(pdf_with_text([("Visible line", 72, 700), ("Ana Souza hidden", 72, 100)], crop=(0, 400, 612, 792)))
    assert macos.pdf.text(source) == "Visible line"  # the name isn't shown, but it's in the file
    done = macos.pdf.redact(source, "Ana Souza", tmp_path / "out.pdf")
    assert done.matches == {"Ana Souza": 1} and done.pages == {1: 1}
    assert b"Souza" not in _raw_text(done.path)


def test_redact_writes_nothing_when_a_target_would_get_through(tmp_path, monkeypatch):
    from macos import pdf
    from tests.helpers import pdf_with_text

    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_with_text([("Contract of Ana Souza", 72, 700)]))
    output = tmp_path / "out.pdf"
    output.write_bytes(b"what was there")
    monkeypatch.setattr(pdf, "_flatten", lambda document, number, boxes: None)  # a redaction that missed
    with pytest.raises(macos.MacOSError, match=r"would still hold 'Ana Souza' \(in page 1\), so nothing was written"):
        macos.pdf.redact(source, "Ana Souza", output)
    assert output.read_bytes() == b"what was there"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["in.pdf", "out.pdf"]  # nothing left beside it


def test_redact_finds_a_name_typed_with_combining_accents(tmp_path):
    from tests.helpers import pdf_with_text

    blank = tmp_path / "blank.pdf"
    blank.write_bytes(pdf_with_text([("Contract", 72, 700)]))
    source = macos.pdf.watermark(blank, "Jos\xe9 Silva", tmp_path / "in.pdf")  # an é of its own
    done = macos.pdf.redact(source, "José Silva", tmp_path / "out.pdf")  # e and a combining accent
    assert done.matches == {"José Silva": 1} and done.pages == {1: 1}
