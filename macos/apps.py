# -*- coding: utf-8 -*-

"""
List, open, activate, quit and uninstall applications.

::

    for app in macos.apps.running():
        print(app.name, app.bundle_id, app.pid)

    safari = macos.apps.open("Safari")
    macos.apps.frontmost()                  # App(name='Safari', ...)
    safari.quit()

    macos.apps.uninstall("Slack", dry_run=True)   # the app and its leftovers, to the Trash

Running applications come from ``NSWorkspace`` (the same list the Dock and the
Force Quit window use), queried natively through the Objective-C runtime.
"""

import ctypes
import errno
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
from typing import Iterator, List, Optional, Sequence, Tuple, Union

from . import _cf, _libc, _objc, finder, spotlight, system
from ._libc import ENOATTR as _ENOATTR, XATTR_NOFOLLOW as _XATTR_NOFOLLOW, pids as _pids
from ._objc import BOOL, NSInteger, NSUInteger
from ._system import applescript, framework, require_macos, run as _run
from .errors import AppNotFoundError, CommandError, MacOSError

__all__ = [
    "App",
    "running",
    "frontmost",
    "get",
    "open",
    "open_with",
    "install_from_dmg",
    "LoginItem",
    "login_items",
    "add_login_item",
    "remove_login_item",
    "default_for",
    "set_default_for",
    "default_browser",
    "is_quarantined",
    "unquarantine",
    "InstalledApp",
    "installed",
    "uninstall",
]

# NSApplicationActivationPolicy
_POLICY_REGULAR = 0

# NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps.
# Without the second flag, macOS 13 and earlier only activate the app when no
# other app is active, and from a script some app (the terminal) always is.
_ACTIVATE_OPTIONS = (1 << 0) | (1 << 1)


@lru_cache(maxsize=None)
def _running_application_class() -> int:
    framework("AppKit")
    return _objc.cls("NSRunningApplication")


@lru_cache(maxsize=None)
def _workspace() -> int:
    framework("AppKit")
    return _objc.send(_objc.cls("NSWorkspace"), "sharedWorkspace")


def _handle(pid: int) -> Optional[int]:
    """The ``NSRunningApplication`` for ``pid``, or ``None`` if it isn't an app."""
    return _objc.send(
        _running_application_class(), "runningApplicationWithProcessIdentifier:", pid, argtypes=(ctypes.c_int,)
    )


def _handles(include_background: bool) -> Iterator[int]:
    """
    Yield an ``NSRunningApplication`` for every running app.

    ``NSWorkspace.runningApplications`` would be the obvious source, but it is
    only refreshed by notifications on the *main* run loop, which a script
    never spins: from a worker thread it keeps returning a stale list. Asking
    LaunchServices about each process is always current, and costs a few
    milliseconds.
    """
    for pid in _pids():
        handle = _handle(pid)
        if handle and (include_background or _objc.send(handle, "activationPolicy", restype=NSInteger) == _POLICY_REGULAR):
            yield handle


@dataclass(frozen=True)
class App:
    """A running application."""

    name: Optional[str]
    bundle_id: Optional[str]
    pid: int
    path: Optional[str]

    def _handle(self) -> int:
        handle = _handle(self.pid)
        if not handle:
            raise AppNotFoundError("{} (pid {}) is no longer running".format(self.name, self.pid))
        return handle

    @property
    def is_running(self) -> bool:
        with _objc.autorelease_pool():
            handle = _handle(self.pid)
            return bool(handle) and not _objc.send(handle, "isTerminated", restype=BOOL)

    @property
    def is_active(self) -> bool:
        """Whether this is the frontmost application."""
        with _objc.autorelease_pool():
            return bool(_objc.send(self._handle(), "isActive", restype=BOOL))

    @property
    def is_hidden(self) -> bool:
        with _objc.autorelease_pool():
            return bool(_objc.send(self._handle(), "isHidden", restype=BOOL))

    def activate(self, *, timeout: float = 2.0) -> bool:
        """
        Bring the application to the front and return whether it is now frontmost.

        Waits up to ``timeout`` seconds for the switch to happen.
        """
        if self.path:
            # Since macOS 14, AppKit ignores activation requests from a process
            # that isn't active itself, which a script never is: the call
            # returns YES and nothing happens. LaunchServices (`open`) has no
            # such restriction.
            self._handle()  # raise AppNotFoundError if it has quit
            _run(["open", "-a", self.path])
        else:
            with _objc.autorelease_pool():
                _objc.send(
                    self._handle(), "activateWithOptions:", _ACTIVATE_OPTIONS, argtypes=(NSUInteger,), restype=BOOL
                )

        deadline = time.monotonic() + timeout
        while not self.is_active:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True

    def hide(self) -> bool:
        with _objc.autorelease_pool():
            return bool(_objc.send(self._handle(), "hide", restype=BOOL))

    def unhide(self) -> bool:
        with _objc.autorelease_pool():
            return bool(_objc.send(self._handle(), "unhide", restype=BOOL))

    def quit(self, *, force: bool = False, timeout: Optional[float] = None) -> bool:
        """
        Ask the application to quit, like choosing *Quit* from its menu.

        The app may show a "save changes?" dialog or refuse. ``force=True``
        kills it instead, like *Force Quit*, losing unsaved work. With a
        ``timeout`` (seconds), wait for it to exit and return whether it did;
        otherwise return whether the request was delivered.
        """
        with _objc.autorelease_pool():
            selector = "forceTerminate" if force else "terminate"
            delivered = bool(_objc.send(self._handle(), selector, restype=BOOL))

        if timeout is None or not delivered:
            return delivered

        deadline = time.monotonic() + timeout
        while self.is_running:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True


