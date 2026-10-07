# -*- coding: utf-8 -*-

"""
Read text in images (OCR) with Apple's Vision framework.

::

    macos.vision.text("receipt.png")                    # 'Total: $42.00\\n...'
    macos.vision.text("scan.jpg", languages=["fr-FR"])
    for line in macos.vision.lines("slide.png"):
        print(line.text, line.confidence)

Recognition runs on the Mac, offline, with the same engine as Live Text in
Photos and Preview: nothing to install and no permission needed.
"""

import ctypes
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from . import _cf, _files, _objc
from ._objc import BOOL, NSInteger, NSUInteger
from ._system import framework
from .errors import MacOSError, NotSupportedError

__all__ = [
    "text",
    "lines",
    "languages",
    "barcodes",
    "classify",
    "faces",
    "animals",
    "remove_background",
    "scan_document",
    "image_distance",
    "duplicates",
    "best_shot",
    "horizon",
    "aesthetics",
    "Aesthetics",
    "body_pose",
    "hand_pose",
    "Pose",
    "Hand",
    "smart_crop",
    "TextLine",
    "Barcode",
    "Animal",
]

Image = Union[bytes, str, "os.PathLike[str]"]

# VNRequestTextRecognitionLevel
_ACCURATE = 0
_FAST = 1


@dataclass(frozen=True)
class TextLine:
    """A line of text found in an image."""

    text: str
    confidence: float
    """From 0.0 to 1.0."""
    box: Tuple[float, float, float, float]
    """``(x, y, width, height)`` as fractions of the image size, from its top-left corner."""


@dataclass(frozen=True)
class Barcode:
    """A barcode or QR code found in an image."""

    payload: Optional[str]
    """What it encodes, e.g. a URL (``None`` for binary content)."""
    kind: str
    """The symbology, e.g. ``'QR'``, ``'EAN13'``, ``'Code128'``, ``'PDF417'``."""
    box: Tuple[float, float, float, float]
    """``(x, y, width, height)`` as fractions of the image size, from its top-left corner."""


@dataclass(frozen=True)
class Animal:
    """A cat or dog found in an image."""

    kind: str
    """``'cat'`` or ``'dog'``."""
    confidence: float
    box: Tuple[float, float, float, float]
    """``(x, y, width, height)`` as fractions of the image size, from its top-left corner."""


@lru_cache(maxsize=None)
def _load() -> None:
    framework("Foundation")
    framework("Vision")


def _refuse_pdf(image: Image) -> None:
    """
    Raise ``ValueError`` for a PDF.

    Vision reads images: given a PDF it sees a 0 x 0 picture. Reading only its
    first page would quietly drop the rest, so the caller picks the pages.
    """
    if isinstance(image, (bytes, bytearray)):
        head = bytes(image[:1024])
    else:
        try:
            with open(Path(image).expanduser(), "rb") as file:
                head = file.read(1024)
        except OSError:
            return  # missing or unreadable: the usual errors follow
    # The header opens the file, maybe after some blank padding. Anywhere else
    # it's only text, such as a PNG comment that mentions a PDF.
    if re.match(rb"[\x00\s]*%PDF-\d", head):
        raise ValueError(
            "Vision reads images, not PDFs: draw the pages with macos.pdf.render(), "
            "e.g. macos.vision.text(macos.pdf.render(path, page=1, size=2048))"
        )


def _handler(image: Image) -> int:
    """An autoreleased ``VNImageRequestHandler`` for a path or image bytes."""
    _refuse_pdf(image)
    options = _objc.send(_objc.cls("NSDictionary"), "dictionary")
    handler = _objc.send(_objc.cls("VNImageRequestHandler"), "alloc")
    if isinstance(image, (bytes, bytearray)):
        handler = _objc.send(
            handler, "initWithData:options:", _objc.nsdata(bytes(image)), options, argtypes=(_objc.id, _objc.id)
        )
    else:
        path = Path(image).expanduser().absolute()
        if not path.exists():
            raise FileNotFoundError(str(path))
        handler = _objc.send(
            handler, "initWithURL:options:", _objc.file_url(path), options, argtypes=(_objc.id, _objc.id)
        )
    return _objc.send(handler, "autorelease")


def _request(languages: Optional[Sequence[str]], fast: bool) -> int:
    request = _objc.send(_objc.send(_objc.cls("VNRecognizeTextRequest"), "alloc"), "init")
    request = _objc.send(request, "autorelease")
    _objc.send(request, "setRecognitionLevel:", _FAST if fast else _ACCURATE, argtypes=(NSInteger,), restype=None)
    _objc.send(request, "setUsesLanguageCorrection:", not fast, argtypes=(BOOL,), restype=None)
    if languages:
        codes = _objc.nsarray_of([_objc.nsstring(code) for code in languages])
        _objc.send(request, "setRecognitionLanguages:", codes, argtypes=(_objc.id,), restype=None)
    return request


