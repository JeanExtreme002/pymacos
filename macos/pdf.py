# -*- coding: utf-8 -*-

"""
Read, merge, split, rotate, encrypt and redact PDFs, or make them from images.

::

    macos.pdf.page_count("report.pdf")              # 12
    macos.pdf.text("report.pdf")                    # all the text
    macos.pdf.text("report.pdf", pages=[1])         # just the first page
    macos.pdf.merge(["a.pdf", "b.pdf"], "both.pdf")
    macos.pdf.extract("report.pdf", [1, 3], "summary.pdf")
    macos.pdf.encrypt("report.pdf", "locked.pdf", password="1234")
    macos.pdf.redact("contract.pdf", ["Jane Doe"], "public.pdf")

Uses PDFKit, the framework behind Preview. Page numbers start at 1, like in
Preview.
"""

import ctypes
import math
import os
import re
import shutil
from contextlib import contextmanager
from functools import lru_cache
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple, Union

from . import _cf, _files, _objc
from ._objc import BOOL, NSUInteger
from ._system import framework
from .errors import MacOSError, PermissionDeniedError
from .image import _hex_color as _color

__all__ = [
    "page_count",
    "text",
    "metadata",
    "merge",
    "extract",
    "rotate",
    "encrypt",
    "watermark",
    "ocr",
    "compress",
    "grayscale",
    "render",
    "from_images",
    "Metadata",
    "FormField",
    "form_fields",
    "fill_form",
    "sign",
    "add_text",
    "Bookmark",
    "bookmarks",
    "set_bookmarks",
    "images",
    "redact",
    "Redaction",
]

PathLike = Union[str, "os.PathLike[str]"]

_MAX_RENDER = 4096
# kPDFDisplayBoxCropBox (kCGPDFCropBox in Core Graphics): the part of the page
# that shows. What's drawn, measured and placed: what a viewer cropped away
# must stay away in what's made from the page.
_CROP_BOX = 1
_OPAQUE_RGB = 5  # kCGImageAlphaNoneSkipLast: the pixels of a bitmap drawn here, on an opaque page


@dataclass(frozen=True)
class Metadata:
    """The information a PDF records about itself, as in Preview's *Tools › Show Inspector*."""

    title: Optional[str]
    author: Optional[str]
    subject: Optional[str]
    keywords: List[str]
    creator: Optional[str]
    """The app the document was made in, such as ``'Microsoft Word'``."""
    producer: Optional[str]
    """The software that wrote the PDF, such as ``'macOS Version 15.6 Quartz PDFContext'``."""
    created: Optional[datetime]
    """In the local time zone."""
    modified: Optional[datetime]


@contextmanager
def _open(path: PathLike, password: Optional[str] = None) -> Iterator[int]:
    """Yield a ``PDFDocument`` for ``path``, inside an autorelease pool."""
    resolved = Path(path).expanduser().absolute()
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    framework("PDFKit")
    with _objc.autorelease_pool():
        document = _objc.send(_objc.cls("PDFDocument"), "alloc")
        document = _objc.send(document, "initWithURL:", _objc.file_url(resolved), argtypes=(_objc.id,))
        if not document:
            raise ValueError("{} is not a PDF".format(resolved))
        _objc.send(document, "autorelease")
        if _objc.send(document, "isLocked", restype=BOOL):
            unlocked = password is not None and _objc.send(
                document, "unlockWithPassword:", _objc.nsstring(password), argtypes=(_objc.id,), restype=BOOL
            )
            if not unlocked:
                raise PermissionDeniedError(
                    "{} is encrypted: {}".format(resolved, "wrong password" if password else "pass its password")
                )
        yield document


def _count(document: int) -> int:
    return int(_objc.send(document, "pageCount", restype=NSUInteger))


def _page(document: int, number: int) -> int:
    count = _count(document)
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= count:
        raise ValueError("page {!r} is out of range: the PDF has {} page(s), numbered from 1".format(number, count))
    return _objc.send(document, "pageAtIndex:", number - 1, argtypes=(NSUInteger,))


def page_count(path: PathLike, *, password: Optional[str] = None) -> int:
    """Return the number of pages."""
    with _open(path, password) as document:
        return _count(document)


def text(path: PathLike, pages: Optional[Iterable[int]] = None, *, password: Optional[str] = None) -> str:
    """
    Return the text of a PDF, or only of ``pages`` (numbered from 1), one page after another.

    Scanned pages have no text layer and give ``""``: read those with
    :func:`render` and :func:`macos.vision.text`.
    """
    with _open(path, password) as document:
        numbers = list(pages) if pages is not None else range(1, _count(document) + 1)
        parts = []
        for number in numbers:
            # A pool per page: each page's text would otherwise stay alive until the last one's read.
            with _objc.autorelease_pool():
                parts.append(_objc.pystring(_objc.send(_page(document, number), "string")) or "")
        return "\n".join(part.rstrip("\n") for part in parts)


def _attribute_text(attributes: int, key: str) -> Optional[str]:
    value = _objc.send(attributes, "objectForKey:", _objc.nsstring(key), argtypes=(_objc.id,))
    if not value or not _objc.send(value, "isKindOfClass:", _objc.cls("NSString"), argtypes=(_objc.id,), restype=BOOL):
        return None
    return (_objc.pystring(value) or "").strip() or None


def _attribute_date(attributes: int, key: str) -> Optional[datetime]:
    value = _objc.send(attributes, "objectForKey:", _objc.nsstring(key), argtypes=(_objc.id,))
    if not value or not _objc.send(value, "isKindOfClass:", _objc.cls("NSDate"), argtypes=(_objc.id,), restype=BOOL):
        return None
    return datetime.fromtimestamp(_objc.send(value, "timeIntervalSince1970", restype=ctypes.c_double)).astimezone()


def metadata(path: PathLike, *, password: Optional[str] = None) -> Metadata:
    """Return the title, author, keywords, dates and the apps that made a PDF."""
    with _open(path, password) as document:
        attributes = _objc.send(document, "documentAttributes")
        if not attributes:
            return Metadata(None, None, None, [], None, None, None, None)
        words = _objc.send(attributes, "objectForKey:", _objc.nsstring("Keywords"), argtypes=(_objc.id,))
        keywords: List[str] = []
        if words and _objc.send(words, "isKindOfClass:", _objc.cls("NSArray"), argtypes=(_objc.id,), restype=BOOL):
            keywords = [text for text in (_objc.pystring(word) for word in _objc.nsarray(words)) if text]
        elif words:
            # Some PDFs store the keywords as a single string.
            keywords = [word.strip() for word in (_objc.pystring(words) or "").split(",") if word.strip()]
        return Metadata(
            title=_attribute_text(attributes, "Title"),
            author=_attribute_text(attributes, "Author"),
            subject=_attribute_text(attributes, "Subject"),
            keywords=keywords,
            creator=_attribute_text(attributes, "Creator"),
            producer=_attribute_text(attributes, "Producer"),
            created=_attribute_date(attributes, "CreationDate"),
            modified=_attribute_date(attributes, "ModDate"),
        )


def _write_pdf(document: int, name: str, options: Optional[int] = None) -> bool:
    """Write ``document`` to the file ``name``, with ``writeToFile:withOptions:`` when there are ``options``."""
    if options:
        return bool(
            _objc.send(
                document,
                "writeToFile:withOptions:",
                _objc.nsstring(name),
                options,
                argtypes=(_objc.id, _objc.id),
                restype=BOOL,
            )
        )
    return bool(_objc.send(document, "writeToFile:", _objc.nsstring(name), argtypes=(_objc.id,), restype=BOOL))


def _save(document: int, output: PathLike, options: Optional[int] = None) -> Path:
    """
    Write ``document`` to ``output``, never encrypted unless ``options`` asks for it, and return the path.

    Through a file beside ``output``, moved in place at the end: the output
    may be one of the inputs, which PDFKit reads lazily while writing, and a
    failure never leaves a half-written file behind.
    """
    plain = _decrypted(document)
    return _files.write_atomically(output, lambda name: _write_pdf(plain, name, options))


def _new_document() -> int:
    return _objc.new("PDFDocument")


def _append(target: int, page: int) -> None:
    # Copy the page: inserting the original would move it out of its document.
    copy = _objc.send(_objc.send(page, "copy"), "autorelease")
    _objc.send(target, "insertPage:atIndex:", copy, _count(target), argtypes=(_objc.id, NSUInteger), restype=None)


def _decrypted(document: int) -> int:
    """
    ``document`` itself, or, when it's encrypted, an unencrypted copy of it (autoreleased).

    PDFKit writes an unlocked document with the encryption it was opened
    with: the result of rotating or redacting an encrypted PDF would still
    ask for its password. So its pages (annotations and form fields come
    with them), its metadata and its bookmarks go into a new document, the
    one every function here saves, the same way for all of them.
    """
    if not _objc.send(document, "isEncrypted", restype=BOOL):
        return document
    plain = _new_document()
    for number in range(1, _count(document) + 1):
        _append(plain, _page(document, number))
    attributes = _objc.send(document, "documentAttributes")
    if attributes:
        _objc.send(plain, "setDocumentAttributes:", attributes, argtypes=(_objc.id,), restype=None)
    root = _objc.send(document, "outlineRoot")
    if root:
        copy = _objc.new("PDFOutline")
        _copy_outline(document, root, plain, copy)
        _objc.send(plain, "setOutlineRoot:", copy, argtypes=(_objc.id,), restype=None)
    return plain


def _copy_outline(source: int, outline: int, target: int, copy: int) -> None:
    """Rebuild the entries under ``outline`` (of ``source``) under ``copy``, pointing to ``target``'s pages."""
    pages = _count(target)
    for index in range(int(_objc.send(outline, "numberOfChildren", restype=NSUInteger))):
        child = _objc.send(outline, "childAtIndex:", index, argtypes=(NSUInteger,))
        entry = _objc.new("PDFOutline")
        _objc.send(entry, "setLabel:", _objc.send(child, "label"), argtypes=(_objc.id,), restype=None)
        destination = _objc.send(child, "destination")
        page = _objc.send(destination, "page") if destination else None
        at = int(_objc.send(source, "indexForPage:", page, argtypes=(_objc.id,), restype=NSUInteger)) if page else pages
        if at < pages:
            # The same spot, on the copy of its page: the old destination points into the encrypted document.
            point = _objc.send(destination, "point", restype=_objc.CGPoint)
            moved = _objc.send(
                _objc.send(_objc.cls("PDFDestination"), "alloc"),
                "initWithPage:atPoint:",
                _objc.send(target, "pageAtIndex:", at, argtypes=(NSUInteger,)),
                point,
                argtypes=(_objc.id, _objc.CGPoint),
            )
            _objc.send(moved, "autorelease")
            _objc.send(entry, "setDestination:", moved, argtypes=(_objc.id,), restype=None)
        else:
            action = _objc.send(child, "action")  # a link to a web page or another file: no page to remap
            if action:
                _objc.send(entry, "setAction:", action, argtypes=(_objc.id,), restype=None)
        _objc.send(entry, "setIsOpen:", _objc.send(child, "isOpen", restype=BOOL), argtypes=(BOOL,), restype=None)
        count = int(_objc.send(copy, "numberOfChildren", restype=NSUInteger))
        _objc.send(copy, "insertChild:atIndex:", entry, count, argtypes=(_objc.id, NSUInteger), restype=None)
        _copy_outline(source, child, target, entry)


def merge(inputs: Sequence[PathLike], output: PathLike, *, password: Optional[str] = None) -> Path:
    """
    Join PDFs, one after another, into ``output``, and return its path.

    ``password`` unlocks any encrypted input (they must share it); the
    merged PDF itself is not encrypted.
    """
    if not inputs:
        raise ValueError("merge() needs at least one PDF")
    framework("PDFKit")
    with _objc.autorelease_pool():
        merged = _new_document()
        for path in inputs:
            with _open(path, password) as document:
                for number in range(1, _count(document) + 1):
                    _append(merged, _page(document, number))
        return _save(merged, output)


