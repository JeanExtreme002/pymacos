"""Unit tests for :mod:`macos.defaults`. They run on any platform."""

import sys

import pytest

import macos


def test_defaults_argument_checks():
    with pytest.raises(ValueError, match="domain must not be empty"):
        macos.defaults.read(" ", "key")
    with pytest.raises(ValueError, match="domain must not be empty"):
        macos.defaults.keys("")
    with pytest.raises(ValueError, match="use delete"):
        macos.defaults.write("com.example.app", "key", None)
    with pytest.raises(ValueError, match="key must not be empty"):
        macos.defaults.write("com.example.app", " ", 1)
    with pytest.raises(ValueError, match="key must not be empty"):
        macos.defaults.delete("com.example.app", "")


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


def test_defaults_restored_restores_every_key_of_a_whole_domain_before_raising(monkeypatch):
    from macos import defaults

    tried = []

    def refuse(domain, name, *args, **kwargs):
        tried.append(name)
        raise macos.PermissionDeniedError("isn't writable")

    monkeypatch.setattr(defaults, "_check", lambda domain: None)
    monkeypatch.setattr(defaults, "_own", lambda domain, key, default, current_host: default)  # nothing set when it starts
    monkeypatch.setattr(defaults, "keys", lambda domain, current_host=False: ["a", "b", "c"])  # set in the block
    monkeypatch.setattr(defaults, "delete", refuse)

    with pytest.raises(macos.PermissionDeniedError):
        with macos.defaults.restored("com.example.app"):
            pass

    assert tried == ["a", "b", "c"]  # each delete tried, though the first failed


def test_defaults_restored_never_hides_the_blocks_own_error(unwritable):
    with pytest.raises(ZeroDivisionError) as raised:
        with macos.defaults.restored(("com.example.app", "a"), ("com.example.app", "b")):
            1 / 0

    assert unwritable.set == [("app", None), ("app", None)]  # both still tried
    if sys.version_info >= (3, 11):
        assert len(raised.value.__notes__) == 2 and "isn't writable" in raised.value.__notes__[0]


def test_defaults_restored_dropped_unfinished_still_raises_what_it_couldnt_restore(unwritable):
    manager = macos.defaults.restored(("com.example.app", "a"))
    manager.__enter__()
    with pytest.raises(macos.PermissionDeniedError):
        manager.gen.close()  # what dropping it does: GeneratorExit, which is no error of the block's


def test_defaults_restored_goes_on_after_any_error(monkeypatch):
    from macos import defaults

    tried = []

    def broken(domain, name, *args, **kwargs):
        tried.append(name)
        raise ValueError("can't hold it")

    monkeypatch.setattr(defaults, "_check", lambda domain: None)
    monkeypatch.setattr(defaults, "_own", lambda domain, key, default, current_host: {"a": 1, "b": 2}[key])
    monkeypatch.setattr(defaults, "keys", lambda domain, current_host=False: ["a", "b"])
    monkeypatch.setattr(defaults, "write", broken)

    with pytest.raises(ValueError, match="can't hold it"):
        with macos.defaults.restored(("com.example.app", "a"), "com.example.other"):
            monkeypatch.setattr(defaults, "_own", lambda domain, key, default, current_host: 0)  # all changed
            monkeypatch.setattr(defaults, "keys", lambda domain, current_host=False: 1 / 0)  # can't list the domain

    assert tried == ["a", "a", "b"]  # the key, then each of the domain's, though listing it failed


def test_appearance_setters_pass_the_error_on(unwritable):
    with pytest.raises(macos.PermissionDeniedError):
        macos.appearance.set_hide_menu_bar(True)
    with pytest.raises(macos.PermissionDeniedError):
        macos.trackpad.set_natural_scrolling(True)


