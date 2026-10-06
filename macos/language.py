# -*- coding: utf-8 -*-

"""
Understand text, offline: its language, its sentiment, its meaning, and the
names and keywords in it.

::

    macos.language.detect("Hola, ¿cómo estás?")    # 'es'
    macos.language.guess("Hola, ¿cómo estás?")     # [('es', 1.0), ('pt', 0.0), ...]
    macos.language.sentiment("I love this!")       # 1.0

Uses Apple's NaturalLanguage framework: nothing to install, no network and
no permission.
"""

import ctypes
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional, Tuple

from . import _files, _objc
from ._objc import NSInteger, NSUInteger
from ._system import framework
from .errors import NotSupportedError

__all__ = ["detect", "guess", "sentiment", "similarity", "embedding", "entities", "keywords", "Entity"]

_PARAGRAPH = 2  # NLTokenUnitParagraph


@lru_cache(maxsize=None)
def _load() -> ctypes.CDLL:
    framework("Foundation")
    return framework("NaturalLanguage")


def _recognizer(text: str) -> int:
    recognizer = _objc.new("NLLanguageRecognizer")
    _objc.send(recognizer, "processString:", _objc.nsstring(text), argtypes=(_objc.id,), restype=None)
    return recognizer


def detect(text: str) -> Optional[str]:
    """
    Return the most likely language of ``text`` as an ISO code (``'en'``, ``'fr'``, ``'zh-Hans'``...).

    Returns ``None`` when there's nothing to detect. A few words are enough,
    but a single word is often guessed wrong: check :func:`guess` for how sure
    the answer is.
    """
    _load()
    if not text.strip():
        return None
    with _objc.autorelease_pool():
        return _objc.pystring(_objc.send(_recognizer(text), "dominantLanguage"))


def guess(text: str, *, limit: int = 3) -> List[Tuple[str, float]]:
    """Return the ``limit`` most likely languages of ``text``, with their probability (0.0 to 1.0)."""
    if limit <= 0:
        raise ValueError("limit must be positive, not {}".format(limit))
    _load()
    if not text.strip():
        return []
    with _objc.autorelease_pool():
        hypotheses = _objc.send(_recognizer(text), "languageHypothesesWithMaximum:", limit, argtypes=(NSUInteger,))
        found = []
        for key in _objc.nsarray(_objc.send(hypotheses, "allKeys")):
            value = _objc.send(hypotheses, "objectForKey:", key, argtypes=(_objc.id,))
            probability = float(_objc.send(value, "doubleValue", restype=ctypes.c_double))
            found.append((_objc.pystring(key) or "", round(probability, 4)))
    return sorted(found, key=lambda pair: -pair[1])


def sentiment(text: str) -> Optional[float]:
    """
    Score how positive ``text`` sounds, from -1.0 (very negative) to 1.0 (very positive).

    Returns ``None`` for empty text. The score is a rough signal, best for
    comparing texts such as reviews or messages: a neutral sentence won't
    always come out at exactly 0.
    """
    library = _load()
    # The tagger scores one paragraph at a time: treat the text as one.
    flat = " ".join(text.split())
    if not flat:
        return None
    try:
        scheme = ctypes.c_void_p.in_dll(library, "NLTagSchemeSentimentScore").value
    except ValueError:  # NaturalLanguage without sentiment support (before macOS 10.15)
        return None
    if scheme is None:
        return None
    with _objc.autorelease_pool():
        tagger = _objc.send(_objc.cls("NLTagger"), "alloc")
        tagger = _objc.send(tagger, "initWithTagSchemes:", _objc.nsarray_of([scheme]), argtypes=(_objc.id,))
        _objc.send(tagger, "autorelease")
        _objc.send(tagger, "setString:", _objc.nsstring(flat), argtypes=(_objc.id,), restype=None)
        tag = _objc.send(
            tagger,
            "tagAtIndex:unit:scheme:tokenRange:",
            0,
            _PARAGRAPH,
            scheme,
            None,
            argtypes=(NSUInteger, NSInteger, _objc.id, ctypes.c_void_p),
        )
        score = _objc.pystring(tag)
    return float(score) if score else None


_COSINE = 0  # NLDistanceTypeCosine
_WORD = 0  # NLTokenUnitWord
_ENTITY_KINDS = {"PersonalName": "person", "PlaceName": "place", "OrganizationName": "organization"}


def _language_of(text: str, language: Optional[str]) -> str:
    code = language or detect(text) or "en"
    return code.split("-")[0]  # embeddings are per language, not per region


def _model(kind: str, language: str) -> int:
    """The word or sentence ``NLEmbedding`` for ``language`` (autoreleased)."""
    model = _objc.send(
        _objc.cls("NLEmbedding"), "{}EmbeddingForLanguage:".format(kind), _objc.nsstring(language), argtypes=(_objc.id,)
    )
    if not model:
        raise NotSupportedError("no {} embedding for the language {!r} on this Mac".format(kind, language))
    return model


