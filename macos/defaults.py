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
import math
import warnings
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, TypeVar, Union

from . import _cf
from ._system import add_note
from .errors import PermissionDeniedError

__all__ = ["read", "write", "delete", "keys", "restored", "GLOBAL"]

GLOBAL = "NSGlobalDomain"
"""The preferences every app shares, such as the appearance: ``defaults -g``."""

_GLOBAL_NAMES = {GLOBAL, "-g", "-globalDomain", ".GlobalPreferences"}
_MISSING = object()

_T = TypeVar("_T")


def _as_int(value: object, fallback: _T) -> Union[int, _T]:
    """``value`` as an int, or ``fallback`` when a hand-edited preference holds something else (text, a list...)."""
    number = _as_float(value, None)
    return fallback if number is None else int(number)


def _as_float(value: object, fallback: _T) -> Union[float, _T]:
    """``value`` as a finite float, or ``fallback`` when a hand-edited preference holds something else."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _preferences() -> ctypes.CDLL:
    """CoreFoundation, with the CFPreferences calls declared (once, in :func:`macos._cf.lib`: the handle is shared)."""
    return _cf.lib()


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


def _check(domain: str, key: Optional[str] = None, *, reading: bool = False) -> None:
    if not domain or not domain.strip():
        raise ValueError("domain must not be empty")
    if "/" in domain:
        # CFPreferences takes a domain with a slash for a file, as the defaults command does: an absolute
        # one is that file, a relative one is under ~/Library/Preferences (".." included). Written to, it
        # creates any .plist a domain taken from input names: refused. Read, it's a .plist read by its
        # path, which worked: it warns, and 2.0 refuses it too.
        if not reading:
            raise ValueError(
                "domain must be a name such as 'com.apple.dock' or NSGlobalDomain, not a path: {!r}".format(domain)
            )
        warnings.warn(
            "a domain is a name such as 'com.apple.dock', not a path ({!r}): reading a .plist by its path "
            "works today, and pymacos 2.0 will raise ValueError".format(domain),
            DeprecationWarning,
            stacklevel=3,
        )
    if key is not None and (not isinstance(key, str) or not key.strip()):
        raise ValueError("key must not be empty")


def _domain(domain: str) -> int:
    """The domain as CFPreferences names it: an owned string, or the global domain's constant."""
    if domain in _GLOBAL_NAMES:
        constant = ctypes.c_void_p.in_dll(_preferences(), "kCFPreferencesAnyApplication").value
        return _cf.retain(int(constant or 0))
    return _cf.string(domain)


def keys(domain: str, *, current_host: bool = False) -> List[str]:
    """The keys the domain has, sorted, such as ``["autohide", "orientation", ...]`` for ``"com.apple.dock"``."""
    _check(domain, reading=True)
    return _keys(domain, current_host)


def _keys(domain: str, current_host: bool) -> List[str]:
    cf = _preferences()
    with _cf.owned(_domain(domain)) as name, _cf.owned(
        cf.CFPreferencesCopyKeyList(name, _user(), _host(current_host))
    ) as found:
        return sorted(_cf.to_python(found) or [])


def _synchronize(domain: str) -> None:
    """Drop this process's copy of ``domain``'s values, so the next read sees what other processes wrote since."""
    _check(domain)
    with _cf.owned(_domain(domain)) as name:
        _preferences().CFPreferencesAppSynchronize(name)


def read(domain: str, key: Optional[str] = None, *, default: Any = None, current_host: bool = False) -> Any:
    """
    The value of ``key`` in ``domain`` (an app's bundle ID, or :data:`GLOBAL`), or ``default`` when it isn't set.

    A domain is a name: one with a slash in it, which the ``defaults``
    command takes for a file's path, still reads that ``.plist`` but warns
    (``DeprecationWarning``); pymacos 2.0 will raise :class:`ValueError`, as
    :func:`write` already does.
    As apps see it, a key an app's domain doesn't set falls back to the
    global domain's value (``defaults read`` doesn't). Without ``key``,
    returns all the domain's own values, as a ``dict``.
    ``current_host=True`` reads the settings kept for this Mac only, like
    ``defaults -currentHost``.
    """
    _check(domain, reading=True)
    if key is None:
        return {name: _value(domain, name, None, current_host) for name in _keys(domain, current_host)}
    return _value(domain, key, default, current_host)


