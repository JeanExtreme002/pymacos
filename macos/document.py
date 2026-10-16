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
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

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
    """The document at ``path``, which must be a file, or an ``.rtfd`` folder; and not a PDF, which :mod:`macos.pdf` reads."""
    require_macos()
    found = _files.existing(path)
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


def _reads_as_utf8(source: Path) -> bool:
    """Whether to read a text or HTML file as UTF-8: it is, and an HTML page doesn't name its own encoding."""
    if source.suffix.lower() not in (".txt", ".text", ".html", ".htm"):
        return False  # the other formats say their encoding themselves
    if source.suffix.lower() in (".html", ".htm"):
        with open(str(source), "rb") as handle:
            if _CHARSET.search(handle.read(4096)):
                return False
    return _is_utf8(source)


# The page each gatekeeper (see _page_only) lets WebKit load, by the gatekeeper: set for the load, gone after.
_PAGES: Dict[int, str] = {}


def _will_send(gatekeeper: int, _command: int, _view: int, _resource: int, request: int, *_rest: int) -> Optional[int]:
    """WebKit's ``willSendRequest:``: the request to make, or ``None`` for none. Only the page itself gets through."""
    url = _objc.send(request, "URL")
    scheme = (_objc.pystring(_objc.send(url, "scheme")) if url else None) or ""
    path = (_objc.pystring(_objc.send(url, "path")) if url else None) or ""
    if scheme.lower() == "file" and path and os.path.realpath(path) == _PAGES.get(gatekeeper):
        return request
    return None


# ``willSendRequest:``'s C signature: the gatekeeper, the selector, the view, the resource, the request, the
# redirect response and the data source, all objects; it answers an object (the request, or nil).
_WillSendRequest = ctypes.CFUNCTYPE(ctypes.c_void_p, *([ctypes.c_void_p] * 7))


@lru_cache(maxsize=None)
def _gatekeeper_class() -> int:
    """
    A ``WebResourceLoadDelegate`` that refuses every load but the page's own.

    What an HTML page refers to (pictures, style sheets, frames) is fetched by WebKit as the page
    is read, from the web and from this Mac's files alike, and asked about here first:
    ``willSendRequest:`` answering ``nil`` cancels the load. The only other boundary the reader
    has, ``ReadAccessURL`` (``NSReadAccessURLDocumentOption``), is for the asynchronous loading
    API: the synchronous one used here fetches with or without it (checked).
    """
    framework("WebKit")
    return _objc.define_class(
        "PyMacOSPageOnlyLoads",
        {"webView:resource:willSendRequest:redirectResponse:fromDataSource:": ("@@:@@@@@", _WillSendRequest, _will_send)},
    )


def _options(source: Path, resources: bool = True) -> Tuple[Optional[int], Optional[int]]:
    """
    The reading options (autoreleased): UTF-8 for text and HTML that is, and the gatekeeper when ``resources`` is off.

    With the gatekeeper made, if any: its page is noted in ``_PAGES`` for the load, to be dropped after it.
    """
    options: Dict[str, int] = {}
    gatekeeper = None
    if _reads_as_utf8(source):
        options["CharacterEncoding"] = _objc.send(
            _objc.cls("NSNumber"), "numberWithUnsignedInteger:", _UTF8, argtypes=(ctypes.c_ulong,)
        )
    if not resources and source.suffix.lower() in _WEB_FORMATS:
        gatekeeper = _objc.send(_objc.send(_objc.send(_gatekeeper_class(), "alloc"), "init"), "autorelease")
        _PAGES[gatekeeper] = os.path.realpath(str(source))
        options["WebResourceLoadDelegate"] = gatekeeper  # NSWebResourceLoadDelegateDocumentOption
    return (_objc.nsdictionary_of(options) if options else None), gatekeeper


def _load(source: Path, resources: bool = True) -> int:
    """The document as an ``NSAttributedString`` (autoreleased); see :func:`text` for ``resources``."""
    if source.suffix.lower() in _WEB_FORMATS:
        _files.require_main_thread("reading an HTML page or a web archive")
    framework("AppKit")
    error = ctypes.c_void_p()
    options, gatekeeper = _options(source, resources)
    try:
        loaded = _objc.send(
            _objc.send(_objc.cls("NSAttributedString"), "alloc"),
            "initWithURL:options:documentAttributes:error:",
            _objc.file_url(source),
            options,
            None,
            ctypes.byref(error),
            argtypes=(_objc.id, _objc.id, ctypes.c_void_p, ctypes.c_void_p),
        )
    finally:
        if gatekeeper is not None:  # the load is synchronous: nothing asks this gatekeeper after it
            _PAGES.pop(gatekeeper, None)
    if not loaded:
        raise MacOSError("could not read {}: {}".format(source, _objc.error_message(error, "unknown format")))
    return _objc.send(loaded, "autorelease")


def text(path: PathLike, *, resources: bool = True) -> str:
    """
    The text of a document: Word (``.docx``, ``.doc``), RTF, HTML,
    OpenDocument (``.odt``), a web archive or plain text.

    ::

        macos.document.text("minutes.docx")   # 'Meeting minutes\\n...'

    For a PDF, see :func:`macos.pdf.text`. HTML is read as in :func:`convert`,
    by WebKit: the page's pictures, style sheets and frames are fetched while
    it's read, from the web and from files on this Mac (``file://``) alike,
    which lets a page make this Mac fetch addresses of its choosing, or read
    local files. ``resources=False`` reads the page alone, fetching nothing it
    refers to: use it for HTML you don't trust. HTML pages and web archives
    need the main thread: from another thread they raise
    :class:`~macos.MainThreadError`.
    """
    source = _existing(path)
    with _objc.autorelease_pool():
        return _objc.pystring(_objc.send(_load(source, resources), "string")) or ""


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
        raise MacOSError("could not write {}: {}".format(target, _objc.error_message(error)))
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


def convert(
    source: PathLike, output: PathLike, *, paper: Optional[str] = None, margin: float = 72.0, resources: bool = True
) -> Path:
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

    HTML is read by WebKit, as a browser would: the page's pictures, style
    sheets and frames are fetched while it's read, from the web and from files
    on this Mac (``file://``) alike, which lets a page make this Mac fetch
    addresses of its choosing, or pull local files into the document.
    ``resources=False`` reads the page alone, fetching nothing it refers to
    (its pictures are then left out): use it for HTML you don't trust. HTML
    pages, web archives and PDF output need the main thread (AppKit lays out
    and prints only there): from another thread they raise
    :class:`~macos.MainThreadError`.
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
        document = _load(origin, resources)
        if kind == ".pdf":
            _print_pdf(document, target, paper, margin)
        else:
            _save(document, target, _TYPES[kind])
    return target
