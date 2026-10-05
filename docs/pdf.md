# PDF

{mod}`macos.pdf` reads, merges, splits, rotates, encrypts and redacts PDFs, and
makes them from images, with PDFKit, the framework behind Preview. Pages are numbered from 1, like in Preview.

```python
import macos

macos.pdf.page_count("report.pdf")            # 12
macos.pdf.text("report.pdf")                  # all the text
macos.pdf.text("report.pdf", pages=[1, 2])    # only some pages
```

## Document details

{func}`~macos.pdf.metadata` returns what the PDF records about itself:

```python
details = macos.pdf.metadata("report.pdf")
details.title      # 'Quarterly report'
details.author     # 'Alice'
details.created    # datetime.datetime(2024, 5, 1, 10, 30, tzinfo=...)
```

The {class}`~macos.pdf.Metadata` also has the `subject`, the `keywords`, the
`modified` date, the `creator` (the app it was made in) and the `producer`
(the software that wrote the PDF). Missing fields are `None`.

## Merging and splitting

```python
macos.pdf.merge(["january.pdf", "february.pdf"], "q1.pdf")
macos.pdf.extract("report.pdf", [1], "cover.pdf")            # one page
macos.pdf.extract("report.pdf", [3, 1, 2], "reordered.pdf")
```

{func}`~macos.pdf.extract` keeps the pages in the order you give, so it also
reorders pages.

## Rotating pages

```python
macos.pdf.rotate("scan.pdf", 90, "scan.pdf")               # every page, clockwise
macos.pdf.rotate("scan.pdf", -90, "fixed.pdf", pages=[2])  # only page 2, counter-clockwise
```

The output can be the input itself: it's replaced only once the new file is
written. Every function here writes that way: the new file goes beside the
output (its folder is made if missing) and is moved in place when complete,
so a failure leaves nothing half-written. A file it replaces keeps its
permissions; a new one gets the usual ones, as any file you save.

## Watermarks

{func}`~macos.pdf.watermark` writes a text across every page, diagonally and
see-through:

```python
macos.pdf.watermark("contract.pdf", "DRAFT", "contract-draft.pdf")
macos.pdf.watermark("id.pdf", "Only for Acme Inc.", "id-acme.pdf", color="#d00000", opacity=0.3)
```

The text is sized to fit each page. The pages keep their look and their text,
but not their links or form fields.

## Making PDFs smaller

{func}`~macos.pdf.compress` works like Preview's *Export › Reduce File Size*:
images are scaled down and compressed again, which makes PDFs of scans and
photos several times smaller, while text stays sharp.

```python
macos.pdf.compress("scan.pdf", "scan-small.pdf")
```

Photos lose detail, so keep the original. A PDF with only text has nothing to
shrink: then the output is a copy of it, never a bigger file. An encrypted PDF
(opened with `password=`) can't be copied as it is, since the result isn't
encrypted: the output is then the smaller of the compressed PDF and the
decrypted one.

## Grayscale

{func}`~macos.pdf.grayscale` saves a copy in shades of gray, for printing
without color, with the *Gray Tone* filter that ships with macOS:

```python
macos.pdf.grayscale("slides.pdf", "slides-print.pdf")
```

## Rendering pages

{func}`~macos.pdf.render` draws a page as PNG bytes. `size` is the longest side
in pixels (up to 4096):

```python
from pathlib import Path

image = macos.pdf.render("report.pdf", page=1, size=1600)
Path("cover.png").write_bytes(image)
```

## PDFs from images

{func}`~macos.pdf.from_images` makes a PDF with one page per image, in order.
Each page takes its image's size:

```python
macos.pdf.from_images(["page1.jpg", "page2.heic"], "document.pdf")
```

Images can also be bytes, so photos of paper become a PDF scan with
{func}`macos.vision.scan_document`:

```python
pages = [macos.vision.scan_document(photo) for photo in ["receipt.jpg", "contract.jpg"]]
macos.pdf.from_images(pages, "scan.pdf")
```

## Scanned PDFs

Scanned documents are images with no text layer, so {func}`~macos.pdf.text`
returns empty text for them. {func}`~macos.pdf.ocr` makes them searchable: it
reads each page with [Vision](vision.md) and adds the text, invisibly, over the
words:

```python
macos.pdf.ocr("scan.pdf", "scan-searchable.pdf")
macos.pdf.text("scan-searchable.pdf")   # the scan's text
```

The pages look the same, and their text can be selected, copied and searched,
in Preview and Spotlight too. Pages that already have text aren't read again,
unless `redo=True`. Every page is redrawn into the new PDF, so links and form
fields aren't kept. `languages` (`["fr-FR", "en-US"]`) helps Vision with
accents and words. To only read a page, render it and use OCR:

