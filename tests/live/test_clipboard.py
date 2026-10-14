"""Tests of :mod:`macos.clipboard` against the real system. Skipped outside macOS."""

import uuid

import pytest

import macos
from macos import _objc
from tests.helpers import small_png


def _clipboard_has_content() -> bool:
    with _objc.autorelease_pool():
        types = _objc.send(macos.clipboard._pasteboard(), "types")
        return bool(types) and _objc.send(types, "count", restype=_objc.NSUInteger) > 0


@pytest.fixture
def restore_clipboard():
    before = macos.clipboard.paste()
    if before is None and _clipboard_has_content():
        # Only text can be saved and put back: don't destroy a copied image
        # or file just to run the tests.
        pytest.skip("the clipboard holds non-text content")
    yield
    if before is None:
        macos.clipboard.clear()
    else:
        macos.clipboard.copy(before)


@pytest.mark.usefixtures("restore_clipboard")
def test_clipboard_round_trip():
    text = "olá 🍎 \"quoted\" \\ {}".format(uuid.uuid4())
    count = macos.clipboard.change_count()

    macos.clipboard.copy(text)

    assert macos.clipboard.paste() == text
    assert macos.clipboard.change_count() > count


@pytest.mark.usefixtures("restore_clipboard")
def test_clipboard_clear():
    macos.clipboard.copy("something")
    macos.clipboard.clear()

    assert macos.clipboard.paste() is None


@pytest.mark.usefixtures("restore_clipboard")
def test_clipboard_keeps_nul_characters():
    macos.clipboard.copy("a\0b")

    assert macos.clipboard.paste() == "a\0b"


_PIXEL_PNG = small_png()


@pytest.mark.usefixtures("restore_clipboard")
def test_clipboard_image_round_trip():
    macos.clipboard.copy_image(_PIXEL_PNG)

    assert macos.clipboard.has_image()
    assert macos.clipboard.paste() is None
    assert macos.clipboard.paste_image().startswith(b"\x89PNG\r\n\x1a\n")

    macos.clipboard.copy("text again")
    assert not macos.clipboard.has_image()
    assert macos.clipboard.paste_image() is None


def test_copy_image_rejects_non_images():
    with pytest.raises(ValueError):
        macos.clipboard.copy_image(b"not an image")


@pytest.mark.usefixtures("restore_clipboard")
def test_clipboard_wait_for_change():
    import threading

    timer = threading.Timer(0.3, macos.clipboard.copy, args=("changed",))
    timer.start()
    try:
        assert macos.clipboard.wait_for_change(timeout=5, interval=0.05) == "changed"
    finally:
        timer.cancel()


@pytest.mark.usefixtures("restore_clipboard")
def test_clipboard_files_round_trip(tmp_path):
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.touch()
    second.touch()

    macos.clipboard.copy_files([first, second])
    assert [path.resolve() for path in macos.clipboard.paste_files()] == [first.resolve(), second.resolve()]

    macos.clipboard.copy("text")
    assert macos.clipboard.paste_files() == []


@pytest.mark.usefixtures("restore_clipboard")
def test_clipboard_watch():
    import threading
    import time

    def copies():
        for text in ("one", "two"):
            time.sleep(0.4)
            macos.clipboard.copy(text)

    threading.Thread(target=copies).start()
    seen = []
    for text in macos.clipboard.watch(timeout=3, include_sensitive=True):
        seen.append(text)
        if len(seen) == 2:
            break
    assert seen == ["one", "two"]
    assert list(macos.clipboard.watch(timeout=0.3, include_sensitive=True)) == []
