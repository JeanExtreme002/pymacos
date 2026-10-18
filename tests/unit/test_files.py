"""Unit tests for :mod:`macos._files`. They run on any platform."""

import ctypes
import errno
import os
import stat
import threading
import types

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


def test_an_output_named_like_the_permission_probe(tmp_path, umask_022):
    target = tmp_path / ".mode"  # the name the probe once took, beside the staged output
    with _files.replacing(target) as temporary:
        temporary.write_bytes(b"done")
    assert target.read_bytes() == b"done" and _mode(target) == 0o644
    assert os.listdir(str(tmp_path)) == [".mode"]


def test_replacing_a_file_keeps_its_permissions(tmp_path, umask_022):
    target = tmp_path / "shared.txt"
    target.write_bytes(b"old")
    os.chmod(str(target), 0o664)
    with _files.replacing(target) as temporary:
        temporary.write_bytes(b"new")
    assert target.read_bytes() == b"new" and _mode(target) == 0o664


def test_replacing_a_file_drops_its_special_bits(tmp_path, umask_022):
    target = tmp_path / "sticky.txt"
    target.write_bytes(b"old")
    os.chmod(str(target), 0o1664)  # the sticky bit: not something the new content earned
    with _files.replacing(target) as temporary:
        temporary.write_bytes(b"new")
    assert _mode(target) == 0o664


def test_a_new_file_follows_the_umask_of_the_moment(tmp_path, umask_022):
    # A program may go private (os.umask) between two writes: the second must not keep the first's mode.
    with _files.replacing(tmp_path / "public") as temporary:
        temporary.write_bytes(b"x")
    os.umask(0o077)
    with _files.replacing(tmp_path / "private") as temporary:
        temporary.write_bytes(b"x")
    assert _mode(tmp_path / "public") == 0o644 and _mode(tmp_path / "private") == 0o600


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


def test_a_symbolic_link_stays_one_and_its_file_is_replaced(tmp_path):
    (tmp_path / "data").mkdir()
    real = tmp_path / "data" / "memo-2024.bin"
    real.write_bytes(b"old")
    link = tmp_path / "memo.m4a"
    link.symlink_to(real)

    with _files.replacing(link) as temporary:
        assert temporary.name == "memo.m4a"  # the caller's name: its extension picks the format
        assert temporary.parent.parent == real.parent  # beside the real file: a rename on its disk
        temporary.write_bytes(b"new")

    assert link.is_symlink() and os.readlink(str(link)) == str(real)
    assert real.read_bytes() == b"new"
    assert sorted(os.listdir(str(tmp_path / "data"))) == ["memo-2024.bin"]


@pytest.mark.parametrize("kind", ["empty folder", "folder", "link to a folder", "link loop"])
def test_an_output_that_cant_be_a_file_fails_before_the_work(tmp_path, kind):
    # A folder named like the output: a long recording mustn't run, then be thrown away.
    target = tmp_path / "clip.mov"
    if kind == "link loop":
        target.symlink_to(tmp_path / "other.mov")
        (tmp_path / "other.mov").symlink_to(target)
        expected = errno.ELOOP
    else:
        folder = tmp_path / "clips" if kind == "link to a folder" else target
        folder.mkdir()
        if kind == "folder":
            (folder / "inside.txt").write_bytes(b"keep")
        if kind == "link to a folder":
            target.symlink_to(folder)
        expected = errno.EISDIR
    calls = []
    with pytest.raises(OSError) as raised:
        _files.write_atomically(target, calls.append)
    assert calls == [] and raised.value.errno == expected
    assert raised.value.filename == str(target)  # the caller's path, not a hidden staging one
    if kind == "folder":
        assert (target / "inside.txt").read_bytes() == b"keep"
    assert not [name for name in os.listdir(str(tmp_path)) if name.startswith(".")]