def extract(path: PathLike, pages: Iterable[int], output: PathLike, *, password: Optional[str] = None) -> Path:
    """
    Save the chosen ``pages`` (numbered from 1, in the order given) as a new PDF, and return its path.

    Use it to split a PDF (``extract(path, [1], "first.pdf")``) or reorder its pages.
    """
    numbers = list(pages)
    if not numbers:
        raise ValueError("extract() needs at least one page")
    with _open(path, password) as document:
        result = _new_document()
        for number in numbers:
            _append(result, _page(document, number))
        return _save(result, output)


def rotate(
    path: PathLike,
    degrees: int,
    output: PathLike,
    *,
    pages: Optional[Iterable[int]] = None,
    password: Optional[str] = None,
) -> Path:
    """
    Turn pages clockwise by ``degrees`` (90, 180 or 270; negative turns counter-clockwise) and save to ``output``.

    Every page turns, or only ``pages`` (numbered from 1). Handy for scans
    that came out sideways::

        macos.pdf.rotate("scan.pdf", 90, "scan.pdf", pages=[2])
    """
    if degrees % 90:
        raise ValueError("degrees must be a multiple of 90, not {}".format(degrees))
    with _open(path, password) as document:
        numbers = list(pages) if pages is not None else list(range(1, _count(document) + 1))
        for number in numbers:
            page = _page(document, number)
            current = _objc.send(page, "rotation", restype=ctypes.c_long)
            _objc.send(page, "setRotation:", (current + degrees) % 360, argtypes=(ctypes.c_long,), restype=None)
        return _save(document, output)


def _pdfkit_string(name: str) -> int:
    return ctypes.c_void_p.in_dll(framework("PDFKit"), name).value or 0


def encrypt(
    path: PathLike,
    output: PathLike,
    password: str,
    *,
    current_password: Optional[str] = None,
    owner_password: Optional[str] = None,
) -> Path:
    """
    Save a copy of a PDF that asks for ``password`` to open, and return its path.

    Preview, Acrobat and browsers all ask for it. ``current_password`` opens a
    PDF that is already encrypted, to change its password. To read or change
    an encrypted PDF with this module, pass ``password=`` to the other
    functions.

    ``owner_password`` is the PDF's other password, the one meant to guard
    its permissions (printing, copying, editing); by default it's
    ``password`` too. Give it a different one when the people who open the
    PDF shouldn't hold the owner's password as well.
    """
    if not password:
        raise ValueError("the password can't be empty")
    if owner_password is not None and not owner_password:
        raise ValueError("the owner password can't be empty; leave it out to use password")
    with _open(path, current_password) as document:
        options = _objc.send(_objc.cls("NSMutableDictionary"), "dictionary")
        secrets = (("PDFDocumentUserPasswordOption", password), ("PDFDocumentOwnerPasswordOption", owner_password or password))
        for key, secret in secrets:
            _objc.send(
                options,
                "setObject:forKey:",
                _objc.nsstring(secret),
                _pdfkit_string(key),
                argtypes=(_objc.id, _objc.id),
                restype=None,
            )
        return _save(document, output, options)


@lru_cache(maxsize=None)
def _core_text() -> ctypes.CDLL:
    text_library = framework("CoreText")
    pointer = ctypes.c_void_p
    text_library.CTFontCreateWithName.argtypes = (pointer, ctypes.c_double, pointer)
    text_library.CTFontCreateWithName.restype = pointer
    text_library.CTLineCreateWithAttributedString.argtypes = (pointer,)
    text_library.CTLineCreateWithAttributedString.restype = pointer
    text_library.CTLineGetTypographicBounds.argtypes = (
        pointer,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    )
    text_library.CTLineGetTypographicBounds.restype = ctypes.c_double
    text_library.CTLineDraw.argtypes = (pointer, pointer)
    text_library.CTLineDraw.restype = None
    return text_library


def _line(text: str, size: float) -> Tuple[int, float, float]:
    """An owned Core Text line of ``text`` in bold Helvetica, its width and its height (ascent + descent)."""
    from . import _cf

    core_text = _core_text()
    with _cf.owned(_cf.string("Helvetica-Bold")) as name:
        font = core_text.CTFontCreateWithName(name, size, None)
    true = _cf.constant(_cf.lib(), "kCFBooleanTrue")
    attributes = _cf.dictionary(
        {
            _cf.constant(core_text, "kCTFontAttributeName"): font,
            # Take the color (and transparency) from the drawing context.
            _cf.constant(core_text, "kCTForegroundColorFromContextAttributeName"): true,
        }
    )
    cf = _cf.lib()
    cf.CFAttributedStringCreate.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    cf.CFAttributedStringCreate.restype = ctypes.c_void_p
    with _cf.owned(font), _cf.owned(attributes), _cf.owned(_cf.string(text)) as string:
        with _cf.owned(cf.CFAttributedStringCreate(None, string, attributes)) as attributed:
            line = core_text.CTLineCreateWithAttributedString(attributed)
    ascent, descent, leading = ctypes.c_double(), ctypes.c_double(), ctypes.c_double()
    width = core_text.CTLineGetTypographicBounds(line, ctypes.byref(ascent), ctypes.byref(descent), ctypes.byref(leading))
    return line, float(width), ascent.value + descent.value


def _open_for_drawing(source: Path, password: Optional[str]) -> int:
    """An owned, unlocked ``CGPDFDocument``, to draw its pages elsewhere; release it with ``CGPDFDocumentRelease``."""
    from . import _cf

    graphics = _graphics()
    with _cf.owned(_cf.file_url(str(source))) as url:
        document = graphics.CGPDFDocumentCreateWithURL(url)
    if not document:
        raise ValueError("{} is not a PDF".format(source))
    if graphics.CGPDFDocumentIsEncrypted(document) and not graphics.CGPDFDocumentIsUnlocked(document):
        unlocked = password is not None and graphics.CGPDFDocumentUnlockWithPassword(document, password.encode("utf-8"))
        if not unlocked:
            graphics.CGPDFDocumentRelease(document)
            raise PermissionDeniedError(
                "{} is encrypted: {}".format(source, "wrong password" if password else "pass its password")
            )
    return int(document)


_INVISIBLE = 3  # kCGTextInvisible: text that selection and search find, but that doesn't show


def _seen_size(graphics: ctypes.CDLL, page: int) -> Tuple[float, float]:
    """The size of a ``CGPDFPage``'s crop box, in points, as it shows: turned when its /Rotate is a quarter turn."""
    box = graphics.CGPDFPageGetBoxRect(page, _CROP_BOX)
    width, height = box.size.width, box.size.height
    if graphics.CGPDFPageGetRotationAngle(page) % 180:
        width, height = height, width
    return width, height


def _draw_page(graphics: ctypes.CDLL, context: int, page: int, width: float, height: float) -> None:
    """Draw a ``CGPDFPage``'s crop box over ``width`` x ``height`` points of ``context``, from its corner, turned as it shows."""
    frame = _objc.CGRect(_objc.CGPoint(0, 0), _objc.CGSize(width, height))
    graphics.CGContextSaveGState(context)
    # Clipped too: what lies outside the crop box mustn't spill into the new page.
    graphics.CGContextClipToRect(context, frame)
    graphics.CGContextConcatCTM(context, graphics.CGPDFPageGetDrawingTransform(page, _CROP_BOX, frame, 0, True))
    graphics.CGContextDrawPDFPage(context, page)
    graphics.CGContextRestoreGState(context)


def _write_pages(
    output: PathLike, sizes: Sequence[Tuple[float, float]], draw: Callable[[int, int, float, float], None]
) -> Path:
    """
    Write a new PDF with one page per size in ``sizes`` (in points), and return its path.

    ``draw(context, index, width, height)`` fills page ``index`` (from 0) of
    the PDF context. What :func:`ocr`, :func:`watermark`, :func:`sign` and
    :func:`from_images` share: they redraw every page into a new PDF. Each
    page is drawn in an autorelease pool of its own, so what drawing one
    page made doesn't pile up until the last.
    """
    graphics = _graphics()

    def write(name: str) -> bool:
        with _cf.owned(_cf.file_url(name)) as url:
            context = graphics.CGPDFContextCreateWithURL(url, None, None)
        if not context:
            return False
        try:
            for index, (width, height) in enumerate(sizes):
                frame = _objc.CGRect(_objc.CGPoint(0, 0), _objc.CGSize(width, height))
                graphics.CGContextBeginPage(context, ctypes.byref(frame))
                with _objc.autorelease_pool():
                    draw(context, index, width, height)
                graphics.CGContextEndPage(context)
            graphics.CGPDFContextClose(context)
        finally:
            graphics.CGContextRelease(context)
        return True

    return _files.write_atomically(output, write)


def _picture_of_page(graphics: ctypes.CDLL, page: int, longest: int) -> int:
    """An owned ``CGImage`` of a ``CGPDFPage`` as it shows, on white, ``longest`` pixels on its longest side."""
    width, height = _seen_size(graphics, page)
    scale = longest / (max(width, height) or 1.0)
    pixels_wide, pixels_high = max(1, round(width * scale)), max(1, round(height * scale))
    space = graphics.CGColorSpaceCreateDeviceRGB()
    context = graphics.CGBitmapContextCreate(None, pixels_wide, pixels_high, 8, 0, space, _OPAQUE_RGB)
    graphics.CGColorSpaceRelease(space)
    if not context:
        raise MacOSError("could not draw a page of {} x {} pixels".format(pixels_wide, pixels_high))
    try:
        graphics.CGContextSetRGBFillColor(context, 1.0, 1.0, 1.0, 1.0)
        graphics.CGContextFillRect(context, _objc.CGRect(_objc.CGPoint(0, 0), _objc.CGSize(pixels_wide, pixels_high)))
        graphics.CGContextScaleCTM(context, scale, scale)
        _draw_page(graphics, context, page, width, height)
        picture = graphics.CGBitmapContextCreateImage(context)
    finally:
        graphics.CGContextRelease(context)
    if not picture:
        raise MacOSError("could not draw a page of {} x {} pixels".format(pixels_wide, pixels_high))
    return int(picture)


def ocr(
    path: PathLike,
    output: PathLike,
    *,
    languages: Optional[Sequence[str]] = None,
    redo: bool = False,
    password: Optional[str] = None,
) -> Path:
    """
    Make a scanned PDF searchable: add the text Vision reads on each page, invisibly, and save it to ``output``.

    ::

        macos.pdf.ocr("scan.pdf", "scan-searchable.pdf")
        macos.pdf.text("scan-searchable.pdf")   # the text of the scan

    The pages look the same, and their text can now be selected, copied and
    searched, in Preview, Spotlight or :func:`text`. Pages that already have
    text aren't read again, unless ``redo=True``. As with :func:`watermark`,
    every page is redrawn into the new PDF, so links and form fields aren't kept. ``languages`` works as in
    :func:`macos.vision.lines` (``["fr-FR", "en-US"]``). ``password`` opens an
    encrypted PDF; the result isn't encrypted.
    """
    from . import vision

    source = _files.existing(path)
    graphics, core_text = _graphics(), _core_text()
    document = _open_for_drawing(source, password)
    try:
        pages = graphics.CGPDFDocumentGetNumberOfPages(document)
        # Read every page first: Vision reads the pages of the file, not the PDF being written. The file is
        # opened once (PDFKit only tells which pages have text), and each page goes to Vision as the
        # picture drawn here, with no image file in between.
        found: Dict[int, List[Any]] = {}
        with _open(source, password) as readable:
            for number in range(1, pages + 1):
                with _objc.autorelease_pool():
                    if not redo and (_objc.pystring(_objc.send(_page(readable, number), "string")) or "").strip():
                        continue
                    page = graphics.CGPDFDocumentGetPage(document, number)
                    longest = max(_seen_size(graphics, page))
                    picture = _picture_of_page(graphics, page, int(min(4096, max(1024, longest * 3))))
                    with _cf.owned(picture):
                        # Word by word: one stretched line would space its words wrong for search and copy.
                        found[number] = vision._picture_words(picture, languages)

        def draw(context: int, index: int, width: float, height: float) -> None:
            _draw_page(graphics, context, graphics.CGPDFDocumentGetPage(document, index + 1), width, height)
            for word, word_box in found.get(index + 1, []):
                _draw_invisible(graphics, core_text, context, word, word_box, width, height)

        sizes = [_seen_size(graphics, graphics.CGPDFDocumentGetPage(document, number)) for number in range(1, pages + 1)]
        return _write_pages(output, sizes, draw)
    finally:
        graphics.CGPDFDocumentRelease(document)


