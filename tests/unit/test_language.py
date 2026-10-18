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


def test_language_sentiment_without_a_score_is_none():
    # The tagger tags text it can't score "Other" ("!!!", emoji only, a language without the model).
    assert macos.language._score("Other") is None
    assert macos.language._score(None) is None
    assert macos.language._score("") is None
    assert macos.language._score("-0.6") == -0.6
    assert macos.language._score("1") == 1.0


@pytest.mark.parametrize("first, second", [("", "hello world"), ("hello", "   "), ("", "")])
def test_language_similarity_of_an_empty_text_raises(first, second):
    with pytest.raises(ValueError, match="nothing to compare"):
        macos.language.similarity(first, second, language="en")


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_language_embedding_of_an_empty_text_raises(text):
    with pytest.raises(ValueError, match="text is empty"):
        macos.language.embedding(text, language="en")


def _offsets(text):
    return {index: index for index in range(len(text) + 1)}  # ASCII: UTF-16 and Python indexes agree


def test_language_entities_joined_across_spaces_only():
    text = "Tim Cook\nSatya Nadella\tSundar  Pichai"
    words = [(0, 3, "person"), (4, 8, "person"), (9, 14, "person"), (15, 22, "person"), (23, 29, "person"),
             (31, 37, "person")]
    assert macos.language._merge(text, _offsets(text), words) == [
        (0, 8, "person"), (9, 22, "person"), (23, 37, "person")
    ]


def test_language_entities_of_different_kinds_stay_apart():
    text = "Apple Paris"
    words = [(0, 5, "organization"), (6, 11, "place")]
    assert macos.language._merge(text, _offsets(text), words) == words
