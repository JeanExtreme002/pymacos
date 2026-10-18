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


def test_browser_keeps_the_separators_out_of_the_titles(browsers):
    # The script takes the record and field separators out of every title and URL, so a page can't
    # split its own record. Were one to come through anyway, the listing fails rather than lose tabs.
    assert "my clean(n)" in macos.browser._LIST["chromium"] and "my clean(u)" in macos.browser._LIST["safari"]
    browsers.stdout = "7\x1f1\x1ffalse\x1fodd\x1ftitle\x1fhttps://a/\x1e" + _TABS
    with pytest.raises(macos.MacOSError, match="can't read"):
        macos.browser.tabs()
    browsers.stdout = "\n"
    assert macos.browser.tabs() == []


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
    browsers.stdout = "spymacos\n"
    script = 'document.querySelector("h1").textContent'

    assert macos.browser.run_js(script) == "pymacos"
    call = browsers.calls[-1]
    assert call["args"][:2] == ["osascript", "-e"] and len(call["args"]) == 3  # nothing after the source
    assert call["input"] == script.encode()  # on stdin: not in the process list, nor pasted into the AppleScript
    assert script not in call["args"][2] and 'tell application "Google Chrome"' in call["args"][2]
    macos.browser.run_js("-1")
    assert browsers.calls[-1]["input"] == b"-1" and len(browsers.args) == 3
    browsers.stdout = "n\n"
    assert macos.browser.run_js("undefined") is None


def test_browser_run_js_keeps_the_string_as_the_page_made_it(browsers):
    # Only osascript's own newline goes: the page's, a \r\n included, stay; and a page's
    # "missing value" is a string, not undefined.
    browsers.stdout = b"sa\r\nb\n\n\n"
    assert macos.browser.run_js("text") == "a\r\nb\n\n"
    browsers.stdout = b"smissing value\n"
    assert macos.browser.run_js("'missing value'") == "missing value"
    browsers.stdout = b"s\n"
    assert macos.browser.run_js("''") == ""
    browsers.stdout = b"v, 1, 2\n"  # not a string: as osascript prints it
    assert macos.browser.run_js("[1, 2]") == "1, 2"
    browsers.stdout = b"v,\n"  # an empty list or object: no space after the comma
    assert macos.browser.run_js("[]") == ""
    browsers.stdout = b"v,, 1\n"
    assert macos.browser.run_js("[[], 1]") == ", 1"
    assert '"s" & pymacosResult' in browsers.args[2]


def test_browser_run_js_never_opens_a_browser_that_quit_meanwhile(browsers):
    # Checked again in the script, where checking doesn't launch it.
    browsers.stdout = "x\n"
    with pytest.raises(macos.MacOSError, match="no browser is running"):
        macos.browser.run_js("1")
    assert browsers.args[2].index('is not running then return "x"') < browsers.args[2].index("tell application")
    for source in macos.browser._LIST.values():
        assert source.index('is not running then return out') < source.index('tell application')


def test_browser_run_js_needs_the_browser_setting(browsers, monkeypatch):
    def refuse(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 1, "", "execution error: Executing JavaScript through AppleScript is turned off. (12)"
        )

    monkeypatch.setattr(_system.subprocess, "run", refuse)
    with pytest.raises(macos.PermissionDeniedError, match="View › Developer › Allow JavaScript from Apple Events"):
        macos.browser.run_js("1")


@pytest.mark.parametrize(
    "stderr",
    [
        "execution error: Erro no Google Chrome: A execução do JavaScript por AppleScript está desativada. (12)",
        "execution error: Fehler in Google Chrome: Die Ausführung von JavaScript über AppleScript ist deaktiviert. (12)",
    ],
)
def test_browser_run_js_needs_the_browser_setting_in_any_language(browsers, monkeypatch, stderr):
    # Chrome writes the message in its own language: its number tells it.
    monkeypatch.setattr(_system.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 1, "", stderr))
    with pytest.raises(macos.PermissionDeniedError, match="Allow JavaScript from Apple Events"):
        macos.browser.run_js("1")


def test_browser_run_js_other_failures_stay_command_errors(browsers, monkeypatch):
    def fail(args, **kwargs):
        stderr = "execution error: Google Chrome got an error: (12) Something else. (-1728)"
        return subprocess.CompletedProcess(args, 1, "", stderr)

    monkeypatch.setattr(_system.subprocess, "run", fail)
    with pytest.raises(macos.CommandError):
        macos.browser.run_js("1")