def _app(handle: int) -> App:
    url = _objc.send(handle, "bundleURL")
    return App(
        name=_objc.pystring(_objc.send(handle, "localizedName")),
        bundle_id=_objc.pystring(_objc.send(handle, "bundleIdentifier")),
        pid=_objc.send(handle, "processIdentifier", restype=ctypes.c_int),
        path=_objc.pystring(_objc.send(url, "path")) if url else None,
    )


def running(*, include_background: bool = False) -> List[App]:
    """
    Return the running applications.

    By default only regular apps (the ones with a Dock icon) are listed.
    ``include_background=True`` adds menu-bar extras, agents and helpers.
    """
    with _objc.autorelease_pool():
        return [_app(handle) for handle in _handles(include_background)]


def frontmost() -> Optional[App]:
    """Return the application that currently has keyboard focus."""
    with _objc.autorelease_pool():
        for handle in _handles(include_background=True):
            if _objc.send(handle, "isActive", restype=BOOL):
                return _app(handle)
    return None


def _is_path(name: str) -> bool:
    return "/" in name or name.startswith("~")


def get(name: str) -> Optional[App]:
    """
    Find a running application by name, bundle identifier or path.

    Names are compared case-insensitively against the displayed (localized)
    name and the ``.app`` file name, with or without the extension, so
    ``"Calculator"`` also finds it on a system where it is shown as
    ``"Calculadora"``. Paths may be symlinks. Returns ``None`` if it isn't
    running.
    """
    if _is_path(name):
        wanted_path = os.path.realpath(os.path.expanduser(name))
        for app in running(include_background=True):
            if app.path and os.path.realpath(app.path) == wanted_path:
                return app
        return None

    wanted = name.casefold()
    for app in running(include_background=True):
        file_name = os.path.basename(app.path or "")
        candidates = (app.name, app.bundle_id, file_name, os.path.splitext(file_name)[0])
        if wanted in {part.casefold() for part in candidates if part}:
            return app
    return None


def _locate(name: str) -> str:
    """Resolve an app name, bundle identifier or path to the real path of its bundle."""
    # Only names that look like paths are paths: a bare "Notes" must find the
    # Notes app even when the current directory has a "Notes" folder.
    if _is_path(name):
        expanded = os.path.expanduser(name)
        if not os.path.isdir(expanded):
            raise AppNotFoundError("no application at {!r}".format(name))
        return os.path.realpath(expanded)

    with _objc.autorelease_pool():
        url = _objc.send(
            _workspace(), "URLForApplicationWithBundleIdentifier:", _objc.nsstring(name), argtypes=(_objc.id,)
        )
        path = _objc.pystring(_objc.send(url, "path")) if url else None
        if path is None:
            # Looks the name up the way `open -a` does: "Safari", "Safari.app"
            # and names with dots in them, like "zoom.us", all work.
            path = _objc.pystring(
                _objc.send(_workspace(), "fullPathForApplication:", _objc.nsstring(name), argtypes=(_objc.id,))
            )
    if path is None:
        raise AppNotFoundError("unable to find application {!r}".format(name))
    return os.path.realpath(path)


