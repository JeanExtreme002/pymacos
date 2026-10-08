# -*- coding: utf-8 -*-

"""
Read and control the tabs of Safari, Chrome and the other Chromium browsers (Brave, Edge, Vivaldi...).

::

    macos.browser.current_tab()         # Tab(title='pymacos', url='https://github.com/...', app='Safari', ...)
    [tab.url for tab in macos.browser.tabs()]
    macos.browser.open("https://macos.readthedocs.io")
    macos.browser.run_js("document.title")

By default it talks to the browser in front, or else the one running; it
never opens a browser to read it. Goes through AppleScript, so the first
time macOS asks to allow the app running Python (your terminal or IDE) to
control the browser. Firefox, Arc and a few others can't be scripted this
way: naming one with ``app=`` raises :class:`~macos.errors.NotSupportedError`,
and by default they're passed over.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from . import apps
from ._system import applescript, run as _run
from .errors import CommandError, MacOSError, NotSupportedError, PermissionDeniedError

__all__ = ["Tab", "BROWSERS", "current_tab", "tabs", "open", "run_js"]

_SAFARI, _CHROMIUM = "safari", "chromium"

# App name: which AppleScript dictionary it has.
_KINDS: Dict[str, str] = {
    "Safari": _SAFARI,
    "Safari Technology Preview": _SAFARI,
    "Google Chrome": _CHROMIUM,
    "Google Chrome Canary": _CHROMIUM,
    "Chromium": _CHROMIUM,
    "Brave Browser": _CHROMIUM,
    "Microsoft Edge": _CHROMIUM,
    "Vivaldi": _CHROMIUM,
}
BROWSERS = tuple(_KINDS)
"""The browsers this module can script."""

_UNSCRIPTABLE = ("Firefox", "Firefox Developer Edition", "Firefox Nightly", "Arc", "Opera", "Orion", "Zen Browser")

_RECORD, _FIELD = "\x1e", "\x1f"  # ASCII record and unit separators: never in a title or URL

_LIST = {
    _SAFARI: """
on run argv
    set out to ""
    tell application "{app}"
        repeat with w in (every window)
            try
                set wid to id of w
                set active to index of current tab of w
                set i to 0
                repeat with t in (every tab of w)
                    set i to i + 1
                    set u to URL of t
                    if u is missing value then set u to ""
                    set n to name of t
                    if n is missing value then set n to ""
                    set out to out & wid & (ASCII character 31) & i & (ASCII character 31) & (i = active) & ¬
                        (ASCII character 31) & n & (ASCII character 31) & u & (ASCII character 30)
                end repeat
            end try
        end repeat
    end tell
    return out
end run
""",
    _CHROMIUM: """
on run argv
    set out to ""
    tell application "{app}"
        repeat with w in (every window)
            set wid to id of w
            set active to active tab index of w
            set i to 0
            repeat with t in (every tab of w)
                set i to i + 1
                set u to URL of t
                if u is missing value then set u to ""
                set n to title of t
                if n is missing value then set n to ""
                set out to out & wid & (ASCII character 31) & i & (ASCII character 31) & (i = active) & ¬
                    (ASCII character 31) & n & (ASCII character 31) & u & (ASCII character 30)
            end repeat
        end repeat
    end tell
    return out
end run
""",
}

_ACTIVATE = {
    _SAFARI: """
on run argv
    tell application "{app}"
        set w to window id ((item 1 of argv) as integer)
        set current tab of w to tab ((item 2 of argv) as integer) of w
        set index of w to 1
        activate
    end tell
end run
""",
    _CHROMIUM: """
on run argv
    tell application "{app}"
        set w to window id ((item 1 of argv) as integer)
        set active tab index of w to ((item 2 of argv) as integer)
        set index of w to 1
        activate
    end tell
end run
""",
}

_CLOSE = """
on run argv
    tell application "{app}" to close tab ((item 2 of argv) as integer) of window id ((item 1 of argv) as integer)
end run
"""

_RELOAD = {
    # Safari's reload is JavaScript, which needs a setting: loading the same URL again doesn't.
    _SAFARI: """
on run argv
    tell application "{app}"
        set t to tab ((item 2 of argv) as integer) of window id ((item 1 of argv) as integer)
        set URL of t to (URL of t)
    end tell
end run
""",
    _CHROMIUM: """
on run argv
    tell application "{app}" to reload tab ((item 2 of argv) as integer) of window id ((item 1 of argv) as integer)
end run
""",
}

_GO = """
on run argv
    tell application "{app}" to set URL of tab ((item 2 of argv) as integer) of window id ((item 1 of argv) as integer) ¬
        to (item 3 of argv)
end run
"""

# The JavaScript comes on stdin, not as an argument like the other scripts'
# values: arguments show in `ps` to the user's other processes for as long as
# the script runs, and page scripts may carry tokens. Nor is it pasted into
# the source: AppleScriptObjC reads it from stdin as UTF-8 text.
_READ_STDIN = """use framework "Foundation"
use scripting additions