def _draw_invisible(
    graphics: ctypes.CDLL,
    core_text: ctypes.CDLL,
    context: int,
    words: str,
    box: Tuple[float, float, float, float],
    width: float,
    height: float,
) -> None:
    """Write ``words`` invisibly over ``box`` (fractions of the page from its top-left), stretched to its width."""
    if not words.strip():
        return
    left, top, wide, tall = box[0] * width, box[1] * height, box[2] * width, box[3] * height
    size = max(tall, 1.0)
    probe, natural_width, _ = _line(words, size)
    _cf.release(probe)
    # A real space after the word: text extraction spaces words by their space characters.
    line, _, _ = _line(words + " ", size)
    try:
        graphics.CGContextSaveGState(context)
        graphics.CGContextSetTextDrawingMode(context, _INVISIBLE)
        # PDF pages measure from their bottom-left corner, going up.
        graphics.CGContextTranslateCTM(context, left, height - top - tall + tall * 0.2)
        graphics.CGContextScaleCTM(context, wide / max(natural_width, 1.0), 1.0)
        graphics.CGContextSetTextPosition(context, 0, 0)
        core_text.CTLineDraw(line, context)
        graphics.CGContextRestoreGState(context)
    finally:
        _cf.release(line)


def watermark(
    path: PathLike,
    text: str,
    output: PathLike,
    *,
    color: str = "#808080",
    opacity: float = 0.25,
    password: Optional[str] = None,
) -> Path:
    """
    Write ``text`` across every page, diagonally and see-through, and save the result to ``output``.

    For drafts and copies you share: ``"CONFIDENTIAL"``, ``"DRAFT"``, a
    name... ``color`` is a hex color and ``opacity`` goes from 0.0
    (invisible) to 1.0. The text is sized to fit each page::

        macos.pdf.watermark("contract.pdf", "DRAFT", "contract-draft.pdf")
        macos.pdf.watermark("id.pdf", "Only for Acme Inc.", "id-acme.pdf", color="#d00000", opacity=0.3)

    The pages keep their look and their text, but not their links or form
    fields, which are redrawn as they appear. ``password`` opens an
    encrypted PDF; the result isn't encrypted.
    """
    if not text.strip():
        raise ValueError("the watermark text can't be empty")
    if not 0.0 < opacity <= 1.0:
        raise ValueError("opacity must be above 0.0 and at most 1.0, not {}".format(opacity))
    red, green, blue = _color(color)
    source = _files.existing(path)
    graphics, core_text = _graphics(), _core_text()
    document = _open_for_drawing(source, password)
    try:
        pages = graphics.CGPDFDocumentGetNumberOfPages(document)
        probe, natural, _ = _line(text, 100)
        _cf.release(probe)

        def draw(context: int, index: int, width: float, height: float) -> None:
            _draw_page(graphics, context, graphics.CGPDFDocumentGetPage(document, index + 1), width, height)
            # The text along the page's diagonal, over 70% of its length.
            angle = math.atan2(height, width)
            size = 100 * 0.7 * math.hypot(width, height) / max(natural, 1.0)
            line, line_width, line_height = _line(text, size)
            try:
                graphics.CGContextSaveGState(context)
                graphics.CGContextSetRGBFillColor(context, red, green, blue, opacity)
                graphics.CGContextTranslateCTM(context, width / 2, height / 2)
                graphics.CGContextRotateCTM(context, angle)
                graphics.CGContextSetTextPosition(context, -line_width / 2, -line_height / 3)
                core_text.CTLineDraw(line, context)
                graphics.CGContextRestoreGState(context)
            finally:
                _cf.release(line)

        sizes = [_seen_size(graphics, graphics.CGPDFDocumentGetPage(document, number)) for number in range(1, pages + 1)]
        return _write_pages(output, sizes, draw)
    finally:
        graphics.CGPDFDocumentRelease(document)


def compress(path: PathLike, output: PathLike, *, password: Optional[str] = None) -> Path:
    """
    Save a smaller copy of a PDF, like Preview's *Export › Reduce File Size*, and return ``output``.

    Images are scaled down and compressed again, which makes PDFs of scans
    and photos several times smaller; text and drawings stay sharp. Photos
    lose detail, so keep the original. A PDF with no images to shrink (only
    text) can't get smaller: then ``output`` is a copy of it, never a bigger
    file. ``password`` opens an encrypted PDF; the result isn't encrypted,
    so the copy it may fall back to is the decrypted PDF, which can come
    out a little bigger than the encrypted file.
    """
    return _filtered(path, output, "Reduce File Size", password, keep_smaller=True)


def grayscale(path: PathLike, output: PathLike, *, password: Optional[str] = None) -> Path:
    """
    Save a copy of a PDF in shades of gray, for printing without color, and return ``output``.

    Uses the *Gray Tone* filter that ships with macOS, like Preview's
    *Export › Quartz Filter*. ``password`` opens an encrypted PDF; the result
    isn't encrypted.
    """
    return _filtered(path, output, "Gray Tone", password)


def _filtered(path: PathLike, output: PathLike, name: str, password: Optional[str], keep_smaller: bool = False) -> Path:
    """Write ``path`` through the Quartz filter ``name`` (from /System/Library/Filters) into ``output``."""
    framework("Quartz")
    location = "/System/Library/Filters/{}.qfilter".format(name)
    with _open(path, password) as document:
        quartz_filter = _objc.send(
            _objc.cls("QuartzFilter"), "quartzFilterWithURL:", _objc.file_url(location), argtypes=(_objc.id,)
        )
        if not quartz_filter:
            raise MacOSError("this macOS has no {} filter".format(name))
        options = _objc.send(
            _objc.cls("NSDictionary"),
            "dictionaryWithObject:forKey:",
            quartz_filter,
            _objc.nsstring("QuartzFilter"),
            argtypes=(_objc.id, _objc.id),
        )
        if not keep_smaller:
            return _save(document, output, options)
        source = Path(path).expanduser().absolute()
        encrypted = bool(_objc.send(document, "isEncrypted", restype=BOOL))
        plain = _decrypted(document)

        def write(name: str) -> bool:
            # Rewriting a PDF can make it bigger (PDFKit writes less compactly than some tools do), and the
            # filter only shrinks images: keep the original when the filtered PDF isn't smaller. An
            # encrypted original can't be kept as it is, since the result is never encrypted: its
            # decrypted copy, unfiltered, stands for it. All of it beside the output, moved in place at
            # the end, which also protects the original when the output is the input itself.
            if not _write_pdf(plain, name, options):
                return False
            if encrypted:
                fallback = name + ".unfiltered.pdf"
                if _write_pdf(plain, fallback) and os.path.getsize(fallback) < os.path.getsize(name):
                    os.replace(fallback, name)
            elif os.path.getsize(name) >= source.stat().st_size:
                shutil.copyfile(str(source), name)
            return True

        return _files.write_atomically(output, write)


def render(path: PathLike, page: int = 1, *, size: int = 1024, password: Optional[str] = None) -> bytes:
    """
    Draw a page as a PNG image and return its bytes. ``size`` is the longest side, in pixels (up to 4096).

    Combine it with :func:`macos.vision.text` to read scanned PDFs::

        macos.vision.text(macos.pdf.render("scan.pdf", page=1, size=2048))
    """
    if not 0 < size <= _MAX_RENDER:
        raise ValueError("size must be from 1 to {}, not {}".format(_MAX_RENDER, size))
    framework("AppKit")
    with _open(path, password) as document:
        target = _page(document, page)
        bounds = _objc.send(target, "boundsForBox:", _CROP_BOX, argtypes=(ctypes.c_long,), restype=_objc.CGRect)
        width, height = bounds.size.width, bounds.size.height
        # A page with /Rotate 90 or 270 is drawn turned: fit the turned shape.
        if _objc.send(target, "rotation", restype=ctypes.c_long) % 180:
            width, height = height, width
        scale = size / (max(width, height) or 1.0)
        # PDFKit rounds the image size down: the extra half pixel makes the
        # longest side come out at exactly `size`.
        box = _objc.CGSize(width * scale + 0.5, height * scale + 0.5)
        image = _objc.send(
            target, "thumbnailOfSize:forBox:", box, _CROP_BOX, argtypes=(_objc.CGSize, ctypes.c_long)
        )
        tiff = _objc.send(image, "TIFFRepresentation")
        rep = _objc.send(_objc.cls("NSBitmapImageRep"), "imageRepWithData:", tiff, argtypes=(_objc.id,))
        if not rep:
            raise MacOSError("page {} could not be drawn".format(page))
        return _objc.png(rep)


