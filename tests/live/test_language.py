"""Tests of :mod:`macos.language` against the real system. Skipped outside macOS."""

import pytest

import macos


def test_language():
    assert macos.language.detect("Olá, tudo bem com você? Hoje o dia está lindo.") == "pt"
    assert macos.language.detect("   ") is None
    top, probability = macos.language.guess("Bonjour tout le monde, comment allez-vous ?")[0]
    assert top == "fr" and 0 < probability <= 1

    assert macos.language.sentiment("I love this, it is wonderful!") > 0.5
    assert macos.language.sentiment("This is terrible and I hate it.") < -0.5
    assert macos.language.sentiment("") is None


def test_similarity_and_embeddings():
    # Two words are too short to detect their language: say it.
    assert macos.language.similarity("car", "automobile", language="en") > macos.language.similarity(
        "car", "banana", language="en"
    )
    try:  # macOS only has the models for the languages it uses (CI runners: English)
        assert macos.language.similarity("carro", "automóvel", language="pt") > macos.language.similarity(
            "carro", "banana", language="pt"
        )
    except macos.NotSupportedError:
        pass
    question = "How do I change my password?"
    assert macos.language.similarity(question, "I forgot the password of my account") > macos.language.similarity(
        question, "What time does the store open?"
    )
    vector = macos.language.embedding("I like dogs", language="en")
    assert len(vector) > 100 and vector == macos.language.embedding("I like dogs", language="en")


def test_entities():
    found = macos.language.entities("Yesterday Tim Cook visited New York with engineers from Apple.")
    assert ("Tim Cook", "person", 10) in [(entity.text, entity.kind, entity.start) for entity in found]
    assert "New York" in [entity.text for entity in found if entity.kind == "place"]
    assert macos.language.entities("   ") == []

    try:  # accents and positions in a non-English text, where the model is installed
        found = macos.language.entities("Tim Cook visitou São Paulo com a Apple ontem 🙂.", language="pt")
    except macos.NotSupportedError:
        return
    assert ("São Paulo", "place", 17) in [(entity.text, entity.kind, entity.start) for entity in found]


def test_entities_without_the_language_model():
    with pytest.raises(macos.NotSupportedError):
        macos.language.entities("東京でティム・クックに会いました", language="ja")


def test_keywords_under_a_script_subtag():
    # macOS files Chinese word classes under "zh-Hans", which is also what detect() answers: no "zh" model.
    if not macos.language._has_scheme("zh-Hans", "LexicalClass"):
        pytest.skip("this Mac has no Chinese word classes")
    text = "今天天气很好，我们去公园散步吧。"
    assert macos.language.detect(text) == "zh-Hans"
    assert "公园" in macos.language.keywords(text)


def test_keywords():
    text = "The new MacBook Pro has amazing battery life and the displays are gorgeous."

    assert macos.language.keywords(text, language="en") == ["MacBook", "Pro", "battery", "life", "displays"]
    assert "display" in macos.language.keywords(text, language="en", lemmas=True)
    assert "has" in macos.language.keywords(text, language="en", verbs=True)
    assert macos.language.keywords("   ") == []
    with pytest.raises(macos.NotSupportedError):
        macos.language.keywords("東京でティム・クックに会いました", language="ja")
