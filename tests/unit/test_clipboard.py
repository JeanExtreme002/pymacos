"""Unit tests for :mod:`macos.clipboard`. They run on any platform."""

import pytest

import macos


def test_clipboard_wait_for_change(monkeypatch):
    counts = iter([1, 1, 1, 2])
    monkeypatch.setattr(macos.clipboard, "change_count", lambda: next(counts))
    monkeypatch.setattr(macos.clipboard, "_is_empty", lambda: False)
    monkeypatch.setattr(macos.clipboard, "paste", lambda: "new text")

    assert macos.clipboard.wait_for_change(interval=0.001) == "new text"


def test_clipboard_wait_for_change_waits_for_the_content_after_a_clear(monkeypatch):
    # The count moves when the copying app clears the clipboard, before it
    # writes the text: reading at that point would give None.
    counts = iter([1, 2, 2, 2])
    empty = iter([True, True, False])
    monkeypatch.setattr(macos.clipboard, "change_count", lambda: next(counts))
    monkeypatch.setattr(macos.clipboard, "_is_empty", lambda: next(empty))
    monkeypatch.setattr(macos.clipboard, "paste", lambda: "written")

    assert macos.clipboard.wait_for_change(interval=0.001) == "written"


def test_clipboard_wait_for_change_times_out(monkeypatch):
    monkeypatch.setattr(macos.clipboard, "change_count", lambda: 1)

    with pytest.raises(TimeoutError):
        macos.clipboard.wait_for_change(timeout=0.01, interval=0.001)


def test_clipboard_wait_for_change_never_sleeps_past_the_timeout(monkeypatch):
    import time

    monkeypatch.setattr(macos.clipboard, "change_count", lambda: 1)
    start = time.monotonic()

    with pytest.raises(TimeoutError):
        macos.clipboard.wait_for_change(timeout=0.05, interval=10)
    assert time.monotonic() - start < 1


def test_copy_files_needs_paths():
    with pytest.raises(ValueError):
        macos.clipboard.copy_files([])


def test_clipboard_watch_yields_each_copy(monkeypatch):
    clipboard = macos.clipboard
    # What the clipboard holds at each check, as (change count, content); a copy clears, then writes.
    moments = iter([(1, "old"), (2, None), (3, "one"), (3, "one"), (4, "image")])
    state = {"now": (1, "old"), "copy_while_reading": False}

    def tick(seconds):
        state["now"] = next(moments, state["now"])

    def paste():
        content = state["now"][1]
        if state["copy_while_reading"]:
            state["copy_while_reading"] = False
            state["now"] = (5, "newer")  # copied again, between the count and the content
        return None if content == "image" else content

    monkeypatch.setattr(clipboard, "change_count", lambda: state["now"][0])
    monkeypatch.setattr(clipboard, "_is_empty", lambda: state["now"][1] is None)
    monkeypatch.setattr(clipboard, "paste", paste)
    monkeypatch.setattr(clipboard.time, "sleep", tick)

    watched = clipboard.watch()
    assert next(watched) == "one"
    state["copy_while_reading"] = True
    state["now"] = (4, "image")
    assert next(watched) == "newer"  # the image read mid-copy is skipped, not yielded twice
    watched.close()
    with pytest.raises(ValueError, match="interval"):
        next(clipboard.watch(interval=0))


@pytest.fixture
def pasteboard(monkeypatch):
    """A fake general pasteboard: the types written, in order, after the last clear."""
    from contextlib import nullcontext

    from macos import _objc, clipboard

    written = []

    def send(receiver, selector, *args, **kwargs):
        if selector == "clearContents":
            del written[:]
        elif selector in ("setData:forType:", "setString:forType:"):
            written.append((args[1], args[0]))
            return True

    monkeypatch.setattr(clipboard, "_pasteboard", lambda: "pasteboard")
    monkeypatch.setattr(_objc, "send", send)
    monkeypatch.setattr(_objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(_objc, "nsstring", lambda text: text)
    monkeypatch.setattr(_objc, "nsdata", lambda payload: payload)
    return written


def test_copy_sensitive_marks_it_for_clipboard_managers(pasteboard):
    macos.clipboard.copy("s3cret", sensitive=True)
    assert pasteboard == [
        ("org.nspasteboard.ConcealedType", b""),
        ("org.nspasteboard.TransientType", b""),
        ("public.utf8-plain-text", "s3cret"),
    ]

    macos.clipboard.copy("hello")
    assert pasteboard == [("public.utf8-plain-text", "hello")]


def test_copy_image_closes_its_file(monkeypatch, tmp_path):
    import builtins

    from macos import clipboard

    opened = []
    real_open = builtins.open

    def tracking_open(*args, **kwargs):
        opened.append(real_open(*args, **kwargs))
        return opened[-1]

    image = tmp_path / "a.png"
    image.write_bytes(b"not really a png")
    monkeypatch.setattr(builtins, "open", tracking_open)
    monkeypatch.setattr(clipboard, "framework", lambda name: (_ for _ in ()).throw(RuntimeError("stop here")))

    with pytest.raises(RuntimeError, match="stop here"):
        clipboard.copy_image(image)
    assert opened and opened[0].closed
