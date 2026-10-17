"""Tests of :mod:`macos.notifications` against the real system. Skipped outside macOS."""

import plistlib
import subprocess

import macos


def test_notifications_is_allowed():
    assert macos.notifications.is_allowed() in (True, False, None)


def test_notifications_settings_are_read_as_defaults_exports_them():
    # The unit tests fake the read: this is CFPreferences against the real settings, which a broken
    # read would hide behind is_allowed()'s None.
    exported = subprocess.run(["defaults", "export", "com.apple.ncprefs", "-"], capture_output=True, timeout=30)
    expected = plistlib.loads(exported.stdout).get("apps") if exported.returncode == 0 and exported.stdout else None
    macos.defaults._synchronize("com.apple.ncprefs")
    assert macos.defaults.read("com.apple.ncprefs", "apps") == expected
