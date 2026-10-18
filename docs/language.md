# Language

{mod}`macos.language` detects the language and the sentiment of a text,
compares meanings, and finds the names and keywords in it, with Apple's
NaturalLanguage framework. It runs on the Mac, offline.

```python
import macos

macos.language.detect("Hola, ¿cómo estás?")  # 'es'
macos.language.sentiment("I love this!")     # 1.0
```

## Detecting the language

{func}`~macos.language.detect` returns an ISO code such as `'en'`, `'fr'`,
`'es'` or `'zh-Hans'`, or `None` for empty text. {func}`~macos.language.guess`
shows how sure it is, for the `limit` most likely languages (3 by default):

```python
macos.language.guess("Bonjour tout le monde")
# [('fr', 0.99), ('ca', 0.004), ('it', 0.002)]
```

A sentence is plenty, but a single word is often guessed wrong: check the
probability before trusting it.

## Sentiment

{func}`~macos.language.sentiment` scores how positive a text sounds, from
`-1.0` (very negative) to `1.0` (very positive), or `None` when there's
nothing to score:

```python
macos.language.sentiment("This is terrible and I hate it.")   # -1.0
macos.language.sentiment("Adorei, ficou ótimo!")              # 0.8
```

It's a rough signal, best for comparing texts such as reviews or messages: a
neutral sentence won't always score exactly 0. Text with no words in it
(`"!!!"`, `"12345"`, emoji only) and languages the sentiment model doesn't
cover, such as Chinese, Japanese or Russian, give `None`.

## Similar meanings

{func}`~macos.language.similarity` scores how close two texts are in meaning,
from -1.0 to 1.0. Compare scores with each other: a value alone means little.

```python
question = "How do I change my password?"
macos.language.similarity(question, "I forgot the password of my account")   # 0.10
macos.language.similarity(question, "What time does the store open?")        # 0.04
```

Two single words use a word model (or the sentence model, when one of them
isn't in it); anything longer, a sentence model. Pass
`language` for single words or very short texts: detecting it needs a few
words, and "car automobile" alone reads as French.

```python
macos.language.similarity("car", "automobile", language="en")   # 0.13
macos.language.similarity("car", "banana", language="en")       # -0.26
```

Opposites such as "happy" and "sad" often score as related, because they show
up in similar sentences. An empty or blank text raises `ValueError`: there's
nothing to compare it with.

## Embeddings

{func}`~macos.language.embedding` turns a text into a vector of numbers that
represents its meaning. Store the vectors of many texts to search them by
meaning, offline:

```python
import math

def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.hypot(*a) * math.hypot(*b))

notes = ["Buy milk and eggs", "Call the dentist", "Renew the passport"]
vectors = [macos.language.embedding(note, language="en") for note in notes]
query = macos.language.embedding("groceries", language="en")

print(max(zip(notes, vectors), key=lambda pair: cosine(query, pair[1]))[0])
```

Only vectors from the same language can be compared. An empty or blank text
raises `ValueError`, so leave blank notes out before indexing:
`[note for note in notes if note.strip()]`.

## Names of people, places and organizations

```python
macos.language.entities("Tim Cook, the CEO of Apple, visited Paris yesterday.")
# [Entity(text='Tim Cook', kind='person', start=0),
#  Entity(text='Apple', kind='organization', start=21),
#  Entity(text='Paris', kind='place', start=36)]
```

`start` is where the name begins in the text. Names written one after the
other with only spaces between them can come back as one ("Paris London
Berlin"); a comma, a newline or a tab keeps them apart. It's a statistical model: common
names are found reliably, unusual ones can be missed. It relies on capital
letters, so names typed in lowercase ("rob", as in chat messages) are usually
missed.

Only proper names count: in "we had dinner at the restaurant", neither
"dinner" nor "restaurant" is an entity. For the main words of a text, see
keywords below.

## Keywords

{func}`~macos.language.keywords` returns the nouns of a text (names included),
in order and without repeats:

```python
macos.language.keywords("The new MacBook Pro has amazing battery life and gorgeous displays.")
# ['MacBook', 'Pro', 'battery', 'life', 'displays']
```

`lemmas=True` gives each word's base form, so variations of a word count once,
and `verbs=True` adds the verbs:

```python
text = "The cats ate and then the cat slept on the sofas"
macos.language.keywords(text)                           # ['cats', 'cat', 'sofas']
macos.language.keywords(text, lemmas=True)              # ['cat', 'sofa']
macos.language.keywords(text, lemmas=True, verbs=True)  # ['cat', 'eat', 'sleep', 'sofa']
```

It's a statistical model: now and then a common word, such as a pronoun, is
taken for a noun.

## Languages on this Mac

macOS keeps language models only for the languages it uses, and downloads the
others on demand. {func}`~macos.language.similarity`,
{func}`~macos.language.embedding`, {func}`~macos.language.entities` and
{func}`~macos.language.keywords` raise
{class}`~macos.NotSupportedError` for a language whose model isn't on the Mac,
instead of returning a misleading result. 

Adding the language in System Settings › General › Language & Region makes macOS download it. Detecting the
language works for every language, always.

## Reference

- {func}`macos.language.detect`
- {func}`macos.language.guess`
- {func}`macos.language.sentiment`
- {func}`macos.language.similarity`
- {func}`macos.language.embedding`
- {func}`macos.language.entities`
- {func}`macos.language.keywords`
- {class}`macos.language.Entity`
