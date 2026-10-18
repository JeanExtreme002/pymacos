"""Unit tests for :mod:`macos._libc`. They run on any platform."""

import ctypes
import errno

import pytest

from macos import _libc
from macos.errors import MacOSError


class _FakeLib:
    """``proc_listallpids`` answering from a list of results, setting errno for a 0."""

    def __init__(self, *table, error=0):
        self.table = list(table)
        self.error = error
        self.calls = 0

    def proc_listallpids(self, buffer, size):
        self.calls += 1
        if not self.table:
            ctypes.set_errno(self.error)
            return 0
        found = self.table.pop(0)
        if buffer is not None:
            for index, pid in enumerate(found[: size // ctypes.sizeof(ctypes.c_int)]):
                buffer[index] = pid
        return len(found)


def test_pids_lists_the_process_table(monkeypatch):
    monkeypatch.setattr(_libc, "lib", lambda: _FakeLib([1, 10, 11], [0, 1, 10, 11]))
    assert _libc.pids() == [1, 10, 11]  # pid 0, the kernel, isn't a process to ask about


@pytest.mark.parametrize("table", [(), ([1, 10],)])  # the sizing call fails, or the real one does
def test_pids_raises_when_macos_wont_list_them(monkeypatch, table):
    monkeypatch.setattr(_libc, "lib", lambda: _FakeLib(*table, error=errno.EPERM))
    with pytest.raises(MacOSError, match="can't list the running processes"):
        _libc.pids()


def test_pids_raises_without_errno_too(monkeypatch):
    monkeypatch.setattr(_libc, "lib", lambda: _FakeLib())
    with pytest.raises(MacOSError, match="no processes listed"):
        _libc.pids()


class _FakeFunction:
    argtypes = None
    restype = None


class _FakeCDLL:
    """A library whose every function is a fresh :class:`_FakeFunction`, kept by name."""

    def __init__(self, path, use_errno=False):
        self.path = path
        self.use_errno = use_errno
        self.functions = {}

    def __getattr__(self, name):
        return self.__dict__["functions"].setdefault(name, _FakeFunction())


def test_lib_declares_the_metadata_calls(monkeypatch):
    monkeypatch.setattr(_libc, "require_macos", lambda: None)
    monkeypatch.setattr(_libc.ctypes, "CDLL", _FakeCDLL)
    libc = _libc.lib.__wrapped__()
    assert libc.use_errno
    assert libc.listxattr.restype is ctypes.c_ssize_t and len(libc.listxattr.argtypes) == 4
    assert libc.setxattr.restype is ctypes.c_int and libc.setxattr.argtypes[4] is ctypes.c_uint32
    assert libc.acl_get_file.restype is ctypes.c_void_p  # a pointer, never truncated to an int
    assert libc.acl_set_file.argtypes == (ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
    assert libc.acl_free.argtypes == (ctypes.c_void_p,)
    assert (_libc.XATTR_CREATE, _libc.ACL_TYPE_EXTENDED) == (2, 0x100)