class _FakeXattrs:
    """libSystem's extended attribute calls, over a dictionary per path, and its access list calls."""

    def __init__(self, files, lists=None):
        self.files = files
        self.lists = lists or {}  # path: the access list, an int standing for an acl_t
        self.set, self.freed = [], []

    def _put(self, data, buffer, size):
        if buffer is None:
            return len(data)
        if size < len(data):
            return -1
        ctypes.memmove(buffer, data, len(data))
        return len(data)

    def listxattr(self, path, buffer, size, options):
        names = b"".join(name + b"\0" for name in self.files.get(path, {}))
        return self._put(names, buffer, size)

    def getxattr(self, path, name, buffer, size, position, options):
        value = self.files.get(path, {}).get(name)
        return -1 if value is None else self._put(value, buffer, size)

    def setxattr(self, path, name, buffer, size, position, options):
        attributes = self.files.setdefault(path, {})
        if options & 0x0002 and name in attributes:  # XATTR_CREATE
            return -1
        attributes[name] = ctypes.string_at(buffer, size)
        return 0

    def acl_get_file(self, path, kind):
        assert kind == 0x100  # ACL_TYPE_EXTENDED
        return self.lists.get(path)

    def acl_set_file(self, path, kind, access):
        assert kind == 0x100 and os.path.exists(os.fsdecode(path))
        self.set.append((path, access, open(os.fsdecode(path), "rb").read()))
        return 0

    def acl_free(self, access):
        self.freed.append(access)
        return 0


def test_replacing_a_file_keeps_its_tags_and_attributes(tmp_path, monkeypatch):
    target = tmp_path / "photo.jpg"
    target.write_bytes(b"old")
    old = os.fsencode(str(target))
    fake = _FakeXattrs(
        lists={old: 7},
        files={
            old: {
                b"com.apple.metadata:_kMDItemUserTags": b"Work",
                b"com.apple.quarantine": b"0081;app",
                b"user.note": b"old note",
                b"com.apple.ResourceFork": b"stale",  # these describe the old content
                b"com.apple.TextEncoding": b"utf-8",
                b"com.apple.cs.CodeSignature": b"sig",
            }
        },
    )
    monkeypatch.setattr(_files, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(_files, "_xattr_lib", lambda: fake)

    with _files.replacing(target) as temporary:
        temporary.write_bytes(b"new")
        new = os.fsencode(str(temporary))
        fake.files[new] = {b"user.note": b"the writer's"}  # set by the tool that wrote it: kept

    assert target.read_bytes() == b"new"
    assert fake.files[new] == {
        b"user.note": b"the writer's",
        b"com.apple.metadata:_kMDItemUserTags": b"Work",
        b"com.apple.quarantine": b"0081;app",
    }
    # The access list goes on the new file once it's in place, not on the staged one.
    assert fake.set == [(old, 7, b"new")] and fake.freed == [7]


def test_a_failed_move_leaves_no_access_list_and_no_staging_folder(tmp_path, monkeypatch):
    # An old file whose list denies deleting it: copied to the staged file, the failed
    # move would leave a staging folder no one can delete.
    target = tmp_path / "locked.txt"
    target.write_bytes(b"old")
    fake = _FakeXattrs({}, lists={os.fsencode(str(target)): 7})
    monkeypatch.setattr(_files, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(_files, "_xattr_lib", lambda: fake)

    def refuse(source, destination):
        raise PermissionError(errno.EPERM, "denied", destination)

    monkeypatch.setattr(_files.os, "replace", refuse)
    with pytest.raises(PermissionError):
        with _files.replacing(target) as temporary:
            temporary.write_bytes(b"new")
    assert target.read_bytes() == b"old"
    assert fake.set == [] and fake.freed == [7]
    assert os.listdir(str(tmp_path)) == ["locked.txt"]


def test_a_new_file_copies_no_attributes(tmp_path, monkeypatch):
    monkeypatch.setattr(_files, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(_files, "_xattr_lib", lambda: pytest.fail("nothing to copy from"))
    with _files.replacing(tmp_path / "new.txt") as temporary:
        temporary.write_bytes(b"x")
    assert (tmp_path / "new.txt").read_bytes() == b"x"


def test_attributes_that_cant_be_copied_dont_fail_the_write(tmp_path, monkeypatch):
    target = tmp_path / "remote.txt"
    target.write_bytes(b"old")

    class Refusing(_FakeXattrs):
        def setxattr(self, *args):
            return -1  # ENOTSUP: a volume without extended attributes

        def acl_set_file(self, *args):
            return -1  # EPERM: not this user's list to copy

    old = os.fsencode(str(target))
    fake = Refusing({old: {b"user.note": b"x"}}, lists={old: 7})
    monkeypatch.setattr(_files, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(_files, "_xattr_lib", lambda: fake)
    with _files.replacing(target) as temporary:
        temporary.write_bytes(b"new")
    assert target.read_bytes() == b"new"


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
