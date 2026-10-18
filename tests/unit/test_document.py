"""Unit tests for :mod:`macos.document`. They run on any platform."""

import sys

import pytest

import macos


def test_convert_checks_the_output_format(fake_run, tmp_path):
    source = tmp_path / "notes.rtf"
    source.write_text("{\\rtf1 hi}")
    with pytest.raises(ValueError, match="can't write '.pages' files; the formats are .doc, .docx"):
        macos.document.convert(source, tmp_path / "notes.pages")
    with pytest.raises(ValueError, match="can't write 'notes' files"):
        macos.document.convert(source, tmp_path / "notes")
    with pytest.raises(FileNotFoundError):
        macos.document.convert(tmp_path / "missing.docx", tmp_path / "out.pdf")


def test_text_points_pdfs_to_the_pdf_module(fake_run, tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4")
    with pytest.raises(ValueError, match="macos.pdf.text"):
        macos.document.text(source)


@pytest.mark.skipif(sys.platform != "darwin", reason="builds the reading options with Foundation")
def test_html_reading_options(tmp_path):
    from macos import _objc

    page = tmp_path / "page.html"
    page.write_text("<p>hi</p>")
    with _objc.autorelease_pool():
        options, _ = macos.document._options(page)
        assert _objc.send(options, "objectForKey:", _objc.nsstring("CharacterEncoding"), argtypes=(_objc.id,))
        notes = tmp_path / "notes.rtf"
        notes.write_text("{\\rtf1 hi}")
        assert macos.document._options(notes) == (None, None)  # RTF says its own encoding and WebKit doesn't read it


def _in_a_thread(work):
    import threading

    caught = []

    def run():
        try:
            work()
        except BaseException as error:  # handed back to the test
            caught.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    return caught[0] if caught else None


def test_what_appkit_does_only_on_the_main_thread_says_so(fake_run, monkeypatch, tmp_path):
    from contextlib import nullcontext

    from macos import _files, _objc

    # fake_run says it's macOS: the thread check and the pool are faked too, so no framework is
    # loaded and the test runs on Linux as well. The worker thread isn't the main one either way.
    monkeypatch.setattr(_files, "on_main_thread", lambda: False)
    monkeypatch.setattr(_objc, "autorelease_pool", nullcontext)
    page = tmp_path / "page.html"
    page.write_text("<p>hi</p>")
    notes = tmp_path / "notes.rtf"
    notes.write_text("{\\rtf1 hi}")
    for work in (
        lambda: macos.document.convert(notes, tmp_path / "notes.pdf"),
        lambda: macos.document.convert(page, tmp_path / "page.txt"),
        lambda: macos.document.text(page),
        lambda: macos.document.convert(notes, tmp_path / "notes.webarchive"),  # WebKit writes it, on the main thread
    ):
        error = _in_a_thread(work)
        assert isinstance(error, macos.MacOSError) and "must run on the main thread" in str(error)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["notes.rtf", "page.html"]  # nothing written


def test_the_utf8_check_reads_a_piece_at_a_time(monkeypatch, tmp_path):
    from macos import document

    monkeypatch.setattr(document, "_CHUNK", 3)  # every multi-byte character is cut between two pieces
    text = tmp_path / "text.txt"
    text.write_bytes("ação 💡 é".encode("utf-8"))
    assert document._is_utf8(text)
    text.write_bytes("açã".encode("utf-8")[:-1])  # the last character cut short
    assert not document._is_utf8(text)
    text.write_bytes("caf\xe9".encode("latin-1"))
    assert not document._is_utf8(text)


def test_the_gatekeeper_lets_through_the_page_alone(monkeypatch, tmp_path):
    """With resources=False, WebKit asks before each load: only the page being read, as a file, is answered."""
    from macos import document

    page = tmp_path / "page.html"
    page.write_text("<p>Hi</p>")
    link = tmp_path / "link.html"
    link.symlink_to(page)
    urls = {
        1: ("file", str(page)),
        2: ("file", str(link)),  # the same file, by another name
        3: ("file", str(tmp_path / "style.css")),
        4: ("http", "/style.css"),
        5: ("https", str(page)),  # the page's path, not as a file
        6: (None, None),  # a request with no URL
        7: ("file", "/tmp/a\x00b.png"),  # realpath raises: refused, not raised into WebKit
    }

    def send(receiver, selector, *args, **kwargs):
        if selector == "URL":
            return receiver if urls[receiver][0] else None
        return (receiver, selector)

    def pystring(answer):
        receiver, selector = answer
        return urls[receiver][0] if selector == "scheme" else urls[receiver][1]

    monkeypatch.setattr(document._objc, "send", send)
    monkeypatch.setattr(document._objc, "pystring", pystring)
    monkeypatch.setitem(document._PAGES, 99, str(page.resolve()))

    answered = {request: document._will_send(99, 0, 0, 0, request, 0, 0) for request in urls}
    assert answered == {1: 1, 2: 2, 3: None, 4: None, 5: None, 6: None, 7: None}
    assert document._will_send(98, 0, 0, 0, 1, 0, 0) is None  # another load's gatekeeper: not its page


@pytest.mark.parametrize("name", ["page.shtml", "page.xhtml", "report.docx", "notes.rtf"])
def test_resources_off_installs_the_gatekeeper_whatever_the_extension(monkeypatch, tmp_path, name):
    from macos import document

    source = tmp_path / name
    source.write_text("x")
    made = {}
    monkeypatch.setattr(document, "_gatekeeper_class", lambda: 1)
    monkeypatch.setattr(document._objc, "send", lambda receiver, selector, *args, **kwargs: 42)
    monkeypatch.setattr(document._objc, "nsdictionary_of", lambda options: made.update(options) or 7)
    monkeypatch.setattr(document, "_reads_as_utf8", lambda path: False)

    options, gatekeeper = document._options(source, resources=False)
    assert (options, gatekeeper) == (7, 42) and made == {"WebResourceLoadDelegate": 42}
    assert document._PAGES.pop(42) == str(source.resolve())
    assert document._options(source) == (None, None)  # resources on: nothing installed


def test_every_html_extension_needs_the_main_thread(monkeypatch, tmp_path):
    from macos import document

    monkeypatch.setattr(document._files, "on_main_thread", lambda: False)
    for name in ("page.html", "page.shtml", "page.xhtml", "saved.webarchive"):
        page = tmp_path / name
        page.write_text("<p>x</p>")
        with pytest.raises(macos.MainThreadError):  # off it, WebKit would wait for the main thread for good
            document._load(page)


def test_resources_off_needs_the_main_thread_unless_webkit_cant_read_it(monkeypatch, tmp_path):
    from macos import document

    monkeypatch.setattr(document._files, "on_main_thread", lambda: False)
    page = tmp_path / "page.foo"
    page.write_text("<html><body><p>x</p></body></html>")
    for name in ("page.foo", "page.docx", "page.odt", "page.text"):  # macOS reads HTML by content, not by name
        disguised = tmp_path / name
        disguised.write_text(page.read_text())
        with pytest.raises(macos.MainThreadError):  # through WebKit, which asks the gatekeeper on the main thread
            document._load(disguised, resources=False)

    def loading(name):
        raise RuntimeError("loading")

    monkeypatch.setattr(document, "framework", loading)
    with pytest.raises(RuntimeError, match="loading"):  # past the guard: resources on, or never WebKit
        document._load(page)
    notes = tmp_path / "notes.rtf"
    notes.write_text("{\\rtf1 x}")
    with pytest.raises(RuntimeError, match="loading"):
        document._load(notes, resources=False)
    package = tmp_path / "notes.rtfd"  # a folder: it can't be a page, whatever's in it
    package.mkdir()
    with pytest.raises(RuntimeError, match="loading"):
        document._load(package, resources=False)


@pytest.mark.parametrize("name", ["page.html", "page.shtml", "page.shtm", "page.xhtml", "page.xht", "notes.txt"])
def test_every_html_extension_is_read_as_utf8(tmp_path, name):
    from macos import document

    source = tmp_path / name
    source.write_text("<p>Olá</p>", encoding="utf-8")
    assert document._reads_as_utf8(source)
    source.write_text('<meta charset="latin-1"><p>Ol\xe1</p>', encoding="latin-1")
    assert not document._reads_as_utf8(source)
    if source.suffix != ".txt":  # a page may also name it in an XML declaration (XHTML)
        source.write_bytes(b'<?xml version="1.0" encoding="ISO-8859-1"?><p>\xc3\xa9</p>')  # valid UTF-8 too
        assert not document._reads_as_utf8(source)


@pytest.mark.parametrize(
    "page",
    [
        b'<script src="a.js" charset="utf-8"></script><p>caf\xc3\xa9</p>',
        b'<link rel="stylesheet" href="a.css" charset="utf-8"><p>caf\xc3\xa9</p>',
        b"<p>Use charset=utf-8 in headers. caf\xc3\xa9</p>",
        b'<!-- <meta charset="latin-1"> --><p>caf\xc3\xa9</p>',
        b'<p>caf\xc3\xa9 <?xml version="1.0" encoding="ISO-8859-1"?></p>',  # not the file's declaration
    ],
)
def test_a_charset_that_names_no_encoding_of_the_page_is_ignored(tmp_path, page):
    from macos import document

    source = tmp_path / "page.html"
    source.write_bytes(page)
    assert document._reads_as_utf8(source)
    source.write_bytes(b'<meta http-equiv="Content-Type" content="text/html; charset=latin-1">' + page)
    assert not document._reads_as_utf8(source)
    source.write_bytes(b'\xef\xbb\xbf\n<?xml version="1.0" encoding="ISO-8859-1"?>' + page)
    assert not document._reads_as_utf8(source)


@pytest.mark.parametrize(
    "paper, margin, error",
    [
        (None, float("nan"), ValueError),  # passes the check against the paper, and the printing never returns
        (None, float("inf"), ValueError),
        (None, -1, ValueError),
        (None, True, TypeError),
        (None, "36", TypeError),
        (3, 72.0, ValueError),
        (b"a4", 72.0, ValueError),
        ("bogus", 72.0, ValueError),
    ],
)
def test_pdf_layout_is_checked_before_reading(fake_run, monkeypatch, tmp_path, paper, margin, error):
    from macos import document

    def loading(*args, **kwargs):
        raise AssertionError("read before the arguments were checked")

    monkeypatch.setattr(document, "_load", loading)
    monkeypatch.setattr(document._files, "on_main_thread", lambda: False)  # and before the thread check
    source = tmp_path / "notes.rtf"
    source.write_text("{\\rtf1 hi}")
    with pytest.raises(error):
        macos.document.convert(source, tmp_path / "notes.pdf", paper=paper, margin=margin)


@pytest.mark.parametrize(
    "kind, utf8, stripped",
    [("NSPlainText", True, True), ("NSHTML", False, True), ("NSOfficeOpenXML", False, True), ("NSWebArchive", False, False)],
)
def test_save_writes_text_as_utf8_and_drops_pictures_the_format_cant_hold(monkeypatch, tmp_path, kind, utf8, stripped):
    from macos import document

    made = {}
    written = []

    def send(receiver, selector, *args, **kwargs):
        if selector == "length":
            return 3
        if selector == "dataFromRange:documentAttributes:error:":
            written.append(receiver)
        return (selector, args)

    monkeypatch.setattr(document._objc, "send", send)
    monkeypatch.setattr(document._objc, "nsstring", lambda value: value)
    monkeypatch.setattr(document._objc, "nsdictionary_of", lambda options: made.update(options) or 7)
    monkeypatch.setattr(document._objc, "pybytes", lambda data: b"x")
    monkeypatch.setattr(document, "_without_attachments", lambda document: "stripped")
    monkeypatch.setattr(document._files, "write_atomically", lambda target, write: write(str(target)))

    document._save("doc", tmp_path / "out", kind)
    assert made["DocumentType"] == kind
    assert ("CharacterEncoding" in made) is utf8
    if utf8:  # NSUTF8StringEncoding, not AppKit's MacRoman
        assert made["CharacterEncoding"] == ("numberWithUnsignedInteger:", (4,))
    assert written == ["stripped" if stripped else "doc"]
    assert (tmp_path / "out").read_bytes() == b"x"
