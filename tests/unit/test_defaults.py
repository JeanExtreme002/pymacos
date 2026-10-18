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

    monkeypatch.setattr(defaults, "_check", lambda domain, key=None: None)
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

    monkeypatch.setattr(defaults, "_check", lambda domain, key=None: None)
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

    monkeypatch.setattr(defaults, "_check", lambda domain, key=None: None)
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
    monkeypatch.setattr(defaults, "_check", lambda domain, key=None: None)
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
    for call in (lambda: macos.defaults.write(domain, "key", 1), lambda: macos.defaults.delete(domain, "key")):
        with pytest.raises(ValueError, match="not a path"):
            call()
    with pytest.raises(ValueError, match="not a path"):
        with macos.defaults.restored(domain):
            pass
    with pytest.raises(ValueError, match="not a path"):
        with macos.defaults.restored((domain, "key")):
            pass
    with pytest.raises(ValueError, match="not a path"):  # after a good one: refused before that one is read
        with macos.defaults.restored("com.example.app", (domain, "key")):
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


@pytest.mark.parametrize("domain", ["/Library/Preferences/com.apple.loginwindow", "rel/x"])
def test_defaults_still_read_a_plist_by_its_path_and_warn(monkeypatch, domain):
    """Reading a .plist by its path worked: it still does, with a DeprecationWarning, and 2.0 refuses it."""
    from macos import defaults

    class Asked(Exception):
        """CoreFoundation was asked: the read went through."""

    monkeypatch.setattr(defaults, "_preferences", lambda: (_ for _ in ()).throw(Asked()))
    reads = (lambda: macos.defaults.read(domain, "key"), lambda: macos.defaults.read(domain), lambda: macos.defaults.keys(domain))
    for call in reads:
        with pytest.warns(DeprecationWarning, match="not a path") as reported, pytest.raises(Asked):
            call()
        assert len(reported) == 1 and reported[0].filename == __file__  # once, at the caller's line


def test_defaults_restored_takes_each_pair_once(monkeypatch):
    # Every domain is checked before any is read, without going over a pair twice: one that can be gone over
    # only once (an iterator) still restores.
    from macos import defaults

    own = {"key": 1}
    monkeypatch.setattr(defaults, "_own", lambda domain, key, default, current_host: own.get(key, default))
    monkeypatch.setattr(defaults, "write", lambda domain, key, value, **kwargs: own.update({key: value}))
    with macos.defaults.restored(iter(("com.example.app", "key"))):
        own["key"] = 2
    assert own == {"key": 1}


def test_defaults_name_the_wrong_type_of_a_domain_or_key():
    with pytest.raises(TypeError, match="domain must be a str, not bytes"):
        macos.defaults.read(b"com.apple.dock", "key")
    with pytest.raises(TypeError, match="domain must be a str, not int"):
        macos.defaults.keys(5)
    with pytest.raises(TypeError, match="key must be a str, not int"):
        macos.defaults.write("com.example.app", 5, 1)
    with pytest.raises(TypeError, match="key must be a str, not NoneType"):
        macos.defaults.delete("com.example.app", None)
    with pytest.raises(TypeError, match="key must be a str, not int"):
        macos.defaults.read("com.example.app", 5)


@pytest.mark.parametrize("value", [["a", None], [1, None], {"x": None}, {"x": [1, {"y": None}]}])
def test_defaults_write_refuses_a_none_inside_before_any_cf_call(monkeypatch, value):
    # CFPreferences aborts the process on the kCFNull a nested None turns into: refused before it's reached.
    from macos import defaults

    def unreachable(*args, **kwargs):
        raise AssertionError("reached CoreFoundation")

    monkeypatch.setattr(defaults, "_store", unreachable)
    monkeypatch.setattr(defaults._cf, "lib", unreachable)
    with pytest.raises(ValueError, match="None"):
        macos.defaults.write("com.example.app", "key", value)


def test_defaults_write_takes_dates_as_utc(monkeypatch):
    import plistlib
    from contextlib import contextmanager
    from datetime import datetime, timedelta, timezone

    from macos import defaults

    class Fake:
        def CFPropertyListCreateWithData(self, *args):
            return 7

    @contextmanager
    def owned(ref):
        yield ref

    written = []
    stored = []
    monkeypatch.setattr(defaults._cf, "lib", lambda: Fake())
    monkeypatch.setattr(defaults._cf, "owned", owned)
    monkeypatch.setattr(defaults._cf, "data", lambda raw: written.append(plistlib.loads(raw)) or 6)
    monkeypatch.setattr(defaults, "_store", lambda domain, key, value, current_host: stored.append(value))
    noon = datetime(2026, 10, 17, 12, 0)
    for value in (noon, noon.replace(tzinfo=timezone.utc), datetime(2026, 10, 17, 9, 0, tzinfo=timezone(timedelta(hours=-3)))):
        macos.defaults.write("com.example.app", "when", value)
    macos.defaults.write("com.example.app", "when", {"at": [datetime(2026, 10, 17, 14, 0, tzinfo=timezone(timedelta(hours=2)))]})
    assert written == [noon, noon, noon, {"at": [noon]}]
    assert stored == [7, 7, 7, 7]


@pytest.mark.parametrize("key", ["", " ", None, 5])
def test_defaults_restored_checks_every_key_before_the_block_runs(monkeypatch, key):
    from macos import defaults

    def unreachable(*args, **kwargs):
        raise AssertionError("read before the checks")

    monkeypatch.setattr(defaults, "_own", unreachable)
    ran = []
    with pytest.raises((ValueError, TypeError)):
        with macos.defaults.restored(("com.example.app", "fine"), ("com.example.app", key)):
            ran.append(True)
    assert ran == []


@pytest.mark.parametrize(
    "value, expected",
    [
        (True, True),
        (False, False),
        ("YES", True),
        (" true ", True),
        ("No", False),
        ("FALSE", False),
        (1, True),
        (0, False),
        (2.5, True),
        (0.5, False),  # CF reads a number by its whole part
        ("1", True),
        ("0", False),
        ("0.5", False),
        ("-3", True),
    ],
)
def test_defaults_as_bool_reads_a_flag_as_macos_does(value, expected):
    from macos import defaults

    assert defaults._as_bool(value, not expected) is expected


@pytest.mark.parametrize("value", ["maybe", "", [1], {"a": 1}, b"1", None, float("nan"), float("inf"), "inf"])
def test_defaults_as_bool_falls_back_for_anything_else(value):
    from macos import defaults

    assert defaults._as_bool(value, True) is True
    assert defaults._as_bool(value, False) is False
