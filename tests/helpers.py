"""Helpers shared by several test modules: small images and markers."""

import os
from pathlib import Path

import pytest


def rgb_png(width, height, pixel):
    """A PNG whose color at (x, y) is ``pixel(x, y)``."""
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def small_png(width=4, height=4):
    """A small valid PNG, so the image tests don't depend on screen access."""
    return rgb_png(width, height, lambda x, y: (255, 0, 0))


def png_size(png):
    import struct

    return struct.unpack(">II", png[16:24])


# A movie macOS ships (a dynamic wallpaper), for the video and vision tests: any of them does, so the tests
# don't depend on the wallpapers of one release. A path that doesn't exist when there is none.
WALLPAPER_MOVIE = next(
    iter(sorted(Path("/System/Library/Desktop Pictures/.wallpapers").glob("*/*.mov"))),
    Path("/System/Library/Desktop Pictures/.wallpapers/none/none.mov"),
)


# GitHub's runners, where the tests that change the Mac may run unasked: a throwaway machine.
# ``CI`` alone isn't enough, as it's set in many a shell that is someone's Mac.
ON_GITHUB = bool(os.environ.get("GITHUB_ACTIONS"))

SETTINGS = pytest.mark.skipif(
    not (ON_GITHUB or os.environ.get("PYMACOS_SETTINGS_TESTS")),
    reason="changes (then restores) a setting of this Mac: set PYMACOS_SETTINGS_TESTS=1 to run",
)

CAPTURE = pytest.mark.skipif(
    not os.environ.get("PYMACOS_CAPTURE_TESTS"),
    reason="turns the camera or the microphone on: set PYMACOS_CAPTURE_TESTS=1 to run",
)


def pdf_form(path):
    """Write a one-page PDF form to ``path``: a text field, a checkbox, a choice and two radio buttons."""
    import ctypes

    from macos import _objc, pdf
    from macos._objc import CGPoint, CGRect, CGSize

    blank = str(path) + ".png"
    with open(blank, "wb") as file:
        file.write(small_png(612, 792))
    pdf.from_images([blank], path)
    with pdf._open(path) as document:
        page = pdf._page(document, 1)

        def widget(name, field_type, x, y, control=None, on=None, choices=None):
            annotation = _objc.send(
                _objc.send(_objc.cls("PDFAnnotation"), "alloc"),
                "initWithBounds:forType:withProperties:",
                CGRect(CGPoint(x, y), CGSize(160, 24)),
                _objc.nsstring("Widget"),
                None,
                argtypes=(CGRect, _objc.id, _objc.id),
            )
            _objc.send(annotation, "setWidgetFieldType:", _objc.nsstring(field_type), argtypes=(_objc.id,), restype=None)
            if control is not None:
                _objc.send(annotation, "setWidgetControlType:", control, argtypes=(ctypes.c_long,), restype=None)
            if on is not None:
                _objc.send(annotation, "setButtonWidgetStateString:", _objc.nsstring(on), argtypes=(_objc.id,), restype=None)
            if choices is not None:
                array = _objc.send(_objc.cls("NSMutableArray"), "array")
                for choice in choices:
                    _objc.send(array, "addObject:", _objc.nsstring(choice), argtypes=(_objc.id,), restype=None)
                _objc.send(annotation, "setChoices:", array, argtypes=(_objc.id,), restype=None)
            _objc.send(annotation, "setFieldName:", _objc.nsstring(name), argtypes=(_objc.id,), restype=None)
            _objc.send(page, "addAnnotation:", annotation, argtypes=(_objc.id,), restype=None)
            _objc.send(annotation, "release", restype=None)

        widget("Full name", "/Tx", 72, 700)
        widget("Agree", "/Btn", 72, 650, control=2)
        widget("Plan", "/Ch", 72, 600, choices=["Free", "Pro"])
        widget("Size", "/Btn", 72, 550, control=1, on="Small")
        widget("Size", "/Btn", 250, 550, control=1, on="Large")
        pdf._save(document, path)
    return path


