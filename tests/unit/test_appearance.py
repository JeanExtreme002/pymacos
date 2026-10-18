"""Unit tests for :mod:`macos.appearance`. They run on any platform."""

import contextlib

import pytest

import macos


def test_appearance_wait_for_change(monkeypatch):
    modes = iter(["light", "light", "light", "dark"])
    monkeypatch.setattr(macos.appearance, "mode", lambda: next(modes))

    assert macos.appearance.wait_for_change(interval=0.001) == "dark"


def test_set_mode(fake_run):
    macos.appearance.set_mode("light")

    assert fake_run.args[:2] == ["osascript", "-e"]
    assert fake_run.args[2].endswith("set dark mode to false")


def test_set_mode_without_the_automation_permission(fake_run):
    fake_run.returncode = 1
    fake_run.stderr = "execution error: Not authorized to send Apple events to System Events. (-1743)"

    with pytest.raises(macos.PermissionDeniedError, match="Automation"):
        macos.appearance.set_mode("dark")

    fake_run.stderr = "execution error: something else (-1)"
    with pytest.raises(macos.CommandError):
        macos.appearance.set_mode("dark")


def test_appearance_argument_checks():
    with pytest.raises(ValueError):
        macos.appearance.wait_for_change(interval=0)
    with pytest.raises(ValueError, match="'dark' or 'light'"):
        macos.appearance.set_mode("blue")


@pytest.mark.parametrize("interval", [float("nan"), float("inf"), -1.0])
def test_wait_for_change_refuses_an_interval_that_is_not_a_positive_number(monkeypatch, interval):
    monkeypatch.setattr(macos.appearance, "mode", lambda: "light")
    monkeypatch.setattr(macos.appearance.time, "sleep", lambda seconds: pytest.fail("slept"))

    with pytest.raises(ValueError, match="interval"):
        macos.appearance.wait_for_change(interval=interval)


def test_wait_for_change_refuses_a_nan_timeout(monkeypatch):
    # A NaN deadline is never reached: without the check it would poll forever.
    monkeypatch.setattr(macos.appearance, "mode", lambda: "light")
    monkeypatch.setattr(macos.appearance.time, "sleep", lambda seconds: pytest.fail("slept"))

    with pytest.raises(ValueError, match="timeout"):
        macos.appearance.wait_for_change(timeout=float("nan"))


def test_wait_for_change_still_times_out_at_once_with_a_zero_timeout(monkeypatch):
    monkeypatch.setattr(macos.appearance, "mode", lambda: "light")
    monkeypatch.setattr(macos.appearance.time, "sleep", lambda seconds: None)

    with pytest.raises(macos.WaitTimeoutError):
        macos.appearance.wait_for_change(timeout=0)


@pytest.fixture
def smoothing(monkeypatch):
    """AppleFontSmoothing kept per host, read as CFPreferencesCopyAppValue does: this Mac's value first."""
    from macos import appearance

    store = {}

    def read(domain, key, *, default=None, current_host=False):
        if current_host:
            return store.get(True, default)
        return store.get(True, store.get(False, default))

    def write(domain, key, value, *, current_host=False):
        store[current_host] = value

    def delete(domain, key, *, current_host=False):
        return store.pop(current_host, None) is not None

    monkeypatch.setattr(appearance.defaults, "read", read)
    monkeypatch.setattr(appearance.defaults, "write", write)
    monkeypatch.setattr(appearance.defaults, "delete", delete)
    return store


def test_set_font_smoothing_removes_a_value_set_for_this_mac_only(smoothing):
    from macos import appearance

    smoothing[True] = 0  # defaults -currentHost write -g AppleFontSmoothing -int 0
    assert not appearance.font_smoothing()
    appearance.set_font_smoothing(True)
    assert appearance.font_smoothing() and smoothing == {}

    smoothing[True] = 2
    appearance.set_font_smoothing(False)
    assert not appearance.font_smoothing() and smoothing == {False: 0}


def test_set_font_smoothing_leaves_this_macs_host_alone_when_it_sets_nothing(smoothing, monkeypatch):
    from macos import appearance

    deleted = []
    monkeypatch.setattr(appearance.defaults, "delete", lambda domain, key, *, current_host=False: deleted.append(current_host))
    appearance.set_font_smoothing(True)
    assert deleted == [False]  # no synchronize of a ByHost domain that may be managed


def test_accent_color_refuses_a_color_macos_did_not_convert(monkeypatch):
    from macos import appearance

    monkeypatch.setattr(appearance, "framework", lambda name: None)
    monkeypatch.setattr(appearance._objc, "cls", lambda name: 1)
    monkeypatch.setattr(appearance._objc, "autorelease_pool", contextlib.nullcontext)
    # The accent color, then the sRGB space, then nothing: the conversion failed.
    answers = iter([10, 20, None])
    monkeypatch.setattr(appearance._objc, "send", lambda *args, **kwargs: next(answers))
    with pytest.raises(macos.MacOSError, match="accent color"):
        appearance.accent_color()  # not '#000000'


@pytest.mark.parametrize("written", ["NO", "false", "0", 0, False])
def test_yes_or_no_preferences_written_as_text_read_as_macos_reads_them(monkeypatch, written):
    from macos import appearance

    # `defaults write -g _HIHideMenuBar NO` stores the text 'NO', which bool() takes for true.
    monkeypatch.setattr(appearance.defaults, "read", lambda domain, key, *, default=None, current_host=False: written)
    monkeypatch.setattr(appearance._cf, "lib", lambda: type("CF", (), {"CFPreferencesAppSynchronize": lambda self, app: None})())
    monkeypatch.setattr(appearance._cf, "constant", lambda cf, name: None)
    assert appearance.menu_bar_hidden() is False
    assert appearance.is_auto() is False


@pytest.mark.parametrize("written", ["YES", "true", "1", 1, True])
def test_yes_or_no_preferences_read_yes_as_true(monkeypatch, written):
    from macos import appearance

    monkeypatch.setattr(appearance.defaults, "read", lambda domain, key, *, default=None, current_host=False: written)
    monkeypatch.setattr(appearance._cf, "lib", lambda: type("CF", (), {"CFPreferencesAppSynchronize": lambda self, app: None})())
    monkeypatch.setattr(appearance._cf, "constant", lambda cf, name: None)
    assert appearance.menu_bar_hidden() is True
    assert appearance.is_auto() is True


@pytest.mark.parametrize("written, smooth", [("0", False), (0, False), ("2", True), (2, True), ("lots", True)])
def test_font_smoothing_reads_a_level_written_as_text(smoothing, written, smooth):
    from macos import appearance

    smoothing[False] = written  # `defaults write -g AppleFontSmoothing 0` stores the text '0'
    assert appearance.font_smoothing() is smooth
