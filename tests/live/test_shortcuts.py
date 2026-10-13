"""Tests of :mod:`macos.shortcuts` against the real system. Skipped outside macOS."""

import uuid

import pytest

import macos


def test_shortcuts():
    try:
        assert isinstance(macos.shortcuts.list(), list)
    except macos.CommandTimeoutError:
        # Seen on GitHub's Intel image, whose Shortcuts service never answers: list() gives up, as it should.
        pytest.skip("the Shortcuts service didn't answer on this Mac")
    with pytest.raises(macos.ShortcutNotFoundError):
        macos.shortcuts.run("Definitely Not A Shortcut {}".format(uuid.uuid4()), timeout=60)  # never hang a run