@lru_cache(maxsize=None)
def _graphics() -> ctypes.CDLL:
    graphics = framework("CoreGraphics")
    pointer = ctypes.c_void_p
    rect = ctypes.POINTER(_objc.CGRect)
    signatures = {
        "CGPDFContextCreateWithURL": ((pointer, rect, pointer), pointer),
        "CGContextBeginPage": ((pointer, rect), None),
        "CGContextEndPage": ((pointer,), None),
        "CGPDFContextClose": ((pointer,), None),
        "CGContextRelease": ((pointer,), None),
        "CGContextSaveGState": ((pointer,), None),
        "CGContextRestoreGState": ((pointer,), None),
        "CGContextConcatCTM": ((pointer, _objc.CGAffineTransform), None),
        "CGContextDrawImage": ((pointer, _objc.CGRect, pointer), None),
        "CGImageGetWidth": ((pointer,), ctypes.c_size_t),
        "CGImageGetHeight": ((pointer,), ctypes.c_size_t),
        "CGPDFDocumentCreateWithURL": ((pointer,), pointer),
        "CGPDFDocumentIsEncrypted": ((pointer,), ctypes.c_bool),
        "CGPDFDocumentIsUnlocked": ((pointer,), ctypes.c_bool),
        "CGPDFDocumentUnlockWithPassword": ((pointer, ctypes.c_char_p), ctypes.c_bool),
        "CGPDFDocumentGetNumberOfPages": ((pointer,), ctypes.c_size_t),
        "CGPDFDocumentGetPage": ((pointer, ctypes.c_size_t), pointer),
        "CGPDFDocumentRelease": ((pointer,), None),
        "CGPDFPageGetBoxRect": ((pointer, ctypes.c_int), _objc.CGRect),
        "CGPDFPageGetRotationAngle": ((pointer,), ctypes.c_int),
        "CGPDFPageGetDrawingTransform": (
            (pointer, ctypes.c_int, _objc.CGRect, ctypes.c_int, ctypes.c_bool),
            _objc.CGAffineTransform,
        ),
        "CGContextDrawPDFPage": ((pointer, pointer), None),
        "CGContextSetRGBFillColor": ((pointer, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double), None),
        "CGContextTranslateCTM": ((pointer, ctypes.c_double, ctypes.c_double), None),
        "CGContextRotateCTM": ((pointer, ctypes.c_double), None),
        "CGContextSetTextPosition": ((pointer, ctypes.c_double, ctypes.c_double), None),
        "CGContextSetTextDrawingMode": ((pointer, ctypes.c_int32), None),
        "CGContextScaleCTM": ((pointer, ctypes.c_double, ctypes.c_double), None),
        "CGContextFillRect": ((pointer, _objc.CGRect), None),
        "CGContextClipToRect": ((pointer, _objc.CGRect), None),
        "CGColorSpaceCreateDeviceRGB": ((), pointer),
        "CGColorSpaceRelease": ((pointer,), None),
        "CGBitmapContextCreate": (
            (pointer, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, pointer, ctypes.c_uint32),
            pointer,
        ),
        "CGBitmapContextCreateImage": ((pointer,), pointer),
        "CGImageRelease": ((pointer,), None),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(graphics, name)
        function.argtypes = argtypes
        function.restype = restype
    return graphics


def _upright_transform(orientation: int, width: float, height: float) -> Tuple[float, ...]:
    """
    The transform that draws a ``width`` x ``height`` image stored with EXIF ``orientation`` upright.

    Core Graphics measures from the bottom-left corner, with y going up.
    """
    return {
        2: (-1, 0, 0, 1, width, 0),  # mirrored left to right
        3: (-1, 0, 0, -1, width, height),  # upside down
        4: (1, 0, 0, -1, 0, height),  # mirrored top to bottom
        5: (0, -1, -1, 0, height, width),  # transposed
        6: (0, -1, 1, 0, 0, width),  # needs a quarter turn clockwise
        7: (0, 1, 1, 0, 0, 0),  # transversed
        8: (0, 1, -1, 0, height, 0),  # needs a quarter turn counter-clockwise
    }.get(orientation, (1, 0, 0, 1, 0, 0))


def _image_source(image: Union[PathLike, bytes]) -> Tuple[int, str]:
    """An owned ``CGImageSource`` for a path or image bytes, and how to name it in errors."""
    from . import image as images

    if isinstance(image, (bytes, bytearray)):
        with _cf.owned(_cf.data(bytes(image))) as payload:
            source = images._io().CGImageSourceCreateWithData(payload, None)
        if not source or not images._io().CGImageSourceGetCount(source):
            _cf.release(source)
            raise ValueError("the bytes are not an image macOS can read")
        return source, "image bytes"
    return images._source(image), str(Path(image).expanduser().absolute())


def from_images(images: Sequence[Union[PathLike, bytes]], output: PathLike) -> Path:
    """
    Make a PDF with one page per image, in order, and return its path.

    Any format macOS opens works (JPEG, PNG, HEIC...). Each page takes the size
    of its image, turned upright, so photos of documents become the pages of a
    scan::

        pages = [macos.vision.scan_document(photo) for photo in photos]
        macos.pdf.from_images(pages, "scan.pdf")

    ``images`` may also hold PNG/JPEG bytes, such as :func:`macos.vision.scan_document` returns.
    JPEG photos are embedded as they are, without compressing them again.
    """
    if not images:
        raise ValueError("from_images() needs at least one image")
    from . import image as image_module

    io = image_module._io()
    graphics = _graphics()
    # Read every image first, so a bad one fails before anything is written.
    pictures = []
    try:
        for image in images:
            source, label = _image_source(image)
            with _cf.owned(source):
                orientation = image_module._describe(source).orientation
                picture = io.CGImageSourceCreateImageAtIndex(source, 0, None)
            if not picture:
                raise ValueError("{} is not an image macOS can read".format(label))
            pictures.append((picture, orientation))

        def stored(picture: int) -> Tuple[float, float]:
            return float(graphics.CGImageGetWidth(picture)), float(graphics.CGImageGetHeight(picture))

        def draw(context: int, index: int, page_width: float, page_height: float) -> None:
            picture, orientation = pictures[index]
            width, height = stored(picture)
            graphics.CGContextSaveGState(context)
            graphics.CGContextConcatCTM(context, _objc.CGAffineTransform(*_upright_transform(orientation, width, height)))
            graphics.CGContextDrawImage(context, _objc.CGRect(_objc.CGPoint(0, 0), _objc.CGSize(width, height)), picture)
            graphics.CGContextRestoreGState(context)

        sizes = []
        for picture, orientation in pictures:
            width, height = stored(picture)
            sizes.append((height, width) if orientation in (5, 6, 7, 8) else (width, height))
        return _write_pages(output, sizes, draw)
    finally:
        for picture, _ in pictures:
            _cf.release(picture)


# --- Forms ----------------------------------------------------------------------

_FIELD_KINDS = {"/Tx": "text", "/Ch": "choice", "/Sig": "signature"}
_BUTTON_KINDS = {0: "button", 1: "radio", 2: "checkbox"}  # PDFWidgetControlType


@dataclass(frozen=True)
class FormField:
    """A field of a PDF form."""

    name: str
    kind: str
    """``'text'``, ``'checkbox'``, ``'radio'``, ``'choice'`` (a list or a menu), ``'button'`` or ``'signature'``."""
    value: Union[str, bool, None]
    """The text or choice filled in, whether a checkbox is ticked, the radio button chosen; ``None`` when empty."""
    options: Tuple[str, ...]
    """What a choice or a group of radio buttons offers; ``()`` for the others."""
    page: int
    """The page it's on, from 1."""


def _widgets(document: int) -> Iterator[Tuple[int, int]]:
    """``(page number, widget annotation)`` for every form field's widget, in page order."""
    for number in range(1, _count(document) + 1):
        page = _page(document, number)
        for annotation in _objc.nsarray(_objc.send(page, "annotations")):
            kind = _objc.pystring(_objc.send(annotation, "type")) or ""
            name = _objc.pystring(_objc.send(annotation, "fieldName"))
            if kind == "Widget" and name:
                yield number, annotation


def _kind(widget: int) -> str:
    field_type = _objc.pystring(_objc.send(widget, "widgetFieldType")) or ""
    if field_type == "/Btn":
        return _BUTTON_KINDS.get(int(_objc.send(widget, "widgetControlType", restype=ctypes.c_long)), "button")
    return _FIELD_KINDS.get(field_type, "text")


def _state(widget: int) -> bool:
    return bool(_objc.send(widget, "buttonWidgetState", restype=ctypes.c_long))


def _on_value(widget: int) -> str:
    """The value a radio button stands for (its "on" state's name)."""
    return _objc.pystring(_objc.send(widget, "buttonWidgetStateString")) or ""


def form_fields(path: PathLike, *, password: Optional[str] = None) -> List[FormField]:
    """
    The fields of a PDF form, in page order, with what's filled in.

    ::

        for field in macos.pdf.form_fields("application.pdf"):
            print(field.name, field.kind, field.value)   # "Full name" text None, "Agree" checkbox False, ...

    Fill them with :func:`fill_form`.
    """
    fields: Dict[str, FormField] = {}
    with _open(path, password) as document:
        for number, widget in _widgets(document):
            name = _objc.pystring(_objc.send(widget, "fieldName")) or ""
            kind = _kind(widget)
            if kind == "radio":
                # The buttons of a group share its name: the field's value is the one chosen.
                known = fields.get(name)
                group = (known.options if known else ()) + (_on_value(widget),)
                chosen = _on_value(widget) if _state(widget) else (known.value if known else None)
                fields[name] = FormField(name, kind, chosen, group, known.page if known else number)
                continue
            if name in fields:
                continue  # the same field shown again, on another page
            if kind == "checkbox":
                value: Union[str, bool, None] = _state(widget)
            elif kind in ("button", "signature"):
                value = None
            else:
                value = _objc.pystring(_objc.send(widget, "widgetStringValue")) or None
            options: Tuple[str, ...] = ()
            if kind == "choice":
                options = tuple(_objc.pystring(item) or "" for item in _objc.nsarray(_objc.send(widget, "choices")))
            fields[name] = FormField(name, kind, value, options, number)
    return list(fields.values())


def fill_form(
    path: PathLike,
    values: Mapping[str, Union[str, bool]],
    output: PathLike,
    *,
    password: Optional[str] = None,
) -> Path:
    """
    Fill in a PDF form's fields by name, and save it to ``output``; the fields stay editable.

    ::

        macos.pdf.fill_form("application.pdf", {"Full name": "Jane Doe", "Agree": True, "Plan": "Pro"}, "filled.pdf")

    Text fields and choices take text; checkboxes ``True`` or ``False``; a
    group of radio buttons the option to choose. The names are those
    :func:`form_fields` gives; an unknown one, or an option a field doesn't
    offer, raises :class:`ValueError` before anything is written.
    """
    known = {field.name: field for field in form_fields(path, password=password)}
    for name, value in values.items():
        field = known.get(name)
        if field is None:
            raise ValueError("the form has no field named {!r}; see macos.pdf.form_fields()".format(name))
        if field.kind == "checkbox" and not isinstance(value, bool):
            raise ValueError("{!r} is a checkbox: pass True or False, not {!r}".format(name, value))
        if field.kind in ("text", "choice", "radio") and not isinstance(value, str):
            raise ValueError("{!r} takes text, not {!r}".format(name, value))
        if field.kind in ("radio", "choice") and field.options and value not in field.options:
            raise ValueError("{!r} offers {}, not {!r}".format(name, ", ".join(field.options), value))
        if field.kind in ("button", "signature"):
            raise ValueError("{!r} is a {} field: it can't be filled in".format(name, field.kind))
    with _open(path, password) as document:
        for _, widget in _widgets(document):
            name = _objc.pystring(_objc.send(widget, "fieldName")) or ""
            if name not in values:
                continue
            value, kind = values[name], known[name].kind
            if kind == "checkbox":
                _objc.send(widget, "setButtonWidgetState:", 1 if value else 0, argtypes=(ctypes.c_long,), restype=None)
            elif kind == "radio":
                chosen = 1 if _on_value(widget) == value else 0
                _objc.send(widget, "setButtonWidgetState:", chosen, argtypes=(ctypes.c_long,), restype=None)
            else:
                _objc.send(widget, "setWidgetStringValue:", _objc.nsstring(str(value)), argtypes=(_objc.id,), restype=None)
        return _save(document, output)


# --- Signing --------------------------------------------------------------------

_CORNERS = ("bottom_right", "bottom_left", "top_right", "top_left")
Position = Union[str, Tuple[float, float]]


def _check_position(position: Position) -> None:
    if isinstance(position, str) and position not in _CORNERS:
        raise ValueError("position must be one of {} or (x, y), not {!r}".format(", ".join(_CORNERS), position))


def _unrotated(box: Tuple[float, float, float, float], width: float, height: float, rotation: int) -> Tuple[float, ...]:
    """
    A box ``(x, y, w, h)`` on the page as it's seen, turned by ``rotation``, in the page's own (unrotated) coordinates.

    ``width`` and ``height`` are the unrotated page's; the result's w and h swap at 90 and 270 degrees.
    """
    x, y, w, h = box
    turn = rotation % 360
    if turn == 90:
        return width - y - h, x, h, w
    if turn == 180:
        return width - x - w, height - y - h, w, h
    if turn == 270:
        return y, height - x - w, h, w
    return x, y, w, h


def _seen(box: Tuple[float, float, float, float], width: float, height: float, rotation: int) -> Tuple[float, ...]:
    """The inverse of :func:`_unrotated`: a box in the page's own coordinates, as the page is seen."""
    x, y, w, h = box
    turn = rotation % 360
    if turn == 90:
        return y, width - x - w, h, w
    if turn == 180:
        return width - x - w, height - y - h, w, h
    if turn == 270:
        return height - y - h, x, h, w
    return x, y, w, h


_SIDES = ("right", "left", "above", "below")
_CASE_INSENSITIVE = 1  # NSCaseInsensitiveSearch


def _find(document: int, text: str, page: Optional[int]) -> Tuple[int, Tuple[float, ...]]:
    """
    Where ``text`` first shows, on ``page`` or anywhere: its page number, and its box as the page is seen.
    """
    if not text.strip():
        raise ValueError("near must not be empty")
    count = _count(document)
    if page is not None:
        _page(document, page)  # checks the number
    found = _objc.send(
        document, "findString:withOptions:", _objc.nsstring(text), _CASE_INSENSITIVE, argtypes=(_objc.id, NSUInteger)
    )
    for selection in _objc.nsarray(found) if found else []:
        for candidate in _objc.nsarray(_objc.send(selection, "pages")):
            number = int(_objc.send(document, "indexForPage:", candidate, argtypes=(_objc.id,), restype=NSUInteger)) + 1
            if not 1 <= number <= count or (page is not None and number != page):
                continue
            box = _objc.send(selection, "boundsForPage:", candidate, argtypes=(_objc.id,), restype=_objc.CGRect)
            # From the crop box's corner, as sign() and add_text() place things.
            bounds = _objc.send(candidate, "boundsForBox:", _CROP_BOX, argtypes=(ctypes.c_long,), restype=_objc.CGRect)
            rotation = int(_objc.send(candidate, "rotation", restype=ctypes.c_long))
            own = (box.origin.x - bounds.origin.x, box.origin.y - bounds.origin.y, box.size.width, box.size.height)
            return number, _seen(own, bounds.size.width, bounds.size.height, rotation)
    where = "page {}".format(page) if page is not None else "the PDF"
    raise ValueError("{!r} isn't on {}: see macos.pdf.text() for what it holds".format(text, where))


def _next_to(anchor: Tuple[float, ...], width: float, height: float, side: str, gap: float) -> Tuple[float, float]:
    """Where a box of ``width`` × ``height`` goes beside ``anchor`` (a box as the page is seen), ``gap`` points away."""
    x, y, w, h = anchor
    if side == "right":
        return x + w + gap, y + (h - height) / 2
    if side == "left":
        return x - gap - width, y + (h - height) / 2
    if side == "above":
        return x, y + h + gap
    return x, y - gap - height  # below


def _check_near(near: Optional[str], position: Optional[Position], side: str) -> None:
    if near is not None and position is not None:
        raise ValueError("give position or near, not both")
    if side not in _SIDES:
        raise ValueError("side must be one of {}, not {!r}".format(", ".join(_SIDES), side))


def _origin(
    position: Position, width: float, height: float, page_width: float, page_height: float, margin: float
) -> Tuple[float, float]:
    """Where a box of ``width`` × ``height`` goes: its bottom-left corner, in points from the page's bottom-left."""
    if isinstance(position, tuple):
        return float(position[0]), float(position[1])
    x = margin if position.endswith("left") else page_width - margin - width
    y = margin if position.startswith("bottom") else page_height - margin - height
    return x, y


def sign(
    path: PathLike,
    image: PathLike,
    output: PathLike,
    *,
    page: Optional[int] = None,
    position: Optional[Position] = None,
    near: Optional[str] = None,
    side: str = "right",
    gap: float = 8,
    width: float = 150,
    margin: float = 36,
    password: Optional[str] = None,
) -> Path:
    """
    Put an image of a signature (or a stamp, a logo) on a page, and save the result to ``output``.

    ::

        macos.pdf.sign("contract.pdf", "signature.png", "signed.pdf")                   # last page, bottom right
        macos.pdf.sign("form.pdf", "signature.png", "signed.pdf", page=1, position=(72, 120), width=180)
        macos.pdf.sign("contract.pdf", "signature.png", "signed.pdf", near="Signature:")   # beside that text

    ``near`` puts it beside a text of the page, found as :func:`text`
    reads it (case doesn't matter): to its ``side``, ``"right"``, ``"left"``,
    ``"above"`` or ``"below"``, ``gap`` points away. It searches ``page``
    when given, else the whole PDF, and takes the first match.

    ``page`` is from 1; the last one by default. ``position`` is a corner
    (``"bottom_right"``, ``"bottom_left"``, ``"top_right"``, ``"top_left"``,
    ``margin`` points from the edges) or the ``(x, y)`` of the image's
    bottom-left corner, in points from the page's bottom-left. ``width`` is
    in points (72 per inch); the height keeps the image's proportions. A PNG
    with a transparent background looks best.

    It's an image, not a cryptographic signature. The pages are redrawn
    as they look, filled-in form fields included, so they're no longer
    editable, and links go: fill the form first, with :func:`fill_form`.
    """
    from . import image as images

    if width <= 0:
        raise ValueError("width must be positive, not {}".format(width))
    _check_near(near, position, side)
    corner: Position = position if position is not None else "bottom_right"
    _check_position(corner)
    source, _ = _image_source(image)
    with _cf.owned(source):
        picture = images._io().CGImageSourceCreateImageAtIndex(source, 0, None)
    if not picture:
        raise ValueError("{} is not an image macOS can read".format(image))
    graphics = _graphics()
    try:
        with _open(path, password) as document:
            count = _count(document)
            anchor: Optional[Tuple[float, ...]] = None
            if near is not None:
                target, anchor = _find(document, near, page)
            else:
                target = count if page is None else page
                _page(document, target)  # checks the number
            aspect = graphics.CGImageGetHeight(picture) / max(graphics.CGImageGetWidth(picture), 1)

            def seen(number: int) -> Tuple[float, float]:
                bounds = _objc.send(
                    _page(document, number), "boundsForBox:", _CROP_BOX, argtypes=(ctypes.c_long,), restype=_objc.CGRect
                )
                if _objc.send(_page(document, number), "rotation", restype=ctypes.c_long) % 180:
                    return bounds.size.height, bounds.size.width
                return bounds.size.width, bounds.size.height

            def draw(context: int, index: int, page_width: float, page_height: float) -> None:
                # PDFKit draws the page as it looks: its crop box, rotation and form fields included.
                _objc.send(
                    _page(document, index + 1),
                    "drawWithBox:toContext:",
                    _CROP_BOX,
                    context,
                    argtypes=(ctypes.c_long, _objc.id),
                    restype=None,
                )
                if index + 1 == target:
                    size = _objc.CGSize(width, width * aspect)
                    if anchor is not None:
                        x, y = _next_to(anchor, size.width, size.height, side, gap)
                    else:
                        x, y = _origin(corner, size.width, size.height, page_width, page_height, margin)
                    graphics.CGContextDrawImage(context, _objc.CGRect(_objc.CGPoint(x, y), size), picture)

            return _write_pages(output, [seen(number) for number in range(1, count + 1)], draw)
    finally:
        _cf.release(picture)


# --- Adding text --------------------------------------------------------------


def add_text(
    path: PathLike,
    text: str,
    output: PathLike,
    *,
    page: Optional[int] = None,
    position: Optional[Position] = None,
    near: Optional[str] = None,
    side: str = "right",
    gap: float = 6,
    size: float = 12,
    color: str = "#000000",
    font: Optional[str] = None,
    margin: float = 36,
    password: Optional[str] = None,
) -> Path:
    """
    Write ``text`` on a page, as a text box you can still edit or move in Preview, and save the result to ``output``.

    ::

        macos.pdf.add_text("contract.pdf", "Received on 29/09/2026", "stamped.pdf")            # page 1, top left
        macos.pdf.add_text("form.pdf", "Jane Doe", "filled.pdf", page=2, position=(120, 540), size=14)
        macos.pdf.add_text("form.pdf", "Jane Doe", "filled.pdf", near="Name:")                  # right after that text
        macos.pdf.add_text("draft.pdf", "Checked\\nby Ana", "notes.pdf", position="top_right", color="#c00000")

    ``page`` is from 1; the first one by default. ``position``, ``near``,
    ``side`` and ``gap`` work as for :func:`sign`: a corner, ``margin`` points from
    the edges, or the ``(x, y)`` of the text's bottom-left corner, in points
    from the page's bottom-left. ``size`` is in points; ``font`` a font's
    name, such as ``"Helvetica-Bold"`` (the system font by default); ``color``
    a hex color. Lines break at ``\\n``. The page's own text is left as it
    is: this adds to it.
    """
    if not text.strip():
        raise ValueError("text must not be empty")
    if size <= 0:
        raise ValueError("size must be positive, not {}".format(size))
    _check_near(near, position, side)
    corner: Position = position if position is not None else "top_left"
    _check_position(corner)
    red, green, blue = _color(color)
    framework("AppKit")
    with _open(path, password) as document:
        anchor: Optional[Tuple[float, ...]] = None
        if near is not None:
            number, anchor = _find(document, near, page)
        else:
            number = 1 if page is None else page
        target = _page(document, number)
        if font is None:
            typeface = _objc.send(_objc.cls("NSFont"), "systemFontOfSize:", float(size), argtypes=(ctypes.c_double,))
        else:
            typeface = _objc.send(
                _objc.cls("NSFont"), "fontWithName:size:", _objc.nsstring(font), float(size), argtypes=(_objc.id, ctypes.c_double)
            )
            if not typeface:
                raise ValueError("no font is named {!r}; see macos.system.fonts()".format(font))
        ink = _objc.send(
            _objc.cls("NSColor"),
            "colorWithSRGBRed:green:blue:alpha:",
            red,
            green,
            blue,
            1.0,
            argtypes=(ctypes.c_double,) * 4,
        )
        # Measure the text as it will be drawn, to size the box around it.
        attributes = _objc.send(
            _objc.cls("NSDictionary"),
            "dictionaryWithObject:forKey:",
            typeface,
            _objc.nsstring("NSFont"),
            argtypes=(_objc.id, _objc.id),
        )
        measured = _objc.send(
            _objc.send(_objc.cls("NSAttributedString"), "alloc"),
            "initWithString:attributes:",
            _objc.nsstring(text),
            attributes,
            argtypes=(_objc.id, _objc.id),
        )
        _objc.send(measured, "autorelease")
        extent = _objc.send(measured, "size", restype=_objc.CGSize)
        width, height = extent.width + 8, extent.height + 4  # a little room: FreeText boxes pad their text
        # The corners of the page as it shows: a cropped page's corners aren't its media box's.
        bounds = _objc.send(target, "boundsForBox:", _CROP_BOX, argtypes=(ctypes.c_long,), restype=_objc.CGRect)
        # Place it on the page as it's seen: a rotated page's corners aren't its unrotated ones.
        rotation = int(_objc.send(target, "rotation", restype=ctypes.c_long))
        seen = (bounds.size.height, bounds.size.width) if rotation % 180 else (bounds.size.width, bounds.size.height)
        if anchor is not None:
            x, y = _next_to(anchor, width, height, side, gap)
        else:
            x, y = _origin(corner, width, height, seen[0], seen[1], margin)
        # PDFKit keeps a text box's text upright as the page is seen: give it the box in page coordinates.
        left, bottom, across, up = _unrotated((x, y, width, height), bounds.size.width, bounds.size.height, rotation)
        box = _objc.CGRect(_objc.CGPoint(bounds.origin.x + left, bounds.origin.y + bottom), _objc.CGSize(across, up))
        note = _objc.send(
            _objc.send(_objc.cls("PDFAnnotation"), "alloc"),
            "initWithBounds:forType:withProperties:",
            box,
            _objc.nsstring("FreeText"),
            None,
            argtypes=(_objc.CGRect, _objc.id, _objc.id),
        )
        _objc.send(note, "autorelease")
        _objc.send(note, "setContents:", _objc.nsstring(text), argtypes=(_objc.id,), restype=None)
        _objc.send(note, "setFont:", typeface, argtypes=(_objc.id,), restype=None)
        _objc.send(note, "setFontColor:", ink, argtypes=(_objc.id,), restype=None)
        clear = _objc.send(_objc.cls("NSColor"), "clearColor")
        _objc.send(note, "setColor:", clear, argtypes=(_objc.id,), restype=None)  # no background
        border = _objc.send(_objc.send(_objc.cls("PDFBorder"), "alloc"), "init")
        _objc.send(border, "autorelease")
        _objc.send(border, "setLineWidth:", 0.0, argtypes=(ctypes.c_double,), restype=None)
        _objc.send(note, "setBorder:", border, argtypes=(_objc.id,), restype=None)
        _objc.send(target, "addAnnotation:", note, argtypes=(_objc.id,), restype=None)
        return _save(document, output)


# --- Bookmarks ---------------------------------------------------------------------


@dataclass(frozen=True)
class Bookmark:
    """An entry of a PDF's table of contents (its outline), as the sidebar shows it."""

    title: str
    page: int
    """The page it opens, from 1; 0 when it points nowhere in the document."""
    level: int = 0
    """How deep it sits: 0 for a chapter, 1 for its sections, and so on."""


def bookmarks(path: PathLike, *, password: Optional[str] = None) -> List[Bookmark]:
    """
    A PDF's table of contents, in order, sections under their chapter: ``[]`` when it has none.

    ::

        for mark in macos.pdf.bookmarks("book.pdf"):
            print("  " * mark.level + mark.title, mark.page)
    """
    found: List[Bookmark] = []

    def walk(outline: int, level: int, document: int) -> None:
        for index in range(int(_objc.send(outline, "numberOfChildren", restype=NSUInteger))):
            child = _objc.send(outline, "childAtIndex:", index, argtypes=(NSUInteger,))
            destination = _objc.send(child, "destination")
            target = _objc.send(destination, "page") if destination else None
            number = 0
            if target:
                index = int(_objc.send(document, "indexForPage:", target, argtypes=(_objc.id,), restype=NSUInteger))
                number = index + 1 if index < _count(document) else 0  # NSNotFound: a page of another document
            found.append(Bookmark(_objc.pystring(_objc.send(child, "label")) or "", number, level))
            walk(child, level + 1, document)

    with _open(path, password) as document:
        root = _objc.send(document, "outlineRoot")
        if root:
            walk(root, 0, document)
    return found


def set_bookmarks(
    path: PathLike,
    marks: Sequence[Union[Bookmark, Tuple[str, int], Tuple[str, int, int]]],
    output: PathLike,
    *,
    password: Optional[str] = None,
) -> Path:
    """
    Give a PDF a table of contents, in place of the one it has, and save it to ``output``.

    ::

        macos.pdf.set_bookmarks("book.pdf", [
            ("Introduction", 1),
            ("Chapter 1", 3),
            ("1.1 Getting started", 4, 1),     # (title, page, level): a section of Chapter 1
            ("Chapter 2", 12),
        ], "book-with-contents.pdf")

    Each entry is ``(title, page)``, ``(title, page, level)`` or a
    :class:`Bookmark`; pages are from 1, and a level may go at most one
    deeper than the entry before it. An empty list takes the contents away.
    """
    entries = [mark if isinstance(mark, Bookmark) else Bookmark(*mark) for mark in marks]
    previous = -1
    for entry in entries:
        if not entry.title.strip():
            raise ValueError("a bookmark's title must not be empty")
        if entry.level < 0 or entry.level > previous + 1:
            raise ValueError("{!r} is at level {}, deeper than the entry before it allows".format(entry.title, entry.level))
        previous = entry.level
    with _open(path, password) as document:
        pages = [_page(document, entry.page) for entry in entries]  # checks every number first
        root = _objc.send(_objc.send(_objc.cls("PDFOutline"), "alloc"), "init")
        _objc.send(root, "autorelease")
        parents = [root]
        for entry, page in zip(entries, pages):
            del parents[entry.level + 1:]
            outline = _objc.send(_objc.send(_objc.cls("PDFOutline"), "alloc"), "init")
            _objc.send(outline, "autorelease")
            _objc.send(outline, "setLabel:", _objc.nsstring(entry.title), argtypes=(_objc.id,), restype=None)
            # Opens at the top-left corner of the page as it's shown: its visible part (the crop box),
            # turned by its rotation, back into the page's own coordinates.
            bounds = _objc.send(page, "boundsForBox:", _CROP_BOX, argtypes=(ctypes.c_long,), restype=_objc.CGRect)
            rotation = int(_objc.send(page, "rotation", restype=ctypes.c_long))
            width, height = bounds.size.width, bounds.size.height
            shown_height = height if rotation % 180 == 0 else width
            x, y, _, _ = _unrotated((0, shown_height, 0, 0), width, height, rotation)
            top = _objc.CGPoint(bounds.origin.x + x, bounds.origin.y + y)
            destination = _objc.send(
                _objc.send(_objc.cls("PDFDestination"), "alloc"),
                "initWithPage:atPoint:",
                page,
                top,
                argtypes=(_objc.id, _objc.CGPoint),
            )
            _objc.send(destination, "autorelease")
            _objc.send(outline, "setDestination:", destination, argtypes=(_objc.id,), restype=None)
            parent = parents[-1]
            count = int(_objc.send(parent, "numberOfChildren", restype=NSUInteger))
            _objc.send(parent, "insertChild:atIndex:", outline, count, argtypes=(_objc.id, NSUInteger), restype=None)
            parents.append(outline)
        # An empty root, not nil: PDFKit keeps the old outline when given nil.
        _objc.send(document, "setOutlineRoot:", root, argtypes=(_objc.id,), restype=None)
        return _save(document, output)


# --- Embedded images ----------------------------------------------------------------

_STREAM = 9  # kCGPDFObjectTypeStream
_RAW, _JPEG, _JPEG2000 = 0, 1, 2  # CGPDFDataFormat
_COMPONENTS = {b"DeviceRGB": 3, b"DeviceGray": 1, b"DeviceCMYK": 4}
_CALIBRATED = {b"CalRGB": 3, b"CalGray": 1}  # written as arrays: [/CalRGB << ... >>], drawn here as device colors
_Visitor = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p)
_INVERTED = bytes(range(255, -1, -1))  # each 8-bit sample s becomes 255 - s, through bytes.translate


