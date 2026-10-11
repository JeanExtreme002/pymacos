"""Tests of :mod:`macos.appearance` against the real system. Skipped outside macOS."""

import pytest

import macos

from tests.helpers import ON_GITHUB


def test_appearance():
    import re

    assert macos.appearance.mode() in ("dark", "light")
    assert macos.appearance.is_dark() == (macos.appearance.mode() == "dark")
    assert isinstance(macos.appearance.is_auto(), bool)
    assert re.fullmatch(r"#[0-9a-f]{6}", macos.appearance.accent_color())


def test_appearance_wait_for_change_times_out():
    with pytest.raises(TimeoutError):
        macos.appearance.wait_for_change(timeout=0.3, interval=0.1)


@pytest.mark.skipif(ON_GITHUB, reason="the Automation prompt would block a CI runner")
def test_set_mode_to_the_current_mode():
    current = macos.appearance.mode()

    macos.appearance.set_mode(current)

    assert macos.appearance.mode() == current
