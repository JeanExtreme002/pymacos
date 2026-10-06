# Spotlight

{mod}`macos.spotlight` searches files with Spotlight and reads their metadata.
Results come from the index Spotlight already keeps, so searches are instant
and match what the Spotlight bar finds.

## Searching

{func}`~macos.spotlight.search` takes the same queries as the Spotlight bar:

```python
import macos

macos.spotlight.search("invoice")                  # names and contents
macos.spotlight.search("kind:pdf invoice")         # only PDFs
macos.spotlight.search("kind:image date:today")    # images from today
```

It returns a list of {class}`pathlib.Path`. Narrow it down with `folder`
(searched recursively) and `limit`:

```python
macos.spotlight.search("kind:pdf", folder="~/Documents", limit=10)
```

## Searching by file name

{func}`~macos.spotlight.search_name` matches the file name, extension included,
ignoring case and accents:

```python
macos.spotlight.search_name("report")                 # report.pdf, Report 2026.docx, ...
macos.spotlight.search_name("Calculator.app", folder="/System/Applications")
```

The name is matched literally: characters such as `*` or `"` have no special
meaning.

## Metadata queries

For precise searches, use Spotlight's metadata attributes. The names are the
keys that {func}`~macos.spotlight.metadata` returns:

```python
macos.spotlight.search("kMDItemPixelHeight > 2000")                  # large images
macos.spotlight.search('kMDItemContentType == "com.adobe.pdf"')
macos.spotlight.search("kMDItemFSSize > 1000000000", folder="~")     # files over 1 GB
```

A malformed query raises `ValueError`. A query starting with `-` is searched
for as a query, never taken as one of `mdfind`'s options.

## Reading metadata

{func}`~macos.spotlight.metadata` returns everything Spotlight knows about a
file, as a dict:

```python
data = macos.spotlight.metadata("photo.jpg")
data["kMDItemPixelWidth"]                     # 4032
data["kMDItemContentType"]                    # 'public.jpeg'
data["kMDItemContentCreationDate"]            # datetime.datetime(2026, 9, 1, 14, 3, 12)
```

Dates are {class}`datetime.datetime` objects in UTC, without a time zone. Files that Spotlight hasn't
indexed, such as those in folders it skips, only have the basic
`kMDItemFS...` attributes (name, size, dates).

## Reference

- {func}`macos.spotlight.search`
- {func}`macos.spotlight.search_name`
- {func}`macos.spotlight.metadata`
