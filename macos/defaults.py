# -*- coding: utf-8 -*-

"""
Read and change the preferences of apps and of the system, like the ``defaults`` command, with Python values.

::

    macos.defaults.read("com.apple.dock", "autohide")            # True
    macos.defaults.write("com.apple.dock", "autohide", True)
    macos.defaults.read("NSGlobalDomain", "AppleInterfaceStyle")  # 'Dark'
    macos.defaults.delete("com.example.app", "cache-size")
    macos.defaults.read("com.apple.screencapture")                # {'location': '~/Desktop', ...}

    with macos.defaults.restored("com.apple.dock"):              # put back as it was, afterwards
        macos.defaults.write("com.apple.dock", "autohide", True)

Values are ``bool``, ``int``, ``float``, ``str``, ``bytes``,
:class:`~datetime.datetime`, and lists and dicts of them, like property lists.
Goes through CFPreferences, as apps do, so changes reach ``cfprefsd`` at once;
most apps only read them when they start, so restart them to see a change.
"""

import ctypes
import functools
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Callable, Iterator, List, Optional, Tuple, Union

from . import _cf
from ._system import framework
from .errors import PermissionDeniedError

__all__ = ["read", "write", "delete", "keys", "restored", "GLOBAL"]

GLOBAL = "NSGlobalDomain"
"""The preferences every app shares, such as the appearance: ``defaults -g``."""

_GLOBAL_NAMES = {GLOBAL, "-g", "-globalDomain", ".GlobalPreferences"}
_MISSING = object()


@lru_cache(maxsize=None)
def _preferences() -> ctypes.CDLL:
    cf = framework("CoreFoundation")
    pointer = ctypes.c_void_p
    cf.CFPreferencesCopyAppValue.argtypes = (pointer, pointer)
    cf.CFPreferencesCopyAppValue.restype = pointer
    cf.CFPreferencesSetAppValue.argtypes = (pointer, pointer, pointer)
    cf.CFPreferencesSetAppValue.restype = None
    cf.CFPreferencesAppSynchronize.argtypes = (pointer,)
    cf.CFPreferencesAppSynchronize.restype = ctypes.c_bool
    cf.CFPreferencesCopyKeyList.argtypes = (pointer, pointer, pointer)
    cf.CFPreferencesCopyKeyList.restype = pointer
    cf.CFPreferencesSetValue.argtypes = (pointer, pointer, pointer, pointer, pointer)
    cf.CFPreferencesSetValue.restype = None
    cf.CFPreferencesSynchronize.argtypes = (pointer, pointer, pointer)
    cf.CFPreferencesSynchronize.restype = ctypes.c_bool
    cf.CFPreferencesCopyValue.argtypes = (pointer, pointer, pointer, pointer)
    cf.CFPreferencesCopyValue.restype = pointer
    return cf


def _host(current_host: bool) -> Optional[int]:
    """This Mac only (``defaults -currentHost``), or any host."""
    cf = _preferences()
    return ctypes.c_void_p.in_dll(cf, "kCFPreferencesCurrentHost" if current_host else "kCFPreferencesAnyHost").value


def _user() -> Optional[int]:
    return ctypes.c_void_p.in_dll(_preferences(), "kCFPreferencesCurrentUser").value


def _store(domain: str, key: str, value: Optional[int], current_host: bool = False) -> None:
    """Set (or, with ``None``, remove) a key, and write it out."""
    cf = _preferences()
    with _cf.owned(_domain(domain)) as name, _cf.owned(_cf.string(key)) as wanted:
        if domain in _GLOBAL_NAMES or current_host:
            # The global domain and a single host take the call with an explicit user and host;
            # SetAppValue is for app domains, on any host.
            user, host = _user(), _host(current_host)
            cf.CFPreferencesSetValue(wanted, value, name, user, host)
            saved = cf.CFPreferencesSynchronize(name, user, host)
        else:
            cf.CFPreferencesSetAppValue(wanted, value, name)
            saved = cf.CFPreferencesAppSynchronize(name)
    if not saved:
        # CFPreferences takes the change in memory either way; only the
        # synchronize says whether cfprefsd wrote it out. It refuses a domain
        # this process can't write: one managed by a configuration profile,
        # one in another user's or the system's folder, or a sandboxed app's
        # container. Without this check write() would look like it worked.
        raise PermissionDeniedError(
            "couldn't save {!r} in the {!r} preferences: the domain isn't writable by this process "
            "(managed by a configuration profile, owned by another user or the system, or in a sandboxed "
            "app's container)".format(key, domain)
        )


def _check(domain: str) -> None:
    if not domain or not domain.strip():
        raise ValueError("domain must not be empty")


def _domain(domain: str) -> int:
    """The domain as CFPreferences names it: an owned string, or the global domain's constant."""
    if domain in _GLOBAL_NAMES:
        constant = ctypes.c_void_p.in_dll(_preferences(), "kCFPreferencesAnyApplication").value
        return _cf.retain(int(constant or 0))
    return _cf.string(domain)


def keys(domain: str, *, current_host: bool = False) -> List[str]:
    """The keys the domain has, sorted, such as ``["autohide", "orientation", ...]`` for ``"com.apple.dock"``."""
    _check(domain)
    cf = _preferences()
    with _cf.owned(_domain(domain)) as name, _cf.owned(
        cf.CFPreferencesCopyKeyList(name, _user(), _host(current_host))
    ) as found:
        return sorted(_cf.to_python(found) or [])