def _value(domain: str, key: str, default: Any, current_host: bool) -> Any:
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
    A domain with a slash in it (a file's path, to the ``defaults`` command)
    raises :class:`ValueError`: see :func:`read`.
    A domain this process can't write (managed by a configuration profile,
    another user's, the system's, a sandboxed app's container) raises
    :class:`~macos.errors.PermissionDeniedError`.
    """
    _check(domain, key)
    if value is None:
        raise ValueError("value must not be None; use delete() to remove a key")
    with _cf.owned(_cf.from_python(value)) as converted:
        _store(domain, key, converted, current_host)


def delete(domain: str, key: str, *, current_host: bool = False) -> bool:
    """
    Remove ``key`` from ``domain``; return whether it was set.

    Like :func:`write`, raises :class:`~macos.errors.PermissionDeniedError` when the domain isn't writable,
    and :class:`ValueError` for a domain with a slash in it (a file's path).
    """
    _check(domain, key)
    existed = _own(domain, key, _MISSING, current_host) is not _MISSING
    _store(domain, key, None, current_host)
    return existed


def _identical(first: Any, second: Any) -> bool:
    """
    Whether two preference values are the same, types included.

    ``True == 1`` in Python, but a preference that went from a boolean to a
    number isn't as it was: apps read the type too.
    """
    if type(first) is not type(second):
        return False
    if isinstance(first, dict):
        return first.keys() == second.keys() and all(_identical(first[key], second[key]) for key in first)
    if isinstance(first, list):
        return len(first) == len(second) and all(_identical(one, other) for one, other in zip(first, second))
    return bool(first == second)


@contextmanager
def restored(*what: Union[str, Tuple[str, str]], current_host: bool = False) -> Iterator[None]:
    """
    Put preferences back exactly as they were when the ``with`` block ends, even if it fails.

    ::

        with macos.defaults.restored(("com.apple.finder", "CreateDesktop")):
            macos.finder.set_show_desktop_icons(False)   # a clean desktop for a recording
            record_demo()
        macos.finder.restart()                           # Finder reads it again: the icons are back

    Each argument is a ``(domain, key)`` pair, or a whole domain (``"com.apple.dock"``); one with a slash
    in it (a file's path) raises :class:`ValueError` before anything is read, as it would be written back.
    Keys that weren't set are deleted again, not written with a value, so
    macOS goes back to its own default. It restores the preferences only:
    restart the Dock, Finder or app that read the changed ones, as the
    ``set_*`` functions do.

    A key that can't be written back doesn't keep the others from being
    restored: the first error is raised once they all were tried. When the
    block itself fails, its error is the one raised, with the restore's
    failures noted on it (as a warning before Python 3.11).
    """
    missing = object()
    saved: List[Tuple[str, Optional[str], Any]] = []  # (domain, key or None for all, value)
    for item in what:  # every domain checked before any is read
        if isinstance(item, str):
            _check(item)
        else:
            domain, key = item
            _check(domain)
    for item in what:
        if isinstance(item, str):
            # The domain's own layer, as keys() lists it and the restore writes it back:
            # read() would give the values in effect, from a profile or the global
            # domain too, and the restore would copy those into the user's own file.
            own = {name: _own(item, name, missing, current_host) for name in keys(item, current_host=current_host)}
            saved.append((item, None, {name: value for name, value in own.items() if value is not missing}))
        else:
            domain, key = item
            saved.append((domain, key, _own(domain, key, missing, current_host)))
    failed: Optional[BaseException] = None
    try:
        yield
    except GeneratorExit:
        raise  # the context manager closed without its block ending (dropped): not an error to keep
    except BaseException as error:
        failed = error
        raise
    finally:
        # One key that can't be written back mustn't keep the others from
        # being restored, in its domain or another: each change is tried on
        # its own, and the first failure raised once they all were. It never
        # hides the error of the block itself, which stays the one raised.
        failures: List[Exception] = []

        def attempt(change: Callable[[], object]) -> None:
            try:
                change()
            except Exception as error:
                failures.append(error)

        def delete_added(domain: str, value: Dict[str, Any]) -> None:
            for name in keys(domain, current_host=current_host):
                if name not in value:
                    attempt(functools.partial(delete, domain, name, current_host=current_host))

        def restore_key(domain: str, name: str, old: Any) -> None:
            # The domain's own value: one equal to the global fallback still has to be written back.
            if not _identical(_own(domain, name, missing, current_host), old):
                write(domain, name, old, current_host=current_host)

        for domain, name_or_all, value in saved:
            if name_or_all is None:
                attempt(functools.partial(delete_added, domain, value))
                for name, old in value.items():
                    attempt(functools.partial(restore_key, domain, name, old))
            elif value is missing:
                attempt(functools.partial(delete, domain, name_or_all, current_host=current_host))
            else:
                attempt(functools.partial(write, domain, name_or_all, value, current_host=current_host))
        if failures:
            first = failed if failed is not None else failures[0]
            for problem in failures:
                if problem is not first:
                    add_note(first, "restoring a preference failed too: {}".format(problem))
            if failed is None:
                raise first
