"""Unit tests for :mod:`macos.camera`. They run on any platform."""

import pytest

import macos


def test_temporary_photo_is_removed_on_failure(monkeypatch, tmp_path):
    from macos import _capture

    monkeypatch.setattr(macos.camera.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(_capture, "request_permission", lambda media: False)
    monkeypatch.setattr(_capture, "_status", lambda media: _capture._DENIED)  # denied, not left unanswered

    with pytest.raises(macos.PermissionDeniedError):
        macos.camera.photo()

    assert list(tmp_path.iterdir()) == []


def test_camera_argument_checks(tmp_path):
    with pytest.raises(ValueError, match="can't save '.gif'"):
        macos.camera.photo(tmp_path / "out.gif")
    with pytest.raises(ValueError, match=".mov"):
        macos.camera.record(tmp_path / "out.mp4", 1)
    with pytest.raises(ValueError, match="positive"):
        macos.camera.record(tmp_path / "out.mov", 0)


def test_the_camera_works_only_on_the_main_thread(monkeypatch, tmp_path):
    import threading

    from macos import _capture

    monkeypatch.setattr(_capture, "require_permission", lambda media: None)
    errors = []

    def elsewhere():
        for work in (lambda: macos.camera.photo(tmp_path / "me.jpg"), lambda: macos.camera.record(tmp_path / "clip.mov", 1)):
            try:
                work()
            except macos.MacOSError as error:
                errors.append(str(error))

    thread = threading.Thread(target=elsewhere)
    thread.start()
    thread.join()
    assert len(errors) == 2 and all("must run on the main thread" in error for error in errors)


def test_a_capture_that_timed_out_is_forgotten(monkeypatch):
    from macos import camera

    monkeypatch.setattr(camera._objc, "run_until", lambda done, timeout: done())
    monkeypatch.setattr(camera._objc, "new", lambda name: 0xC0FFEE)
    monkeypatch.setattr(camera._objc, "define_class", lambda *args, **kwargs: None)
    delegate = camera._delegate("photo")
    with pytest.raises(macos.MacOSError, match="didn't finish the photo"):
        camera._wait(delegate, "photo")
    # Its callback, arriving late, is dropped: the next delegate at the same address doesn't read it.
    camera._store(delegate, {"done": True, "data": b"old photo"})
    camera._movie_started(delegate, 0, 0, 0, 0)
    assert delegate not in camera._results and delegate not in camera._started and delegate not in camera._waiting

    again = camera._delegate("photo")
    camera._store(again, {"done": True, "data": b"new photo"})
    assert camera._wait(again, "photo")["data"] == b"new photo"
    assert again not in camera._results and again not in camera._waiting


@pytest.fixture
def capture_stubs(monkeypatch):
    """photo() and _record() up to the session: what was made, started and forgotten, in order."""
    from contextlib import nullcontext

    from macos import _capture, camera

    happened = []
    monkeypatch.setattr(camera._files, "require_main_thread", lambda what: None)
    monkeypatch.setattr(_capture, "require_permission", lambda media: None)
    monkeypatch.setattr(camera._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(camera._objc, "new", lambda name: name)
    monkeypatch.setattr(camera, "_device", lambda which: "device")
    monkeypatch.setattr(camera, "_input", lambda device: "input")
    monkeypatch.setattr(camera, "_delegate", lambda kind: happened.append("delegate") or "the-delegate")
    monkeypatch.setattr(camera, "_forget", lambda delegate: happened.append("forget"))
    return happened


def test_the_camera_isnt_turned_on_when_its_delegate_cant_be_made(capture_stubs, monkeypatch, tmp_path):
    from macos import camera

    def interrupted(kind):
        raise KeyboardInterrupt

    monkeypatch.setattr(camera, "_delegate", interrupted)
    monkeypatch.setattr(camera, "_session", lambda inputs, output: capture_stubs.append("camera on"))
    for work in (lambda: macos.camera.photo(tmp_path / "me.jpg"), lambda: camera._record(tmp_path / "clip.mov", 1, None, False)):
        with pytest.raises(KeyboardInterrupt):
            work()
    assert "camera on" not in capture_stubs  # nothing between the camera turning on and the block that turns it off


def test_a_session_that_fails_to_start_forgets_its_delegate(capture_stubs, monkeypatch, tmp_path):
    from macos import camera

    def refused(inputs, output):
        raise macos.MacOSError("the camera can't be used that way")

    monkeypatch.setattr(camera, "_session", refused)
    for work in (lambda: macos.camera.photo(tmp_path / "me.jpg"), lambda: camera._record(tmp_path / "clip.mov", 1, None, False)):
        with pytest.raises(macos.MacOSError, match="can't be used that way"):
            work()
    assert capture_stubs == ["delegate", "forget", "delegate", "forget"]
