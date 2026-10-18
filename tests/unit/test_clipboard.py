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

    with pytest.raises(macos.WaitTimeoutError) as caught:
        macos.clipboard.wait_for_change(timeout=0.01, interval=0.001)
    assert isinstance(caught.value, TimeoutError) and isinstance(caught.value, macos.MacOSError)


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

    watched = clipboard.watch(include_sensitive=True)
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


def test_watch_can_skip_what_is_marked_sensitive(monkeypatch):
    clipboard = macos.clipboard
    # (change count, content, marked as concealed or transient) at each check.
    moments = iter([(1, "old", False), (2, "s3cret", True), (3, "hello", False)])
    state = {"now": (1, "old", False)}

    monkeypatch.setattr(clipboard, "change_count", lambda: state["now"][0])
    monkeypatch.setattr(clipboard, "_is_empty", lambda: False)
    monkeypatch.setattr(clipboard, "_is_sensitive", lambda: state["now"][2])
    monkeypatch.setattr(clipboard, "paste", lambda: state["now"][1])
    monkeypatch.setattr(clipboard.time, "sleep", lambda seconds: state.update(now=next(moments, state["now"])))

    assert next(clipboard.watch(include_sensitive=False)) == "hello"  # the password is skipped
    moments = iter([(1, "old", False), (2, "s3cret", True)])
    state["now"] = (1, "old", False)
    assert next(clipboard.watch(include_sensitive=True)) == "s3cret"  # asked for, every copy


