"""Unit tests for the test suite's own switches and the Makefile and workflows around it. They run on any platform."""

import importlib
import re
from pathlib import Path

import pytest

from tests import helpers

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "On", " 1 "])
def test_a_switch_is_on_when_set_to_say_so(monkeypatch, value):
    monkeypatch.setenv("PYMACOS_EXAMPLE_TESTS", value)
    assert helpers.switch("PYMACOS_EXAMPLE_TESTS") is True


@pytest.mark.parametrize("value", ["", "0", "false", "False", "no", "off", " 0 "])
def test_a_switch_written_to_say_off_stays_off(monkeypatch, value):
    monkeypatch.setenv("PYMACOS_EXAMPLE_TESTS", value)
    assert helpers.switch("PYMACOS_EXAMPLE_TESTS") is False


def test_an_unset_switch_is_off(monkeypatch):
    monkeypatch.delenv("PYMACOS_EXAMPLE_TESTS", raising=False)
    assert helpers.switch("PYMACOS_EXAMPLE_TESTS") is False


def test_a_switch_neither_on_nor_off_is_off_with_a_warning(monkeypatch):
    monkeypatch.setenv("PYMACOS_EXAMPLE_TESTS", "enabled")
    with pytest.warns(UserWarning, match="PYMACOS_EXAMPLE_TESTS='enabled'"):
        assert helpers.switch("PYMACOS_EXAMPLE_TESTS") is False


@pytest.mark.parametrize("value, on", [("true", True), ("1", False), ("false", False), ("", False)])
def test_only_github_s_own_value_counts_as_its_runners(monkeypatch, value, on):
    monkeypatch.setenv("GITHUB_ACTIONS", value)
    try:
        assert importlib.reload(helpers).ON_GITHUB is on
    finally:
        monkeypatch.undo()
        importlib.reload(helpers)


def test_the_settings_switch_set_to_zero_skips_the_settings_tests(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("PYMACOS_SETTINGS_TESTS", "0")
    monkeypatch.setenv("PYMACOS_CAPTURE_TESTS", "false")
    try:
        reloaded = importlib.reload(helpers)
        assert reloaded.SETTINGS.args == (True,)
        assert reloaded.CAPTURE.args == (True,)
    finally:
        monkeypatch.undo()
        importlib.reload(helpers)


def test_make_test_coverage_holds_the_unit_gate_ci_applies():
    makefile = (_ROOT / "Makefile").read_text()
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    local = re.search(r"^COVERAGE_MIN = (\d+)$", makefile, re.MULTILINE)
    assert local, "the Makefile names no COVERAGE_MIN"
    assert "--cov-fail-under=$(COVERAGE_MIN)" in makefile
    unit = re.search(r"pytest tests/unit .*--cov-fail-under=(\d+)", workflow)
    assert unit and unit.group(1) == local.group(1)


def test_the_release_workflow_refuses_a_tag_off_main():
    workflow = (_ROOT / ".github" / "workflows" / "publish.yml").read_text()
    assert "fetch-depth: 0" in workflow
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" FETCH_HEAD' in workflow