def pdf_with_images(images):
    """
    A one-page PDF drawing raw images, written by hand: each is ``(color space, decode, width, height, samples)``.

    ``color space`` is PDF source such as ``"/DeviceGray"`` or ``"[/CalRGB << /WhitePoint [0.95 1 1.09] >>]"``;
    ``decode`` is ``None`` or an array's source such as ``"[1 0]"``.
    """
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"]
    names = " ".join("/Im{0} {1} 0 R".format(index, 5 + index) for index in range(len(images)))
    drawing = " ".join("q 100 0 0 100 {} 0 cm /Im{} Do Q".format(index * 110, index) for index in range(len(images)))
    objects.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << {} >> >> "
                   "/Contents 4 0 R >>".format(names))  # fmt: skip
    objects.append("<< /Length {} >>\nstream\n{}\nendstream".format(len(drawing), drawing))
    for space, decode, width, height, samples in images:
        extra = " /Decode {}".format(decode) if decode else ""
        objects.append(
            "<< /Type /XObject /Subtype /Image /Width {} /Height {} /ColorSpace {} /BitsPerComponent 8{} /Length {} >>\n"
            "stream\n".format(width, height, space, extra, len(samples))
        )
        objects[-1] = objects[-1].encode("latin-1") + samples + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += "{} 0 obj\n".format(number).encode()
        out += body if isinstance(body, bytes) else body.encode("latin-1")
        out += b"\nendobj\n"
    table = len(out)
    out += "xref\n0 {}\n0000000000 65535 f \n".format(len(objects) + 1).encode()
    out += b"".join("{:010d} 00000 n \n".format(offset).encode() for offset in offsets)
    out += "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n".format(len(objects) + 1, table).encode()
    return bytes(out)


def pdf_with_text(lines, rotate=0, crop=None, invisible=(), annotations=(), title=None):
    """
    A one-page Letter PDF, written by hand, with each ``(text, x, y)`` in 18-point Helvetica.

    ``crop`` is a CropBox, ``(left, bottom, right, top)``: the part of the page that shows.
    The lines whose index is in ``invisible`` are drawn invisibly, as OCR adds its text.
    ``annotations`` are the bodies of annotation dictionaries, written as they are, such as
    ``"/Subtype /Text /Rect [72 600 92 620] /Subj (Review)"``. ``title`` goes in the document's information.
    """
    cropped = " /CropBox [{} {} {} {}]".format(*crop) if crop else ""
    # The rendering mode outlives BT ... ET: set it on every line, or one invisible line hides the rest.
    drawing = " ".join(
        "BT {} Tr /F1 18 Tf {} {} Td ({}) Tj ET".format(3 if index in invisible else 0, x, y, text)
        for index, (text, x, y) in enumerate(lines)
    )
    first_annotation = 6
    listed = " ".join("{} 0 R".format(first_annotation + index) for index in range(len(annotations)))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]{} /Rotate {} "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R{} >>".format(
            cropped, rotate, " /Annots [{}]".format(listed) if annotations else ""
        ),
        "<< /Length {} >>\nstream\n{}\nendstream".format(len(drawing), drawing),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        *("<< /Type /Annot {} >>".format(body) for body in annotations),
    ]
    if title is not None:
        objects.append("<< /Title ({}) >>".format(title))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += "{} 0 obj\n{}\nendobj\n".format(number, body).encode("latin-1")
    table = len(out)
    out += "xref\n0 {}\n0000000000 65535 f \n".format(len(objects) + 1).encode()
    out += b"".join("{:010d} 00000 n \n".format(offset).encode() for offset in offsets)
    information = " /Info {} 0 R".format(len(objects)) if title is not None else ""
    out += "trailer\n<< /Size {} /Root 1 0 R{} >>\nstartxref\n{}\n%%EOF\n".format(
        len(objects) + 1, information, table
    ).encode()
    return bytes(out)


def docx_with_table(path, title, rows):
    """Write a minimal Word document: a bold title, then a table of ``rows`` (lists of cell texts)."""
    import zipfile
    from xml.sax.saxutils import escape

    types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    relations = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="word/document.xml" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/></Relationships>'
    )
    table = "".join(
        "<w:tr>{}</w:tr>".format("".join("<w:tc><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:tc>".format(escape(cell)) for cell in row))
        for row in rows
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{}</w:t></w:r></w:p>"
        '<w:tbl><w:tblPr><w:tblBorders><w:insideV w:val="single" w:sz="4"/></w:tblBorders></w:tblPr>{}</w:tbl>'
        "</w:body></w:document>"
    ).format(escape(title), table)
    with zipfile.ZipFile(str(path), "w") as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", relations)
        archive.writestr("word/document.xml", body)
    return path
