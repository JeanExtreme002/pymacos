"""Tests of :mod:`macos.shortcuts` against the real system. Skipped outside macOS."""

import uuid

import pytest

import macos


def test_shortcuts():
    assert isinstance(macos.shortcuts.list(), list)
    with pytest.raises(macos.ShortcutNotFoundError):
        macos.shortcuts.run("Definitely Not A Shortcut {}".format(uuid.uuid4()), timeout=60)  # never hang a run
