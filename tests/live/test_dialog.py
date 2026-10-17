"""Tests of :mod:`macos.dialog` against the real system. Skipped outside macOS."""

import pytest

import macos


def test_dialogs_close_after_their_timeout():
    try:
        assert macos.dialog.confirm("pymacos test: this closes by itself", timeout=1) is False
        assert macos.dialog.prompt("pymacos test: this closes by itself", timeout=1) is None
        macos.dialog.alert("pymacos test: this closes by itself", timeout=1)
    except macos.MacOSError as error:
        # Only a session that can't show anything (no window server: over SSH, in a service) is a skip,
        # which osascript_error says as a plain MacOSError. A CommandError, a script osascript refused
        # to compile or run, is a failure of the package: skipping it would keep CI green over it.
        if type(error) is not macos.MacOSError or "can't show a dialog" not in str(error):
            raise
        pytest.skip("dialogs can't be shown here: {}".format(error))