def test_browser_open(browsers, monkeypatch):
    macos.browser.open("https://example.com")
    assert browsers.args == ["open", "-a", "Google Chrome", "https://example.com"]

    monkeypatch.setattr(apps, "running", lambda **kwargs: [])
    monkeypatch.setattr(apps, "default_browser", lambda: "/Applications/Safari.app")
    macos.browser.open("https://example.com")
    assert browsers.args == ["open", "-a", "/Applications/Safari.app", "https://example.com"]


def test_browser_open_without_a_default_browser(browsers, monkeypatch):
    # A plain `open url` would hand it to whatever handles its scheme: a file:// URL to a .command would run.
    monkeypatch.setattr(apps, "running", lambda **kwargs: [])
    monkeypatch.setattr(apps, "default_browser", lambda: None)
    with pytest.raises(macos.AppNotFoundError, match="no default web browser") as raised:
        macos.browser.open("file:///tmp/evil.command?token=s3cret")
    assert browsers.calls == [] and "s3cret" not in str(raised.value)


def test_browser_argument_checks(browsers):
    with pytest.raises(macos.NotSupportedError, match="Firefox can't be scripted"):
        macos.browser.tabs("Firefox")
    with pytest.raises(ValueError, match="app must be one of"):
        macos.browser.tabs("Netscape")


def test_browser_tab_reload_and_go(browsers):
    tab = macos.browser.tabs()[1]

    tab.reload()
    assert browsers.args[3:] == ["--", "7", "2"] and "reload tab" in browsers.args[2]
    tab.go("https://example.com/?q=\"quoted\"&token=s3cret")
    # The URL comes on stdin, as run_js's script: an argument would show in the process list.
    assert browsers.args[3:] == ["--", "7", "2"] and "s3cret" not in " ".join(browsers.args)
    assert browsers.calls[-1]["input"] == "https://example.com/?q=\"quoted\"&token=s3cret"
    assert "set URL of tab" in browsers.args[2] and "to pymacosScript" in browsers.args[2]


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


@pytest.mark.parametrize(
    "url",
    [
        "localhost/x?token=s3cret",
        # urlsplit reads the host as the scheme of these.
        "127.0.0.1:8000/?token=s3cret",
        "localhost:3000/x?token=s3cret",
        "example.com:8080/?token=s3cret",
        "/Users/me/page.html?token=s3cret",
    ],
)
def test_browser_open_refuses_a_url_without_a_scheme(browsers, url):
    # `open` would take it for a file here, and quote its path, token and all, in its error.
    with pytest.raises(ValueError, match="must have a scheme") as raised:
        macos.browser.open(url)
    assert browsers.calls == [] and "s3cret" not in str(raised.value)


@pytest.mark.parametrize("url", ["tel:5550100", "mailto:a@example.com", "https://localhost:3000/"])
def test_browser_open_takes_a_scheme_followed_by_digits(browsers, url):
    macos.browser.open(url)  # a scheme, not a host and its port
    assert browsers.calls


def test_browser_open_in_a_browser_that_isnt_installed(browsers, monkeypatch):
    def missing(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "Unable to find application named 'Vivaldi'")

    monkeypatch.setattr(_system.subprocess, "run", missing)
    with pytest.raises(macos.AppNotFoundError, match="Vivaldi isn't installed") as raised:
        macos.browser.open("https://localhost/?token=s3cret", app="Vivaldi")
    assert "s3cret" not in str(raised.value) and "s3cret" not in repr(raised.value.args)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__

    def damaged(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "The application cannot be opened. (-10669)")

    monkeypatch.setattr(_system.subprocess, "run", damaged)
    with pytest.raises(macos.CommandError):
        macos.browser.open("https://example.com", app="Vivaldi")


def test_browser_tab_actions_refuse_an_app_that_isnt_a_browser(browsers):
    # The app name goes into the script's source: a Tab built by hand must not smuggle AppleScript in.
    tab = macos.browser.Tab(
        title="x", url="https://example.com", app='Safari" to do shell script "touch /tmp/pwned', window=1, index=1, active=True
    )
    for action in (tab.activate, tab.close, tab.reload, lambda: tab.go("https://example.com")):
        with pytest.raises(ValueError, match="isn't a browser"):
            action()
    assert browsers.calls == []  # nothing ran
