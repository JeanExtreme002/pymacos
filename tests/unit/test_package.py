"""Unit tests for the package itself: lazy submodules, the shortcuts, and the deprecation helper."""

import subprocess
import sys
import warnings

import pytest

import macos
from macos import _system


def test_importing_the_package_loads_no_submodule():
    code = "import sys, macos; print(sorted(m for m in sys.modules if m.startswith('macos.')))"
    loaded = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert loaded.strip() == "['macos.errors']"


def test_every_public_name_resolves():
    for name in macos.__all__:
        assert getattr(macos, name) is not None
    assert macos.notify is macos.notifications.notify
    assert macos.open is macos.launch.open


def test_private_submodules_stay_reachable():
    assert macos._objc.__name__ == "macos._objc"


def test_unknown_attributes_raise_attribute_error():
    with pytest.raises(AttributeError, match="has no attribute 'nope'"):
        macos.nope


def test_dir_lists_the_lazy_names():
    assert {"pdf", "notify", "MacOSError"} <= set(dir(macos))


def test_timeouts_raise_command_timeout_error(monkeypatch):
    def slow(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(_system.sys, "platform", "darwin")
    monkeypatch.setattr(_system.subprocess, "run", slow)
    with pytest.raises(macos.CommandTimeoutError, match="'sleep' didn't finish within 2 seconds") as caught:
        _system.run(["sleep", "5"], timeout=2)
    assert isinstance(caught.value, TimeoutError) and isinstance(caught.value, macos.MacOSError)
    assert caught.value.cmd == ["sleep", "5"] and caught.value.timeout == 2


def test_command_timeout_error_survives_pickling():
    import pickle

    error = pickle.loads(pickle.dumps(macos.CommandTimeoutError(["log", "show"], 30)))
    assert (error.cmd, error.timeout, str(error)) == (["log", "show"], 30, "'log' didn't finish within 30 seconds")


def test_deprecated_functions_warn_and_still_work():
    @_system.deprecated("macos.volume.set", removal="2.0")
    def set_volume(level):
        """Set the volume."""
        return level * 2

    expected = r"set_volume\(\) is deprecated and will be removed in pymacos 2.0; use macos.volume.set instead"
    with pytest.warns(DeprecationWarning, match=expected):
        assert set_volume(21) == 42
    assert set_volume.__name__ == "set_volume"
    assert set_volume.__doc__.startswith("Deprecated: use :func:`macos.volume.set` instead.")


def test_deprecation_warnings_point_at_the_caller():
    @_system.deprecated("new", removal="2.0")
    def old():
        pass

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        old()
    assert caught[0].filename == __file__
