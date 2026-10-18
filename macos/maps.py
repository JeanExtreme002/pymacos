# -*- coding: utf-8 -*-

"""
Turn an address into coordinates, and coordinates into an address, as Maps does.

::

    place = macos.maps.geocode("20 W 34th St, New York, NY")[0]
    place.latitude, place.longitude          # (40.748479, -73.985411)
    macos.maps.reverse_geocode(48.8584, 2.2945).city   # 'Paris'

Goes through Apple's geocoding service (``CLGeocoder``): it needs the
internet but no permission, not even Location. Apple limits how many
requests an app makes in a short time: space out large batches.
"""

import ctypes
import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import quote, urlencode

from . import _files, _objc
from ._system import framework, require_macos, run as _run
from .errors import MacOSError, WaitTimeoutError

__all__ = [
    "Place",
    "geocode",
    "reverse_geocode",
    "open",
    "directions",
]

# kCLErrorDomain's codes.
_NETWORK, _NOT_FOUND = 2, 8


class _Coordinate(ctypes.Structure):
    _fields_ = [("latitude", ctypes.c_double), ("longitude", ctypes.c_double)]


@dataclass(frozen=True)
class Place:
    """A place found by :func:`geocode` or :func:`reverse_geocode`. Parts macOS doesn't know are ``None``."""

    name: Optional[str]
    """Such as ``'Eiffel Tower'`` or ``'1 Infinite Loop'``."""
    street: Optional[str]
    """The street, with the number when there's one: ``'Unter den Linden 77'``."""
    city: Optional[str]
    state: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]
    country_code: Optional[str]
    """ISO 3166 code, such as ``'BR'``."""
    latitude: float
    longitude: float
    time_zone: Optional[str]
    """Such as ``'America/Sao_Paulo'``."""


# One geocoding request at a time, as CLGeocoder allows; its answer lands in _answers.
_lock = threading.Lock()
_CANCELED = 10  # kCLErrorGeocodeCanceled: only a request that was canceled answers so
_DRAIN = 5.0  # seconds to wait for a canceled request's answer, to discard it
# Requests given up on (timed out, or interrupted) whose one answer hasn't come yet. The block is
# shared, so their answers can't be told apart from a new request's: the next answers are theirs.
_abandoned = [0]


def _check_point(latitude: float, longitude: float) -> None:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("latitude must be from -90 to 90 and longitude from -180 to 180, not {}, {}".format(latitude, longitude))


def _text(placemark: int, key: str) -> Optional[str]:
    return _objc.pystring(_objc.send(placemark, key)) or None


def _place(placemark: int) -> Place:
    location = _objc.send(placemark, "location")
    point = _objc.send(location, "coordinate", restype=_Coordinate)
    # The postal address writes the street as each country does: "1 Infinite Loop", "Unter den Linden 77".
    address = _objc.send(placemark, "postalAddress")
    street = _objc.pystring(_objc.send(address, "street")) if address else None
    zone = _objc.send(placemark, "timeZone")
    return Place(
        name=_text(placemark, "name"),
        street=street or _text(placemark, "thoroughfare"),
        city=_text(placemark, "locality"),
        state=_text(placemark, "administrativeArea"),
        postal_code=_text(placemark, "postalCode"),
        country=_text(placemark, "country"),
        country_code=_text(placemark, "ISOcountryCode"),
        latitude=round(point.latitude, 6),
        longitude=round(point.longitude, 6),
        time_zone=_objc.pystring(_objc.send(zone, "name")) if zone else None,
    )


Answer = Tuple[List[Place], Optional[Tuple[int, str]]]
# An exception, when the answer couldn't be read: the caller gets it, not a timeout.
_answers: List[Union[Answer, Exception]] = []


def _answer(found: List[Place], failure: Optional[Tuple[int, str]]) -> None:
    """File an answer for the request waiting, unless it's a canceled request's, which nobody waits for."""
    if failure and failure[0] == _CANCELED:
        return
    _answers.append((found, failure))


