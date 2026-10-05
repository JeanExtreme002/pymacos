# -*- coding: utf-8 -*-

"""
A minimal Objective-C bridge over ctypes.

Just enough of the runtime to message Cocoa objects without PyObjC:
``send(obj, "selector:", arg, argtypes=(...), restype=...)``.

``objc_msgSend`` is a trampoline, not a real variadic function: on arm64 it
must be called through a prototype whose argument and return types match the
method exactly, or arguments land in the wrong registers. That is why every
call names its ``argtypes``/``restype`` instead of relying on ctypes defaults.
"""

import ctypes
import os
import platform
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator, Optional, Sequence

from . import _cf
from ._system import framework, require_macos

id = ctypes.c_void_p
SEL = ctypes.c_void_p
Class = ctypes.c_void_p
NSUInteger = ctypes.c_ulong
NSInteger = ctypes.c_long
BOOL = ctypes.c_bool


@lru_cache(maxsize=None)
def _libobjc() -> ctypes.CDLL:
    require_macos()
    lib = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    # Foundation defines NSString, NSArray and NSBundle, which the helpers
    # below use directly. Load it explicitly instead of relying on AppKit (or
    # the interpreter) having pulled it in already.
    framework("Foundation")

    lib.objc_getClass.argtypes = (ctypes.c_char_p,)
    lib.objc_getClass.restype = Class
    lib.sel_registerName.argtypes = (ctypes.c_char_p,)
    lib.sel_registerName.restype = SEL
    lib.objc_autoreleasePoolPush.argtypes = ()
    lib.objc_autoreleasePoolPush.restype = ctypes.c_void_p
    lib.objc_autoreleasePoolPop.argtypes = (ctypes.c_void_p,)
    lib.objc_autoreleasePoolPop.restype = None
    return lib


def _needs_stret(restype: Any) -> bool:
    """
    Whether a method returning ``restype`` must go through ``objc_msgSend_stret``.

    On x86_64, structs larger than 16 bytes (a CGRect, for example) come back
    through a hidden pointer, which plain ``objc_msgSend`` doesn't handle.
    arm64 has no such variant: ``objc_msgSend`` covers every return type.
    """
    return (
        platform.machine() == "x86_64"
        and isinstance(restype, type)
        and issubclass(restype, ctypes.Structure)
        and ctypes.sizeof(restype) > 16
    )


@lru_cache(maxsize=None)
def _prototype(restype: Any, argtypes: Sequence[Any]) -> Any:
    signature = ctypes.CFUNCTYPE(restype, id, SEL, *argtypes)
    # Declaring the struct return type makes ctypes pass the hidden pointer
    # itself, which is exactly the calling convention _stret expects.
    entry = _libobjc().objc_msgSend_stret if _needs_stret(restype) else _libobjc().objc_msgSend
    address = ctypes.cast(entry, ctypes.c_void_p).value
    assert address is not None
    return signature(address)


@lru_cache(maxsize=None)
def cls(name: str) -> int:
    """Look up an Objective-C class by name."""
    pointer = _libobjc().objc_getClass(name.encode())
    if not pointer:
        raise LookupError("Objective-C class {!r} is not loaded".format(name))
    return pointer


@lru_cache(maxsize=None)
def sel(name: str) -> int:
    """Register (or look up) a selector by name."""
    return _libobjc().sel_registerName(name.encode())


def send(receiver: Optional[int], selector: str, *args: Any, argtypes: Sequence[Any] = (), restype: Any = id) -> Any:
    """Send ``selector`` to ``receiver`` and return the result as ``restype``."""
    if len(args) != len(argtypes):
        raise TypeError("send({!r}) got {} arguments but {} argtypes".format(selector, len(args), len(argtypes)))
    return _prototype(restype, tuple(argtypes))(receiver, sel(selector), *args)


@contextmanager
def autorelease_pool() -> Iterator[None]:
    """Drain autoreleased Cocoa objects created inside the block."""
    lib = _libobjc()
    pool = lib.objc_autoreleasePoolPush()
    try:
        yield
    finally:
        lib.objc_autoreleasePoolPop(pool)