def test_sensitive_means_either_marker(monkeypatch):
    from contextlib import nullcontext

    from macos import _objc, clipboard

    types = []
    monkeypatch.setattr(clipboard, "_pasteboard", lambda: "pasteboard")
    monkeypatch.setattr(_objc, "send", lambda receiver, selector, *args, **kwargs: "types")
    monkeypatch.setattr(_objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(_objc, "nsarray", lambda array: list(types))
    monkeypatch.setattr(_objc, "pystring", lambda kind: kind)
    types[:] = ["public.utf8-plain-text"]
    assert not clipboard._is_sensitive()
    types[:] = ["org.nspasteboard.TransientType", "public.utf8-plain-text"]
    assert clipboard._is_sensitive()
    types[:] = ["org.nspasteboard.ConcealedType"]
    assert clipboard._is_sensitive()


def test_clipboard_wait_for_change_can_wait_on_past_a_concealed_copy(monkeypatch):
    counts = iter([1, 2, 2, 3, 3])  # a password is copied (2), then a link (3); each read again after the paste
    sensitive = iter([True, False])
    monkeypatch.setattr(macos.clipboard, "change_count", lambda: next(counts))
    monkeypatch.setattr(macos.clipboard, "_is_empty", lambda: False)
    monkeypatch.setattr(macos.clipboard, "_is_sensitive", lambda: next(sensitive))
    monkeypatch.setattr(macos.clipboard, "paste", lambda: "copied")

    assert macos.clipboard.wait_for_change(interval=0.001, include_sensitive=False) == "copied"
    assert next(counts, None) is None  # it waited for the third count


def test_clipboard_watch_warns_until_told_about_concealed_copies(monkeypatch):
    """The default (every copy) stays until 2.0, which will skip concealed ones: leaving it out says so."""
    monkeypatch.setattr(macos.clipboard, "change_count", lambda: 1)
    with pytest.warns(DeprecationWarning, match="include_sensitive"):
        assert list(macos.clipboard.watch(timeout=0.001, interval=0.001)) == []


@pytest.mark.parametrize("text", [None, 123, b"bytes", "\ud800"])
@pytest.mark.parametrize("sensitive", [False, True])
def test_copy_refuses_bad_text_before_clearing_the_clipboard(pasteboard, monkeypatch, text, sensitive):
    from macos import _objc

    # The real nsstring encodes as UTF-8: a lone surrogate fails there.
    monkeypatch.setattr(_objc, "nsstring", lambda value: value.encode("utf-8").decode("utf-8"))
    macos.clipboard.copy("before")

    with pytest.raises((TypeError, UnicodeEncodeError)):
        macos.clipboard.copy(text, sensitive=sensitive)
    assert pasteboard == [("public.utf8-plain-text", "before")]  # what it held, and no stray markers


def test_copy_sensitive_leaves_no_markers_when_the_text_is_refused(pasteboard, monkeypatch):
    from macos import _objc

    send = _objc.send

    def refuse_text(receiver, selector, *args, **kwargs):
        if selector == "setString:forType:":
            return False
        return send(receiver, selector, *args, **kwargs)

    monkeypatch.setattr(_objc, "send", refuse_text)
    with pytest.raises(macos.MacOSError, match="refused the text"):
        macos.clipboard.copy("s3cret", sensitive=True)
    assert pasteboard == []  # not the markers alone, which watchers would take for a copy


@pytest.mark.parametrize("paths", ["/etc/hosts", b"/etc/hosts", __import__("pathlib").Path("/etc/hosts")])
def test_copy_files_refuses_a_single_path(monkeypatch, paths):
    from macos import clipboard

    monkeypatch.setattr(clipboard, "_pasteboard", lambda: pytest.fail("the clipboard was touched"))
    with pytest.raises(TypeError, match=r"use \["):
        clipboard.copy_files(paths)


def test_copy_files_refuses_an_empty_path(monkeypatch):
    from macos import clipboard

    # Path("") is the current folder: it must not be copied in its place.
    monkeypatch.setattr(clipboard, "_pasteboard", lambda: pytest.fail("the clipboard was touched"))
    with pytest.raises(FileNotFoundError):
        clipboard.copy_files([""])


def test_copy_files_reports_a_missing_file(monkeypatch, tmp_path):
    from macos import clipboard

    monkeypatch.setattr(clipboard, "_pasteboard", lambda: pytest.fail("the clipboard was touched"))
    with pytest.raises(FileNotFoundError, match="nothing.txt"):
        clipboard.copy_files([tmp_path / "nothing.txt"])
    with pytest.raises(FileNotFoundError):  # a "folder" that is a file
        clipboard.copy_files([__file__ + "/inside"])


def test_copy_files_reports_a_permission_problem_as_one(monkeypatch, tmp_path):
    from macos import clipboard

    def denied(path, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(clipboard.os, "lstat", denied)
    monkeypatch.setattr(clipboard, "_pasteboard", lambda: pytest.fail("the clipboard was touched"))
    with pytest.raises(PermissionError):
        clipboard.copy_files([tmp_path / "locked.txt"])


def test_copy_files_takes_a_generator_and_a_broken_link(monkeypatch, tmp_path):
    from macos import clipboard

    link = tmp_path / "broken"
    link.symlink_to(tmp_path / "gone")
    written = []
    monkeypatch.setattr(clipboard, "_pasteboard", lambda: 1)
    monkeypatch.setattr(clipboard._objc, "autorelease_pool", __import__("contextlib").nullcontext)
    monkeypatch.setattr(clipboard._objc, "file_url", lambda path: path)
    monkeypatch.setattr(clipboard._objc, "nsarray_of", lambda items: list(items))

    def send(receiver, selector, *args, **kwargs):
        if selector == "writeObjects:":
            written.extend(args[0])
        return True

    monkeypatch.setattr(clipboard._objc, "send", send)
    clipboard.copy_files(path for path in [link, __file__])
    assert written == [link, __import__("pathlib").Path(__file__).absolute()]


class _Clock:
    """A fake time.monotonic and time.sleep: time only passes when slept, or when the test says so."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_watch_stops_at_the_timeout_while_copies_keep_coming(monkeypatch):
    clipboard = macos.clipboard
    clock = _Clock()
    copies = {"count": 1}

    def change_count():
        return copies["count"]

    monkeypatch.setattr(clipboard.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(clipboard.time, "sleep", clock.sleep)
    monkeypatch.setattr(clipboard, "change_count", change_count)
    monkeypatch.setattr(clipboard, "_is_empty", lambda: False)
    monkeypatch.setattr(clipboard, "paste", lambda: "copy {}".format(copies["count"]))

    def sleep(seconds):
        clock.sleep(seconds)
        copies["count"] += 1  # the first copy lands while it waits

    monkeypatch.setattr(clipboard.time, "sleep", sleep)
    yielded = []
    for text in clipboard.watch(timeout=2, interval=0.1, include_sensitive=True):
        yielded.append(text)
        assert len(yielded) < 100, "watch() ignored its timeout"
        clock.now += 0.5  # a slow loop body, while another copy lands
        copies["count"] += 1
    assert 2 <= clock.now <= 2.5 and len(yielded) == 4


def test_wait_for_change_stops_at_the_timeout_while_concealed_copies_keep_coming(monkeypatch):
    clipboard = macos.clipboard
    clock = _Clock()
    copies = {"count": 1}

    def change_count():
        copies["count"] += 1  # a new concealed copy at every look
        clock.now += 0.1
        return copies["count"]

    monkeypatch.setattr(clipboard.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(clipboard.time, "sleep", clock.sleep)
    monkeypatch.setattr(clipboard, "change_count", change_count)
    monkeypatch.setattr(clipboard, "_is_empty", lambda: False)
    monkeypatch.setattr(clipboard, "_is_sensitive", lambda: True)
    monkeypatch.setattr(clipboard, "paste", lambda: "s3cret")

    with pytest.raises(macos.WaitTimeoutError):
        clipboard.wait_for_change(timeout=2, interval=0.1, include_sensitive=False)
    assert clock.now < 3


def _recopied_at_the_deadline(monkeypatch):
    """A fake clipboard where the first copy is read past the deadline, and copied over while it's read."""
    clipboard = macos.clipboard
    clock = _Clock()
    copies = {"count": 1}

    def paste():
        if copies["count"] == 2:
            clock.now += 0.2  # a slow read, through the deadline
            copies["count"] += 1  # and a second plain copy lands meanwhile
            return "copy 2"
        return "copy {}".format(copies["count"])

    def sleep(seconds):
        clock.sleep(seconds)
        copies["count"] = max(copies["count"], 2)  # the first copy lands while it waits

    monkeypatch.setattr(clipboard.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(clipboard.time, "sleep", sleep)
    monkeypatch.setattr(clipboard, "change_count", lambda: copies["count"])
    monkeypatch.setattr(clipboard, "_is_empty", lambda: False)
    monkeypatch.setattr(clipboard, "_is_sensitive", lambda: False)
    monkeypatch.setattr(clipboard, "paste", paste)


def test_wait_for_change_returns_a_copy_overwritten_at_the_deadline(monkeypatch):
    # Two plain copies landed in time: "nothing was copied" would be wrong, and the newer one is there.
    _recopied_at_the_deadline(monkeypatch)
    assert macos.clipboard.wait_for_change(timeout=0.1, interval=0.01, include_sensitive=False) == "copy 3"


def test_watch_yields_the_newer_copy_when_one_is_overwritten_at_the_deadline(monkeypatch):
    _recopied_at_the_deadline(monkeypatch)
    assert list(macos.clipboard.watch(timeout=0.1, interval=0.01, include_sensitive=False)) == ["copy 3"]


@pytest.mark.parametrize(
    "timeout, interval",
    [(float("inf"), float("inf")), (1e300, float("inf")), (None, 1e300), (float("inf"), 1e300)],
)
def test_wait_for_change_and_watch_never_hand_time_sleep_a_value_it_overflows_on(monkeypatch, timeout, interval):
    clipboard = macos.clipboard
    clock = _Clock()
    copies = {"count": 1}

    def sleep(seconds):
        if not seconds < 1e12:  # as time.sleep does, past what a C time value holds
            raise OverflowError("timestamp too large to convert to C _PyTime_t")
        clock.sleep(seconds)
        copies["count"] += 1  # a copy lands while it waits

    monkeypatch.setattr(clipboard.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(clipboard.time, "sleep", sleep)
    monkeypatch.setattr(clipboard, "change_count", lambda: copies["count"])
    monkeypatch.setattr(clipboard, "_is_empty", lambda: False)
    monkeypatch.setattr(clipboard, "paste", lambda: "copied")

    assert clipboard.wait_for_change(timeout=timeout, interval=interval) == "copied"
    assert next(clipboard.watch(timeout=timeout, interval=interval, include_sensitive=True)) == "copied"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval": float("nan")},
        {"interval": float("inf")},  # no deadline: time.sleep would overflow
        {"interval": 0},
        {"timeout": float("nan")},
    ],
)
def test_wait_for_change_and_watch_refuse_values_that_would_hang(monkeypatch, kwargs):
    clipboard = macos.clipboard
    monkeypatch.setattr(clipboard, "change_count", lambda: pytest.fail("the clipboard was read"))

    with pytest.raises(ValueError):
        clipboard.wait_for_change(**kwargs)
    with pytest.raises(ValueError):
        clipboard.watch(include_sensitive=True, **kwargs)  # at the call, not at the first next()


def test_wait_for_change_still_takes_an_infinite_interval_with_a_timeout(monkeypatch):
    monkeypatch.setattr(macos.clipboard, "change_count", lambda: 1)
    with pytest.raises(macos.WaitTimeoutError):
        macos.clipboard.wait_for_change(timeout=0.01, interval=float("inf"))


@pytest.fixture
def images(monkeypatch):
    """A fake pasteboard holding ``images["public.png"]`` / ``images["public.tiff"]`` bytes (``None``: not there)."""
    from contextlib import nullcontext

    from macos import _objc, clipboard

    held = {"public.png": None, "public.tiff": None, "rep": None}

    def send(receiver, selector, *args, **kwargs):
        if selector == "dataForType:":
            data = held[args[0]]
            return None if data is None else ("NSData", data)  # an object, even for no bytes
        if selector == "imageRepWithData:":
            return held["rep"]
        return None

    monkeypatch.setattr(clipboard, "_pasteboard", lambda: "pasteboard")
    monkeypatch.setattr(_objc, "send", send)
    monkeypatch.setattr(_objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(_objc, "nsstring", lambda text: text)
    monkeypatch.setattr(_objc, "cls", lambda name: name)
    monkeypatch.setattr(_objc, "pybytes", lambda data: data[1] if data else None)
    return held


def test_paste_image_returns_none_only_without_an_image(images):
    assert macos.clipboard.paste_image() is None
    images["public.png"] = b"\x89PNG"
    assert macos.clipboard.paste_image() == b"\x89PNG"


def test_paste_image_refuses_an_empty_png(images):
    images["public.png"] = b""  # an entry, with no bytes
    with pytest.raises(macos.MacOSError):
        macos.clipboard.paste_image()


def test_paste_image_refuses_tiff_macos_cant_decode(images):
    images["public.tiff"] = b"garbage"  # imageRepWithData: gives nil
    with pytest.raises(macos.MacOSError):
        macos.clipboard.paste_image()