@lru_cache(maxsize=None)
def _handler() -> int:
    """The completion block, ``void (^)(NSArray<CLPlacemark *> *, NSError *)``, made once: blocks live for good."""

    def done(placemarks: Optional[int], error: Optional[int]) -> None:
        if _abandoned[0]:
            _abandoned[0] -= 1  # a request given up on: canceled or not, nobody waits for it
            return
        try:
            failure = None
            if error:
                code = int(_objc.send(error, "code", restype=ctypes.c_long))
                if code == _CANCELED:
                    return  # a canceled request's answer, which nobody waits for: not even read
                failure = (code, _objc.pystring(_objc.send(error, "localizedDescription")) or "")
            # Read everything now: the placemarks go away with the block's call.
            found = [_place(placemark) for placemark in _objc.nsarray(placemarks)] if placemarks else []
        except Exception as problem:  # an exception must not cross back into Objective-C: _ask raises it
            _answers.append(problem)
            return
        _answer(found, failure)

    return _objc.block(done, b"v@?@@", ctypes.c_void_p, ctypes.c_void_p)


def _frameworks() -> None:
    framework("CoreLocation")
    framework("Contacts")  # for the placemarks' postal addresses


def _ask(selector: str, argument: int, timeout: float) -> List[Place]:
    # The answers come on the main queue. The process's main thread, as macOS sees it (pthread_main_np),
    # as camera and the other main-thread APIs check: not Python's idea of it, which can differ.
    _files.require_main_thread("Geocoding")
    with _lock:
        if _abandoned[0]:
            # An interrupted request's answer, still to come: let it land before this request is sent.
            # macOS answers a canceled request at once; one that never answers is given up on.
            _objc.run_until(lambda: not _abandoned[0], _DRAIN)
            _abandoned[0] = 0
        del _answers[:]
        geocoder = _objc.send(_objc.send(_objc.cls("CLGeocoder"), "alloc"), "init")
        try:
            _objc.send(geocoder, selector, argument, _handler(), argtypes=(_objc.id, ctypes.c_void_p), restype=None)
            try:
                answered = _objc.run_until(lambda: bool(_answers), timeout)
            except BaseException:  # Ctrl-C while waiting: the answer must not pass for the next request's
                if not _answers:
                    _abandon(geocoder)
                raise
            if not answered:
                # A request answers once, even canceled: wait for that answer here (it comes at once),
                # so it can't pass for the next request's.
                _abandon(geocoder)
                _objc.run_until(lambda: not _abandoned[0], _DRAIN)
                raise WaitTimeoutError("Apple's geocoding service didn't answer within {} seconds".format(timeout))
        finally:
            _objc.send(geocoder, "release", restype=None)
        answer = _answers.pop()
    if isinstance(answer, Exception):
        raise answer
    found, failure = answer
    return _result(found, failure)


def _abandon(geocoder: int) -> None:
    """Cancel ``geocoder``'s request, whose answer, when it comes, is then dropped."""
    _abandoned[0] += 1
    _objc.send(geocoder, "cancelGeocode", restype=None)


def _check_timeout(timeout: float) -> None:
    # NaN passes "<= 0", and would make the wait endless.
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive number of seconds, not {}".format(timeout))


def _result(found: List[Place], failure: Optional[Tuple[int, str]]) -> List[Place]:
    """The places, or the error the service gave; finding nothing isn't an error."""
    if failure and failure[0] != _NOT_FOUND:
        if failure[0] == _NETWORK:
            raise MacOSError("could not reach Apple's geocoding service (offline, or too many requests): " + failure[1])
        raise MacOSError("geocoding failed: {} (error {})".format(failure[1], failure[0]))
    return found