NSUTF8StringEncoding = 4


def nsstring(text: str) -> int:
    """
    Create an autoreleased ``NSString`` from a Python string.

    Built from an explicit byte length, not a C string, so an embedded NUL
    character is kept instead of silently ending the string.
    """
    raw = text.encode("utf-8")
    string = send(cls("NSString"), "alloc")
    string = send(
        string,
        "initWithBytes:length:encoding:",
        raw,
        len(raw),
        NSUTF8StringEncoding,
        argtypes=(ctypes.c_char_p, NSUInteger, NSUInteger),
    )
    return send(string, "autorelease")


def pystring(obj: Optional[int]) -> Optional[str]:
    """Convert an ``NSString`` to a Python string (``None`` stays ``None``), NUL characters included."""
    if not obj:
        return None
    data = send(obj, "dataUsingEncoding:", NSUTF8StringEncoding, argtypes=(NSUInteger,))
    if not data:
        return None
    length = send(data, "length", restype=NSUInteger)
    return ctypes.string_at(send(data, "bytes", restype=ctypes.c_void_p), length).decode("utf-8") if length else ""


def nsdata(payload: bytes) -> int:
    """Create an autoreleased ``NSData`` holding a copy of ``payload``."""
    return send(
        cls("NSData"), "dataWithBytes:length:", payload, len(payload), argtypes=(ctypes.c_char_p, NSUInteger)
    )


def pybytes(obj: Optional[int]) -> Optional[bytes]:
    """Copy the contents of an ``NSData`` into Python bytes (``None`` stays ``None``)."""
    if not obj:
        return None
    length = send(obj, "length", restype=NSUInteger)
    return ctypes.string_at(send(obj, "bytes", restype=ctypes.c_void_p), length) if length else b""


def nsarray(obj: Optional[int]) -> Iterator[int]:
    """Iterate over the elements of an ``NSArray``."""
    if not obj:
        return
    for index in range(send(obj, "count", restype=NSUInteger)):
        yield send(obj, "objectAtIndex:", index, argtypes=(NSUInteger,))


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


def nsarray_of(objects: Sequence[int]) -> int:
    """Create an autoreleased ``NSArray`` holding ``objects``."""
    items = (ctypes.c_void_p * len(objects))(*objects)
    return send(cls("NSArray"), "arrayWithObjects:count:", items, len(objects), argtypes=(ctypes.c_void_p, NSUInteger))


def file_url(path: "os.PathLike[str] | str") -> int:
    """Create an autoreleased file ``NSURL`` for ``path``."""
    return send(cls("NSURL"), "fileURLWithPath:", nsstring(os.fspath(path)), argtypes=(id,))


def error_message(error: ctypes.c_void_p) -> Optional[str]:
    """The ``localizedDescription`` of an ``NSError`` out-parameter, or ``None`` if none was set."""
    return pystring(send(error.value, "localizedDescription")) if error.value else None


def png(rep: int) -> bytes:
    """Encode an ``NSBitmapImageRep`` as PNG bytes."""
    data = send(
        rep,
        "representationUsingType:properties:",
        4,  # NSBitmapImageFileTypePNG
        send(cls("NSDictionary"), "dictionary"),
        argtypes=(NSUInteger, id),
    )
    return pybytes(data) or b""


def new(class_name: str) -> int:
    """``[[class_name alloc] init]``, autoreleased."""
    return send(send(send(cls(class_name), "alloc"), "init"), "autorelease")


def cgimage_png(image: Optional[int]) -> bytes:
    """Encode an owned ``CGImage`` as PNG bytes, then release it. Needs AppKit loaded."""
    if not image:
        raise ValueError("no image to encode")
    try:
        rep = send(cls("NSBitmapImageRep"), "alloc")
        rep = send(rep, "initWithCGImage:", image, argtypes=(ctypes.c_void_p,))
        send(rep, "autorelease")
        return png(rep)
    finally:
        _cf.release(image)


class CGAffineTransform(ctypes.Structure):
    _fields_ = [(name, ctypes.c_double) for name in ("a", "b", "c", "d", "tx", "ty")]


