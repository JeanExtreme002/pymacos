# -*- coding: utf-8 -*-

"""
Convert documents between Word, RTF, HTML, OpenDocument, plain text and PDF,
and read their text.

::

    macos.document.convert("report.docx", "report.pdf")
    macos.document.convert("page.html", "page.docx")
    macos.document.text("contract.docx")     # 'CONTRACT\\nThe parties...'

Goes through the text system of macOS, the one TextEdit uses: no Word or
LibreOffice needed. What TextEdit keeps survives (fonts, bold, colours,
lists, tables, links); the page layout of Word documents (columns, headers
and footers, text boxes) doesn't, so a converted PDF looks like the document
opened in TextEdit, not in Word. Tables are lost when writing Word files
(``.docx``, ``.doc``): their cells become lines.
"""

import codecs
import ctypes
import os
import re
from pathlib import Path
from typing import Optional, Tuple, Union

from . import _files, _objc
from ._system import framework, require_macos
from .errors import MacOSError

__all__ = ["convert", "text"]

PathLike = Union[str, "os.PathLike[str]"]

# Output extension -> NSDocumentTypeDocumentAttribute value.
_TYPES = {
    ".txt": "NSPlainText",
    ".rtf": "NSRTF",
    ".html": "NSHTML",
    ".htm": "NSHTML",
    ".docx": "NSOfficeOpenXML",
    ".doc": "NSDocFormat",
    ".odt": "NSOpenDocument",
    ".webarchive": "NSWebArchive",
}
_PAPERS = {"a4": (595.28, 841.89), "letter": (612.0, 792.0), "legal": (612.0, 1008.0)}
_UTF8 = 4  # NSUTF8StringEncoding
_CHARSET = re.compile(rb"charset\s*=", re.I)
_CHUNK = 1 << 20  # bytes read at a time to check a file is UTF-8
# Read through WebKit, which AppKit only runs on the main thread.
_WEB_FORMATS = (".html", ".htm", ".webarchive")


def _existing(path: PathLike) -> Path:
    require_macos()
    found = Path(path).expanduser().absolute()
    if not found.is_file() and not (found.suffix.lower() == ".rtfd" and found.is_dir()):
        raise FileNotFoundError(str(found))
    if found.suffix.lower() == ".pdf":
        raise ValueError("{} is a PDF: macos.pdf.text() reads its text".format(found))
    return found


def _is_utf8(source: Path) -> bool:
    """Whether a file is valid UTF-8, read a piece at a time: a big text file isn't held in memory whole."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        with open(str(source), "rb") as handle:
            for piece in iter(lambda: handle.read(_CHUNK), b""):
                decoder.decode(piece)
        decoder.decode(b"", final=True)  # a character cut off at the end
    except UnicodeDecodeError:
        return False
    return True


def _options(source: Path) -> Optional[int]:
    """Read text and HTML as UTF-8, unless it isn't or an HTML page names its own encoding."""
    if source.suffix.lower() not in (".txt", ".text", ".html", ".htm"):
        return None  # the other formats say their encoding themselves
    if source.suffix.lower() in (".html", ".htm"):
        with open(str(source), "rb") as handle:
            if _CHARSET.search(handle.read(4096)):
                return None
    if not _is_utf8(source):
        return None
    number = _objc.send(_objc.cls("NSNumber"), "numberWithUnsignedInteger:", _UTF8, argtypes=(ctypes.c_ulong,))
    return _objc.send(
        _objc.cls("NSDictionary"),
        "dictionaryWithObject:forKey:",
        number,
        _objc.nsstring("CharacterEncoding"),
        argtypes=(_objc.id, _objc.id),
    )


def _load(source: Path) -> int:
    """The document as an ``NSAttributedString`` (autoreleased)."""
    if source.suffix.lower() in _WEB_FORMATS:
        _files.require_main_thread("reading an HTML page or a web archive")
    framework("AppKit")
    error = ctypes.c_void_p()
    loaded = _objc.send(
        _objc.send(_objc.cls("NSAttributedString"), "alloc"),
        "initWithURL:options:documentAttributes:error:",
        _objc.file_url(source),
        _options(source),
        None,
        ctypes.byref(error),
        argtypes=(_objc.id, _objc.id, ctypes.c_void_p, ctypes.c_void_p),
    )
    if not loaded:
        raise MacOSError("could not read {}: {}".format(source, _objc.error_message(error) or "unknown format"))
    return _objc.send(loaded, "autorelease")


def text(path: PathLike) -> str:
    """
    The text of a document: Word (``.docx``, ``.doc``), RTF, HTML,
    OpenDocument (``.odt``), a web archive or plain text.

    ::

        macos.document.text("minutes.docx")   # 'Meeting minutes\\n...'

    For a PDF, see :func:`macos.pdf.text`. HTML is read as in :func:`convert`:
    its pictures and style sheets are fetched, and it needs the main thread.
    """
    source = _existing(path)
    with _objc.autorelease_pool():
        return _objc.pystring(_objc.send(_load(source), "string")) or ""


def _save(document: int, target: Path, kind: str) -> None:
    attributes = _objc.send(
        _objc.cls("NSDictionary"),
        "dictionaryWithObject:forKey:",
        _objc.nsstring(kind),
        _objc.nsstring("DocumentType"),
        argtypes=(_objc.id, _objc.id),
    )
    length = _objc.send(document, "length", restype=ctypes.c_ulong)
    error = ctypes.c_void_p()
    data = _objc.send(
        document,
        "dataFromRange:documentAttributes:error:",
        _files.NSRange(0, length),
        attributes,
        ctypes.byref(error),
        argtypes=(_files.NSRange, _objc.id, ctypes.c_void_p),
    )
    if not data:
        raise MacOSError("could not write {}: {}".format(target, _objc.error_message(error) or "unknown error"))
    payload = _objc.pybytes(data) or b""
    _files.write_atomically(target, lambda name: Path(name).write_bytes(payload))