def geocode(address: str, *, timeout: float = 15) -> List[Place]:
    """
    The places matching ``address``, the likeliest first; ``[]`` when none does.

    ::

        place = macos.maps.geocode("1 Infinite Loop, Cupertino")[0]
        place.latitude, place.longitude      # (37.3318, -122.0302)
        place.city, place.country_code       # ('Cupertino', 'US')

    Any address works, whole or in part, in any language; names come back
    in the system's language. The service guesses rather than give up, so
    check the place's ``country_code`` or ``city`` for vague addresses.
    Raises :class:`~macos.WaitTimeoutError` (a ``TimeoutError``) if the
    service doesn't answer within ``timeout`` seconds, a positive number.
    """
    if not address.strip():
        raise ValueError("address must not be empty")
    _check_timeout(timeout)
    _frameworks()
    with _objc.autorelease_pool():
        return _ask("geocodeAddressString:completionHandler:", _objc.nsstring(address), timeout)


def reverse_geocode(latitude: float, longitude: float, *, timeout: float = 15) -> Optional[Place]:
    """
    The address at ``latitude``, ``longitude``, or ``None`` when macOS finds nothing there.

    Out at sea it's the ocean's name, without an address. ``timeout`` works
    as in :func:`geocode`.

    ::

        macos.maps.reverse_geocode(37.8199, -122.4783).city   # 'San Francisco'
    """
    _check_point(latitude, longitude)
    _check_timeout(timeout)
    _frameworks()
    with _objc.autorelease_pool():
        location = _objc.send(
            _objc.send(_objc.cls("CLLocation"), "alloc"),
            "initWithLatitude:longitude:",
            float(latitude),
            float(longitude),
            argtypes=(ctypes.c_double, ctypes.c_double),
        )
        try:
            found = _ask("reverseGeocodeLocation:completionHandler:", location, timeout)
        finally:
            _objc.send(location, "release", restype=None)
    return found[0] if found else None


# --- The Maps app ---------------------------------------------------------------

Where = Union[str, Place, Tuple[float, float]]
_MODES = {"car": "d", "walk": "w", "transit": "r"}  # Maps' dirflg


def _where(place: Where) -> str:
    """An address, a :class:`Place` or ``(latitude, longitude)``, as Maps' URLs write a place."""
    if isinstance(place, (Place, tuple)):
        latitude, longitude = (place.latitude, place.longitude) if isinstance(place, Place) else place
        _check_point(latitude, longitude)
        return "{},{}".format(_degrees(latitude), _degrees(longitude))
    if not place.strip():
        raise ValueError("the place must not be empty")
    return place


def _degrees(value: float) -> str:
    """``value`` in plain decimals, as Maps reads them: ``'0.00001'``, not ``'1e-05'``; ``'2'`` for 2.0."""
    text = "{:.6f}".format(float(value)).rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _show(query: Dict[str, str]) -> None:
    require_macos()
    _run(["open", "maps://?" + urlencode(query, quote_via=quote)])


def open(place: Where) -> None:
    """
    Show ``place`` in the Maps app: an address, a :class:`Place`, or ``(latitude, longitude)``.

    ::

        macos.maps.open("20 W 34th St, New York, NY")
        macos.maps.open(macos.maps.geocode("Eiffel Tower")[0])
    """
    if isinstance(place, (Place, tuple)):
        query = {"ll": _where(place)}
        name = place.name if isinstance(place, Place) else None
        query["q"] = name or query["ll"]
    else:
        query = {"q": _where(place)}
    _show(query)


def directions(to: Where, start: Optional[Where] = None, *, by: str = "car") -> None:
    """
    Open the Maps app with the route to ``to``, from ``start`` (where the Mac is, by default).

    ::

        macos.maps.directions("Aeroporto de Congonhas", by="transit")
        macos.maps.directions((48.8584, 2.2945), start="Gare du Nord, Paris", by="walk")

    ``by`` is ``"car"``, ``"walk"`` or ``"transit"``. Places are written as
    for :func:`open`. Without ``start``, Maps asks for the Mac's location.
    """
    if by not in _MODES:
        raise ValueError("by must be 'car', 'walk' or 'transit', not {!r}".format(by))
    query = {"daddr": _where(to), "dirflg": _MODES[by]}
    if start is not None:
        query["saddr"] = _where(start)
    _show(query)