def ciimage(image: "bytes | bytearray | os.PathLike[str] | str") -> int:
    """
    An autoreleased ``CIImage`` of an image file or its bytes, turned upright.

    The EXIF orientation is applied, so a portrait photo comes out standing.
    Loads AppKit and CoreImage.
    """
    framework("AppKit")
    core_image = framework("CoreImage")
    options = send(
        cls("NSDictionary"),
        "dictionaryWithObject:forKey:",
        send(cls("NSNumber"), "numberWithBool:", True, argtypes=(BOOL,)),
        ctypes.c_void_p.in_dll(core_image, "kCIImageApplyOrientationProperty").value,
        argtypes=(id, id),
    )
    if isinstance(image, (bytes, bytearray)):
        picture = send(cls("CIImage"), "imageWithData:options:", nsdata(bytes(image)), options, argtypes=(id, id))
        label = "the image"
    else:
        path = os.path.abspath(os.path.expanduser(os.fspath(image)))
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        picture = send(cls("CIImage"), "imageWithContentsOfURL:options:", file_url(path), options, argtypes=(id, id))
        label = path
    if not picture:
        raise ValueError("{} is not an image macOS can read".format(label))
    return picture


@lru_cache(maxsize=None)
def _color_space_model() -> Any:
    """``CGColorSpaceGetModel``, declared once: CoreGraphics' handle is shared."""
    function = framework("CoreGraphics").CGColorSpaceGetModel
    function.argtypes = (ctypes.c_void_p,)
    function.restype = ctypes.c_int
    return function


def ciimage_cgimage(image: int) -> int:
    """
    Render a ``CIImage`` into an owned ``CGImage``.

    RGB pixels keep the image's own color space (Display P3 for iPhone
    photos, for example) instead of being squeezed into sRGB.
    """
    context = send(cls("CIContext"), "contextWithOptions:", None, argtypes=(id,))
    extent = send(image, "extent", restype=CGRect)
    space = send(image, "colorSpace", restype=ctypes.c_void_p)
    if space and _color_space_model()(space) == 1:  # kCGColorSpaceModelRGB
        rgba8 = ctypes.c_int.in_dll(framework("CoreImage"), "kCIFormatRGBA8").value
        rendered = send(
            context,
            "createCGImage:fromRect:format:colorSpace:",
            image,
            extent,
            rgba8,
            space,
            argtypes=(id, CGRect, ctypes.c_int, ctypes.c_void_p),
            restype=ctypes.c_void_p,
        )
    else:
        rendered = send(context, "createCGImage:fromRect:", image, extent, argtypes=(id, CGRect), restype=ctypes.c_void_p)
    if not rendered:
        raise ValueError("the image could not be drawn")
    return int(rendered)


def ciimage_png(image: int) -> bytes:
    """Render a Core Image ``CIImage`` into PNG bytes. Needs AppKit and CoreImage loaded."""
    return cgimage_png(ciimage_cgimage(image))


# Blocks, classes made at run time and waiting on the run loop: what the APIs
# that answer through callbacks (permissions, camera, microphone) need.


class _BlockDescriptor(ctypes.Structure):
    _fields_ = [("reserved", ctypes.c_ulong), ("size", ctypes.c_ulong), ("signature", ctypes.c_char_p)]


class _BlockLiteral(ctypes.Structure):
    _fields_ = [
        ("isa", ctypes.c_void_p),
        ("flags", ctypes.c_int),
        ("reserved", ctypes.c_int),
        ("invoke", ctypes.c_void_p),
        ("descriptor", ctypes.POINTER(_BlockDescriptor)),
    ]


_BLOCK_IS_GLOBAL = 1 << 28  # never copied to the heap: the memory below is used as is
_BLOCK_HAS_SIGNATURE = 1 << 30

# The Python objects behind each block, kept alive as long as the process
# runs: an API may call a block (or keep it) after the call that took it returns.
_KEEP_ALIVE: list = []


