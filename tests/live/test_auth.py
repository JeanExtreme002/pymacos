"""Tests of :mod:`macos.auth` against the real system. Skipped outside macOS."""

import pytest

import macos


def test_auth_is_available():
    available = macos.auth.is_available()
    touch_id = macos.auth.is_available(only_touch_id=True)
    assert isinstance(available, bool) and isinstance(touch_id, bool)
    # Touch ID is one of the ways to confirm: when it can ask, confirm() can.
    assert available or not touch_id
    if not touch_id:
        # Without Touch ID, asking for it alone fails before showing anything.
        with pytest.raises(macos.NotSupportedError):
            macos.auth.confirm("test", only_touch_id=True)
