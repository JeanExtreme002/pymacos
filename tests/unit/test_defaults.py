"""Unit tests for :mod:`macos.defaults`. They run on any platform."""

import pytest

import macos


def test_defaults_argument_checks():
    with pytest.raises(ValueError, match="domain must not be empty"):
        macos.defaults.read(" ", "key")
    with pytest.raises(ValueError, match="domain must not be empty"):
        macos.defaults.keys("")
    with pytest.raises(ValueError, match="use delete"):
        macos.defaults.write("com.example.app", "key", None)


class _UnwritablePreferences:
    """Stands in for CFPreferences when the domain can't be written: every synchronize fails."""

    def __init__(self):
        self.set = []

    def CFPreferencesSetAppValue(self, key, value, name):
        self.set.append(("app", value))

    def CFPreferencesSetValue(self, key, value, name, user, host):
        self.set.append(("any", value))

    def CFPreferencesAppSynchronize(self, name):
        return False

    def CFPreferencesSynchronize(self, name, user, host):
        return False

    def CFPreferencesCopyValue(self, key, name, user, host):
        return None


@pytest.fixture
def unwritable(monkeypatch):
    from contextlib import contextmanager

    from macos import defaults

    @contextmanager
    def owned(ref):
        yield ref

    fake = _UnwritablePreferences()
    monkeypatch.setattr(defaults, "_preferences", lambda: fake)
    monkeypatch.setattr(defaults, "_domain", lambda domain: 1)
    monkeypatch.setattr(defaults, "_user", lambda: 2)
    monkeypatch.setattr(defaults, "_host", lambda current_host: 3)
    monkeypatch.setattr(defaults._cf, "owned", owned)
    monkeypatch.setattr(defaults._cf, "string", lambda text: 4)
    monkeypatch.setattr(defaults._cf, "from_python", lambda value: 5)
    return fake


def test_defaults_write_raises_when_the_domain_isnt_writable(unwritable):
    for call in (
        lambda: macos.defaults.write("com.example.app", "key", 1),
        lambda: macos.defaults.write(macos.defaults.GLOBAL, "key", 1),
        lambda: macos.defaults.write("com.example.app", "key", 1, current_host=True),
        lambda: macos.defaults.delete("com.example.app", "key"),
    ):
        with pytest.raises(macos.PermissionDeniedError, match="isn't writable"):
            call()
    assert unwritable.set == [("app", 5), ("any", 5), ("any", 5), ("app", None)]


def test_defaults_restored_restores_every_key_before_raising(unwritable):
    with pytest.raises(macos.PermissionDeniedError):
        with macos.defaults.restored(("com.example.app", "a"), ("com.example.app", "b")):
            pass

    assert unwritable.set == [("app", None), ("app", None)]  # both deletes tried, though the first failed


def test_appearance_setters_pass_the_error_on(unwritable):
    with pytest.raises(macos.PermissionDeniedError):
        macos.appearance.set_hide_menu_bar(True)
    with pytest.raises(macos.PermissionDeniedError):
        macos.trackpad.set_natural_scrolling(True)
