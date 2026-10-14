# -*- coding: utf-8 -*-

"""
Core Graphics over ctypes: the bitmap contexts and images several modules draw
with, each signature declared once.

``framework("CoreGraphics")`` is one cached handle, so modules that declared
the same functions each on their own were setting the very same ``argtypes``
again, and could disagree: the last one loaded would win for all of them. A
function more than one module calls is declared here, and they ask
:func:`lib`; one only a single module calls stays declared there.
"""

import ctypes
from functools import lru_cache

from . import _objc
from ._system import framework


@lru_cache(maxsize=None)
def lib() -> ctypes.CDLL:
    graphics = framework("CoreGraphics")
    pointer = ctypes.c_void_p
    signatures = {
        # Bitmap contexts: drawing into memory.
        "CGBitmapContextCreate": (
            (pointer, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, pointer, ctypes.c_uint32),
            pointer,
        ),
        "CGBitmapContextCreateImage": ((pointer,), pointer),
        "CGContextDrawImage": ((pointer, _objc.CGRect, pointer), None),
        "CGContextFillRect": ((pointer, _objc.CGRect), None),
        "CGContextSetRGBFillColor": ((pointer, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double), None),
        "CGContextRelease": ((pointer,), None),
        "CGColorSpaceCreateDeviceRGB": ((), pointer),
        "CGColorSpaceRelease": ((pointer,), None),
        # Images.
        "CGImageGetWidth": ((pointer,), ctypes.c_size_t),
        "CGImageGetHeight": ((pointer,), ctypes.c_size_t),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(graphics, name)
        function.argtypes = argtypes
        function.restype = restype
    return graphics