def _perform_on(picture: int, request: int) -> List[int]:
    """Run a Vision request on a ``CIImage`` (already upright) and return its observations (autoreleased)."""
    handler = _objc.send(_objc.cls("VNImageRequestHandler"), "alloc")
    handler = _objc.send(
        handler,
        "initWithCIImage:options:",
        picture,
        _objc.send(_objc.cls("NSDictionary"), "dictionary"),
        argtypes=(_objc.id, _objc.id),
    )
    _objc.send(handler, "autorelease")
    error = ctypes.c_void_p()
    ok = _objc.send(
        handler,
        "performRequests:error:",
        _objc.nsarray_of([request]),
        ctypes.byref(error),
        argtypes=(_objc.id, ctypes.c_void_p),
        restype=BOOL,
    )
    if not ok:
        raise _error(error, "the image could not be analyzed", prefix="the image could not be analyzed: ")
    return list(_objc.nsarray(_objc.send(request, "results")))


def _perform(image: Image, request: int) -> List[int]:
    """Run a Vision request on an image and return its result observations (autoreleased)."""
    handler = _handler(image)
    error = ctypes.c_void_p()
    ok = _objc.send(
        handler,
        "performRequests:error:",
        _objc.nsarray_of([request]),
        ctypes.byref(error),
        argtypes=(_objc.id, ctypes.c_void_p),
        restype=BOOL,
    )
    if not ok:
        raise _error(error, "the image could not be read", prefix="the image could not be read: ")
    return list(_objc.nsarray(_objc.send(request, "results")))


def _box(observation: int) -> Tuple[float, float, float, float]:
    box = _objc.send(observation, "boundingBox", restype=_objc.CGRect)
    # Vision measures from the bottom-left corner.
    return (box.origin.x, 1.0 - box.origin.y - box.size.height, box.size.width, box.size.height)


def _confidence(observation: int) -> float:
    return round(float(_objc.send(observation, "confidence", restype=ctypes.c_float)), 3)


def _error(error: ctypes.c_void_p, fallback: str, prefix: str = "") -> MacOSError:
    message = _objc.error_message(error)
    return MacOSError(prefix + message if message else fallback)


def lines(image: Image, *, languages: Optional[Sequence[str]] = None, fast: bool = False) -> List[TextLine]:
    """
    Find the lines of text in an image, top to bottom.

    ``image`` is a path or the image file's bytes, in any format macOS can
    open (PNG, JPEG, HEIC, TIFF...); for a PDF, draw its pages with
    :func:`macos.pdf.render`. ``languages`` lists the languages to
    expect, most likely first (e.g. ``["fr-FR", "en-US"]``; see
    :func:`languages`); by default Vision detects them. ``fast=True`` trades
    accuracy for speed.
    """
    _load()
    found: List[Any] = []
    with _objc.autorelease_pool():
        for observation in _perform(image, _request(languages, fast)):
            candidates = _objc.send(observation, "topCandidates:", 1, argtypes=(NSUInteger,))
            for candidate in _objc.nsarray(candidates):
                found.append(
                    TextLine(
                        text=_objc.pystring(_objc.send(candidate, "string")) or "",
                        confidence=_confidence(candidate),
                        box=_box(observation),
                    )
                )
    # Vision returns lines in detection order: sort them top to bottom (then
    # left to right), as the docs promise.
    return sorted(found, key=lambda line: (round(line.box[1], 2), line.box[0]))


def _utf16(text: str, index: int) -> int:
    """The UTF-16 offset of ``text[index]``: NSString counts UTF-16 units, Python code points."""
    return len(text[:index].encode("utf-16-le")) // 2


def _spans(line: str, needle: str) -> List[Tuple[int, int]]:
    """
    Where ``needle`` is in ``line``, ignoring case: ``(start, end)`` indexes of ``line``.

    Case folding can change lengths ("ß" becomes "ss"), so each folded
    character is mapped back to the character of the line it came from.
    """
    wanted = needle.casefold()
    if not wanted:
        return []
    origin = [index for index, char in enumerate(line) for _ in char.casefold()]
    folded = line.casefold()
    spans = []
    start = folded.find(wanted)
    while start >= 0:
        spans.append((origin[start], origin[start + len(wanted) - 1] + 1))
        start = folded.find(wanted, start + len(wanted))
    return spans