def test_defaults_restored_snapshots_the_domains_own_values_only(monkeypatch):
    from macos import defaults

    own = {"size": 48}  # what the user's file sets
    in_effect = {"size": 48, "managed": True}  # what read() gives, a configuration profile's key included
    written = []

    monkeypatch.setattr(defaults, "_check", lambda domain: None)
    monkeypatch.setattr(defaults, "read", lambda domain, key=None, **kwargs: in_effect if key is None else in_effect.get(key))
    monkeypatch.setattr(defaults, "_own", lambda domain, key, default, current_host: own.get(key, default))
    monkeypatch.setattr(defaults, "keys", lambda domain, current_host=False: sorted(own))

    def write(domain, key, value, **kwargs):
        written.append((key, value))
        own[key] = value

    monkeypatch.setattr(defaults, "write", write)
    monkeypatch.setattr(defaults, "delete", lambda domain, key, **kwargs: own.pop(key, None) is not None)

    with macos.defaults.restored("com.example.app"):
        own["size"] = 64
    assert own == {"size": 48}
    assert ("managed", True) not in written  # the profile's value isn't copied into the user's file


def test_defaults_restored_puts_back_a_value_that_only_changed_type(monkeypatch):
    from macos import defaults

    own = {"enabled": True, "sizes": [1.0, 2], "nested": {"on": False}}
    written = []
    monkeypatch.setattr(defaults, "_check", lambda domain: None)
    monkeypatch.setattr(defaults, "_own", lambda domain, key, default, current_host: own.get(key, default))
    monkeypatch.setattr(defaults, "keys", lambda domain, current_host=False: sorted(own))

    def write(domain, key, value, **kwargs):
        written.append(key)
        own[key] = value

    monkeypatch.setattr(defaults, "write", write)
    with macos.defaults.restored("com.example.app"):
        own.update(enabled=1, sizes=[1, 2], nested={"on": 0})  # equal in Python, not to the apps that read them
    assert own == {"enabled": True, "sizes": [1.0, 2], "nested": {"on": False}}
    assert type(own["enabled"]) is bool and type(own["sizes"][0]) is float and type(own["nested"]["on"]) is bool
    assert sorted(written) == ["enabled", "nested", "sizes"]
    written.clear()
    with macos.defaults.restored("com.example.app"):
        pass
    assert written == []  # nothing changed: nothing written


@pytest.mark.parametrize("domain", ["/tmp/x", "../x", "evil/sub", "~/x", "/"])
def test_defaults_refuse_a_domain_that_is_a_path(monkeypatch, domain):
    # CFPreferences takes "/tmp/x" for /tmp/x.plist and "evil/sub" for ~/Library/Preferences/evil/sub.plist:
    # a domain from user input would write any file. Refused before CoreFoundation is asked anything.
    from macos import defaults

    monkeypatch.setattr(defaults, "_preferences", lambda: pytest.fail("CoreFoundation asked about a path"))
    calls = [
        lambda: macos.defaults.read(domain, "key"),
        lambda: macos.defaults.read(domain),
        lambda: macos.defaults.write(domain, "key", 1),
        lambda: macos.defaults.delete(domain, "key"),
        lambda: macos.defaults.keys(domain),
    ]
    for call in calls:
        with pytest.raises(ValueError, match="not a path"):
            call()
    with pytest.raises(ValueError, match="not a path"):
        with macos.defaults.restored(domain):
            pass
    with pytest.raises(ValueError, match="not a path"):
        with macos.defaults.restored((domain, "key")):
            pass


@pytest.mark.parametrize(
    "domain",
    [
        "com.apple.dock",
        "NSGlobalDomain",
        "-g",
        "-globalDomain",
        ".GlobalPreferences",
        "com.apple.driver.AppleBluetoothMultitouch.trackpad",
        "com.apple.print.custompresets.forprinter.Brother_HL",
        "com.github.pymacos.test-123",
    ],
)
def test_defaults_take_the_global_names_and_bundle_ids(monkeypatch, domain):
    from macos import defaults

    class Accepted(Exception):
        """The check let the domain through: CoreFoundation is asked next."""

    monkeypatch.setattr(defaults, "_preferences", lambda: (_ for _ in ()).throw(Accepted()))
    monkeypatch.setattr(defaults._cf, "from_python", lambda value: 0)  # write() converts the value first: not on Linux
    with pytest.raises(Accepted):
        macos.defaults.read(domain, "key")
    with pytest.raises(Accepted):
        macos.defaults.write(domain, "key", 1, current_host=True)