def _bundle_id(path: str) -> Optional[str]:
    with _objc.autorelease_pool():
        bundle = _objc.send(_objc.cls("NSBundle"), "bundleWithPath:", _objc.nsstring(path), argtypes=(_objc.id,))
        return _objc.pystring(_objc.send(bundle, "bundleIdentifier")) if bundle else None


def _bundle_path(handle: int) -> Optional[str]:
    url = _objc.send(handle, "bundleURL")
    path = _objc.pystring(_objc.send(url, "path")) if url else None
    return os.path.realpath(path) if path else None


def _find_launched(path: str, bundle_id: Optional[str]) -> Optional[App]:
    """The running instance of the bundle at ``path``, if it is up yet."""
    with _objc.autorelease_pool():
        if bundle_id is not None:
            # Only asks about this one bundle id, instead of listing every
            # process on each poll.
            candidates = _objc.nsarray(
                _objc.send(
                    _running_application_class(),
                    "runningApplicationsWithBundleIdentifier:",
                    _objc.nsstring(bundle_id),
                    argtypes=(_objc.id,),
                )
            )
        else:
            candidates = _handles(include_background=True)

        for handle in candidates:
            # Two copies of an app share a bundle id; only the one at `path`
            # is the one that was asked for. Comparing the path on the handle
            # also avoids building an App for every other process.
            if _bundle_path(handle) == path and not _objc.send(handle, "isTerminated", restype=BOOL):
                return _app(handle)
    return None


# What `open` says when the app itself can't be found (kLSApplicationNotFoundErr is -10814), as
# opposed to an app that's there but won't open: damaged, quarantined, for another processor...
_APP_MISSING = ("unable to find application", "-10814")


def _app_missing(error: CommandError) -> bool:
    text = (error.stderr or "").lower()
    return any(marker in text for marker in _APP_MISSING)


def open(name: str, *, background: bool = False, timeout: float = 10.0) -> App:
    """
    Launch an application (or activate it, if it's already running) and return it.

    ``name`` may be an app name (``"Safari"``), a bundle identifier
    (``"com.apple.Safari"``) or a path to an ``.app``. ``background=True``
    launches it without bringing it to the front.

    Raises :class:`~macos.errors.AppNotFoundError` when there's no such
    app, and :class:`~macos.errors.CommandError`, with macOS's reason, when
    it's there but won't open (damaged, blocked by Gatekeeper...).
    """
    path = _locate(name)
    bundle_id = _bundle_id(path)

    try:
        _run(["open", *(["-g"] if background else []), "-a", path])
    except CommandError as error:
        if _app_missing(error):
            raise AppNotFoundError("unable to launch {!r}: {}".format(name, error.stderr or error)) from error
        raise  # found, but it won't open: its reason says why

    deadline = time.monotonic() + timeout
    while True:
        app = _find_launched(path, bundle_id)
        if app is not None:
            return app
        if time.monotonic() >= deadline:
            raise AppNotFoundError("{!r} was launched but did not show up within {}s".format(name, timeout))
        time.sleep(0.1)


_ALL_ROLES = 0xFFFFFFFF  # kLSRolesAll
_POSIX_PATH_STYLE = 0  # kCFURLPOSIXPathStyle


def open_with(target: Union[str, "os.PathLike[str]"], app: str, *, background: bool = False) -> None:
    """
    Open a file, folder or URL with a specific app, like Finder's *Open With*.

    ``app`` is an app name (``"Preview"``), bundle identifier
    (``"com.apple.Preview"``) or path to an ``.app``, as for :func:`open`.
    ``background=True`` opens it without bringing the app to the front::

        macos.apps.open_with("report.pdf", "Preview")

    Raises :class:`~macos.errors.AppNotFoundError` when there's no such app,
    and :class:`~macos.errors.CommandError`, with macOS's reason, when the
    app or the file won't open. Also available as ``macos.open_with``.
    """
    from .launch import _flags, _resolve  # launch imports this module

    _, arguments = _resolve(target)
    resolved = arguments[-1]
    try:
        _run(["open", *_flags(background), "-a", _locate(app), *arguments])
    except CommandError as error:
        if _app_missing(error):
            raise AppNotFoundError("{!r} could not open {}: {}".format(app, resolved, error.stderr or error)) from error
        raise