def _words(image: Image, languages: Optional[Sequence[str]] = None) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """Every word of the image's text, with its own box (fractions of the image from its top-left)."""
    _load()
    with _objc.autorelease_pool():
        return _words_of(_perform(image, _request(languages, False)))


def _picture_words(
    picture: int, languages: Optional[Sequence[str]] = None
) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """
    :func:`_words` for a ``CGImage`` already drawn (a page of a PDF), handed to Vision as it is.

    No image file in between: encoding a page as PNG for Vision to decode it
    again is most of the work for a large page.
    """
    _load()
    framework("CoreImage")
    with _objc.autorelease_pool():
        wrapped = _objc.send(_objc.cls("CIImage"), "imageWithCGImage:", picture, argtypes=(ctypes.c_void_p,))
        if not wrapped:
            raise MacOSError("the picture could not be read")
        return _words_of(_perform_on(wrapped, _request(languages, False)))


def _words_of(observations: List[int]) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    found = []
    for observation in observations:
        candidates = _objc.send(observation, "topCandidates:", 1, argtypes=(NSUInteger,))
        for candidate in _objc.nsarray(candidates):
            line = _objc.pystring(_objc.send(candidate, "string")) or ""
            for match in re.finditer(r"\S+", line):
                first, last = _utf16(line, match.start()), _utf16(line, match.end())
                error = ctypes.c_void_p()
                part = _objc.send(
                    candidate,
                    "boundingBoxForRange:error:",
                    _files.NSRange(first, last - first),
                    ctypes.byref(error),
                    argtypes=(_files.NSRange, ctypes.c_void_p),
                )
                if part:
                    found.append((match.group(0), _box(part)))
    return found


def _occurrences(
    image: Image, needle: str, languages: Optional[Sequence[str]] = None
) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """
    Every place ``needle`` shows up in the image's text, ignoring case: ``(line, box)``.

    The box surrounds the matching characters only, not the whole line, as
    fractions of the image from its top-left corner.
    """
    _load()
    found = []
    with _objc.autorelease_pool():
        for observation in _perform(image, _request(languages, False)):
            candidates = _objc.send(observation, "topCandidates:", 1, argtypes=(NSUInteger,))
            for candidate in _objc.nsarray(candidates):
                line = _objc.pystring(_objc.send(candidate, "string")) or ""
                for start, end in _spans(line, needle):
                    first, last = _utf16(line, start), _utf16(line, end)
                    error = ctypes.c_void_p()
                    part = _objc.send(
                        candidate,
                        "boundingBoxForRange:error:",
                        _files.NSRange(first, last - first),
                        ctypes.byref(error),
                        argtypes=(_files.NSRange, ctypes.c_void_p),
                    )
                    found.append((line, _box(part) if part else _box(observation)))
    return sorted(found, key=lambda match: (round(match[1][1], 2), match[1][0]))


def text(image: Image, *, languages: Optional[Sequence[str]] = None, fast: bool = False) -> str:
    """Return all the text in an image, one line per line found (see :func:`lines`)."""
    return "\n".join(line.text for line in lines(image, languages=languages, fast=fast))


def languages(*, fast: bool = False) -> List[str]:
    """The language codes that text recognition supports, e.g. ``['en-US', 'fr-FR', ...]`` (macOS 12+)."""
    _load()
    with _objc.autorelease_pool():
        request = _request(None, fast)
        error = ctypes.c_void_p()
        codes = _objc.send(
            request, "supportedRecognitionLanguagesAndReturnError:", ctypes.byref(error), argtypes=(ctypes.c_void_p,)
        )
        if not codes:
            raise _error(error, "the supported languages could not be read")
        return [code for code in (_objc.pystring(item) for item in _objc.nsarray(codes)) if code]


def barcodes(image: Image) -> List[Barcode]:
    """
    Find QR codes and barcodes (EAN, UPC, Code 128, PDF417, Aztec, Data Matrix...) in an image.

    ::

        [code.payload for code in macos.vision.barcodes("poster.jpg")]   # ['https://...']
    """
    _load()
    found = []
    with _objc.autorelease_pool():
        for observation in _perform(image, _objc.new("VNDetectBarcodesRequest")):
            kind = _objc.pystring(_objc.send(observation, "symbology")) or ""
            found.append(
                Barcode(
                    payload=_objc.pystring(_objc.send(observation, "payloadStringValue")),
                    kind=kind.replace("VNBarcodeSymbology", ""),
                    box=_box(observation),
                )
            )
    return found


