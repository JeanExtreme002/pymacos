# Vision

{mod}`macos.vision` analyzes images with Apple's Vision framework: it reads
text (OCR), QR codes and barcodes, says what an image shows, finds faces,
scans documents, crops to the subject and finds duplicate photos. It
runs on the Mac, offline: nothing to install, no model to download and no
permission to grant.

## Reading text

```python
import macos

macos.vision.text("receipt.png")
# 'Coffee Shop\nTotal: $42.00\nThank you!'
```

The image can be a path or the bytes of an image file, in any format macOS
opens (PNG, JPEG, HEIC, TIFF...). That makes it easy to combine with other
features:

```python
macos.vision.text(macos.clipboard.paste_image())      # text of a copied image
macos.vision.text(macos.screenshot(region=(0, 0, 800, 600)))
```

Bytes that aren't an image raise {class}`~macos.MacOSError`.
Vision reads images, not PDFs: a PDF raises `ValueError`. Draw the pages you
want with {func}`macos.pdf.render` first:

```python
macos.vision.text(macos.pdf.render("scan.pdf", page=1, size=2048))
```

## Languages

By default Vision detects the language. When you know it, pass `languages`,
most likely first. This improves accents and language-specific characters:

```python
macos.vision.text("menu.jpg", languages=["fr-FR", "en-US"])
```

{func}`~macos.vision.languages` lists the supported codes:

```python
macos.vision.languages()   # ['en-US', 'fr-FR', 'it-IT', 'de-DE', 'es-ES', 'pt-BR', ...]
```

## Lines, confidence and position

{func}`~macos.vision.lines` returns each line with how confident Vision is and
where it is in the image:

```python
for line in macos.vision.lines("slide.png"):
    print(line.text, line.confidence, line.box)
```

```text
Quarterly results 1.0 (0.08, 0.10, 0.52, 0.09)
Revenue grew 12% 0.98 (0.08, 0.25, 0.41, 0.06)
```

`box` is `(x, y, width, height)` as fractions of the image size, measured from
the top-left corner, so it works whatever the image's resolution.

## Speed

Recognition is accurate by default. `fast=True` is a few times faster but
less precise, and it doesn't correct words with a dictionary:

```python
macos.vision.text("page.png", fast=True)
```

## QR codes and barcodes

{func}`~macos.vision.barcodes` reads QR codes and barcodes (EAN, UPC, Code 128,
PDF417, Aztec, Data Matrix...):

```python
for code in macos.vision.barcodes("poster.jpg"):
    print(code.kind, code.payload)   # QR https://python.org
```

Each {class}`~macos.vision.Barcode` has its `payload` (`None` for binary
content), its `kind` (`'QR'`,
`'EAN13'`...) and its `box`. To make a QR code, see {func}`macos.image.qr_code`.

## What's in an image

{func}`~macos.vision.classify` returns labels for what an image shows, most
likely first:

```python
macos.vision.classify("holiday.jpg")
# [('outdoor', 0.85), ('sky', 0.84), ('cloudy', 0.74)]
```

Labels are English words from Vision's own list of over a thousand categories.
`limit` (5 by default) and `min_confidence` (0.1, from 0.0 to 1.0) decide how
many come back; a `min_confidence` outside that range is used as it is today
and warns (`DeprecationWarning`): pymacos 2.0 will raise `ValueError`.

## Faces

{func}`~macos.vision.faces` returns a box for each face found. It locates faces;
it doesn't recognize people.

```python
len(macos.vision.faces("team.jpg"))   # 4
```

## Removing the background

{func}`~macos.vision.remove_background` cuts out the subject of a photo (a
person, an animal, an object) and returns it as a PNG with a transparent
background, like *Lift Subject from Background* in Photos:

```python
from pathlib import Path

Path("cutout.png").write_bytes(macos.vision.remove_background("dog.jpg"))
Path("tight.png").write_bytes(macos.vision.remove_background("dog.jpg", crop=True))
```

By default the result keeps the photo's size; `crop=True` trims it to the
subject. It returns `None` when nothing stands out, and needs macOS 14 or later.

## Cats and dogs

{func}`~macos.vision.animals` finds cats and dogs, the only animals Vision
recognizes:

```python
for animal in macos.vision.animals("garden.jpg"):
    print(animal.kind, animal.confidence)   # dog 0.93
```

## Scanning documents

{func}`~macos.vision.scan_document` turns a photo of a sheet of paper (a
receipt, a contract, a whiteboard) into a flat, straight scan, like the
*Scan Documents* feature of the iPhone:

```python
from pathlib import Path

scan = macos.vision.scan_document("receipt.jpg")
Path("receipt.png").write_bytes(scan)
macos.vision.text(scan)   # OCR reads a scan better than the photo
```

Vision finds the page's four corners and corrects the perspective, so only the
page is left. It returns `None` when the photo doesn't show a document, and
needs macOS 12 or later. To put
several scans in one PDF, see {func}`macos.pdf.from_images`.

## Smart cropping

{func}`~macos.vision.smart_crop` crops and scales an image to a size, centring
the crop on what draws the eye (a face, an animal, the main object) instead of
the middle of the picture. Handy for thumbnails and avatars:

```python
Path("avatar.png").write_bytes(macos.vision.smart_crop("portrait.jpg", 256, 256))
Path("banner.png").write_bytes(macos.vision.smart_crop("landscape.jpg", 1500, 500))
```

Images are only scaled down: when the image is too small, the result keeps the
requested proportions at the largest size it can.

## Duplicate photos

{func}`~macos.vision.duplicates` groups the images that show the same picture:
copies, resized or re-saved versions, burst shots:

```python
photos = sorted(Path("~/Pictures/Trip").expanduser().glob("*.jpg"))

for group in macos.vision.duplicates(photos):
    print("Same picture:", [photo.name for photo in group])
```

It compares what the images show, not their bytes, so a JPEG and a smaller
PNG of the same photo match. Only groups of two or more come back. Raise
`threshold` (0.3 by default) to also group similar shots.

{func}`~macos.vision.image_distance` gives the underlying number for two
images: copies are usually under 0.15 and unrelated photos around 0.7 to 0.9.

```python
macos.vision.image_distance("IMG_1.jpg", "IMG_1_edited.jpg")   # 0.06
```

Small images (a few hundred pixels) carry less detail, so their distances are
less reliable.

## The best shot

{func}`~macos.vision.best_shot` picks the photo where the faces look best:
sharp, well lit, eyes open, facing the camera. With
{func}`~macos.vision.duplicates`, it keeps one photo of each burst:

```python
for group in macos.vision.duplicates(photos):
    keep = macos.vision.best_shot(group) or group[0]

    for photo in group:
        if photo != keep:
            macos.finder.trash(photo)
```

It returns `None` when no photo has a face. In a group photo, every face
counts equally.

## Horizon

{func}`~macos.vision.horizon` tells how tilted a photo's horizon is, in degrees:
positive when it rises to the right. It returns `None` when there's no horizon,
when it's level (under about 1.5°), and when it's too tilted to tell (over
about 10°). {func}`macos.image.straighten` levels the photo:

```python
macos.vision.horizon("beach.jpg")                      # 4.5
macos.image.straighten("beach.jpg", "beach-level.jpg")
```

## How good a photo looks

{func}`~macos.vision.aesthetics` scores a photo from -1.0 to 1.0, as Photos
judges it (focus, exposure, composition...), and tells whether it's a
"utility" picture: a screenshot, a photo of a receipt or a document.

```python
macos.vision.aesthetics("sunset.jpg")    # Aesthetics(score=0.71, utility=False)
macos.vision.aesthetics("receipt.jpg")   # Aesthetics(score=0.29, utility=True)
```

With {func}`~macos.vision.duplicates` and {func}`~macos.vision.best_shot`, it
keeps the best photos of a trip, or sorts screenshots out of a photo folder.
It's the judgment of Apple's model, so not every picture of text counts as a
utility one. It needs macOS 15 or later.

## Body and hand poses

{func}`~macos.vision.body_pose` finds each person's joints, and
{func}`~macos.vision.hand_pose` each hand's:

```python
for person in macos.vision.body_pose("dance.jpg"):
    wrist, shoulder = person.joints.get("right_wrist"), person.joints.get("right_shoulder")
    if wrist and shoulder and wrist[1] < shoulder[1]:
        print("a raised right hand")

for hand in macos.vision.hand_pose("photo.jpg"):
    thumb, index = hand.joints.get("thumb_tip"), hand.joints.get("index_tip")
    if thumb and index and thumb[1] < index[1]:
        print(hand.side, "thumbs up")
```

Each joint is `(x, y, confidence)`: fractions of the image from its top-left
corner, and how sure Vision is. A {class}`~macos.vision.Pose` has 19 joints
(`nose`, `left_shoulder`, `right_knee`...) and a {class}`~macos.vision.Hand`
21 (`wrist`, `thumb_tip`, `index_mcp`...), with its `side` (`'left'` or
`'right'`, the person's own, or `None` when Vision can't tell).
{func}`~macos.vision.hand_pose` finds up to `max_hands` hands (4 by default).
Only the joints Vision sees are there. With
{func}`macos.camera.photo`, they make a posture check or a gesture trigger.

## Reference

- {func}`macos.vision.text`
- {func}`macos.vision.lines`
- {func}`macos.vision.languages`
- {class}`macos.vision.TextLine`
- {func}`macos.vision.barcodes`
- {class}`macos.vision.Barcode`
- {func}`macos.vision.classify`
- {func}`macos.vision.faces`
- {func}`macos.vision.remove_background`
- {func}`macos.vision.animals`
- {class}`macos.vision.Animal`
- {func}`macos.vision.scan_document`
- {func}`macos.vision.smart_crop`
- {func}`macos.vision.image_distance`
- {func}`macos.vision.duplicates`
- {func}`macos.vision.best_shot`
- {func}`macos.vision.horizon`
- {func}`macos.vision.aesthetics`
- {class}`macos.vision.Aesthetics`
- {func}`macos.vision.body_pose`
- {class}`macos.vision.Pose`
- {func}`macos.vision.hand_pose`
- {class}`macos.vision.Hand`