@lru_cache(maxsize=None)
def _launch_services() -> ctypes.CDLL:
    services = framework("CoreServices")
    services.UTTypeCreatePreferredIdentifierForTag.argtypes = (_cf.CFTypeRef, _cf.CFTypeRef, _cf.CFTypeRef)
    services.UTTypeCreatePreferredIdentifierForTag.restype = _cf.CFTypeRef
    services.LSCopyDefaultApplicationURLForContentType.argtypes = (_cf.CFTypeRef, ctypes.c_uint32, ctypes.c_void_p)
    services.LSCopyDefaultApplicationURLForContentType.restype = _cf.CFTypeRef
    services.LSCopyDefaultApplicationURLForURL.argtypes = (_cf.CFTypeRef, ctypes.c_uint32, ctypes.c_void_p)
    services.LSCopyDefaultApplicationURLForURL.restype = _cf.CFTypeRef
    services.LSSetDefaultRoleHandlerForContentType.argtypes = (_cf.CFTypeRef, ctypes.c_uint32, _cf.CFTypeRef)
    services.LSSetDefaultRoleHandlerForContentType.restype = ctypes.c_int32
    services.UTTypeIsDeclared.argtypes = (_cf.CFTypeRef,)
    services.UTTypeIsDeclared.restype = ctypes.c_bool
    return services


def _app_path(url: Optional[int]) -> Optional[str]:
    """The path of an owned ``CFURL`` (released here), or ``None``."""
    with _cf.owned(url):
        if not url:
            return None
        with _cf.owned(_cf.lib().CFURLCopyFileSystemPath(url, _POSIX_PATH_STYLE)) as path:
            return _cf.to_str(path)


def default_for(kind: str) -> Optional[str]:
    """
    Return the path of the app that opens a kind of file by default, or ``None`` if none does.

    ``kind`` is a file extension (``"pdf"``, ``".png"``) or a type identifier
    (``"public.plain-text"``)::

        macos.apps.default_for("pdf")    # '/System/Applications/Preview.app'
    """
    services = _launch_services()
    # A dotted name that doesn't start with a dot is tried as a type
    # identifier first ("com.adobe.pdf"). If no app handles it, it's a
    # multi-part extension ("tar.gz"), and its last part decides the type.
    if "." in kind and not kind.startswith("."):
        with _cf.owned(_cf.string(kind)) as identifier:
            app = _app_path(services.LSCopyDefaultApplicationURLForContentType(identifier, _ALL_ROLES, None))
        if app is not None:
            return app

    extension = kind.rsplit(".", 1)[-1]
    with _cf.owned(_cf.string("public.filename-extension")) as tag_class, _cf.owned(_cf.string(extension)) as tag:
        with _cf.owned(services.UTTypeCreatePreferredIdentifierForTag(tag_class, tag, None)) as identifier:
            return _app_path(services.LSCopyDefaultApplicationURLForContentType(identifier, _ALL_ROLES, None))


def set_default_for(kind: str, app: str, *, timeout: float = 60.0) -> None:
    """
    Make ``app`` open a kind of file by default, like Get Info › Open with › Change All.

    ``kind`` works as in :func:`default_for`: an extension (``"pdf"``) or a
    type identifier (``"public.plain-text"``). ``app`` is a name, bundle ID or
    path, as for :func:`open`::

        macos.apps.set_default_for("md", "Visual Studio Code")

    Since macOS 26, macOS asks the user to confirm the change: this waits up
    to ``timeout`` seconds for the answer, and raises
    :class:`~macos.errors.MacOSError` if it's declined or doesn't come. The
    default browser can't be set this way: macOS asks for that one in System
    Settings.
    """
    path = _locate(app)
    with _cf.owned(_content_type(kind)) as identifier:
        type_name = _cf.to_str(identifier) or ""
    with _objc.autorelease_pool():
        workspace = _workspace()
        selector = "setDefaultApplicationAtURL:toOpenContentType:completionHandler:"
        if _objc.send(workspace, "respondsToSelector:", _objc.sel(selector), argtypes=(_objc.SEL,), restype=BOOL):
            _set_default_with_workspace(workspace, path, type_name, app, kind, timeout)
            return
    # Before macOS 12: LaunchServices' older call, which recent systems ignore.
    bundle_id = _bundle_id(path)
    if not bundle_id:
        raise AppNotFoundError("{!r} has no bundle identifier to register".format(app))
    with _cf.owned(_cf.string(type_name)) as identifier, _cf.owned(_cf.string(bundle_id)) as handler:
        status = _launch_services().LSSetDefaultRoleHandlerForContentType(identifier, _ALL_ROLES, handler)
    if status != 0:
        raise MacOSError("could not make {} the default for {!r} (error {})".format(app, kind, status))