def classify(image: Image, *, limit: int = 5, min_confidence: float = 0.1) -> List[Tuple[str, float]]:
    """
    Say what an image shows, as ``(label, confidence)`` pairs, most likely first.

    ::

        macos.vision.classify("holiday.jpg")   # [('beach', 0.91), ('sky', 0.87), ('ocean', 0.74)]

    Labels are English words from Vision's own taxonomy (over a thousand
    categories, such as ``'dog'``, ``'food'`` or ``'document'``).
    """
    if limit <= 0:
        raise ValueError("limit must be positive, not {}".format(limit))
    _load()
    with _objc.autorelease_pool():
        observations = _perform(image, _objc.new("VNClassifyImageRequest"))
        labels = [
            (_objc.pystring(_objc.send(observation, "identifier")) or "", _confidence(observation))
            for observation in observations
        ]
    ranked = sorted((pair for pair in labels if pair[1] >= min_confidence), key=lambda pair: -pair[1])
    return ranked[:limit]


def faces(image: Image) -> List[Tuple[float, float, float, float]]:
    """
    Find faces in an image, as ``(x, y, width, height)`` boxes (fractions of the image, from the top-left).

    It locates faces; it doesn't tell who they are.
    """
    _load()
    with _objc.autorelease_pool():
        return [_box(observation) for observation in _perform(image, _objc.new("VNDetectFaceRectanglesRequest"))]


def animals(image: Image) -> List[Animal]:
    """Find cats and dogs in an image. (Those are the only animals Vision recognizes.)"""
    _load()
    found = []
    with _objc.autorelease_pool():
        for observation in _perform(image, _objc.new("VNRecognizeAnimalsRequest")):
            for label in _objc.nsarray(_objc.send(observation, "labels")):
                found.append(
                    Animal(
                        kind=(_objc.pystring(_objc.send(label, "identifier")) or "").lower(),
                        confidence=_confidence(label),
                        box=_box(observation),
                    )
                )
    return found


def remove_background(image: Image, *, crop: bool = False) -> Optional[bytes]:
    """
    Cut out the subject of a photo (a person, an animal, an object) and return it as a PNG with a transparent background.

    It's the "lift subject from background" of Photos and Preview. ``crop=True``
    trims the result to the subject; by default it keeps the image's size.
    Returns ``None`` when no subject stands out. Needs macOS 14 or later::

        Path("cutout.png").write_bytes(macos.vision.remove_background("dog.jpg"))
    """
    _load()
    framework("AppKit")
    framework("CoreImage")
    with _objc.autorelease_pool():
        handler = _handler(image)
        try:
            request = _objc.new("VNGenerateForegroundInstanceMaskRequest")
        except LookupError:
            raise NotSupportedError("removing backgrounds needs macOS 14 or later") from None
        error = ctypes.c_void_p()
        ok = _objc.send(
            handler,
            "performRequests:error:",
            _objc.nsarray_of([request]),
            ctypes.byref(error),
            argtypes=(_objc.id, ctypes.c_void_p),
            restype=BOOL,
        )
        if not ok:
            raise _error(error, "the image could not be read", prefix="the image could not be read: ")
        results = list(_objc.nsarray(_objc.send(request, "results")))
        if not results:
            return None
        observation = results[0]
        instances = _objc.send(observation, "allInstances")
        if not instances or not _objc.send(instances, "count", restype=NSUInteger):
            return None

        buffer = _objc.send(
            observation,
            "generateMaskedImageOfInstances:fromRequestHandler:croppedToInstancesExtent:error:",
            instances,
            handler,
            crop,
            ctypes.byref(error),
            argtypes=(_objc.id, _objc.id, BOOL, ctypes.c_void_p),
            restype=ctypes.c_void_p,
        )
        if not buffer:
            raise _error(error, "the background could not be removed")

        # Pixel buffer -> Core Image -> PNG. The buffer comes retained
        # (CF_RETURNS_RETAINED): released once drawn, or every call would leak
        # a full-size image.
        with _cf.owned(buffer):
            picture = _objc.send(_objc.cls("CIImage"), "imageWithCVPixelBuffer:", buffer, argtypes=(ctypes.c_void_p,))
            return _objc.ciimage_png(picture)