```python
macos.vision.text(macos.pdf.render("scan.pdf", page=1, size=2048))
```

## Encrypted PDFs

Pass `password` to open an encrypted PDF. Without it, or with the wrong one,
the functions raise {class}`~macos.PermissionDeniedError`:

```python
macos.pdf.text("statement.pdf", password="1234")
macos.pdf.merge(["statement.pdf", "cover.pdf"], "all.pdf", password="1234")
```

{func}`~macos.pdf.merge` uses the password for every encrypted input, so they
must share it. The files the functions write are never encrypted, whatever they
did to the PDF (rotating, filling a form, adding bookmarks, redacting...): its
pages, metadata and bookmarks are copied into a new, unencrypted PDF. Only
{func}`~macos.pdf.encrypt` writes encrypted PDFs.

To encrypt a PDF, {func}`~macos.pdf.encrypt` saves a copy that asks for a
password to open, in Preview, Acrobat and browsers alike:

```python
macos.pdf.encrypt("statement.pdf", "locked.pdf", "1234")
macos.pdf.encrypt("locked.pdf", "relocked.pdf", "new-pass", current_password="1234")
macos.pdf.encrypt("statement.pdf", "locked.pdf", "1234", owner_password="only-for-me")
```

A PDF has two passwords: the one that opens it, and the owner's, meant to
guard its permissions (printing, copying, editing). By default both are
`password`; `owner_password` gives the owner's its own.

## Forms

{func}`~macos.pdf.form_fields` lists a PDF form's fields and what's filled
in, and {func}`~macos.pdf.fill_form` fills them in by name; the fields stay
editable:

```python
for field in macos.pdf.form_fields("application.pdf"):
    print(field.name, field.kind, field.value)   # Full name text None

macos.pdf.fill_form("application.pdf", {"Full name": "Jane Doe", "Agree": True, "Plan": "Pro"}, "filled.pdf")
```

Text fields and choices take text; checkboxes `True` or `False`; a group of
radio buttons the option to choose. An unknown name, or an option a field
doesn't offer, raises `ValueError` before anything is written.

## Signing

{func}`~macos.pdf.sign` puts an image of a signature (or a stamp, a logo) on
a page, the last one by default:

```python
macos.pdf.sign("filled.pdf", "signature.png", "signed.pdf")                     # bottom right
macos.pdf.sign("filled.pdf", "signature.png", "signed.pdf", page=1, position=(72, 120), width=180)
```

The easiest is to put it beside a text of the page, such as the line where
it goes:

```python
macos.pdf.sign("contract.pdf", "signature.png", "signed.pdf", near="Signature:")
macos.pdf.sign("contract.pdf", "signature.png", "signed.pdf", near="Witness", side="below", gap=4)
```

`near` finds the text as {func}`~macos.pdf.text` reads it (case doesn't
matter), on `page` when given, else anywhere in the PDF, and takes the first
match; `side` is `"right"` (the default), `"left"`, `"above"` or `"below"`,
and `gap` the room between them, in points.

Without `near`, `position` is a corner (`"bottom_right"`, `"bottom_left"`,
`"top_right"`, `"top_left"`, `margin` points from the edges, 36 by default)
or the `(x, y)` of the image's bottom-left
corner, in points from the page's bottom-left (72 points make an inch,
2.54 cm). `width` is in points too. A PNG with a transparent background
looks best.

It's an image, not a cryptographic signature. The pages are redrawn as
they look, filled-in fields included, so they're no longer editable:
fill the form first.

## Adding text

{func}`~macos.pdf.add_text` writes text on a page, as a text box you can still
edit or move in Preview:

```python
macos.pdf.add_text("contract.pdf", "Received on 29/09/2026", "stamped.pdf")      # page 1, top left
macos.pdf.add_text("form.pdf", "Jane Doe", "filled.pdf", page=2, position=(120, 540), size=14)
macos.pdf.add_text("draft.pdf", "Checked\nby Ana", "notes.pdf", position="top_right", color="#c00000")
```

It goes where {func}`~macos.pdf.sign` puts a signature: beside a text of
the page, such as a form's label, or in a corner, or at a point:

```python
macos.pdf.add_text("form.pdf", "Jane Doe", "filled.pdf", near="Name:")
```

`size` is in points; `font` a font's name, such as `"Helvetica-Bold"`;
`color` a hex color. It adds to the page: its own text can't be edited.

## Table of contents

{func}`~macos.pdf.bookmarks` reads a PDF's table of contents (the sidebar's
outline), and {func}`~macos.pdf.set_bookmarks` gives it one:

```python
for mark in macos.pdf.bookmarks("book.pdf"):
    print("  " * mark.level + mark.title, mark.page)

macos.pdf.set_bookmarks("book.pdf", [
    ("Introduction", 1),
    ("Chapter 1", 3),
    ("1.1 Getting started", 4, 1),     # (title, page, level): a section of Chapter 1
    ("Chapter 2", 12),
], "book-with-contents.pdf")
```

An empty list takes the table of contents away.

## Embedded images

{func}`~macos.pdf.images` saves the pictures a PDF holds into a folder:

```python
macos.pdf.images("brochure.pdf", "brochure-images")   # [PosixPath('brochure-images/page1-1.jpg'), ...]
```

`pages` keeps only some pages' pictures (numbered from 1). JPEG (and JPEG
2000) pictures are saved as they're embedded, without compressing them again;
the others become PNG (or TIFF, for CMYK). A picture used on several
pages is saved once, and rare encodings (indexed colors, 1-bit masks) are
skipped. To save whole pages as images, see {func}`~macos.pdf.render`.

## Redacting

A black rectangle drawn over text in a PDF hides it only on screen: the text
is still there, to copy, search or extract. {func}`~macos.pdf.redact` removes
it for good before blacking it out:

```python
import re

done = macos.pdf.redact("contract.pdf", ["Jane Doe", "123-45-6789"], "contract-public.pdf")
done.matches   # {'Jane Doe': 3, '123-45-6789': 1}
done.pages     # {1: 2, 4: 2}: the pages redrawn, with their matches

ssn = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
macos.pdf.redact("list.pdf", [ssn, email], "list-public.pdf")
```

A text matches as whole words, ignoring case and any spacing or line break
between them: a name split over two lines is found, and `"Ana"` doesn't black
out "Banana". A compiled {mod}`re` pattern catches what follows a shape: IDs,
emails, phone numbers. The {class}`~macos.pdf.Redaction` it returns tells how
many times each target was found, and on which pages.

Each page with a match is redrawn as a picture of what it shows, with black
boxes over the matches: there's no text under them anymore, and what the
page's crop hid is gone too. Its annotations (form fields, comments, stamps)
become part of the picture. The rest of that page still
shows, but its text can no longer be selected or searched; run
{func}`~macos.pdf.ocr` on the result to get it back, without what was
redacted. Pages without a match don't change.

What else in the file holds a match goes too:

- form fields and comments, wherever they hold it: a value, a field's name
  or choices, a comment or its author, a link's address. Their page is
  flattened, with a box over them (its other fields become part of the
  picture);
- the title, author, subject, keywords and creator, and bookmark titles, where the
  match becomes `█`. These count in the {class}`~macos.pdf.Redaction` too: a
  target found only in the title is redacted, not reported missing.

When a target isn't found at all, {func}`~macos.pdf.redact` raises
{class}`ValueError` and writes nothing: a redaction that missed would look
like it worked. A match found in the text but that can't be placed on the
page raises {class}`~macos.MacOSError`, writing nothing too.

```{warning}
It finds only what the PDF holds as text. **Look over the result before
sharing it**, and compare the counts with what you expect. These stay
visible:

- text in pictures: a scanned page, a screenshot, a logo, a signature;
- text turned into shapes, as some design and print PDFs have;
- fonts whose letters can't be read back (the text {func}`~macos.pdf.text`
  returns looks garbled);
- words split by a hyphen at the end of a line.

A scanned page has no text to find: run {func}`~macos.pdf.ocr` first. On a
scan made searchable that way, the boxes go where the OCR placed the words,
which may be a little off the picture: check those pages closely.
```

## Reference

- {func}`macos.pdf.page_count`
- {func}`macos.pdf.text`
- {func}`macos.pdf.metadata`
- {func}`macos.pdf.merge`
- {func}`macos.pdf.extract`
- {func}`macos.pdf.rotate`
- {func}`macos.pdf.encrypt`
- {func}`macos.pdf.watermark`
- {func}`macos.pdf.compress`
- {func}`macos.pdf.grayscale`
- {func}`macos.pdf.render`
- {func}`macos.pdf.from_images`
- {class}`macos.pdf.Metadata`
- {func}`macos.pdf.ocr`
- {class}`macos.pdf.FormField`
- {func}`macos.pdf.form_fields`
- {func}`macos.pdf.fill_form`
- {func}`macos.pdf.sign`
- {func}`macos.pdf.add_text`
- {class}`macos.pdf.Bookmark`
- {func}`macos.pdf.bookmarks`
- {func}`macos.pdf.set_bookmarks`
- {func}`macos.pdf.images`
- {func}`macos.pdf.redact`
- {class}`macos.pdf.Redaction`