def similarity(first: str, second: str, *, language: Optional[str] = None) -> float:
    """
    Score how close two texts are in meaning, from -1.0 to 1.0 (higher is closer).

    Two single words are compared with a word model (a sentence model when
    one of them isn't in it), anything longer with a sentence model.
    ``language`` (``'en'``, ``'fr'``...) is detected when
    omitted, but detection needs a few words: for single words or very short
    texts, pass it (``similarity("car", "automobile", language="en")``), or
    they may be read as another language. Like :func:`entities`, it raises
    :class:`~macos.errors.NotSupportedError` for a language whose model this
    Mac doesn't have. The scores are for comparing: ``similarity(q, a)`` against
    ``similarity(q, b)`` says which of ``a`` and ``b`` is closer to ``q``,
    while a value alone means little. Opposites (``'happy'``/``'sad'``) often
    score as related, since they appear in similar contexts.
    """
    _load()
    code = _language_of(first + " " + second, language)
    with _objc.autorelease_pool():
        kind = "sentence"
        if len(first.split()) == 1 and len(second.split()) == 1:
            words = _model("word", code)
            known = all(
                _objc.send(words, "containsString:", _objc.nsstring(word), argtypes=(_objc.id,), restype=_objc.BOOL)
                for word in (first.strip(), second.strip())
            )
            if known:
                kind = "word"
        model = _model(kind, code)
        distance = _objc.send(
            model,
            "distanceBetweenString:andString:distanceType:",
            _objc.nsstring(first.strip() if kind == "word" else first),
            _objc.nsstring(second.strip() if kind == "word" else second),
            _COSINE,
            argtypes=(_objc.id, _objc.id, NSInteger),
            restype=ctypes.c_double,
        )
    # A cosine distance: 0 for the same meaning, 2 for the opposite one.
    return round(1.0 - float(distance), 4)


def embedding(text: str, *, language: Optional[str] = None) -> List[float]:
    """
    Return the sentence embedding of ``text``: a vector of numbers that represents its meaning.

    Store vectors to search many texts by meaning (compare them with cosine
    similarity). All texts must use the same ``language`` to be comparable;
    it's detected when omitted.
    """
    _load()
    code = _language_of(text, language)
    with _objc.autorelease_pool():
        vector = _objc.send(_model("sentence", code), "vectorForString:", _objc.nsstring(text), argtypes=(_objc.id,))
        if not vector:
            raise ValueError("no embedding for this text")
        return [float(_objc.send(value, "doubleValue", restype=ctypes.c_double)) for value in _objc.nsarray(vector)]


@dataclass(frozen=True)
class Entity:
    """A name found in a text."""

    text: str
    kind: str
    """``'person'``, ``'place'`` or ``'organization'``."""
    start: int
    """Where it begins in the text, as a Python string index."""


def _has_scheme(language: str, scheme: str) -> bool:
    """Whether this Mac has the model behind a tag scheme (``"NameType"``, ``"LexicalClass"``...) for ``language``."""
    with _objc.autorelease_pool():
        schemes = _objc.send(
            _objc.cls("NLTagger"),
            "availableTagSchemesForUnit:language:",
            _WORD,
            _objc.nsstring(language),
            argtypes=(NSInteger, _objc.id),
        )
        return scheme in {_objc.pystring(found) for found in _objc.nsarray(schemes)}


def _has_names(language: str) -> bool:
    return _has_scheme(language, "NameType")


