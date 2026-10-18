"""Unit tests for :mod:`macos.volume`. They run on any platform."""

import pytest

import macos


@pytest.mark.parametrize("output, expected", [("88\n", 88), ("0\n", 0), ("missing value\n", None)])
def test_volume_get(fake_run, output, expected):
    fake_run.stdout = output

    assert macos.volume.get() == expected
    assert fake_run.args == ["osascript", "-e", "output volume of (get volume settings)"]


@pytest.mark.parametrize("output, expected", [("true\n", True), ("false\n", False), ("missing value\n", None)])
def test_volume_is_muted(fake_run, output, expected):
    fake_run.stdout = output

    assert macos.volume.is_muted() is expected


def test_volume_set_mute_unmute(fake_run):
    macos.volume.set(30)
    assert fake_run.args == ["osascript", "-e", "set volume output volume 30"]
    macos.volume.mute()
    assert fake_run.args == ["osascript", "-e", "set volume output muted true"]
    macos.volume.unmute()
    assert fake_run.args == ["osascript", "-e", "set volume output muted false"]
    assert all(call["timeout"] for call in fake_run.calls)  # a wedged audio daemon doesn't hang the caller


@pytest.mark.parametrize(
    "level, error",
    [(101, ValueError), (-1, ValueError), (True, TypeError), (50.5, TypeError), ("50", TypeError)],
)
def test_volume_set_rejects_bad_levels(level, error):
    with pytest.raises(error):
        macos.volume.set(level)


def test_volume_set_formats_a_plain_int(fake_run):
    class Odd(int):
        def __format__(self, spec):
            return '10\ndo shell script "echo pwned"'

    macos.volume.set(Odd(10))

    assert fake_run.args == ["osascript", "-e", "set volume output volume 10"]