@lru_cache(maxsize=None)
def _pdf_objects() -> ctypes.CDLL:
    graphics = _graphics()
    pointer = ctypes.c_void_p
    signatures = {
        "CGPDFPageGetDictionary": ((pointer,), pointer),
        "CGPDFDictionaryGetDictionary": ((pointer, ctypes.c_char_p, ctypes.POINTER(pointer)), ctypes.c_bool),
        "CGPDFDictionaryGetName": ((pointer, ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p)), ctypes.c_bool),
        "CGPDFDictionaryGetInteger": ((pointer, ctypes.c_char_p, ctypes.POINTER(ctypes.c_long)), ctypes.c_bool),
        "CGPDFDictionaryGetArray": ((pointer, ctypes.c_char_p, ctypes.POINTER(pointer)), ctypes.c_bool),
        "CGPDFArrayGetName": ((pointer, ctypes.c_size_t, ctypes.POINTER(ctypes.c_char_p)), ctypes.c_bool),
        "CGPDFArrayGetStream": ((pointer, ctypes.c_size_t, ctypes.POINTER(pointer)), ctypes.c_bool),
        "CGPDFArrayGetCount": ((pointer,), ctypes.c_size_t),
        "CGPDFArrayGetNumber": ((pointer, ctypes.c_size_t, ctypes.POINTER(ctypes.c_double)), ctypes.c_bool),
        "CGPDFDictionaryApplyFunction": ((pointer, _Visitor, pointer), None),
        "CGPDFObjectGetValue": ((pointer, ctypes.c_int, pointer), ctypes.c_bool),
        "CGPDFStreamGetDictionary": ((pointer,), pointer),
        "CGPDFStreamCopyData": ((pointer, ctypes.POINTER(ctypes.c_int)), pointer),
        "CGDataProviderCreateWithCFData": ((pointer,), pointer),
        "CGDataProviderRelease": ((pointer,), None),
        "CGColorSpaceCreateDeviceGray": ((), pointer),
        "CGColorSpaceCreateDeviceCMYK": ((), pointer),
        "CGImageCreate": (
            (ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, pointer, ctypes.c_uint32,
             pointer, pointer, ctypes.c_bool, ctypes.c_int),
            pointer,
        ),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(graphics, name)
        function.argtypes = argtypes
        function.restype = restype
    return graphics