def _set_default_with_workspace(workspace: int, path: str, type_name: str, app: str, kind: str, timeout: float) -> None:
    """``NSWorkspace``'s way (macOS 12+), which reports back through a completion handler."""
    framework("UniformTypeIdentifiers")
    content_type = _objc.send(_objc.cls("UTType"), "typeWithIdentifier:", _objc.nsstring(type_name), argtypes=(_objc.id,))
    if not content_type:
        raise ValueError("{!r} isn't a kind of file macOS knows".format(kind))
    results: List[Optional[str]] = []

    def done(error: int) -> None:
        results.append(_objc.pystring(_objc.send(error, "localizedDescription")) if error else None)

    handler = _objc.block(done, b"v@?@", ctypes.c_void_p)
    _objc.send(
        workspace,
        "setDefaultApplicationAtURL:toOpenContentType:completionHandler:",
        _objc.file_url(path),
        content_type,
        handler,
        argtypes=(_objc.id, _objc.id, ctypes.c_void_p),
        restype=None,
    )
    # Since macOS 26 the user is asked to confirm: the handler comes with their answer.
    if not _objc.run_until(lambda: bool(results), timeout):
        raise MacOSError("{} wasn't confirmed as the default for {!r} within {} seconds".format(app, kind, timeout))
    if results[0]:
        raise MacOSError("could not make {} the default for {!r}: {}".format(app, kind, results[0]))


def _content_type(kind: str) -> int:
    """The type identifier for an extension or an identifier, as an owned string."""
    services = _launch_services()
    if "." in kind and not kind.startswith("."):
        identifier = _cf.string(kind)
        if services.UTTypeIsDeclared(identifier):
            return identifier
        _cf.release(identifier)
    extension = kind.rsplit(".", 1)[-1]
    with _cf.owned(_cf.string("public.filename-extension")) as tag_class, _cf.owned(_cf.string(extension)) as tag:
        return int(services.UTTypeCreatePreferredIdentifierForTag(tag_class, tag, None))


def install_from_dmg(
    image: Union[str, "os.PathLike[str]"],
    *,
    destination: Union[str, "os.PathLike[str]"] = "/Applications",
    replace: bool = False,
) -> str:
    """
    Install the app a disk image holds, as dragging it to Applications does, and return its new path.

    ::

        macos.apps.install_from_dmg("~/Downloads/Rectangle.dmg")   # '/Applications/Rectangle.app'

    The image is mounted, the ``.app`` at its top is copied into
    ``destination``, and the image is unmounted. An app already there raises
    :class:`FileExistsError`, unless ``replace=True``. Installers (``.pkg``)
    aren't run.
    """
    target_folder = Path(destination).expanduser()
    if not target_folder.is_dir():
        raise NotADirectoryError(str(target_folder))
    mounted = system.mount_image(image)
    succeeded = False
    try:
        found = sorted(entry for entry in mounted.iterdir() if entry.suffix == ".app" and entry.is_dir())
        if not found:
            raise AppNotFoundError("{} has no app at its top".format(Path(image).name))
        source = found[0]
        target = target_folder / source.name
        if target.exists() and not replace:
            raise FileExistsError(str(target))
        # Copied beside it first, then swapped in: a failed copy leaves the installed app as it was.
        token = uuid.uuid4().hex  # unique per call: two installs of the same app don't share these
        staged = target_folder / ".{}.installing-{}".format(source.name, token)
        try:
            _run(["ditto", str(source), str(staged)])  # keeps the signature, attributes and links
            if target.exists():
                old = target_folder / ".{}.replaced-{}".format(source.name, token)
                os.rename(str(target), str(old))
                try:
                    os.rename(str(staged), str(target))
                except OSError:
                    os.rename(str(old), str(target))  # put the old app back
                    raise
                shutil.rmtree(str(old), ignore_errors=True)
            else:
                os.rename(str(staged), str(target))
        finally:
            if staged.exists():
                shutil.rmtree(str(staged), ignore_errors=True)
        succeeded = True
    finally:
        try:
            system.unmount_image(mounted, force=True)
        except MacOSError:
            if succeeded:
                raise  # installed, but the image stays mounted: say so
            # Otherwise the error that stopped the install is the one to see, not this one.
    return str(target)


@dataclass(frozen=True)
class LoginItem:
    """An app (or file) opened when you log in, as listed in System Settings › General › Login Items."""

    name: str
    """As System Settings shows it, in the system's language (``'Xadrez'`` for Chess in Portuguese)."""
    path: Optional[str]


