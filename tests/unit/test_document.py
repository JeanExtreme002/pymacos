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
    assert answered == {1: 1, 2: 2, 3: None, 4: None, 5: None, 6: None}
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