def _natural(name: bytes) -> List[Union[int, str]]:
    """A key sorting names as people do: ``Im2`` before ``Im10``."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name.decode("latin-1"))]


def _components(graphics: ctypes.CDLL, info: int) -> Optional[int]:
    """How many color components an image has, for the color spaces it can rebuild; ``None`` for the others."""
    name = ctypes.c_char_p()
    if graphics.CGPDFDictionaryGetName(info, b"ColorSpace", ctypes.byref(name)):
        return _COMPONENTS.get(name.value or b"")
    array = ctypes.c_void_p()
    if graphics.CGPDFDictionaryGetArray(info, b"ColorSpace", ctypes.byref(array)):
        kind = ctypes.c_char_p()
        profile = ctypes.c_void_p()
        if graphics.CGPDFArrayGetName(array, 0, ctypes.byref(kind)) and kind.value in _CALIBRATED:
            return _CALIBRATED[kind.value]
        if (
            kind.value == b"ICCBased"
            and graphics.CGPDFArrayGetStream(array, 1, ctypes.byref(profile))
        ):
            count = ctypes.c_long()
            if graphics.CGPDFDictionaryGetInteger(graphics.CGPDFStreamGetDictionary(profile), b"N", ctypes.byref(count)):
                return int(count.value) if count.value in (1, 3, 4) else None
    return None


def _decode(graphics: ctypes.CDLL, info: int, components: int) -> Optional[str]:
    """
    How an image's /Decode maps its samples: ``"default"``, ``"inverted"``, or ``None`` for another mapping.

    [1 0] per component (common for masks and scans) is an inversion; anything else isn't rebuilt.
    """
    array = ctypes.c_void_p()
    if not graphics.CGPDFDictionaryGetArray(info, b"Decode", ctypes.byref(array)):
        return "default"
    values = []
    for index in range(graphics.CGPDFArrayGetCount(array)):
        value = ctypes.c_double()
        if not graphics.CGPDFArrayGetNumber(array, index, ctypes.byref(value)):
            return None
        values.append(value.value)
    if values == [0.0, 1.0] * components:
        return "default"
    if values == [1.0, 0.0] * components:
        return "inverted"
    return None


def _save_image(graphics: ctypes.CDLL, stream: int, target: Path) -> Optional[Path]:
    """Write an image XObject's picture to ``target`` (its suffix set here), or ``None`` for a kind it can't rebuild."""
    from . import image as images

    kind = ctypes.c_int()
    data = graphics.CGPDFStreamCopyData(stream, ctypes.byref(kind))
    if not data:
        return None
    with _cf.owned(data):
        if kind.value in (_JPEG, _JPEG2000):
            path = target.with_suffix(".jpg" if kind.value == _JPEG else ".jp2")
            path.write_bytes(_cf.to_bytes(data))  # as embedded, without compressing it again
            return path
        info = graphics.CGPDFStreamGetDictionary(stream)
        numbers = {}
        for key in (b"Width", b"Height", b"BitsPerComponent"):
            value = ctypes.c_long()
            if not graphics.CGPDFDictionaryGetInteger(info, key, ctypes.byref(value)):
                return None
            numbers[key] = int(value.value)
        components = _components(graphics, info)
        width, height, bits = numbers[b"Width"], numbers[b"Height"], numbers[b"BitsPerComponent"]
        if components is None or bits != 8 or width <= 0 or height <= 0:
            return None  # an indexed palette, a mask...: kinds it doesn't rebuild
        if _cf.lib().CFDataGetLength(data) < width * height * components:
            return None
        mapping = _decode(graphics, info, components)
        if mapping is None:
            return None  # a sample mapping these images can't be drawn with
        pixels = data
        if mapping == "inverted":
            # A new buffer with the samples flipped; the original stays with its owner above.
            pixels = _cf.data(_cf.to_bytes(data)[: width * height * components].translate(_INVERTED))
        create = {1: "CGColorSpaceCreateDeviceGray", 3: "CGColorSpaceCreateDeviceRGB", 4: "CGColorSpaceCreateDeviceCMYK"}
        space = getattr(graphics, create[components])()
        provider = graphics.CGDataProviderCreateWithCFData(pixels)
        if pixels != data:
            _cf.release(pixels)  # the provider holds it now
        try:
            picture = graphics.CGImageCreate(
                width, height, 8, 8 * components, width * components, space, 0, provider, None, False, 0
            )
        finally:
            graphics.CGDataProviderRelease(provider)
            graphics.CGColorSpaceRelease(space)
        if not picture:
            return None
        try:
            # PNG has no CMYK: those go to TIFF, which keeps them as they are.
            path = target.with_suffix(".tiff" if components == 4 else ".png")
            kind_name = "public.tiff" if components == 4 else "public.png"
            io = images._io()
            return images._write(path, kind_name, lambda destination: io.CGImageDestinationAddImage(destination, picture, None))
        finally:
            graphics.CGImageRelease(picture)


def images(
    path: PathLike,
    folder: PathLike,
    *,
    pages: Optional[Iterable[int]] = None,
    password: Optional[str] = None,
) -> List[Path]:
    """
    Save the pictures embedded in a PDF into ``folder``, and return their paths, page by page.

    ::

        macos.pdf.images("brochure.pdf", "brochure-images")   # [PosixPath('brochure-images/page1-1.jpg'), ...]

    JPEG and JPEG 2000 pictures are saved as they're embedded, without
    compressing them again; the others become PNG (or TIFF, for CMYK). A
    picture used on several pages is saved once. Pictures in rare
    encodings (indexed colors, 1-bit masks...) are skipped. ``pages``
    (numbered from 1) keeps only those pages' pictures. To save whole
    pages as images, see :func:`render`.
    """
    source = Path(path).expanduser().absolute()
    if not source.exists():
        raise FileNotFoundError(str(source))
    target = Path(folder).expanduser().absolute()
    graphics = _pdf_objects()
    document = _open_for_drawing(source, password)
    saved: List[Path] = []
    try:
        target.mkdir(parents=True, exist_ok=True)  # once the PDF opened: no empty folder for one that can't be read
        count = graphics.CGPDFDocumentGetNumberOfPages(document)
        wanted = list(pages) if pages is not None else list(range(1, count + 1))
        for number in wanted:
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= count:
                raise ValueError("page {!r} is out of range: the PDF has {} page(s), numbered from 1".format(number, count))
        seen = set()
        for number in wanted:
            found: List[int] = []  # this page's image streams, forms opened

            def collect(dictionary: int) -> None:
                resources, objects = ctypes.c_void_p(), ctypes.c_void_p()
                if not graphics.CGPDFDictionaryGetDictionary(dictionary, b"Resources", ctypes.byref(resources)):
                    return
                if not graphics.CGPDFDictionaryGetDictionary(resources, b"XObject", ctypes.byref(objects)):
                    return
                named: List[Tuple[bytes, int]] = []

                def visit(key: bytes, value: int, info: int) -> None:
                    stream = ctypes.c_void_p()
                    if graphics.CGPDFObjectGetValue(value, _STREAM, ctypes.byref(stream)) and stream.value:
                        named.append((key, stream.value))

                visitor = _Visitor(visit)
                graphics.CGPDFDictionaryApplyFunction(objects, visitor, None)
                # The dictionary's own order isn't fixed: go by name, naturally (Im2 before Im10), the same on any Mac.
                named.sort(key=lambda item: _natural(item[0]))
                for _, stream in named:
                    if stream in seen:
                        continue
                    seen.add(stream)
                    info = graphics.CGPDFStreamGetDictionary(stream)
                    subtype = ctypes.c_char_p()
                    graphics.CGPDFDictionaryGetName(info, b"Subtype", ctypes.byref(subtype))
                    if subtype.value == b"Image":
                        found.append(stream)
                    elif subtype.value == b"Form":
                        collect(info)  # a group of drawings, which may hold pictures of its own

            collect(graphics.CGPDFPageGetDictionary(graphics.CGPDFDocumentGetPage(document, number)))
            index = 0
            for stream in found:
                written = _save_image(graphics, stream, target / "page{}-{}".format(number, index + 1))
                if written:
                    saved.append(written)
                    index += 1  # numbered by the pictures saved: no gaps for the ones skipped
    finally:
        graphics.CGPDFDocumentRelease(document)
    return saved


# --- Redaction --------------------------------------------------------------------

Target = Union[str, "re.Pattern[str]"]


_REDACTION_SCALE = 3.0  # 216 dots per inch: sharp enough to read and print the rest of the page
_REDACTION_LONGEST = 6000  # pixels, for huge pages
_BLOCK = "\u2588"  # █, what redacted text becomes in metadata and bookmarks
_REDACTION_QUALITY = 0.9  # JPEG quality of a flattened page: crisp text, a fraction of the raw pixels


def _patterns(targets: Union[Target, Sequence[Target]]) -> List[Tuple[str, "re.Pattern[str]"]]:
    """
    Each target as it was given (the text, or the pattern's source) and a pattern to find it.

    A text matches ignoring case and any spacing or line break between its words, and only
    as whole words: "Ana" doesn't match inside "Banana".
    """
    items = [targets] if isinstance(targets, (str, re.Pattern)) else list(targets)
    if not items:
        raise ValueError("redact() needs at least one text or pattern")
    found = []
    for item in items:
        if isinstance(item, re.Pattern):
            if not isinstance(item.pattern, str):
                raise ValueError("the pattern {!r} is for bytes: compile it from a str".format(item.pattern))
            if item.fullmatch(""):
                raise ValueError("the pattern {!r} matches an empty text".format(item.pattern))
            found.append((item.pattern, item))
        elif isinstance(item, str) and item.strip():
            words = r"\s+".join(re.escape(word) for word in item.split())
            # Whole words: no letter or digit right before or after, where the text itself starts or ends with one.
            before = r"(?<!\w)" if re.match(r"\w", item.strip()) else ""
            after = r"(?!\w)" if re.search(r"\w$", item.strip()) else ""
            found.append((item, re.compile(before + words + after, re.IGNORECASE)))
        else:
            raise ValueError("redact() takes texts and compiled patterns, not {!r}".format(item))
    labels = [label for label, _ in found]
    repeated = sorted({label for label in labels if labels.count(label) > 1})
    if repeated:
        # Redaction.matches counts by target: the same one twice would count each match twice.
        raise ValueError("each target once: {} is given more than once".format(", ".join(map(repr, repeated))))
    return found


def _utf16_offsets(text: str) -> List[int]:
    """
    Where each of Python's indexes in ``text`` falls counted as PDFKit counts, in UTF-16 units (one
    past the end included): a character beyond the Basic Multilingual Plane, like an emoji, takes two.
    """
    offsets = [0]
    for character in text:
        offsets.append(offsets[-1] + (2 if ord(character) > 0xFFFF else 1))
    return offsets


def _seen_box(page: int, box: Any) -> Tuple[float, ...]:
    """``box`` (page coordinates) as the page is seen: from the corner of its visible part, turned as it's shown."""
    bounds = _objc.send(page, "boundsForBox:", _CROP_BOX, argtypes=(ctypes.c_long,), restype=_objc.CGRect)
    rotation = int(_objc.send(page, "rotation", restype=ctypes.c_long))
    own = (box.origin.x - bounds.origin.x, box.origin.y - bounds.origin.y, box.size.width, box.size.height)
    return _seen(own, bounds.size.width, bounds.size.height, rotation)


