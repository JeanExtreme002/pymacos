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
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

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
        score = _tag(_tagger(flat, [scheme]), 0, _PARAGRAPH, scheme)
    return float(score) if score else None


_COSINE = 0  # NLDistanceTypeCosine
_WORD = 0  # NLTokenUnitWord
_ENTITY_KINDS = {"PersonalName": "person", "PlaceName": "place", "OrganizationName": "organization"}


def _utf16_length(text: str) -> int:
    """``text``'s length as Foundation counts it, in UTF-16 units: encoded in C, not walked in Python."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _tagger(text: str, schemes: Sequence[int], language: Optional[str] = None) -> int:
    """An autoreleased ``NLTagger`` over ``text`` for the tag ``schemes``, told the ``language`` (a code) when given."""
    tagger = _objc.send(_objc.cls("NLTagger"), "alloc")
    tagger = _objc.send(tagger, "initWithTagSchemes:", _objc.nsarray_of(list(schemes)), argtypes=(_objc.id,))
    _objc.send(tagger, "autorelease")
    if text.startswith("\ufeff"):
        # NSString drops a leading byte order mark (a text read with encoding="utf-8" may start with one),
        # which would shift every position by one against the Python text: a word joiner, as wide and as
        # silent, takes its place for the tagger.
        text = "\u2060" + text[1:]
    _objc.send(tagger, "setString:", _objc.nsstring(text), argtypes=(_objc.id,), restype=None)
    if language is not None:
        whole = _files.NSRange(0, _utf16_length(text))
        _objc.send(
            tagger, "setLanguage:range:", _objc.nsstring(language), whole, argtypes=(_objc.id, _files.NSRange), restype=None
        )
    return tagger


def _tag(tagger: int, index: int, unit: int, scheme: int, token: Optional[_files.NSRange] = None) -> Optional[str]:
    """The tag of ``scheme`` at ``index`` (in UTF-16 units), the token's range written to ``token`` when given."""
    tag = _objc.send(
        tagger,
        "tagAtIndex:unit:scheme:tokenRange:",
        index,
        unit,
        scheme,
        ctypes.byref(token) if token is not None else None,
        argtypes=(NSUInteger, NSInteger, _objc.id, ctypes.c_void_p),
    )
    return _objc.pystring(tag)


def _words(tagger: int, text: str, scheme: int) -> Iterator[Tuple[int, int, int, Optional[str]]]:
    """
    The words of ``text`` as the tagger finds them, with their tag of ``scheme``: ``(index, start, end, tag)``,
    where ``index`` is where the word was asked for and ``start``/``end`` where it is, all in UTF-16 units.
    Punctuation and spaces come too, with no tag; a word's tag is read at ``index`` again for another scheme.
    """
    index, total = 0, _utf16_length(text)
    while index < total:
        token = _files.NSRange()
        tag = _tag(tagger, index, _WORD, scheme, token)
        end = token.location + token.length
        yield index, token.location, end, tag
        index = max(end, index + 1)  # always forward, even for a token of no length


def _python_indexes(text: str) -> Dict[int, int]:
    """Python's index for each UTF-16 position the tagger gives (one past the end included)."""
    return {position: index for index, position in enumerate(_objc.utf16_offsets(text))}


def _language_of(text: str, language: Optional[str]) -> str:
    return language or detect(text) or "en"


def _codes(language: str) -> List[str]:
    """
    The codes a model may be filed under for ``language``: the code itself, then its language alone.

    The models are per language, not per region (``'pt-BR'`` finds the Portuguese one), but some only
    exist under a script subtag: ``'zh-Hans'`` has word classes, ``'zh'`` has none. So the code is tried as
    it came first, and only then shortened.
    """
    primary = language.split("-")[0]
    return [language] if primary == language else [language, primary]


def _embedding(kind: str, language: str) -> Optional[int]:
    """The word or sentence ``NLEmbedding`` for ``language`` (autoreleased), or ``None`` when this Mac has none."""
    for code in _codes(language):
        model = _objc.send(
            _objc.cls("NLEmbedding"), "{}EmbeddingForLanguage:".format(kind), _objc.nsstring(code), argtypes=(_objc.id,)
        )
        if model:
            return model
    return None


def _model(kind: str, language: str) -> int:
    """The word or sentence ``NLEmbedding`` for ``language`` (autoreleased)."""
    model = _embedding(kind, language)
    if not model:
        raise NotSupportedError("no {} embedding for the language {!r} on this Mac".format(kind, language))
    return model


def similarity(first: str, second: str, *, language: Optional[str] = None) -> float:
    """
    Score how close two texts are in meaning, from -1.0 to 1.0 (higher is closer).

    Two single words are compared with a word model (a sentence model when
    one of them isn't in it, or when the language has no word model), anything
    longer with a sentence model.
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
        words = _embedding("word", code) if len(first.split()) == 1 and len(second.split()) == 1 else None
        if words:
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


def _with_scheme(language: str, scheme: str) -> Optional[str]:
    """The code of :func:`_codes` this Mac has the ``scheme`` model under, or ``None`` when it has none."""
    for code in _codes(language):
        if _has_scheme(code, scheme):
            return code
    return None


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
    wanted = _language_of(text, language)
    code = _with_scheme(wanted, "NameType")
    if code is None:
        raise NotSupportedError(
            "this Mac has no name recognition for the language {!r}".format(wanted)
        )
    scheme = ctypes.c_void_p.in_dll(library, "NLTagSchemeNameType").value
    if scheme is None:
        raise NotSupportedError("name recognition is not available on this Mac")
    # NSString indexes count UTF-16 units; map them back to Python indexes.
    offsets = _python_indexes(text)
    words: List[Tuple[int, int, str]] = []
    with _objc.autorelease_pool():
        for _, start, end, tag in _words(_tagger(text, [scheme], code), text, scheme):
            kind = _ENTITY_KINDS.get(tag or "")
            if kind and end > start:
                words.append((start, end, kind))

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
    asked = _language_of(text, language)
    code = _with_scheme(asked, "LexicalClass")
    if code is None:
        raise NotSupportedError("this Mac has no word classes for the language {!r}".format(asked))
    lexical = ctypes.c_void_p.in_dll(library, "NLTagSchemeLexicalClass").value
    lemma = ctypes.c_void_p.in_dll(library, "NLTagSchemeLemma").value
    if lexical is None or lemma is None:
        raise NotSupportedError("word classes are not available on this Mac")
    wanted = {"Noun", "Verb"} if verbs else {"Noun"}

    offsets = _python_indexes(text)
    found: List[str] = []
    seen = set()
    with _objc.autorelease_pool():
        tagger = _tagger(text, [lexical, lemma], code)
        for index, start, end, kind in _words(tagger, text, lexical):
            if end > start and kind in wanted:
                word = text[offsets[start]:offsets[end]]
                if lemmas:
                    word = _tag(tagger, index, _WORD, lemma) or word
                if word.casefold() not in seen:
                    seen.add(word.casefold())
                    found.append(word)
    return found