def block(function: Any, signature: bytes, *argtypes: Any) -> int:
    """
    An Objective-C block that calls ``function`` with the block's arguments, for APIs that take one.

    ``signature`` is the block's type encoding, such as ``b"v@?c"`` for
    ``void (^)(BOOL)``; ``argtypes`` are the ctypes of its arguments. The
    block lives for the rest of the process, so make few of them.
    """
    invoke = ctypes.CFUNCTYPE(None, ctypes.c_void_p, *argtypes)(lambda _block, *arguments: function(*arguments))
    descriptor = _BlockDescriptor(0, ctypes.sizeof(_BlockLiteral), signature)
    global_block = ctypes.c_void_p.in_dll(ctypes.CDLL("/usr/lib/libSystem.B.dylib"), "_NSConcreteGlobalBlock")
    literal = _BlockLiteral(
        ctypes.addressof(global_block),
        _BLOCK_IS_GLOBAL | _BLOCK_HAS_SIGNATURE,
        0,
        ctypes.cast(invoke, ctypes.c_void_p),
        ctypes.pointer(descriptor),
    )
    _KEEP_ALIVE.append((invoke, descriptor, literal))
    return ctypes.addressof(literal)


_CLASSES: dict = {}


def define_class(name: str, methods: Any, protocols: Sequence[str] = ()) -> int:
    """
    Create (once) an ``NSObject`` subclass whose methods are Python functions, and return it.

    ``methods`` maps a selector to ``(type encoding, ctypes function type,
    function)``; each function gets ``(self, _cmd, *arguments)``. Used for
    the delegates the camera and microphone APIs call back.
    """
    if name in _CLASSES:
        return int(_CLASSES[name][0])
    lib = _libobjc()
    lib.objc_allocateClassPair.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t)
    lib.objc_allocateClassPair.restype = ctypes.c_void_p
    lib.class_addMethod.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
    lib.class_addMethod.restype = ctypes.c_bool
    lib.objc_registerClassPair.argtypes = (ctypes.c_void_p,)
    lib.objc_registerClassPair.restype = None
    lib.objc_getProtocol.argtypes = (ctypes.c_char_p,)
    lib.objc_getProtocol.restype = ctypes.c_void_p
    lib.class_addProtocol.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    lib.class_addProtocol.restype = ctypes.c_bool
    lib.objc_getClass.argtypes = (ctypes.c_char_p,)
    new_class = lib.objc_allocateClassPair(cls("NSObject"), name.encode(), 0)
    if not new_class:  # already made, by another copy of this module
        existing = lib.objc_getClass(name.encode())
        _CLASSES[name] = (existing, [])
        return int(existing)
    implementations = []
    for selector, (types, function_type, function) in methods.items():
        implementation = function_type(function)
        implementations.append(implementation)
        lib.class_addMethod(new_class, sel(selector), ctypes.cast(implementation, ctypes.c_void_p), types.encode())
    for protocol in protocols:
        found = lib.objc_getProtocol(protocol.encode())
        if found:
            lib.class_addProtocol(new_class, found)
    lib.objc_registerClassPair(new_class)
    _CLASSES[name] = (new_class, implementations)
    return int(new_class)


def spin(seconds: float) -> None:
    """
    Turn this thread's run loop once, for up to ``seconds``, inside an autorelease pool.

    The pool drains what the callbacks run meanwhile autoreleased, so a
    listener turning the run loop for hours doesn't grow. A run loop with
    nothing to wait for comes back at once: then just pause.
    """
    with autorelease_pool():
        if not _cf.run_loop(seconds):
            time.sleep(seconds)


def run_until(done: Any, timeout: float) -> bool:
    """
    Spin the current thread's run loop until ``done()`` is true or ``timeout`` seconds pass; return ``done()``.

    Callbacks scheduled on the main queue (the camera's, for example) only
    run while the main thread's run loop turns, which a script never does.
    """
    deadline = time.monotonic() + timeout
    while not done():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # No pool here: what the callbacks hand over (to camera's delegate,
        # say) must outlive the slice, until the caller's own pool drains it.
        if not _cf.run_loop(min(0.05, remaining), once=False):
            time.sleep(min(0.05, remaining))
    return bool(done())
