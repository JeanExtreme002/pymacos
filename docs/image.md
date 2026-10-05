# Images

{mod}`macos.image` reads, converts, resizes and edits images, including the
HEIC photos from iPhones, reads and changes their metadata, and generates QR
codes. It uses ImageIO, the framework
behind Preview and Photos, so there's no Pillow or C library to install.

```python
import macos

macos.image.info("IMG_0042.heic")
# ImageInfo(width=4032, height=3024, format='heic', has_alpha=False, orientation=6, dpi=72.0)

macos.image.convert("IMG_0042.heic", "IMG_0042.jpg")
macos.image.resize("IMG_0042.heic", "small.jpg", width=800)
```

## Converting

{func}`~macos.image.convert` writes the format of the output's extension:
`.jpg`, `.png`, `.heic`, `.tiff`, `.gif` or `.bmp`. It reads anything macOS
opens, WebP, AVIF and camera RAW files included.

```python
macos.image.convert("photo.heic", "photo.jpg", quality=0.8)   # quality: 0.0 to 1.0
macos.image.convert("scan.tiff", "scan.png")
```

`quality` applies to JPEG and HEIC. PNG, TIFF and BMP keep every pixel as it
is; GIF holds 256 colors at most, so a photo loses some of its colors.

Metadata such as the date, camera and orientation is kept. Animated GIFs and
multi-page TIFFs keep all their frames when converted to GIF or TIFF; the other
formats hold a single image, so they get the first frame. To convert a whole
folder of iPhone photos:

```python
from pathlib import Path

for photo in Path("~/Downloads").expanduser().glob("*.heic"):
    macos.image.convert(photo, photo.with_suffix(".jpg"))
```

## Resizing

{func}`~macos.image.resize` scales an image to fit a width, a height or both,
keeping its proportions:

```python
macos.image.resize("photo.jpg", "thumb.jpg", width=300)
macos.image.resize("photo.jpg", "fit.png", width=1024, height=1024)
```

Photos taken in portrait are turned upright first, following their EXIF
orientation. The metadata (date, camera, location, DPI) is kept. Images are
only scaled down: a size larger than the original keeps the original size.

## Cropping, rotating and flipping

```python
macos.image.crop("screenshot.png", "button.png", (40, 120, 200, 60))   # x, y, width, height
macos.image.rotate("scan.jpg", "upright.jpg", 90)                      # clockwise
macos.image.flip("selfie.jpg", "mirrored.jpg")                         # left and right swapped
macos.image.flip("photo.jpg", "upside-down.jpg", direction="vertical")
```

The crop box is in pixels from the top-left corner. {func}`~macos.image.rotate`
turns by 90, 180 or 270 degrees; negative values turn counter-clockwise. As
with {func}`~macos.image.resize`, photos are turned upright first, the
metadata is kept, and the output's extension sets the format.

## Straightening

{func}`~macos.image.straighten` levels a photo whose horizon is tilted, found
with {func}`macos.vision.horizon`. The photo is turned and cropped to the
largest part with the same proportions, so no empty corners show:

```python
macos.image.straighten("beach.jpg", "beach-level.jpg")
```

A photo without a tilted horizon is saved unchanged.

## Enhancing and effects

```python
macos.image.enhance("dim.jpg", "better.jpg")             # like Enhance in Photos
macos.image.effect("portrait.jpg", "noir.jpg", "noir")   # like the Photos filters
```

{func}`~macos.image.enhance` fixes the exposure, contrast, colors and red
eyes as Core Image judges best for the photo. {func}`~macos.image.effect`
applies one of the Photos filters: `"noir"`, `"mono"` and `"tonal"` (black and
white, each its own way), `"chrome"`, `"fade"`, `"instant"`, `"process"` and
`"transfer"` (vintage colors).

## Backgrounds

```python
macos.image.blur_background("me.jpg", "me-portrait.jpg")  # like Portrait mode
macos.image.replace_background("me.jpg", "beach.jpg", "me-at-the-beach.jpg")
```

Vision finds the people in the photo and keeps them sharp, in front of a
blurred background or of another picture (scaled to fill it). `strength`
sets the blur. Both raise `ValueError` when the photo shows no person, and
need macOS 12 or later. With
{func}`macos.camera.photo`, they make a quick portrait from the webcam.

## Watermarks

{func}`~macos.image.watermark` writes a text across a photo, diagonally and
see-through, sized to fit it:

```python
macos.image.watermark("house.jpg", "house-listing.jpg", "Acme Realty")
macos.image.watermark("draft.png", "draft-marked.png", "DRAFT", color="#d00000", opacity=0.5)
```

## Contact sheets

{func}`~macos.image.contact_sheet` lays images out as thumbnails in a grid,
on one picture, to see many at a glance:

```python
photos = sorted(Path("~/Pictures/Trip").expanduser().glob("*.jpg"))
macos.image.contact_sheet(photos, "trip-overview.jpg", columns=6, size=200)
```