_LOGIN_ITEMS = """
on run argv
    set out to ""
    tell application "System Events"
        repeat with entry in login items
            set out to out & (name of entry) & (ASCII character 31) & (path of entry) & (ASCII character 30)
        end repeat
    end tell
    return out
end run
"""

_ADD_LOGIN_ITEM = """
on run argv
    tell application "System Events" to make login item at end with properties {path:(item 1 of argv)}
end run
"""

_REMOVE_LOGIN_ITEM = """
on run argv
    tell application "System Events" to delete (every login item whose path is (item 1 of argv))
end run
"""


def login_items() -> List[LoginItem]:
    """
    The apps that open when you log in.

    Goes through System Events: the first time, macOS asks to allow the app
    running Python to control it. Apps that register themselves as
    background items (with their own switch in System Settings) aren't listed.
    """
    found = []
    for record in applescript("System Events", _LOGIN_ITEMS).rstrip("\n").split("\x1e"):
        fields = record.split("\x1f")
        if len(fields) == 2:
            name, path = fields
            found.append(LoginItem(name=name, path=path if path and path != "missing value" else None))
    return found


def add_login_item(app: str) -> LoginItem:
    """
    Open ``app`` (a name, bundle ID or path, as for :func:`open`) each time you log in, and return the :class:`LoginItem`.

    An app already there isn't added twice.
    """
    path = _locate(app)
    for item in login_items():
        if item.path and os.path.realpath(item.path) == path:
            return item
    applescript("System Events", _ADD_LOGIN_ITEM, path)
    added = next((item for item in login_items() if item.path and os.path.realpath(item.path) == path), None)
    if added is None:
        raise MacOSError("{} wasn't added to the login items: System Events didn't list it afterwards".format(path))
    return added


def remove_login_item(app: str) -> bool:
    """
    Stop opening ``app`` at login; return whether it was a login item.

    ``app`` is its name as :func:`login_items` shows it, or an app's name,
    bundle ID or path, as for :func:`open`.
    """
    items = login_items()
    matches = [item for item in items if item.name == app and item.path]
    if not matches:
        try:
            path = _locate(app)
        except AppNotFoundError:
            return False
        matches = [item for item in items if item.path and os.path.realpath(item.path) == path]
    for item in matches:
        applescript("System Events", _REMOVE_LOGIN_ITEM, item.path or "")
    return bool(matches)


def default_browser() -> Optional[str]:
    """Return the path of the default web browser, e.g. ``'/Applications/Safari.app'``."""
    services = _launch_services()
    with _cf.owned(_cf.string("https://example.com")) as text:
        with _cf.owned(_cf.lib().CFURLCreateWithString(None, text, None)) as url:
            return _app_path(services.LSCopyDefaultApplicationURLForURL(url, _ALL_ROLES, None))


# --- Quarantine ---------------------------------------------------------------

_QUARANTINE = b"com.apple.quarantine"


def is_quarantined(path: Union[str, "os.PathLike[str]"]) -> bool:
    """
    Whether macOS marked ``path`` as downloaded from the internet, so it checks it before it first opens.

    That mark is what makes macOS say an app "is damaged and can't be
    opened" or asks "Are you sure you want to open it?".
    """
    target = Path(os.path.expanduser(os.fspath(path)))
    if not os.path.lexists(target):
        raise FileNotFoundError(str(target))
    size = _libc.lib().getxattr(os.fsencode(target), _QUARANTINE, None, 0, 0, _XATTR_NOFOLLOW)
    if size >= 0:
        return True
    error = ctypes.get_errno()
    if error == _ENOATTR:
        return False
    # Anything else (no access, a disk error...) says nothing about the mark: don't guess.
    raise OSError(error, "can't read the quarantine of {}: {}".format(target, os.strerror(error)))


def unquarantine(path: Union[str, "os.PathLike[str]"]) -> int:
    """
    Remove the downloaded-from-the-internet mark from ``path`` and, for an app or a folder, everything in it.

    ::

        macos.apps.unquarantine("/Applications/Tool.app")   # opens without "is damaged"

    Returns how many files had it. Like ``xattr -dr com.apple.quarantine``:
    do it only for apps you trust, since it skips the check macOS makes
    the first time they open. Gatekeeper still applies its other rules.
    """
    target = Path(os.path.expanduser(os.fspath(path)))
    if not os.path.lexists(target):
        raise FileNotFoundError(str(target))
    libc = _libc.lib()
    paths = [target]
    if target.is_dir() and not target.is_symlink():
        def unreadable(error: OSError) -> None:
            raise error  # a folder it can't list would keep its files quarantined

        for folder, folders, files in os.walk(target, onerror=unreadable):
            paths.extend(Path(folder, name) for name in folders + files)
    removed = 0
    for item in paths:
        if libc.removexattr(os.fsencode(item), _QUARANTINE, _XATTR_NOFOLLOW) == 0:
            removed += 1
        else:
            error = ctypes.get_errno()
            if error not in (_ENOATTR, errno.ENOENT):
                raise OSError(error, "can't remove the quarantine from {}: {}".format(item, os.strerror(error)))
    return removed