# Everything an annotation holds as text, and saves with it: a comment and its author, a form field's
# value, name, default, choices and button states, a stamp's name, a link's address.
_ANNOTATION_TEXTS = (
    "contents",
    "userName",
    "widgetStringValue",
    "widgetDefaultStringValue",
    "fieldName",
    "caption",
    "buttonWidgetStateString",
    "choices",
    "values",
    "stampName",
    "toolTip",
    "URL",
    "action",
)


def _texts_of(value: Optional[int]) -> List[str]:
    """The strings in an Objective-C value: a string, a URL, an array of them, or an action's URL."""
    if not value:
        return []

    def kind(name: str) -> bool:
        return bool(_objc.send(value, "isKindOfClass:", _objc.cls(name), argtypes=(_objc.id,), restype=BOOL))

    if kind("NSString"):
        return [_objc.pystring(value) or ""]
    if kind("NSURL"):
        return [_objc.pystring(_objc.send(value, "absoluteString")) or ""]
    if kind("NSArray"):
        return [text for item in _objc.nsarray(value) for text in _texts_of(item)]
    if kind("NSDictionary"):
        return [text for item in _objc.nsarray(_objc.send(value, "allValues")) for text in _texts_of(item)]
    if _objc.send(value, "respondsToSelector:", _objc.sel("URL"), argtypes=(_objc.SEL,), restype=BOOL):
        return _texts_of(_objc.send(value, "URL"))  # a link's action
    return []


def _annotation_texts(annotation: int) -> List[str]:
    """
    Every string an annotation saves: each entry of its dictionary (``/Subj``, ``/RC``, ``/T``... and any
    other), and what PDFKit reads out of them, like a link action's address.
    """
    found = _texts_of(_objc.send(annotation, "annotationKeyValues"))
    for getter in _ANNOTATION_TEXTS:
        if _objc.send(annotation, "respondsToSelector:", _objc.sel(getter), argtypes=(_objc.SEL,), restype=BOOL):
            found += _texts_of(_objc.send(annotation, getter))
    # Once each: a choice's label and value, or a field's name and tooltip, are often the same string.
    return list(dict.fromkeys(text for text in found if text))


def _redactions(
    page: int, number: int, patterns: Sequence[Tuple[str, "re.Pattern[str]"]], counts: List[int]
) -> Tuple[int, List[Tuple[float, ...]]]:
    """
    How many matches ``page`` holds, and the boxes to black out, as it's seen: its matching text, and the
    annotations that hold a match.

    A match may have no box (text drawn hidden or at zero size): it still counts, so its page is redrawn
    and the text goes. One whose place PDFKit can't tell raises: it would stay on show.
    """
    boxes = []
    found = 0
    content = _objc.pystring(_objc.send(page, "string")) or ""
    offsets = _utf16_offsets(content)  # once per page: per match, it would grow with the square of the page
    for index, (label, pattern) in enumerate(patterns):
        for match in pattern.finditer(content):
            if not match.group():
                continue
            start, end = offsets[match.start()], offsets[match.end()]
            selection = _objc.send(page, "selectionForRange:", _files.NSRange(start, end - start), argtypes=(_files.NSRange,))
            if not selection:
                raise MacOSError(
                    "{!r} is on page {}, but where it's drawn can't be told, so nothing was written".format(label, number)
                )
            counts[index] += 1
            found += 1
            # Line by line: a match broken over two lines would otherwise black out the box around both.
            for line in _objc.nsarray(_objc.send(selection, "selectionsByLine")):
                box = _objc.send(line, "boundsForPage:", page, argtypes=(_objc.id,), restype=_objc.CGRect)
                if box.size.width > 0 and box.size.height > 0:
                    boxes.append(_seen_box(page, box))
    for annotation in _objc.nsarray(_objc.send(page, "annotations")):
        # Each on its own: joined, "Jane" in one and "Doe" in the other would make a match that isn't there.
        held = _annotation_texts(annotation)
        hits = 0
        for index, (_, pattern) in enumerate(patterns):
            times = sum(1 for text in held for match in pattern.finditer(text) if match.group())
            counts[index] += times
            hits += times
        if hits:
            found += hits
            box = _objc.send(annotation, "bounds", restype=_objc.CGRect)
            boxes.append(_seen_box(page, box))  # the whole annotation: it goes, as part of the picture
    return found, boxes


