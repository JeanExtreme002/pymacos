"""Tests of :mod:`macos.document` against the real system. Skipped outside macOS."""

import http.server
import threading
import zipfile

import pytest

import macos
from tests.helpers import ON_GITHUB, docx_with_table, png_size, small_png


@pytest.fixture
def report(tmp_path):
    return docx_with_table(tmp_path / "report.docx", "Relatório mensal", [["Mês", "Total"], ["Setembro", "R$ 1.234"]])


def test_text_of_a_word_document(report):
    assert macos.document.text(report) == "Relatório mensal\nMês\nTotal\nSetembro\nR$ 1.234\n"


@pytest.mark.parametrize("extension", [".rtf", ".html", ".odt", ".docx", ".doc", ".txt", ".webarchive"])
def test_convert_between_formats(report, tmp_path, extension):
    output = macos.document.convert(report, tmp_path / "out" / ("report" + extension))
    assert output == tmp_path / "out" / ("report" + extension)
    assert "Setembro" in macos.document.text(output) and "Relatório" in macos.document.text(output)
    assert [path.name for path in output.parent.iterdir()] == [output.name]  # no temporary file left


def test_convert_writes_plain_text_as_utf8(tmp_path):
    source = tmp_path / "u.txt"
    source.write_text("café 日本 😀 end", encoding="utf-8")
    # The bytes themselves: text() would read AppKit's MacRoman back as well.
    assert macos.document.convert(source, tmp_path / "out.txt").read_bytes().decode("utf-8") == "café 日本 😀 end"


def test_pictures_are_kept_only_where_the_format_holds_them(tmp_path):
    (tmp_path / "pic.png").write_bytes(small_png())
    page = tmp_path / "page.html"
    page.write_text('<p>a <img src="pic.png"> b</p>', encoding="utf-8")
    assert macos.document.convert(page, tmp_path / "out.txt").read_text(encoding="utf-8") == "a  b\n"  # no U+FFFC
    assert b"Attachment" not in macos.document.convert(page, tmp_path / "out.html").read_bytes()  # no dangling <img>
    assert b"image/png" in macos.document.convert(page, tmp_path / "out.webarchive").read_bytes()


def test_a_charset_attribute_doesnt_stop_utf8_detection(tmp_path):
    page = tmp_path / "page.html"
    page.write_text('<script src="a.js" charset="utf-8"></script><p>Use charset=utf-8. café ñ</p>', encoding="utf-8")
    assert macos.document.text(page, resources=False) == "Use charset=utf-8. café ñ\n"


def test_convert_keeps_tables_except_in_word_files(report, tmp_path):
    assert "<table:table " in zipfile.ZipFile(macos.document.convert(report, tmp_path / "a.odt")).read("content.xml").decode()
    assert b"\\trowd" in macos.document.convert(report, tmp_path / "a.rtf").read_bytes()
    assert b"<w:tbl>" not in zipfile.ZipFile(macos.document.convert(report, tmp_path / "a.docx")).read("word/document.xml")


def test_convert_to_pdf_lays_out_pages(tmp_path):
    source = tmp_path / "long.html"
    paragraphs = "".join("<p>Parágrafo {} de um relatório comprido.</p>".format(number) for number in range(150))
    source.write_text("<html><body><h1>Relatório</h1>{}</body></html>".format(paragraphs))

    a4 = macos.document.convert(source, tmp_path / "long.pdf", paper="a4")
    assert macos.pdf.page_count(a4) > 1
    text = macos.pdf.text(a4)
    assert text.startswith("Relatório") and "Parágrafo 149 de um relatório comprido." in text  # UTF-8, and nothing lost
    width, height = png_size(macos.pdf.render(a4, 1, size=1000))
    assert abs(width / height - 595.28 / 841.89) < 0.01

    letter = macos.document.convert(source, tmp_path / "letter.pdf", paper="letter", margin=36)
    width, height = png_size(macos.pdf.render(letter, 1, size=1000))
    assert abs(width / height - 612 / 792) < 0.01
    wide = macos.document.convert(source, tmp_path / "wide.pdf", paper="a4", margin=150)
    assert macos.pdf.page_count(wide) > macos.pdf.page_count(a4)  # wider margins: less on each page

    with pytest.raises(ValueError, match="paper is"):
        macos.document.convert(source, tmp_path / "x.pdf", paper="a5")
    with pytest.raises(ValueError, match="margin must leave room"):
        macos.document.convert(source, tmp_path / "x.pdf", margin=400)