def scan_document(image: Image) -> Optional[bytes]:
    """
    Turn a photo of a document (a page, a receipt, a card) into a flat, straight scan, as PNG bytes.

    Finds the document's edges, crops the rest of the photo away and corrects
    the perspective, like the scanner in Notes. Returns ``None`` when no
    document is found::

        scan = macos.vision.scan_document("receipt_photo.jpg")
        macos.vision.text(scan)                          # read it
        macos.pdf.from_images([scan], "receipt.pdf")     # or file it
    """
    _refuse_pdf(image)
    _load()
    with _objc.autorelease_pool():
        picture = _objc.ciimage(image)
        extent = _objc.send(picture, "extent", restype=_objc.CGRect)
        width, height = extent.size.width, extent.size.height

        # Detect on the upright pixels, so the corners match `picture`: the CIImage itself, not a PNG of it.
        observations = _perform_on(picture, _objc.new("VNDetectDocumentSegmentationRequest"))
        # The detector always returns a quadrilateral; on anything but a
        # document its confidence is 0 (measured: 0.99 for a photographed page).
        if not observations or _objc.send(observations[0], "confidence", restype=ctypes.c_float) < 0.5:
            return None
        document = observations[0]

        correction = _objc.send(
            _objc.cls("CIFilter"), "filterWithName:", _objc.nsstring("CIPerspectiveCorrection"), argtypes=(_objc.id,)
        )
        _objc.send(
            correction, "setValue:forKey:", picture, _objc.nsstring("inputImage"), argtypes=(_objc.id, _objc.id), restype=None
        )
        for corner, key in (
            ("topLeft", "inputTopLeft"),
            ("topRight", "inputTopRight"),
            ("bottomLeft", "inputBottomLeft"),
            ("bottomRight", "inputBottomRight"),
        ):
            # Vision and Core Image both measure from the bottom-left corner;
            # Vision in fractions, Core Image in pixels.
            point = _objc.send(document, corner, restype=_objc.CGPoint)
            vector = _objc.send(
                _objc.cls("CIVector"),
                "vectorWithX:Y:",
                point.x * width,
                point.y * height,
                argtypes=(ctypes.c_double, ctypes.c_double),
            )
            _objc.send(correction, "setValue:forKey:", vector, _objc.nsstring(key), argtypes=(_objc.id, _objc.id), restype=None)
        flat = _objc.send(correction, "valueForKey:", _objc.nsstring("outputImage"), argtypes=(_objc.id,))
        if not flat:
            raise MacOSError("the perspective could not be corrected")
        return _objc.ciimage_png(flat)


def _feature_print(image: Image) -> int:
    """A retained ``VNFeaturePrintObservation`` (+1) for ``image``."""
    with _objc.autorelease_pool():
        observations = _perform(image, _objc.new("VNGenerateImageFeaturePrintRequest"))
        if not observations:
            raise MacOSError("no feature print for this image")
        return _objc.send(observations[0], "retain")


def _distance(first: int, second: int) -> float:
    value = ctypes.c_float()
    error = ctypes.c_void_p()
    ok = _objc.send(
        first,
        "computeDistance:toFeaturePrintObservation:error:",
        ctypes.byref(value),
        second,
        ctypes.byref(error),
        argtypes=(ctypes.c_void_p, _objc.id, ctypes.c_void_p),
        restype=BOOL,
    )
    if not ok:
        raise _error(error, "the images could not be compared")
    return round(float(value.value), 4)


def image_distance(first: Image, second: Image) -> float:
    """
    How different two images look: 0.0 for the same picture, growing as they differ.

    Measured on photos, a resized or re-compressed copy scores below 0.15 and
    unrelated photos around 0.7 to 0.9. Very small images (a few hundred
    pixels) score less reliably. See :func:`duplicates` to group a whole folder.
    """
    _load()
    one, two = _feature_print(first), _feature_print(second)
    try:
        return _distance(one, two)
    finally:
        _objc.send(one, "release", restype=None)
        _objc.send(two, "release", restype=None)