Each thumbnail fits a `size` × `size` square, `gap` pixels apart, on a
`background` color.

## Hiding faces

{func}`~macos.image.blur_faces` saves a copy with every face pixelated, for
sharing a photo of people who didn't agree to be in it:

```python
macos.image.blur_faces("street.jpg", "street-safe.jpg")
```

Faces are found with {func}`macos.vision.faces`. Combine it with
{func}`~macos.image.strip_metadata` to also remove the location.

## Main colors

{func}`~macos.image.dominant_colors` returns the main colors of an image, the
most present first:

```python
macos.image.dominant_colors("cover.jpg")   # ['#1d3557', '#f1faee', '#e63946', '#457b9d', '#a8dadc']
macos.image.dominant_colors("logo.png", count=2)
```

Transparent pixels are left out, and an image with fewer colors returns
fewer.

## Image details

{func}`~macos.image.info` returns an {class}`~macos.image.ImageInfo` with the
`width` and `height` in pixels, the `format` (`'jpeg'`, `'png'`, `'heic'`...),
whether it `has_alpha` (transparency), the EXIF `orientation` and the `dpi`.
The size is as stored: a portrait photo with orientation 6 or 8 shows with
its width and height swapped.

## Metadata

{func}`~macos.image.taken_at` and {func}`~macos.image.location` read when and
where a photo was taken, from its EXIF and GPS data:

```python
macos.image.taken_at("IMG_0042.heic")   # datetime.datetime(2024, 5, 1, 10, 30)
macos.image.location("IMG_0042.heic")   # (37.8199, -122.4783): latitude, longitude
```

Both return `None` when the image doesn't record it, as with screenshots and
most images from the web. The date is the camera's clock; it carries a time
zone when the photo records one, as iPhones do. {func}`~macos.image.metadata` returns everything the file records, as
nested dictionaries (`'{Exif}'`, `'{GPS}'`, `'{TIFF}'`...):

```python
macos.image.metadata("IMG_0042.heic")["{TIFF}"]["Model"]   # 'iPhone 15 Pro'
```

## Changing the date and location

{func}`~macos.image.set_taken_at` and {func}`~macos.image.set_location`
change when and where a photo was taken. Photos and other apps sort and map
photos with these values, so this fixes a camera with the wrong clock, or
adds a location to photos taken without GPS:

```python
from datetime import datetime, timedelta

macos.image.set_taken_at("IMG_0042.jpg", datetime(2024, 5, 1, 10, 30))
macos.image.set_location("IMG_0042.jpg", 37.8199, -122.4783)

# The camera was 3 hours behind for the whole trip:
for photo in Path("~/Pictures/Trip").expanduser().glob("*.jpg"):
    macos.image.set_taken_at(photo, macos.image.taken_at(photo) + timedelta(hours=3))
```

They change the file itself, or save a copy with `output=`, in the format of
its extension, as {func}`~macos.image.convert` does (a `.png` copy of a JPEG
is a PNG). JPEG, PNG and TIFF keep their pixels untouched when the format
stays the same; HEIC photos may be saved again. A
`datetime` with a time zone records it too, and {func}`~macos.image.taken_at`
returns it.

## Removing metadata

iPhone photos record where they were taken. Before sharing one,
{func}`~macos.image.strip_metadata` saves a copy without the location, the
date, the camera or the editing software:

```python
macos.image.strip_metadata("IMG_0042.heic", "share.jpg")
```

Only the orientation is kept, so the picture still shows upright. As with
{func}`~macos.image.convert`, the output's extension sets the format.

## QR codes

{func}`~macos.image.qr_code` generates a QR code as PNG bytes:

```python
from pathlib import Path

image = macos.image.qr_code("https://python.org", size=512)
Path("site.png").write_bytes(image)
```

`size` is the side in pixels, up to 4096. `correction` sets how much damage
the code survives: `"L"`, `"M"` (the default), `"Q"` or `"H"`; higher levels
hold less data. To read QR codes, see {func}`macos.vision.barcodes`.

## Reference

- {func}`macos.image.info`
- {func}`macos.image.metadata`
- {func}`macos.image.taken_at`
- {func}`macos.image.location`
- {func}`macos.image.strip_metadata`
- {func}`macos.image.set_taken_at`
- {func}`macos.image.set_location`
- {func}`macos.image.convert`
- {func}`macos.image.resize`
- {func}`macos.image.crop`
- {func}`macos.image.rotate`
- {func}`macos.image.flip`
- {func}`macos.image.straighten`
- {func}`macos.image.blur_faces`
- {func}`macos.image.enhance`
- {func}`macos.image.effect`
- {func}`macos.image.blur_background`
- {func}`macos.image.replace_background`
- {func}`macos.image.watermark`
- {func}`macos.image.contact_sheet`
- {func}`macos.image.dominant_colors`
- {func}`macos.image.qr_code`
- {class}`macos.image.ImageInfo`
