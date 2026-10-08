"""Unit tests for :mod:`macos.browser`. They run on any platform."""

import subprocess

import pytest

import macos
from macos import _system, apps

_TABS = (
    "7\x1f1\x1ffalse\x1fDocs\x1fhttps://macos.readthedocs.io/\x1e"
    "7\x1f2\x1ftrue\x1fpymacos\x1fhttps://github.com/JeanExtreme002/pymacos\x1e"
    "9\x1f1\x1ftrue\x1fNew Tab\x1f\x1e\n"
)


@pytest.fixture
def browsers(fake_run, monkeypatch):
    """Chrome and Firefox are running; Chrome answers with two windows' tabs."""

    def app(name):
        return apps.App(name=name, bundle_id=None, pid=1, path=None)

    monkeypatch.setattr(apps, "running", lambda **kwargs: [app("Finder"), app("Firefox"), app("Google Chrome")])
    monkeypatch.setattr(apps, "frontmost", lambda: app("Terminal"))
    fake_run.stdout = _TABS
    return fake_run


def test_browser_tabs(browsers):
    tabs = macos.browser.tabs()

    assert [(tab.window, tab.index, tab.active, tab.title) for tab in tabs] == [
        (7, 1, False, "Docs"),
        (7, 2, True, "pymacos"),
        (9, 1, True, "New Tab"),
    ]
    assert tabs[1].url == "https://github.com/JeanExtreme002/pymacos" and tabs[2].url == ""
    assert {tab.app for tab in tabs} == {"Google Chrome"}
    assert browsers.args[:2] == ["osascript", "-e"] and 'tell application "Google Chrome"' in browsers.args[2]
    assert macos.browser.current_tab().title == "pymacos"  # the front window's shown tab


def test_browser_prefers_the_one_in_front(browsers, monkeypatch):
    monkeypatch.setattr(apps, "frontmost", lambda: apps.App(name="Safari", bundle_id=None, pid=2, path=None))
    monkeypatch.setattr(apps, "running", lambda **kwargs: [apps.App(name="Safari", bundle_id=None, pid=2, path=None)])

    macos.browser.tabs()

    assert 'tell application "Safari"' in browsers.args[2] and "current tab" in browsers.args[2]


def test_browser_never_opens_a_browser(fake_run, monkeypatch):
    monkeypatch.setattr(apps, "running", lambda **kwargs: [])
    monkeypatch.setattr(apps, "frontmost", lambda: None)

    assert macos.browser.tabs() == [] and macos.browser.current_tab() is None
    assert macos.browser.tabs("Safari") == []
    with pytest.raises(macos.MacOSError, match="no browser is running"):
        macos.browser.run_js("1 + 1")
    assert fake_run.calls == []


def test_browser_tab_actions_pass_numbers_as_arguments(browsers):
    tab = macos.browser.tabs()[0]

    tab.activate()
    assert browsers.args[3:] == ["--", "7", "1"] and "active tab index" in browsers.args[2]
    tab.close()
    assert browsers.args[3:] == ["--", "7", "1"] and "close tab" in browsers.args[2]


def test_browser_run_js(browsers):
    browsers.stdout = "pymacos\n"
    script = 'document.querySelector("h1").textContent'

    assert macos.browser.run_js(script) == "pymacos"
    call = browsers.calls[-1]
    assert call["args"][:2] == ["osascript", "-e"] and len(call["args"]) == 3  # nothing after the source
    assert call["input"] == script  # on stdin: not in the process list, nor pasted into the AppleScript
    assert script not in call["args"][2] and 'tell application "Google Chrome"' in call["args"][2]
    macos.browser.run_js("-1")
    assert browsers.calls[-1]["input"] == "-1" and len(browsers.args) == 3
    browsers.stdout = "missing value\n"
    assert macos.browser.run_js("undefined") is None


def test_browser_run_js_needs_the_browser_setting(browsers, monkeypatch):
    def refuse(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 1, "", "execution error: Executing JavaScript through AppleScript is turned off. (12)"
        )

    monkeypatch.setattr(_system.subprocess, "run", refuse)
    with pytest.raises(macos.PermissionDeniedError, match="View › Developer › Allow JavaScript from Apple Events"):
        macos.browser.run_js("1")


def test_browser_open(browsers, monkeypatch):
    macos.browser.open("https://example.com")
    assert browsers.args == ["open", "-a", "Google Chrome", "https://example.com"]

    monkeypatch.setattr(apps, "running", lambda **kwargs: [])
    monkeypatch.setattr(apps, "default_browser", lambda: "/Applications/Safari.app")
    macos.browser.open("https://example.com")
    assert browsers.args == ["open", "-a", "/Applications/Safari.app", "https://example.com"]


def test_browser_argument_checks(browsers):
    with pytest.raises(macos.NotSupportedError, match="Firefox can't be scripted"):
        macos.browser.tabs("Firefox")
    with pytest.raises(ValueError, match="app must be one of"):
        macos.browser.tabs("Netscape")


def test_browser_tab_reload_and_go(browsers):
    tab = macos.browser.tabs()[1]

    tab.reload()
    assert browsers.args[3:] == ["--", "7", "2"] and "reload tab" in browsers.args[2]
    tab.go("https://example.com/?q=\"quoted\"")
    assert browsers.args[3:] == ["--", "7", "2", "https://example.com/?q=\"quoted\""]  # the URL is an argument
    assert "set URL of tab" in browsers.args[2]


def test_browser_run_js_without_the_automation_permission(browsers, monkeypatch):
    def refuse(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "execution error: Not authorized to send Apple events. (-1743)")

    monkeypatch.setattr(_system.subprocess, "run", refuse)
    with pytest.raises(macos.PermissionDeniedError, match="Automation permission.*Google Chrome"):
        macos.browser.run_js("1")


def test_browser_open_refuses_a_url_that_looks_like_an_option(browsers):
    with pytest.raises(ValueError, match="must not start with '-'"):
        macos.browser.open("-g")
    assert browsers.calls == []


def test_browser_tab_actions_refuse_an_app_that_isnt_a_browser(browsers):
    # The app name goes into the script's source: a Tab built by hand must not smuggle AppleScript in.
    tab = macos.browser.Tab(
        title="x", url="https://example.com", app='Safari" to do shell script "touch /tmp/pwned', window=1, index=1, active=True
    )
    for action in (tab.activate, tab.close, tab.reload, lambda: tab.go("https://example.com")):
        with pytest.raises(ValueError, match="isn't a browser"):
            action()
    assert browsers.calls == []  # nothing ran