on run argv
    set stdin to current application's NSFileHandle's fileHandleWithStandardInput()
    set pymacosScript to (current application's NSString's alloc()'s initWithData:(stdin's readDataToEndOfFile()) ¬
        encoding:(current application's NSUTF8StringEncoding)) as text
"""

_RUN_JS = {
    _SAFARI: _READ_STDIN
    + """    tell application "{app}" to return do JavaScript pymacosScript in current tab of front window
end run
""",
    _CHROMIUM: _READ_STDIN
    + """    tell application "{app}" to return execute active tab of front window javascript pymacosScript
end run
""",
}


@dataclass(frozen=True)
class Tab:
    """A browser tab, as it was when read: after tabs close, the positions shift."""

    title: str
    url: str
    app: str
    """The browser, such as ``'Safari'`` or ``'Google Chrome'``."""
    window: int
    """The window's id, as the browser numbers them."""
    index: int
    """The tab's position in its window, from 1."""
    active: bool
    """Whether it's the tab shown in its window."""

    def activate(self) -> None:
        """Show this tab, bring its window to the front, and the browser too."""
        _script(self.app, _ACTIVATE[_kind(self.app)], str(self.window), str(self.index))

    def close(self) -> None:
        """Close this tab."""
        _script(self.app, _CLOSE, str(self.window), str(self.index))

    def reload(self) -> None:
        """Load the page again."""
        _script(self.app, _RELOAD[_kind(self.app)], str(self.window), str(self.index))

    def go(self, url: str) -> None:
        """Load ``url`` in this tab, in place of its page."""
        _script(self.app, _GO, str(self.window), str(self.index), url)


def _kind(app: str) -> str:
    """The AppleScript dictionary of ``app``, which must be one of :data:`BROWSERS`."""
    if app not in _KINDS:
        raise ValueError("{!r} isn't a browser this module can script; see macos.browser.BROWSERS".format(app))
    return _KINDS[app]


def _script(app: str, source: str, *args: str) -> str:
    # The app name is pasted into the source, so it must be one of BROWSERS: a Tab can be
    # built by hand (from JSON, say), and its app could otherwise carry AppleScript.
    _kind(app)
    return applescript(app, source.replace("{app}", app), *args)


def _browser(app: Optional[str]) -> Optional[str]:
    """``app`` (checked), or the browser in front, or the first one running; ``None`` if none runs."""
    if app is not None:
        if app in _KINDS:
            return app
        if app in _UNSCRIPTABLE:
            raise NotSupportedError("{} can't be scripted; use one of {}".format(app, ", ".join(BROWSERS)))
        raise ValueError("app must be one of {}, not {!r}".format(", ".join(BROWSERS), app))
    front = apps.frontmost()
    if front is not None and front.name in _KINDS:
        return front.name
    for running in apps.running():
        if running.name in _KINDS:
            return running.name
    return None


def _is_running(app: str) -> bool:
    return any(running.name == app for running in apps.running())


def tabs(app: Optional[str] = None) -> List[Tab]:
    """
    Every tab of every window of the browser, front window first; ``[]`` when no browser is running.

    ``app`` is one of :data:`BROWSERS`, such as ``"Safari"`` or
    ``"Google Chrome"``; by default, the browser in front, or else the one
    running. It never opens a browser.
    """
    browser = _browser(app)
    if browser is None or not _is_running(browser):
        return []
    found = []
    for record in _script(browser, _LIST[_KINDS[browser]]).rstrip("\n").split(_RECORD):
        fields = record.split(_FIELD)
        if len(fields) != 5:
            continue
        window, index, active, title, url = fields
        found.append(Tab(title=title, url=url, app=browser, window=int(window), index=int(index), active=active == "true"))
    return found


def current_tab(app: Optional[str] = None) -> Optional[Tab]:
    """The tab shown in the browser's front window, or ``None``. ``app`` works as in :func:`tabs`."""
    for tab in tabs(app):
        if tab.active:
            return tab
    return None


def open(url: str, app: Optional[str] = None) -> None:
    """
    Open ``url`` in a new tab and bring the browser to the front.

    ``app`` works as in :func:`tabs`; with no browser running, it opens
    the default browser. To open a URL in whatever handles it, see :func:`macos.open`.
    A ``url`` starting with ``-`` raises :class:`ValueError`: ``open`` would take it as an option.
    """
    if url.startswith("-"):
        # `open` has no "--": "-g" or "-F" would be one of its options, not a URL.
        raise ValueError("url must not start with '-', not {!r}".format(url))
    browser = _browser(app)
    if browser is None:
        default = apps.default_browser()
        _run(["open", url] if default is None else ["open", "-a", default, url])
        return
    _run(["open", "-a", browser, url])


def run_js(script: str, app: Optional[str] = None) -> Optional[str]:
    """
    Run JavaScript in the current tab, and return its result as text (``None`` for ``undefined``).

    ::

        macos.browser.run_js("document.title")
        macos.browser.run_js("JSON.stringify([...document.links].map(a => a.href))")

    The browser must allow it first, once: in Safari, *Develop › Allow
    JavaScript from Apple Events* (show the Develop menu in Settings ›
    Advanced); in Chrome and the others, *View › Developer › Allow
    JavaScript from Apple Events*. Otherwise it raises
    :class:`~macos.errors.PermissionDeniedError`. Return ``JSON.stringify(...)``
    to get structured data back. With no browser running, it raises
    :class:`~macos.errors.MacOSError`. The script reaches ``osascript`` on its
    standard input, so it doesn't show in the process list.
    """
    browser = _browser(app)
    if browser is None or not _is_running(browser):
        raise MacOSError("no browser is running")
    try:
        output = applescript(browser, _RUN_JS[_KINDS[browser]].replace("{app}", browser), input=script)
    except CommandError as error:
        if "Allow JavaScript from Apple Events" in error.stderr or "JavaScript through AppleScript" in error.stderr:
            where = "Develop" if _KINDS[browser] == _SAFARI else "View › Developer"
            raise PermissionDeniedError(
                "{} doesn't allow JavaScript from scripts: turn on {} › Allow JavaScript from Apple Events".format(
                    browser, where
                )
            ) from None
        raise
    result = output.rstrip("\n")
    return None if result == "missing value" else result