def test_convert_a_word_table_to_pdf(report, tmp_path):
    output = macos.document.convert(report, tmp_path / "report.pdf")
    assert macos.pdf.page_count(output) == 1
    text = macos.pdf.text(output)
    assert "Setembro" in text and "R$ 1.234" in text
    # Drawn as a table, the cells of a row share a line: "Mês" and "Total" aren't on lines of their own.
    assert "Mês\nTotal" not in text


def test_text_reads_the_encoding_an_html_page_declares(tmp_path):
    page = tmp_path / "latin.html"
    page.write_bytes('<html><head><meta charset="iso-8859-1"></head><body><p>Olá ação</p></body></html>'.encode("latin-1"))
    assert macos.document.text(page) == "Olá ação\n"
    plain = tmp_path / "plain.txt"
    plain.write_text("Olá\n", encoding="utf-8")
    assert macos.document.text(plain) == "Olá\n"


@pytest.fixture
def web_server():
    """A local web server that notes what it's asked for."""
    asked = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/css")
            self.end_headers()
            self.wfile.write(b"p { color: red }")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:{}".format(server.server_address[1]), asked
    server.shutdown()
    thread.join()


@pytest.mark.skipif(
    ON_GITHUB,
    reason="WebKit fetching from a local web server raises the Local Network prompt on GitHub's runners, which takes "
    "the focus from the screen tests' window; the rule itself is unit-tested",
)
def test_html_resources_are_not_fetched_when_told_so(tmp_path, web_server):
    address, asked = web_server
    page = tmp_path / "page.html"
    page.write_text(
        '<html><head><link rel="stylesheet" href="{0}/style.css"></head>'
        '<body><p>Hello</p><img src="{0}/pic.png"><iframe src="{0}/frame.html"></iframe></body></html>'.format(address)
    )
    assert macos.document.text(page, resources=False).startswith("Hello")
    assert b"Hello" in macos.document.convert(page, tmp_path / "page.rtf", resources=False).read_bytes()
    assert asked == []
    # Another extension macOS reads through WebKit: told so, it fetches nothing either.
    other = tmp_path / "page.shtml"
    other.write_text(page.read_text())
    assert macos.document.text(other, resources=False).startswith("Hello")
    assert asked == []
    # As a browser would, otherwise: the page's resources are fetched while it's read.
    assert macos.document.text(page).startswith("Hello")
    assert "/style.css" in asked


def test_documents_that_arent_web_pages_read_the_same_with_resources_off(report, tmp_path):
    assert macos.document.text(report, resources=False) == macos.document.text(report)
    notes = tmp_path / "notes.rtf"
    macos.document.convert(report, notes)
    assert macos.document.text(notes, resources=False) == macos.document.text(notes)


def test_resources_off_keeps_this_macs_files_out_of_the_output(tmp_path):
    # WebKit is refused the page's file:// pictures, but AppKit then reads them itself and attaches them.
    secret = tmp_path / "elsewhere" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("TOP-SECRET-123")
    (tmp_path / "elsewhere" / "red.png").write_bytes(small_png(40, 40))
    page = tmp_path / "site" / "page.html"
    page.parent.mkdir()
    page.write_text(
        '<p>Hello</p><img src="file://{0}"><object data="{0}"></object><img src="../elsewhere/red.png">'.format(secret)
    )
    assert macos.document.text(page, resources=False) == "Hello\n"
    archive = macos.document.convert(page, tmp_path / "page.webarchive", resources=False)
    assert b"TOP-SECRET" not in archive.read_bytes()
    assert b"/Subtype /Image" not in macos.document.convert(page, tmp_path / "page.pdf", resources=False).read_bytes()
    # As a browser would, otherwise: the picture is in.
    assert b"/Subtype /Image" in macos.document.convert(page, tmp_path / "with.pdf").read_bytes()


def test_resources_off_survives_urls_that_arent_paths(tmp_path):
    page = tmp_path / "page.html"
    page.write_text('<p>Hi</p><img src="file:///tmp/a%00b.png"><img src="x%00y.png"><link rel="stylesheet" href="s%00.css">')
    assert macos.document.text(page, resources=False) == "Hi\n"  # refused, not a crash
