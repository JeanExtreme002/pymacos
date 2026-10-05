"""Unit tests for :mod:`macos._files`. They run on any platform."""

import os
import stat
import threading

import pytest

import macos
from macos import _files


def _mode(path):
    return stat.S_IMODE(os.stat(str(path)).st_mode)


@pytest.fixture
def umask_022():
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)


def test_a_new_file_gets_the_usual_permissions_not_a_temporary_files(tmp_path, umask_022):
    target = tmp_path / "new" / "folder" / "out.pdf"  # its folders are made
    with _files.replacing(target) as temporary:
        assert temporary.parent.parent == target.parent and temporary.name == "out.pdf"
        assert not temporary.exists()  # for the tools that refuse to replace a file
        temporary.write_bytes(b"done")
    assert target.read_bytes() == b"done"
    assert _mode(target) == 0o644  # 0o666 less the umask, not mkstemp's 0o600
    assert os.listdir(str(target.parent)) == ["out.pdf"]  # nothing left beside it


def test_replacing_a_file_keeps_its_permissions(tmp_path, umask_022):
    target = tmp_path / "shared.txt"
    target.write_bytes(b"old")
    os.chmod(str(target), 0o664)
    with _files.replacing(target) as temporary:
        temporary.write_bytes(b"new")
    assert target.read_bytes() == b"new" and _mode(target) == 0o664


def test_a_failure_leaves_the_target_as_it_was(tmp_path):
    target = tmp_path / "keep.txt"
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError):
        with _files.replacing(target) as temporary:
            temporary.write_bytes(b"half")
            raise RuntimeError("boom")
    assert target.read_bytes() == b"old" and os.listdir(str(tmp_path)) == ["keep.txt"]
    with pytest.raises(macos.MacOSError, match="could not write"):
        with _files.replacing(target):
            pass  # nothing written
    assert target.read_bytes() == b"old" and os.listdir(str(tmp_path)) == ["keep.txt"]


def test_write_atomically(tmp_path):
    target = tmp_path / "out.txt"
    assert _files.write_atomically(str(target), lambda name: open(name, "w").write("hi")) == target
    assert target.read_text() == "hi"
    with pytest.raises(macos.MacOSError, match="could not write"):
        _files.write_atomically(target, lambda name: False)
    assert target.read_text() == "hi"


def test_existing(tmp_path):
    assert _files.existing(str(tmp_path)) == tmp_path
    with pytest.raises(FileNotFoundError):
        _files.existing(tmp_path / "missing")


def test_main_thread_only(monkeypatch):
    assert _files.on_main_thread()
    _files.require_main_thread("this")  # fine here
    errors = []

    def elsewhere():
        assert not _files.on_main_thread()
        try:
            _files.require_main_thread("macos.camera.photo()")
        except macos.MacOSError as error:
            errors.append(str(error))

    thread = threading.Thread(target=elsewhere)
    thread.start()
    thread.join()
    assert errors and errors[0].startswith("macos.camera.photo() must run on the main thread")


def test_nsrange_is_two_unsigned_words():
    import ctypes

    assert ctypes.sizeof(_files.NSRange) == 2 * ctypes.sizeof(ctypes.c_size_t)
    assert (_files.NSRange(3, 4).location, _files.NSRange(3, 4).length) == (3, 4)
