"""Unit tests for :mod:`macos.document`. They run on any platform."""

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


def test_what_appkit_does_only_on_the_main_thread_says_so(fake_run, tmp_path):
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