def read(domain: str, key: Optional[str] = None, *, default: Any = None, current_host: bool = False) -> Any:
    """
    The value of ``key`` in ``domain`` (an app's bundle ID, or :data:`GLOBAL`), or ``default`` when it isn't set.

    As apps see it, a key an app's domain doesn't set falls back to the
    global domain's value (``defaults read`` doesn't). Without ``key``,
    returns all the domain's own values, as a ``dict``.
    ``current_host=True`` reads the settings kept for this Mac only, like
    ``defaults -currentHost``.
    """
    _check(domain)
    if key is None:
        return {name: read(domain, name, current_host=current_host) for name in keys(domain, current_host=current_host)}
    cf = _preferences()
    with _cf.owned(_domain(domain)) as name, _cf.owned(_cf.string(key)) as wanted:
        if current_host:
            copied = cf.CFPreferencesCopyValue(wanted, name, _user(), _host(True))
        else:
            copied = cf.CFPreferencesCopyAppValue(wanted, name)
        with _cf.owned(copied) as value:
            return _cf.to_python(value) if value else default


def _own(domain: str, key: str, default: Any, current_host: bool) -> Any:
    """
    The value ``domain`` itself sets for ``key``, or ``default``.

    Unlike :func:`read`, an app's domain doesn't fall back to the global
    domain's value: this tells whether the key is set there, to delete or
    restore it.
    """
    cf = _preferences()
    with _cf.owned(_domain(domain)) as name, _cf.owned(_cf.string(key)) as wanted:
        with _cf.owned(cf.CFPreferencesCopyValue(wanted, name, _user(), _host(current_host))) as value:
            return _cf.to_python(value) if value else default


def write(domain: str, key: str, value: Any, *, current_host: bool = False) -> None:
    """
    Set ``key`` in ``domain`` to ``value``, as ``defaults write`` does, but with its Python type.

    ``True`` is written as a boolean, ``3`` as an integer, lists as arrays and
    dicts as dictionaries: no ``-bool`` or ``-int`` flags to get right.
    ``current_host=True`` writes it for this Mac only, like ``defaults -currentHost``.
    A domain this process can't write (managed by a configuration profile,
    another user's, the system's, a sandboxed app's container) raises
    :class:`~macos.errors.PermissionDeniedError`.
    """
    _check(domain)
    if value is None:
        raise ValueError("value must not be None; use delete() to remove a key")
    with _cf.owned(_cf.from_python(value)) as converted:
        _store(domain, key, converted, current_host)


def delete(domain: str, key: str, *, current_host: bool = False) -> bool:
    """
    Remove ``key`` from ``domain``; return whether it was set.

    Like :func:`write`, raises :class:`~macos.errors.PermissionDeniedError` when the domain isn't writable.
    """
    _check(domain)
    existed = _own(domain, key, _MISSING, current_host) is not _MISSING
    _store(domain, key, None, current_host)
    return existed


@contextmanager
def restored(*what: Union[str, Tuple[str, str]], current_host: bool = False) -> Iterator[None]:
    """
    Put preferences back exactly as they were when the ``with`` block ends, even if it fails.

    ::

        with macos.defaults.restored(("com.apple.finder", "CreateDesktop")):
            macos.finder.set_show_desktop_icons(False)   # a clean desktop for a recording
            record_demo()
        macos.finder.restart()                           # Finder reads it again: the icons are back

    Each argument is a ``(domain, key)`` pair, or a whole domain (``"com.apple.dock"``).
    Keys that weren't set are deleted again, not written with a value, so
    macOS goes back to its own default. It restores the preferences only:
    restart the Dock, Finder or app that read the changed ones, as the
    ``set_*`` functions do.
    """
    missing = object()
    saved: List[Tuple[str, Optional[str], Any]] = []  # (domain, key or None for all, value)
    for item in what:
        if isinstance(item, str):
            _check(item)
            # The domain's own layer, as keys() lists it and the restore writes it back:
            # read() would give the values in effect, from a profile or the global
            # domain too, and the restore would copy those into the user's own file.
            own = {name: _own(item, name, missing, current_host) for name in keys(item, current_host=current_host)}
            saved.append((item, None, {name: value for name, value in own.items() if value is not missing}))
        else:
            domain, key = item
            _check(domain)
            saved.append((domain, key, _own(domain, key, missing, current_host)))
    try:
        yield
    finally:
        # One key that can't be written back mustn't keep the others from
        # being restored, in its domain or another: each change is tried on
        # its own, and the first failure raised once they all were.
        failure: List[PermissionDeniedError] = []

        def attempt(change: Callable[[], object]) -> None:
            try:
                change()
            except PermissionDeniedError as error:
                failure.append(error)

        for domain, name_or_all, value in saved:
            if name_or_all is None:
                for name in keys(domain, current_host=current_host):
                    if name not in value:
                        attempt(functools.partial(delete, domain, name, current_host=current_host))
                for name, old in value.items():
                    # The domain's own value: one equal to the global fallback still has to be written back.
                    if _own(domain, name, missing, current_host) != old:
                        attempt(functools.partial(write, domain, name, old, current_host=current_host))
            elif value is missing:
                attempt(functools.partial(delete, domain, name_or_all, current_host=current_host))
            else:
                attempt(functools.partial(write, domain, name_or_all, value, current_host=current_host))
        if failure:
            raise failure[0]
