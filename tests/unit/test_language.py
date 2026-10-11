"""Unit tests for :mod:`macos.language`. They run on any platform."""

import pytest

import macos


def test_language_argument_checks():
    with pytest.raises(ValueError):
        macos.language.guess("x", limit=0)


def test_language_codes_are_tried_as_given_then_shortened():
    assert macos.language._codes("zh-Hans") == ["zh-Hans", "zh"]
    assert macos.language._codes("pt-BR") == ["pt-BR", "pt"]
    assert macos.language._codes("en") == ["en"]


def test_language_model_found_under_the_script_subtag(monkeypatch):
    # macOS files the Chinese word classes under "zh-Hans", not "zh": the code is tried as it came first.
    schemes = {("zh-Hans", "LexicalClass"), ("pt", "NameType")}
    monkeypatch.setattr(macos.language, "_has_scheme", lambda code, scheme: (code, scheme) in schemes)

    assert macos.language._with_scheme("zh-Hans", "LexicalClass") == "zh-Hans"
    assert macos.language._with_scheme("pt-BR", "NameType") == "pt"  # per language, not per region
    assert macos.language._with_scheme("zh-Hans", "NameType") is None
    assert macos.language._with_scheme("ja", "LexicalClass") is None