def duplicates(images: Sequence[Image], *, threshold: float = 0.3) -> List[List[Image]]:
    """
    Group images that look like the same picture: copies, resized or re-saved versions, burst shots.

    Returns only the groups with two or more images, each in the order given.
    Two images are grouped when their :func:`image_distance` is below
    ``threshold``; raise it to also group similar (not identical) shots::

        from pathlib import Path

        photos = sorted(Path("~/Pictures/Trip").expanduser().glob("*.jpg"))
        for group in macos.vision.duplicates(photos):
            print("Same picture:", [photo.name for photo in group])

    Every image is compared with every other, so thousands of images take a while.
    """
    if threshold <= 0:
        raise ValueError("threshold must be positive, not {}".format(threshold))
    _load()
    prints: List[int] = []
    try:
        for image in images:
            prints.append(_feature_print(image))
        parent = list(range(len(images)))

        def root(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for first in range(len(images)):
            for second in range(first + 1, len(images)):
                if _distance(prints[first], prints[second]) < threshold:
                    parent[root(second)] = root(first)
    finally:
        for observation in prints:
            _objc.send(observation, "release", restype=None)

    groups: dict = {}
    for index, image in enumerate(images):
        groups.setdefault(root(index), []).append(image)
    return [group for group in groups.values() if len(group) > 1]


def _face_quality(image: Image) -> Optional[float]:
    """The mean capture quality of the faces in ``image`` (0.0 to 1.0), or ``None`` without faces."""
    with _objc.autorelease_pool():
        scores = []
        for face in _perform(image, _objc.new("VNDetectFaceCaptureQualityRequest")):
            quality = _objc.send(face, "faceCaptureQuality")
            if quality:
                scores.append(float(_objc.send(quality, "floatValue", restype=ctypes.c_float)))
    return sum(scores) / len(scores) if scores else None


def best_shot(images: Sequence[Image]) -> Optional[Image]:
    """
    Pick the photo where the faces look best: sharp, well lit, eyes open, facing the camera.

    Returns one of ``images``, or ``None`` when none has a face. With several
    people in a photo, their faces count equally. Pairs well with
    :func:`duplicates`, to keep one photo of each burst::

        for group in macos.vision.duplicates(photos):
            keep = macos.vision.best_shot(group) or group[0]
    """
    if not images:
        raise ValueError("best_shot() needs at least one image")
    _load()
    best: Optional[Image] = None
    best_score = -1.0
    for image in images:
        score = _face_quality(image)
        if score is not None and score > best_score:
            best, best_score = image, score
    return best


def horizon(image: Image) -> Optional[float]:
    """
    How tilted a photo's horizon is, in degrees: positive when it rises to the right (turned counter-clockwise).

    Returns ``None`` when there's no horizon to find, when it's level (less
    than about 1.5°), and when it's tilted too much to tell (more than about
    10°). :func:`macos.image.straighten` levels the photo::

        if macos.vision.horizon("beach.jpg"):
            macos.image.straighten("beach.jpg", "beach-level.jpg")
    """
    _load()
    with _objc.autorelease_pool():
        observations = _perform(image, _objc.new("VNDetectHorizonRequest"))
        if not observations:
            return None
        # Vision gives the angle that levels the photo: the tilt, the other way round.
        angle = float(_objc.send(observations[0], "angle", restype=ctypes.c_double))
    return round(-math.degrees(angle), 2)


def smart_crop(image: Image, width: int, height: int) -> bytes:
    """
    Crop and scale an image to ``width`` x ``height`` pixels, keeping its most interesting part.

    Vision finds where the eye goes (a face, an animal, the main object) and the
    crop is centred there, instead of on the middle of the picture. Useful for
    thumbnails and avatars::

        Path("thumb.png").write_bytes(macos.vision.smart_crop("portrait.jpg", 300, 300))

    The image is never scaled up: when the crop is smaller than ``width`` x
    ``height``, the result keeps the crop's own size, with the same proportions.
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive, not {} x {}".format(width, height))
    _refuse_pdf(image)
    _load()
    with _objc.autorelease_pool():
        picture = _objc.ciimage(image)
        extent = _objc.send(picture, "extent", restype=_objc.CGRect)
        full_width, full_height = extent.size.width, extent.size.height

        # Where to centre the crop: the salient objects' bounding box, or the
        # middle of the picture when nothing stands out.
        center_x, center_y = 0.5, 0.5
        observations = _perform_on(picture, _objc.new("VNGenerateAttentionBasedSaliencyImageRequest"))
        if observations:
            boxes = [
                _objc.send(item, "boundingBox", restype=_objc.CGRect)
                for item in _objc.nsarray(_objc.send(observations[0], "salientObjects"))
            ]
            if boxes:
                left = min(box.origin.x for box in boxes)
                right = max(box.origin.x + box.size.width for box in boxes)
                bottom = min(box.origin.y for box in boxes)
                top = max(box.origin.y + box.size.height for box in boxes)
                center_x, center_y = (left + right) / 2, (bottom + top) / 2

        # The largest crop with the requested proportions that fits the image.
        ratio = width / height
        crop_width = min(full_width, full_height * ratio)
        crop_height = crop_width / ratio
        x = min(max(center_x * full_width - crop_width / 2, 0.0), full_width - crop_width)
        y = min(max(center_y * full_height - crop_height / 2, 0.0), full_height - crop_height)
        rect = _objc.CGRect(_objc.CGPoint(extent.origin.x + x, extent.origin.y + y), _objc.CGSize(crop_width, crop_height))
        cropped = _objc.send(picture, "imageByCroppingToRect:", rect, argtypes=(_objc.CGRect,))

        scale = min(width / crop_width, 1.0)
        # Move the crop to the origin, then scale it.
        moved = _objc.send(
            cropped,
            "imageByApplyingTransform:",
            _objc.CGAffineTransform(scale, 0, 0, scale, -rect.origin.x * scale, -rect.origin.y * scale),
            argtypes=(_objc.CGAffineTransform,),
        )
        return _objc.ciimage_png(moved)


@dataclass(frozen=True)
class Aesthetics:
    """How good a photo looks, as Photos judges it."""

    score: float
    """From -1.0 (poor) to 1.0 (great): focus, exposure, composition..."""
    utility: bool
    """
    Whether it's a "utility" picture rather than a memory: a screenshot, a
    photo of a receipt or a document... as Apple's model judges it, so not
    every picture of text counts.
    """


def aesthetics(image: Image) -> Aesthetics:
    """
    Score how good a photo looks, and tell whether it's a "utility" picture (screenshot, receipt, document).

    The score goes from -1.0 to 1.0. Handy with :func:`duplicates` and
    :func:`best_shot` to keep the best photos, or to tell screenshots and
    receipts apart from real photos::

        photos = [path for path in Path("~/Pictures/Trip").expanduser().glob("*.jpg")]
        best = sorted(photos, key=lambda path: macos.vision.aesthetics(path).score, reverse=True)[:10]

    Needs macOS 15 or later.
    """
    _load()
    try:
        _objc.cls("VNCalculateImageAestheticsScoresRequest")
    except LookupError:
        raise NotSupportedError("aesthetics() needs macOS 15 or later") from None
    with _objc.autorelease_pool():
        observations = _perform(image, _objc.new("VNCalculateImageAestheticsScoresRequest"))
        if not observations:
            raise MacOSError("the photo could not be scored")
        return Aesthetics(
            score=round(float(_objc.send(observations[0], "overallScore", restype=ctypes.c_float)), 3),
            utility=bool(_objc.send(observations[0], "isUtility", restype=BOOL)),
        )


Joint = Tuple[float, float, float]
"""``(x, y, confidence)``: fractions of the image from its top-left corner, and how sure Vision is (0 to 1)."""


@dataclass(frozen=True)
class Pose:
    """The body of one person in an image."""

    joints: Dict[str, Joint]
    """
    Each joint Vision found, by name: ``nose``, ``left_eye``, ``right_eye``,
    ``left_ear``, ``right_ear``, ``neck``, ``left_shoulder``,
    ``right_shoulder``, ``left_elbow``, ``right_elbow``, ``left_wrist``,
    ``right_wrist``, ``root`` (the middle of the hips), ``left_hip``,
    ``right_hip``, ``left_knee``, ``right_knee``, ``left_ankle`` and
    ``right_ankle``. Left and right are the person's own.
    """
    confidence: float


@dataclass(frozen=True)
class Hand:
    """One hand in an image."""

    side: Optional[str]
    """``'left'`` or ``'right'`` (the person's own), or ``None`` when Vision can't tell."""
    joints: Dict[str, Joint]
    """
    Each joint Vision found, by name: ``wrist``, then for each finger
    (``thumb``, ``index``, ``middle``, ``ring``, ``little``) its joints from
    the palm out and its ``tip``: ``thumb_cmc``, ``thumb_mp``, ``thumb_ip``,
    ``thumb_tip``, ``index_mcp``, ``index_pip``, ``index_dip``,
    ``index_tip``...
    """
    confidence: float


_BODY_JOINTS = (
    "Nose LeftEye RightEye LeftEar RightEar Neck LeftShoulder RightShoulder LeftElbow RightElbow "
    "LeftWrist RightWrist Root LeftHip RightHip LeftKnee RightKnee LeftAnkle RightAnkle"
).split()
_HAND_JOINTS = ["Wrist"] + [
    finger + joint
    for finger, joints in (
        ("Thumb", ("CMC", "MP", "IP", "Tip")),
        ("Index", ("MCP", "PIP", "DIP", "Tip")),
        ("Middle", ("MCP", "PIP", "DIP", "Tip")),
        ("Ring", ("MCP", "PIP", "DIP", "Tip")),
        ("Little", ("MCP", "PIP", "DIP", "Tip")),
    )
    for joint in joints
]


def _snake(name: str) -> str:
    """``LeftShoulder`` -> ``left_shoulder``; ``ThumbCMC`` -> ``thumb_cmc``."""
    import re

    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).lower()


@lru_cache(maxsize=None)
def _joint_names(prefix: str, names: Tuple[str, ...]) -> Dict[str, str]:
    """Vision's key for each joint (``"VNHLKWRI"``...) -> its readable name."""
    library = framework("Vision")
    found = {}
    for name in names:
        try:
            key = _objc.pystring(ctypes.c_void_p.in_dll(library, prefix + name).value)
        except ValueError:
            continue
        if key:
            found[key] = _snake(name)
    return found


def _joints(observation: int, group: str, names: Dict[str, str]) -> Dict[str, Joint]:
    error = ctypes.c_void_p()
    group_key = ctypes.c_void_p.in_dll(framework("Vision"), group).value
    points = _objc.send(
        observation,
        "recognizedPointsForJointsGroupName:error:",
        group_key,
        ctypes.byref(error),
        argtypes=(_objc.id, ctypes.c_void_p),
    )
    found: Dict[str, Joint] = {}
    if not points:
        return found
    for key in _objc.nsarray(_objc.send(points, "allKeys")):
        point = _objc.send(points, "objectForKey:", key, argtypes=(_objc.id,))
        confidence = float(_objc.send(point, "confidence", restype=ctypes.c_float))
        if confidence <= 0:
            continue  # not seen
        location = _objc.send(point, "location", restype=_objc.CGPoint)
        name = names.get(_objc.pystring(key) or "", _objc.pystring(key) or "")
        # Vision measures from the bottom-left corner.
        found[name] = (round(location.x, 4), round(1.0 - location.y, 4), round(confidence, 3))
    return found


def body_pose(image: Image) -> List[Pose]:
    """
    Find the people in an image and where their joints are: head, shoulders, elbows, wrists, hips, knees, ankles.

    Returns one :class:`Pose` per person. Each joint is ``(x, y,
    confidence)``, as fractions of the image from its top-left corner, so a
    raised hand is one whose wrist is above the shoulder::

        for person in macos.vision.body_pose("dance.jpg"):
            wrist, shoulder = person.joints.get("right_wrist"), person.joints.get("right_shoulder")
            if wrist and shoulder and wrist[1] < shoulder[1]:
                print("a raised right hand")

    It finds bodies; it doesn't tell who they are. Needs macOS 11 or later.
    """
    _load()
    try:
        _objc.cls("VNDetectHumanBodyPoseRequest")
    except LookupError:
        raise NotSupportedError("body_pose() needs macOS 11 or later") from None
    names = _joint_names("VNHumanBodyPoseObservationJointName", tuple(_BODY_JOINTS))
    with _objc.autorelease_pool():
        return [
            Pose(
                joints=_joints(observation, "VNHumanBodyPoseObservationJointsGroupNameAll", names),
                confidence=_confidence(observation),
            )
            for observation in _perform(image, _objc.new("VNDetectHumanBodyPoseRequest"))
        ]


def hand_pose(image: Image, *, max_hands: int = 4) -> List[Hand]:
    """
    Find hands in an image and where their joints are: the wrist and each finger's joints and tip.

    Returns up to ``max_hands`` :class:`Hand` objects, with the ``side``
    (``'left'`` or ``'right'``) when Vision can tell. Joints are ``(x, y,
    confidence)`` as in :func:`body_pose`. A thumbs-up, for instance, has the
    thumb tip well above the other fingertips::

        for hand in macos.vision.hand_pose("photo.jpg"):
            print(hand.side, hand.joints.get("index_tip"))

    Needs macOS 11 or later.
    """
    if max_hands < 1:
        raise ValueError("max_hands must be at least 1, not {}".format(max_hands))
    _load()
    try:
        _objc.cls("VNDetectHumanHandPoseRequest")
    except LookupError:
        raise NotSupportedError("hand_pose() needs macOS 11 or later") from None
    names = _joint_names("VNHumanHandPoseObservationJointName", tuple(_HAND_JOINTS))
    sides = {-1: "left", 1: "right"}  # VNChirality
    found = []
    with _objc.autorelease_pool():
        request = _objc.new("VNDetectHumanHandPoseRequest")
        _objc.send(request, "setMaximumHandCount:", max_hands, argtypes=(_objc.NSUInteger,), restype=None)
        for observation in _perform(image, request):
            responds = _objc.send(
                observation, "respondsToSelector:", _objc.sel("chirality"), argtypes=(_objc.SEL,), restype=BOOL
            )
            side = sides.get(int(_objc.send(observation, "chirality", restype=NSInteger))) if responds else None
            found.append(
                Hand(
                    side=side,
                    joints=_joints(observation, "VNHumanHandPoseObservationJointsGroupNameAll", names),
                    confidence=_confidence(observation),
                )
            )
    return found