# --- Installed apps -------------------------------------------------------------

_APP_FOLDERS = ("/Applications", "/System/Applications", "~/Applications")


@dataclass(frozen=True)
class InstalledApp:
    """An app installed on this Mac."""

    name: str
    bundle_id: Optional[str]
    version: Optional[str]
    """As the app shows it, such as ``'17.4'``."""
    path: Path


def _installed_app(path: str) -> Optional[InstalledApp]:
    import plistlib

    try:
        # Path's own reader: this module's open() is the one that opens apps.
        info = plistlib.loads(Path(path, "Contents", "Info.plist").read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    if not isinstance(info, dict):
        return None  # a valid plist, but not an app's description
    name = info.get("CFBundleDisplayName") or info.get("CFBundleName") or Path(path).stem
    return InstalledApp(
        name=str(name),
        bundle_id=info.get("CFBundleIdentifier"),
        version=str(info["CFBundleShortVersionString"]) if info.get("CFBundleShortVersionString") else None,
        path=Path(path),
    )


def installed() -> List[InstalledApp]:
    """
    The apps installed on this Mac, by name, with their version and bundle ID.

    ::

        {app.name: app.version for app in macos.apps.installed()}   # {'Safari': '18.3', 'Xcode': '16.2', ...}

    It lists the Applications folders (yours, the Mac's and the system's),
    their subfolders included, and the apps Spotlight knows elsewhere.
    """
    require_macos()
    paths = set()
    for folder in _APP_FOLDERS:
        root = os.path.expanduser(folder)
        for current, folders, _ in os.walk(root):
            for name in list(folders):
                if name.endswith(".app"):
                    paths.add(os.path.realpath(os.path.join(current, name)))
                    folders.remove(name)  # an app's insides aren't other apps: only other folders are walked
    try:
        # Apps installed elsewhere, as Spotlight knows them; nothing is lost if it's off.
        found = spotlight.search('kMDItemContentType == "com.apple.application-bundle"')
        paths.update(os.path.realpath(str(path)) for path in found if "/Contents/" not in str(path))
    except MacOSError:
        pass
    apps = [app for app in (_installed_app(path) for path in paths) if app]
    return sorted(apps, key=lambda app: (app.name.lower(), str(app.path)))


# Where apps leave their files in ~/Library, named after their bundle ID.
_BY_BUNDLE_ID = (
    "Application Scripts",
    "Application Support",
    "Caches",
    "Containers",
    "Cookies",
    "HTTPStorages",
    "LaunchAgents",
    "Logs",
    "Preferences",
    "Preferences/ByHost",
    "Saved Application State",
    "WebKit",
)
# And where many name them after the app instead ("Application Support/Slack").
_BY_NAME = ("Application Support", "Caches", "Logs")
_SUFFIXES = (".plist", ".savedState", ".binarycookies")


def _owned_by(entry: str, bundle_id: str) -> bool:
    """Whether a file named ``entry`` belongs to the app ``bundle_id``: its own, or a helper's (``<id>.helper``)."""
    for suffix in _SUFFIXES:
        if entry.endswith(suffix):
            entry = entry[: -len(suffix)]
            break
    return entry == bundle_id or entry.startswith(bundle_id + ".")


def _leftovers(library: Path, bundle_id: Optional[str], names: Sequence[str], others: Sequence[str] = ()) -> List[Path]:
    """
    The files the app left in ``library`` (a ``~/Library``), by its bundle ID and its names.

    ``others`` are the bundle IDs of the other apps installed: ``com.google.Chrome.canary``'s
    files aren't Chrome's, although they start with its ID.
    """
    found = []

    def entries(folder: str) -> List[str]:
        try:
            return sorted(os.listdir(library / folder))
        except OSError:
            return []

    if bundle_id:
        for folder in _BY_BUNDLE_ID:
            found += [
                library / folder / entry
                for entry in entries(folder)
                if _owned_by(entry, bundle_id) and not any(_owned_by(entry, other) for other in others)
            ]
        # Group Containers are named after a team or group ("group.<id>", "<team>.<id>").
        groups = entries("Group Containers")
        found += [library / "Group Containers" / entry for entry in groups if entry.endswith("." + bundle_id)]
    for folder in _BY_NAME:
        found += [library / folder / entry for entry in entries(folder) if entry in names]
    return list(dict.fromkeys(path for path in found if path.name))


def _vendor(bundle_id: Optional[str]) -> Optional[str]:
    """The maker's part of a bundle ID: ``'org.mozilla'`` for ``'org.mozilla.firefox'``."""
    parts = (bundle_id or "").casefold().split(".")
    return ".".join(parts[:2]) if len(parts) > 2 else None


def _claims(app: InstalledApp, everything: Sequence[InstalledApp]) -> Tuple[List[str], List[str]]:
    """
    The names the app's files may go by, and the bundle IDs of the other apps that start with its own.

    A folder named after the app may just as well be a sibling's: Firefox Developer Edition and
    Firefox Nightly share "Application Support/Firefox" with Firefox. So a name is left out when
    another installed app's name holds it (or is held in it), or when another app comes from the
    same maker.
    """
    others = [other for other in everything if other.path != app.path and other.bundle_id != app.bundle_id]
    vendor = _vendor(app.bundle_id)
    if vendor is not None and any(_vendor(other.bundle_id) == vendor for other in others):
        names: List[str] = []  # a sibling from the same maker may share any of its folders
    else:
        taken = {name.casefold() for other in others for name in (other.name, other.path.stem)}

        def shared(name: str) -> bool:
            wanted = name.casefold()
            return any(wanted in other or other in wanted for other in taken)

        names = sorted(name for name in {app.name, app.path.stem} if not shared(name))
    prefix = "{}.".format(app.bundle_id)
    ids = sorted({other.bundle_id for other in others if other.bundle_id and other.bundle_id.startswith(prefix)})
    return names, ids


def uninstall(name: str, *, dry_run: bool = False, include_name_matches: bool = False) -> List[Path]:
    """
    Uninstall an app: move it to the Trash, with the files it left in your
    Library (settings, caches, logs, saved state, support files), and return
    what was moved, the app first.

    ::

        macos.apps.uninstall("Slack", dry_run=True)   # [PosixPath('/Applications/Slack.app'), ...]
        macos.apps.uninstall("Slack")

    ``name`` is an app name, a bundle ID or a path. ``dry_run=True`` only
    returns what would go, without moving anything. The files are found by
    the app's bundle ID, which only that app uses.

    Many apps also keep a folder named after themselves in Application
    Support, Caches or Logs (``Application Support/Slack``). Those are only
    moved with ``include_name_matches=True``, since a name can be shared:
    Firefox Developer Edition keeps its profiles in Firefox's. Even then a
    name is skipped when another installed app's name holds it, or comes
    from the same maker. They come last in the list: try ``dry_run=True``
    first, and check them. Everything goes to the Trash, so *Put Back* undoes
    it; only this user's files are touched, not ``/Library``'s, which need an
    administrator.

    Raises :class:`~macos.MacOSError` for an app that's running (quit it
    first; ``dry_run`` works all the same) or that comes with macOS, and :class:`~macos.AppNotFoundError` for
    one that isn't found. An app installed for every user may need an
    administrator to be moved: then nothing is moved, and the error says so.
    """
    require_macos()
    path = _locate(name)
    app = _installed_app(path)
    if app is None:
        raise AppNotFoundError("{} isn't an app".format(path))
    if path.startswith(("/System/", "/usr/")):
        raise MacOSError("{} comes with macOS and can't be uninstalled".format(app.name))
    names, others = _claims(app, installed())
    if not include_name_matches:
        names = []  # by bundle ID only: a folder named after the app may be another's too
    found = [Path(path), *_leftovers(Path.home() / "Library", app.bundle_id, names, others)]
    if dry_run:
        return found
    if get(path) is not None:
        raise MacOSError("{} is running: quit it first".format(app.name))
    finder.trash(path)  # the app first: when it can't be moved, its files stay too
    failed = []
    for leftover in found[1:]:
        try:
            finder.trash(leftover)
        except (OSError, MacOSError):
            failed.append(leftover)
    if failed:
        raise MacOSError(
            "{} went to the Trash, but not these files of it: {}".format(app.name, ", ".join(str(item) for item in failed))
        )
    return found