def _flatten(document: int, number: int, boxes: Sequence[Tuple[float, ...]]) -> None:
    """
    Replace page ``number`` with a picture of it, the ``boxes`` blacked out: its text is gone, not covered.

    The picture is of the page's visible part (its crop box), as it's seen: what was cropped away is gone
    too, and the new page shows the same size. It's kept as a JPEG, as PDFKit would write it anyway:
    the document holds every flattened page until it's saved, a few hundred kilobytes each this way,
    not the tens of megabytes of their raw pixels.
    """
    graphics = _graphics()
    page = _page(document, number)
    bounds = _objc.send(page, "boundsForBox:", _CROP_BOX, argtypes=(ctypes.c_long,), restype=_objc.CGRect)
    width, height = bounds.size.width, bounds.size.height
    if int(_objc.send(page, "rotation", restype=ctypes.c_long)) % 180:
        width, height = height, width  # drawn as it's seen, so the picture needs no turning
    scale = min(_REDACTION_SCALE, _REDACTION_LONGEST / max(width, height, 1.0))
    pixels_wide, pixels_high = max(1, round(width * scale)), max(1, round(height * scale))
    space = graphics.CGColorSpaceCreateDeviceRGB()
    context = graphics.CGBitmapContextCreate(None, pixels_wide, pixels_high, 8, 0, space, _OPAQUE_RGB)
    graphics.CGColorSpaceRelease(space)
    if not context:
        raise MacOSError("could not draw page {}".format(number))
    try:
        graphics.CGContextScaleCTM(context, scale, scale)
        graphics.CGContextSetRGBFillColor(context, 1.0, 1.0, 1.0, 1.0)
        graphics.CGContextFillRect(context, _objc.CGRect(_objc.CGPoint(0, 0), _objc.CGSize(width, height)))
        graphics.CGContextSaveGState(context)
        # Its annotations too (form fields, comments, stamps): the new page is a picture, it can't hold them.
        _objc.send(page, "setDisplaysAnnotations:", True, argtypes=(BOOL,), restype=None)
        _objc.send(page, "drawWithBox:toContext:", _CROP_BOX, context, argtypes=(ctypes.c_long, ctypes.c_void_p), restype=None)
        graphics.CGContextRestoreGState(context)
        graphics.CGContextSetRGBFillColor(context, 0.0, 0.0, 0.0, 1.0)
        for x, y, wide, tall in boxes:
            margin = 1.0  # a point around it: no edge of a letter peeks out
            area = _objc.CGRect(_objc.CGPoint(x - margin, y - margin), _objc.CGSize(wide + 2 * margin, tall + 2 * margin))
            graphics.CGContextFillRect(context, area)
        raw = graphics.CGBitmapContextCreateImage(context)
    finally:
        graphics.CGContextRelease(context)
    if not raw:
        raise MacOSError("could not draw page {}".format(number))
    with _cf.owned(raw):
        picture = _jpeg(raw, _REDACTION_QUALITY)
    if not picture:
        raise MacOSError("could not draw page {}".format(number))
    try:
        image = _objc.send(
            _objc.send(_objc.cls("NSImage"), "alloc"),
            "initWithCGImage:size:",
            picture,
            _objc.CGSize(width, height),
            argtypes=(ctypes.c_void_p, _objc.CGSize),
        )
        _objc.send(image, "autorelease")
        flat = _objc.send(_objc.send(_objc.cls("PDFPage"), "alloc"), "initWithImage:", image, argtypes=(_objc.id,))
        if not flat:
            raise MacOSError("could not redraw page {}".format(number))
        _objc.send(flat, "autorelease")
    finally:
        graphics.CGImageRelease(picture)
    _objc.send(document, "insertPage:atIndex:", flat, number - 1, argtypes=(_objc.id, NSUInteger), restype=None)
    _objc.send(document, "removePageAtIndex:", number, argtypes=(NSUInteger,), restype=None)


def _jpeg(picture: int, quality: float) -> Optional[int]:
    """
    An owned ``CGImage`` of ``picture`` compressed as a JPEG, or ``None``.

    It reads from the JPEG's bytes, which a PDF context embeds as they are:
    compressed once, here, not again when the PDF is written.
    """
    from . import image as images

    io = images._io()
    encoded = _objc.send(_objc.cls("NSMutableData"), "data")  # a CFMutableData, autoreleased
    with _cf.owned(_cf.string("public.jpeg")) as kind:
        destination = io.CGImageDestinationCreateWithData(encoded, kind, 1, None)
    if not destination:
        return None
    with _cf.owned(destination), _cf.owned(images._options({"kCGImageDestinationLossyCompressionQuality": quality})) as options:
        io.CGImageDestinationAddImage(destination, picture, options)
        if not io.CGImageDestinationFinalize(destination):
            return None
    with _cf.owned(io.CGImageSourceCreateWithData(encoded, None)) as source:
        if not source:
            return None
        compressed = io.CGImageSourceCreateImageAtIndex(source, 0, None)
    return int(compressed) if compressed else None


def _scrub(text: str, patterns: Sequence[Tuple[str, "re.Pattern[str]"]], counts: List[int]) -> str:
    """``text`` with every match blocked out, each target searched in the original: overlaps are covered whole."""
    hidden = [False] * len(text)
    for index, (_, pattern) in enumerate(patterns):
        for match in pattern.finditer(text):
            if match.group():
                counts[index] += 1
                hidden[match.start():match.end()] = [True] * (match.end() - match.start())
    return "".join(_BLOCK if hide else character for character, hide in zip(text, hidden))


def _scrub_metadata(document: int, patterns: Sequence[Tuple[str, "re.Pattern[str]"]], counts: List[int]) -> None:
    """Redact the title, author, subject, keywords and creator too: they travel with the file."""
    attributes = _objc.send(document, "documentAttributes")
    if not attributes:
        return
    changed = _objc.send(_objc.send(attributes, "mutableCopy"), "autorelease")
    for key in ("Title", "Author", "Subject", "Creator", "Keywords"):
        value = _objc.send(attributes, "objectForKey:", _objc.nsstring(key), argtypes=(_objc.id,))
        if not value:
            continue
        if _objc.send(value, "isKindOfClass:", _objc.cls("NSArray"), argtypes=(_objc.id,), restype=BOOL):
            words = [_scrub(_objc.pystring(word) or "", patterns, counts) for word in _objc.nsarray(value)]
            new = _objc.nsarray_of([_objc.nsstring(word) for word in words])
        elif _objc.send(value, "isKindOfClass:", _objc.cls("NSString"), argtypes=(_objc.id,), restype=BOOL):
            new = _objc.nsstring(_scrub(_objc.pystring(value) or "", patterns, counts))
        else:
            continue
        _objc.send(changed, "setObject:forKey:", new, _objc.nsstring(key), argtypes=(_objc.id, _objc.id), restype=None)
    _objc.send(document, "setDocumentAttributes:", changed, argtypes=(_objc.id,), restype=None)


def _scrub_outline(outline: int, patterns: Sequence[Tuple[str, "re.Pattern[str]"]], counts: List[int]) -> None:
    for index in range(int(_objc.send(outline, "numberOfChildren", restype=NSUInteger))):
        child = _objc.send(outline, "childAtIndex:", index, argtypes=(NSUInteger,))
        label = _objc.pystring(_objc.send(child, "label")) or ""
        scrubbed = _scrub(label, patterns, counts)
        if scrubbed != label:
            _objc.send(child, "setLabel:", _objc.nsstring(scrubbed), argtypes=(_objc.id,), restype=None)
        _scrub_outline(child, patterns, counts)


@dataclass(frozen=True)
class Redaction:
    """What :func:`redact` blacked out."""

    path: Path
    """The redacted PDF."""
    matches: Dict[str, int]
    """
    How many times each target was found and blacked out, by the target as given (a pattern by its
    source): on the pages, in form fields and comments, in the metadata and in the bookmarks.
    """
    pages: Dict[int, int]
    """The pages redrawn, with how many matches each had: check them before sharing the PDF."""


def redact(
    path: PathLike,
    targets: Union[Target, Sequence[Target]],
    output: PathLike,
    *,
    password: Optional[str] = None,
) -> Redaction:
    """
    Black out text in a PDF for good, and save it to ``output``: the text is removed, not just covered.

    ::

        done = macos.pdf.redact("contract.pdf", ["Jane Doe", "123-45-6789"], "public.pdf")
        done.matches   # {'Jane Doe': 3, '123-45-6789': 1}
        done.pages     # {1: 2, 4: 2}: the pages to look over

        ssn = re.compile(r"\\b\\d{3}-\\d{2}-\\d{4}\\b")
        macos.pdf.redact("list.pdf", [ssn], "public.pdf")      # every Social Security number

    ``targets`` are texts, matched as whole words, ignoring case and any
    spacing or line break between them ("Ana" doesn't black out "Banana"),
    or compiled :mod:`re` patterns, for what follows a shape (IDs, emails,
    phone numbers). Each page with a match is redrawn as a picture of what
    it shows (annotations included, crop kept) with black boxes over the
    matches, so there's no text left under them to copy or search; the
    rest of that page stays visible, but its text can't be selected
    anymore (:func:`ocr` gives it back, boxes excluded). Pages without
    matches don't change.

    It also redacts form fields and comments that hold a match anywhere
    (a value, a field's name or choices, a comment or its author, a
    link's address): their page is flattened, with a box over them. And
    the matches in the
    title, author, subject, keywords, creator and bookmarks, which become
    ``█``.

    It returns a :class:`Redaction`: how many times each target was found,
    and on which pages. Raises :class:`ValueError`, writing nothing, when
    a target isn't found at all: a redaction that missed would look like
    it worked; and :class:`~macos.MacOSError`, also writing nothing, for a
    match PDFKit finds in the text but can't place on the page.

    It finds only the text a PDF holds as text, so **look over the result
    before sharing it**: text in pictures (a scan, a screenshot, a logo),
    text turned into shapes, fonts that can't be read back, and words
    split by a hyphen stay visible. On a scan made searchable by OCR, the
    boxes go where the OCR placed the words, which may be a little off.
    Scanned pages have no text to find: run :func:`ocr` first.
    ``password`` opens an encrypted PDF; the result isn't encrypted.
    """
    patterns = _patterns(targets)
    framework("AppKit")
    with _open(path, password) as document:
        counts = [0] * len(patterns)
        flatten = {}
        per_page = {}
        for number in range(1, _count(document) + 1):
            # A pool per page: searching one makes strings and selections, all done with once it's searched.
            with _objc.autorelease_pool():
                found, boxes = _redactions(_page(document, number), number, patterns, counts)
            if found:  # even without a box to draw: redrawing the page is what removes the text
                flatten[number] = boxes
                per_page[number] = found
        # In the document, not saved until every target is found: a miss writes nothing.
        _scrub_metadata(document, patterns, counts)
        root = _objc.send(document, "outlineRoot")
        if root:
            _scrub_outline(root, patterns, counts)
        missing = [repr(label) for (label, _), count in zip(patterns, counts) if not count]
        if missing:
            raise ValueError(
                "{} isn't in the PDF, so nothing was written: check the spelling, "
                "or run macos.pdf.ocr() first on a scan".format(", ".join(missing))
            )
        for number, boxes in flatten.items():
            # A pool per page: drawing one leaves autoreleased objects behind, which would pile up until the
            # end of a long PDF.
            with _objc.autorelease_pool():
                _flatten(document, number, boxes)
        saved = _save(document, output)
    matches = {label: count for (label, _), count in zip(patterns, counts)}
    return Redaction(path=saved, matches=matches, pages=per_page)