def entities(text: str, *, language: Optional[str] = None) -> List[Entity]:
    """
    Find the names of people, places and organizations in a text::

        macos.language.entities("Tim Cook, the CEO of Apple, visited Paris yesterday.")
        # [Entity(text='Tim Cook', kind='person', start=0),
        #  Entity(text='Apple', kind='organization', start=21),
        #  Entity(text='Paris', kind='place', start=36)]

    It's a statistical model: common names are found reliably, unusual ones
    can be missed or mislabelled. It relies on capital letters, so names typed
    in lowercase ("rob", as in chat messages) are usually missed.
    ``language`` is detected when omitted.

    The model is per language, and macOS only has the ones for the languages
    it uses: for others it raises :class:`~macos.errors.NotSupportedError`
    rather than silently finding nothing. Adding the language in System
    Settings › General › Language & Region makes macOS download it.
    """
    library = _load()
    if not text.strip():
        return []
    code = _language_of(text, language)
    if not _has_names(code):
        raise NotSupportedError("this Mac has no name recognition for the language {!r}".format(code))
    scheme = ctypes.c_void_p.in_dll(library, "NLTagSchemeNameType").value
    if scheme is None:
        raise NotSupportedError("name recognition is not available on this Mac")
    # NSString indexes count UTF-16 units; map them back to Python indexes.
    units = text.encode("utf-16-le")
    offsets = {}
    position = 0
    for index, char in enumerate(text):
        offsets[position] = index
        position += len(char.encode("utf-16-le")) // 2
    offsets[position] = len(text)

    words: List[Tuple[int, int, str]] = []
    with _objc.autorelease_pool():
        tagger = _objc.send(_objc.cls("NLTagger"), "alloc")
        tagger = _objc.send(tagger, "initWithTagSchemes:", _objc.nsarray_of([scheme]), argtypes=(_objc.id,))
        _objc.send(tagger, "autorelease")
        _objc.send(tagger, "setString:", _objc.nsstring(text), argtypes=(_objc.id,), restype=None)
        whole = _files.NSRange(0, len(units) // 2)
        _objc.send(tagger, "setLanguage:range:", _objc.nsstring(code), whole, argtypes=(_objc.id, _files.NSRange), restype=None)
        index, total = 0, len(units) // 2
        while index < total:
            found = _files.NSRange()
            tag = _objc.send(
                tagger,
                "tagAtIndex:unit:scheme:tokenRange:",
                index,
                _WORD,
                scheme,
                ctypes.byref(found),
                argtypes=(NSUInteger, NSInteger, _objc.id, ctypes.c_void_p),
            )
            kind = _ENTITY_KINDS.get(_objc.pystring(tag) or "")
            if kind and found.length:
                words.append((found.location, found.location + found.length, kind))
            index = max(found.location + found.length, index + 1)

    # Join neighbouring words of the same kind ("São" + "Paulo").
    merged: List[Tuple[int, int, str]] = []
    for start, end, kind in words:
        if merged and merged[-1][2] == kind:
            gap = text[offsets.get(merged[-1][1], 0) : offsets.get(start, 0)]
            if gap.strip() == "":
                merged[-1] = (merged[-1][0], end, kind)
                continue
        merged.append((start, end, kind))
    return [
        Entity(text=text[offsets[start] : offsets[end]], kind=kind, start=offsets[start]) for start, end, kind in merged
    ]


def keywords(text: str, *, language: Optional[str] = None, verbs: bool = False, lemmas: bool = False) -> List[str]:
    """
    Return the main words of a text: its nouns (names included), in order, without repeats.

    ::

        macos.language.keywords("The new MacBook Pro has amazing battery life and gorgeous displays.")
        # ['MacBook', 'Pro', 'battery', 'life', 'displays']

    ``verbs=True`` adds the verbs. ``lemmas=True`` gives each word's base form
    (``'displays'`` becomes ``'display'``, ``'comeu'`` becomes ``'comer'``),
    which groups the variations of a word together. It's a statistical model:
    now and then a common word is taken for a noun. ``language`` is detected
    when omitted, and :class:`~macos.errors.NotSupportedError` is raised for a
    language whose model this Mac doesn't have.
    """
    library = _load()
    if not text.strip():
        return []
    code = _language_of(text, language)
    if not _has_scheme(code, "LexicalClass"):
        raise NotSupportedError("this Mac has no word classes for the language {!r}".format(code))
    lexical = ctypes.c_void_p.in_dll(library, "NLTagSchemeLexicalClass").value
    lemma = ctypes.c_void_p.in_dll(library, "NLTagSchemeLemma").value
    if lexical is None or lemma is None:
        raise NotSupportedError("word classes are not available on this Mac")
    wanted = {"Noun", "Verb"} if verbs else {"Noun"}

    units = text.encode("utf-16-le")
    found: List[str] = []
    seen = set()
    with _objc.autorelease_pool():
        tagger = _objc.send(_objc.cls("NLTagger"), "alloc")
        tagger = _objc.send(tagger, "initWithTagSchemes:", _objc.nsarray_of([lexical, lemma]), argtypes=(_objc.id,))
        _objc.send(tagger, "autorelease")
        _objc.send(tagger, "setString:", _objc.nsstring(text), argtypes=(_objc.id,), restype=None)
        total = len(units) // 2
        _objc.send(
            tagger,
            "setLanguage:range:",
            _objc.nsstring(code),
            _files.NSRange(0, total),
            argtypes=(_objc.id, _files.NSRange),
            restype=None,
        )
        index = 0
        while index < total:
            token = _files.NSRange()
            kind = _objc.send(
                tagger,
                "tagAtIndex:unit:scheme:tokenRange:",
                index,
                _WORD,
                lexical,
                ctypes.byref(token),
                argtypes=(NSUInteger, NSInteger, _objc.id, ctypes.c_void_p),
            )
            if token.length and _objc.pystring(kind) in wanted:
                word = units[token.location * 2 : (token.location + token.length) * 2].decode("utf-16-le")
                if lemmas:
                    base = _objc.send(
                        tagger,
                        "tagAtIndex:unit:scheme:tokenRange:",
                        index,
                        _WORD,
                        lemma,
                        None,
                        argtypes=(NSUInteger, NSInteger, _objc.id, ctypes.c_void_p),
                    )
                    word = _objc.pystring(base) or word
                if word.casefold() not in seen:
                    seen.add(word.casefold())
                    found.append(word)
            index = max(token.location + token.length, index + 1)
    return found
