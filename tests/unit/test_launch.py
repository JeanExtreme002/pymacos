"""Unit tests for :mod:`macos.launch`. They run on any platform."""

import pytest

import macos


def test_open_takes_any_url_by_default(fake_run):
    macos.open("zoommtg://zoom.us/join?confno=1")
    assert fake_run.args == ["open", "--", "zoommtg://zoom.us/join?confno=1"]


def test_open_keeps_to_the_schemes_given(fake_run, tmp_path):
    macos.open("HTTPS://python.org", schemes={"https", "http"})  # the case of a scheme doesn't matter
    assert fake_run.args == ["open", "--", "HTTPS://python.org"]

    for refused in ("zoommtg://zoom.us/join", "file:///Applications/Calculator.app", "javascript:alert(1)"):
        with pytest.raises(ValueError, match="only http, https may be opened"):
            macos.open(refused, schemes=["https", "http"])
    with pytest.raises(ValueError, match="is a file path"):
        macos.open(tmp_path, schemes=["https"])  # a file or folder counts as "file"
    assert len(fake_run.calls) == 1  # nothing refused was opened

    macos.open(tmp_path, schemes="file")
    assert fake_run.args == ["open", "--", str(tmp_path)]