def _paper(paper: Optional[str], info: int) -> Tuple[float, float]:
    if paper is None:
        size = _objc.send(info, "paperSize", restype=_objc.CGSize)  # the system's, from the region
        return size.width, size.height
    try:
        return _PAPERS[paper.lower()]
    except KeyError:
        raise ValueError("paper is 'a4', 'letter' or 'legal', not {!r}".format(paper)) from None


def _print_pdf(document: int, target: Path, paper: Optional[str], margin: float) -> None:
    """Lay the text out on pages, as printing from TextEdit does, and save them as a PDF."""
    info = _objc.send(_objc.send(_objc.send(_objc.cls("NSPrintInfo"), "sharedPrintInfo"), "copy"), "autorelease")
    width, height = _paper(paper, info)
    if margin < 0 or 2 * margin >= min(width, height):
        raise ValueError("margin must leave room on the page, not {}".format(margin))
    _objc.send(info, "setPaperSize:", _objc.CGSize(width, height), argtypes=(_objc.CGSize,), restype=None)
    for setter in ("setLeftMargin:", "setRightMargin:", "setTopMargin:", "setBottomMargin:"):
        _objc.send(info, setter, float(margin), argtypes=(ctypes.c_double,), restype=None)
    _objc.send(info, "setHorizontalPagination:", 1, argtypes=(ctypes.c_long,), restype=None)  # fit the width
    _objc.send(info, "setVerticalPagination:", 0, argtypes=(ctypes.c_long,), restype=None)  # break into pages
    _objc.send(info, "setJobDisposition:", _objc.nsstring("NSPrintSaveJob"), argtypes=(_objc.id,), restype=None)

    frame = _objc.CGRect(_objc.CGPoint(0, 0), _objc.CGSize(width - 2 * margin, height - 2 * margin))
    view = _objc.send(_objc.send(_objc.cls("NSTextView"), "alloc"), "initWithFrame:", frame, argtypes=(_objc.CGRect,))
    _objc.send(view, "autorelease")
    # Asking for the layout manager switches the view to TextKit 1: TextKit 2 doesn't draw tables.
    _objc.send(view, "layoutManager")
    _objc.send(_objc.send(view, "textStorage"), "setAttributedString:", document, argtypes=(_objc.id,), restype=None)
    _objc.send(view, "setHorizontallyResizable:", False, argtypes=(ctypes.c_bool,), restype=None)
    _objc.send(view, "setVerticallyResizable:", True, argtypes=(ctypes.c_bool,), restype=None)
    _objc.send(view, "sizeToFit", restype=None)

    def write(name: str) -> None:
        _objc.send(
            _objc.send(info, "dictionary"),
            "setObject:forKey:",
            _objc.file_url(name),
            _objc.nsstring("NSJobSavingURL"),
            argtypes=(_objc.id, _objc.id),
            restype=None,
        )
        operation = _objc.send(
            _objc.cls("NSPrintOperation"), "printOperationWithView:printInfo:", view, info, argtypes=(_objc.id, _objc.id)
        )
        _objc.send(operation, "setShowsPrintPanel:", False, argtypes=(ctypes.c_bool,), restype=None)
        _objc.send(operation, "setShowsProgressPanel:", False, argtypes=(ctypes.c_bool,), restype=None)
        if not _objc.send(operation, "runOperation", restype=ctypes.c_bool):
            raise MacOSError("could not write {}".format(target))
        if not os.path.isfile(name) or not os.path.getsize(name):
            raise MacOSError("could not write {}".format(target))

    _files.write_atomically(target, write)


def convert(source: PathLike, output: PathLike, *, paper: Optional[str] = None, margin: float = 72.0) -> Path:
    """
    Convert a document to another format, picked by ``output``'s extension,
    and return the output's path.

    ::

        macos.document.convert("report.docx", "report.pdf")
        macos.document.convert("notes.rtf", "notes.docx")
        macos.document.convert("page.html", "page.txt")

    It reads Word (``.docx``, ``.doc``), RTF (and ``.rtfd``), HTML,
    OpenDocument (``.odt``), web archives and plain text, and writes those
    (except ``.rtfd``) or a PDF. A PDF is laid out on ``paper`` (``'a4'``, ``'letter'`` or
    ``'legal'``; by default the region's, as in TextEdit), ``margin`` points
    from each edge (72 is an inch).

    It converts as TextEdit would: see the module's notes for what a Word
    document's layout keeps.

    HTML is read by WebKit, as a browser would: the page's pictures and
    style sheets are fetched while it's read, from the web and from files on
    this Mac (``file://``) alike. Don't convert HTML you don't trust: it can
    make this Mac fetch addresses of its choosing, or pull local files into
    the document. HTML pages, web archives and PDF output need the main
    thread (AppKit lays out and prints only there): from another thread
    they raise :class:`~macos.MacOSError`.
    """
    origin = _existing(source)
    target = Path(output).expanduser().absolute()
    kind = target.suffix.lower()
    if kind != ".pdf" and kind not in _TYPES:
        known = ", ".join(sorted({".pdf", *_TYPES}))
        raise ValueError("can't write {!r} files; the formats are {}".format(kind or target.name, known))
    if kind == ".pdf":
        _files.require_main_thread("converting to PDF (it lays the text out in a text view, and prints it)")
    with _objc.autorelease_pool():
        document = _load(origin)
        if kind == ".pdf":
            _print_pdf(document, target, paper, margin)
        else:
            _save(document, target, _TYPES[kind])
    return target
