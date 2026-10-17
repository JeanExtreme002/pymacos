"""
The AppleScripts the package hands ``osascript``, compiled against the apps they control.

The other unit tests fake ``osascript`` and only look for pieces of the source, and many of these
scripts never run live on CI (no player plays, no dialog is answered, no browser is scripted): a
script that macOS refuses to compile would ship. This captures each script as the public functions
build it and compiles it with ``osacompile``, which reads the app's dictionary without running
anything or opening the app. A script for an app this Mac doesn't have is skipped.
"""

import os
import subprocess
import sys
from typing import List, Optional
from unittest import mock

import pytest

import macos
from macos import _system, apps, browser, music
from macos.errors import AppNotFoundError

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="osacompile is macOS's")

_RUN = subprocess.run  # the real one: fake_run replaces it for the package


def _source(args: List[str]) -> Optional[str]:
    """The script of an ``osascript -e ... -e ...`` command line, or ``None`` for another command."""
    if args[:1] != ["osascript"]:
        return None
    lines = [value for flag, value in zip(args[1::2], args[2::2]) if flag == "-e"]
    return "\n".join(lines)


def _installed(app: str) -> bool:
    try:
        apps._locate(app)
    except AppNotFoundError:
        return False
    return True


def _tab(app: str) -> browser.Tab:
    return browser.Tab(title="t", url="https://example.com/", app=app, window=1, index=1, active=True)


def _remove_login_item() -> None:
    # It finds the item among login_items() first, which the fake's empty output leaves without one.
    item = apps.LoginItem(name="Calculator", path="/System/Applications/Calculator.app")
    with mock.patch.object(apps, "login_items", lambda: [item]):
        macos.apps.remove_login_item("Calculator")


# What builds each script: (the app it controls, or None for the system's own commands; the call).
_CASES = {
    "notify": (None, lambda: macos.notify("m", title="t", subtitle="s", sound="Glass", check_permission=False)),
    "dialog.alert": (None, lambda: macos.dialog.alert("m", detail="d", timeout=1)),
    "dialog.confirm": (None, lambda: macos.dialog.confirm("m", title="t", timeout=1)),
    "dialog.prompt": (None, lambda: macos.dialog.prompt("m", default="d", title="t", hidden=True, timeout=1)),
    "dialog.choose": (None, lambda: macos.dialog.choose(["a", "b"], prompt="p", default="a", title="t")),
    "dialog.choose_file": (None, lambda: macos.dialog.choose_file("p", types=["public.text"], folder="/tmp")),
    "dialog.choose_files": (None, lambda: macos.dialog.choose_files("p", types=["public.text"], folder="/tmp")),
    "dialog.choose_folder": (None, lambda: macos.dialog.choose_folder("p", folder="/tmp")),
    "volume.get": (None, macos.volume.get),
    "volume.set": (None, lambda: macos.volume.set(30)),
    "volume.mute": (None, macos.volume.mute),
    "volume.unmute": (None, macos.volume.unmute),
    "volume.is_muted": (None, macos.volume.is_muted),
    "appearance.set_mode": ("System Events", lambda: macos.appearance.set_mode("dark")),
    "apps.login_items": ("System Events", macos.apps.login_items),
    "apps.add_login_item": ("System Events", lambda: macos.apps.add_login_item("/System/Applications/Calculator.app")),
    "apps.remove_login_item": ("System Events", _remove_login_item),
    "finder.selection": ("Finder", macos.finder.selection),
    "finder.current_folder": ("Finder", macos.finder.current_folder),
}
for _app in ("Safari", "Google Chrome"):  # one of each dictionary browser.py knows
    _CASES.update({
        "browser.tabs[{}]".format(_app): (_app, lambda app=_app: macos.browser.tabs(app)),
        "browser.current_tab[{}]".format(_app): (_app, lambda app=_app: macos.browser.current_tab(app)),
        "browser.run_js[{}]".format(_app): (_app, lambda app=_app: macos.browser.run_js("1 + 1", app=app)),
        "Tab.activate[{}]".format(_app): (_app, lambda app=_app: _tab(app).activate()),
        "Tab.close[{}]".format(_app): (_app, lambda app=_app: _tab(app).close()),
        "Tab.reload[{}]".format(_app): (_app, lambda app=_app: _tab(app).reload()),
        "Tab.go[{}]".format(_app): (_app, lambda app=_app: _tab(app).go("https://example.com/")),
    })
for _app in music.PLAYERS:
    _CASES.update({
        "music.now_playing[{}]".format(_app): (_app, lambda app=_app: macos.music.now_playing(app)),
        "music.play[{}]".format(_app): (_app, lambda app=_app: macos.music.play(app)),
        "music.pause[{}]".format(_app): (_app, lambda app=_app: macos.music.pause(app)),
        "music.play_pause[{}]".format(_app): (_app, lambda app=_app: macos.music.play_pause(app)),
        "music.next[{}]".format(_app): (_app, lambda app=_app: macos.music.next(app)),
        "music.previous[{}]".format(_app): (_app, lambda app=_app: macos.music.previous(app)),
        "music.volume[{}]".format(_app): (_app, lambda app=_app: macos.music.volume(app)),
        "music.set_volume[{}]".format(_app): (_app, lambda app=_app: macos.music.set_volume(50, app)),
        "music.seek[{}]".format(_app): (_app, lambda app=_app: macos.music.seek(30.5, app)),
    })


@pytest.fixture
def scripts(fake_run, monkeypatch):
    """The scripts the package passes ``osascript``, with every app it may control running."""
    sources: List[str] = []

    def run(args, **kwargs):
        source = _source(list(args))
        if source is not None:
            sources.append(source)
        return fake_run(args, **kwargs)

    monkeypatch.setattr(_system.subprocess, "run", run)
    everything = [apps.App(name=name, bundle_id=None, pid=1, path=None) for name in browser.BROWSERS]
    monkeypatch.setattr(apps, "running", lambda **kwargs: everything)
    monkeypatch.setattr(apps, "frontmost", lambda: None)
    monkeypatch.setattr(music, "_running", lambda: list(music.PLAYERS))
    return sources


@pytest.mark.parametrize("name", sorted(_CASES))
def test_the_scripts_compile(name, scripts):
    app, call = _CASES[name]
    if app is not None and not _installed(app):
        pytest.skip("{} isn't installed: its dictionary is needed to compile".format(app))
    try:
        call()
    except Exception:  # the fake output is empty: what happens to it after the script is captured doesn't matter
        pass
    assert scripts, "{} ran no AppleScript".format(name)
    for source in scripts:
        result = _RUN(["osacompile", "-o", os.devnull, "-e", source], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, "{} doesn't compile: {}\n{}".format(name, result.stderr.strip(), source)
