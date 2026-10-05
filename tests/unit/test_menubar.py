"""Unit tests for :mod:`macos.menubar`. They run on any platform and create no menu bar items."""

import pytest

import macos
from macos import menubar


def test_item_needs_a_title_or_an_icon():
    with pytest.raises(ValueError, match="title, an icon, or both"):
        macos.menubar.Item()


@pytest.mark.parametrize("seconds", [0, -1])
def test_every_needs_a_positive_interval(seconds):
    with pytest.raises(ValueError, match="positive"):
        macos.menubar.every(seconds, lambda: None)


def test_timers_skip_missed_ticks_instead_of_bursting():
    timer = macos.menubar.every(1.0, lambda: None)
    try:
        timer._next = 10.0
        assert menubar._due_timers(9.9) == []
        assert menubar._due_timers(10.0) == [timer]
        assert timer._next == 11.0
        # Busy for 5 s: one call now, the next a full interval later.
        assert menubar._due_timers(16.0) == [timer]
        assert timer._next == 17.0
        assert menubar._due_timers(16.1) == []  # not again at the next slice
        assert menubar._due_timers(17.0) == [timer]
        assert timer._next == 18.0
    finally:
        timer.cancel()
    assert timer not in menubar._timers
    assert menubar._due_timers(1e9) == []


def test_quit_stops_run_from_anywhere():
    menubar._quit.clear()
    macos.menubar.quit()
    assert menubar._quit.is_set()
    menubar._quit.clear()
