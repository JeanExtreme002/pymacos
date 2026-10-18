"""Unit tests for :mod:`macos.maps`. They run on any platform."""

import threading

import pytest

import macos
from macos import maps

PLACE = maps.Place("Eiffel Tower", "5 Avenue Anatole France", "Paris", "Île-de-France", "75007", "France", "FR",
                   48.8584, 2.2945, "Europe/Paris")  # fmt: skip


def test_results_and_errors():
    assert maps._result([PLACE], None) == [PLACE]
    assert maps._result([], (8, "No result")) == []  # nothing found isn't an error
    with pytest.raises(macos.MacOSError, match="could not reach Apple's geocoding service"):
        maps._result([], (2, "The network is down"))
    with pytest.raises(macos.MacOSError, match="error 10"):
        maps._result([], (10, "Canceled"))


def test_argument_checks():
    with pytest.raises(ValueError, match="address must not be empty"):
        maps.geocode("  ")
    for latitude, longitude in ((91, 0), (0, 181), (-90.5, 0)):
        with pytest.raises(ValueError, match="latitude must be"):
            maps.reverse_geocode(latitude, longitude)


def test_only_the_main_thread_gets_answers():
    failures = []

    def ask():
        try:
            maps._ask("geocodeAddressString:completionHandler:", 0, timeout=1)
        except macos.MacOSError as error:
            failures.append(str(error))

    thread = threading.Thread(target=ask)
    thread.start()
    thread.join()
    assert len(failures) == 1 and failures[0].startswith("Geocoding must run on the main thread")


def test_open_and_directions(fake_run):
    maps.open("Avenida Paulista, 1578, São Paulo")
    assert fake_run.args == ["open", "maps://?q=Avenida%20Paulista%2C%201578%2C%20S%C3%A3o%20Paulo"]
    maps.open(PLACE)
    assert fake_run.args[-1] == "maps://?ll=48.8584%2C2.2945&q=Eiffel%20Tower"
    maps.open((-22.95, -43.21))
    assert fake_run.args[-1] == "maps://?ll=-22.95%2C-43.21&q=-22.95%2C-43.21"
    maps.directions((48.8584, 2.2945), start="Gare du Nord", by="walk")
    assert fake_run.args[-1] == "maps://?daddr=48.8584%2C2.2945&dirflg=w&saddr=Gare%20du%20Nord"
    maps.directions("Congonhas")
    assert fake_run.args[-1] == "maps://?daddr=Congonhas&dirflg=d"
    with pytest.raises(ValueError, match="by must be"):
        maps.directions("Congonhas", by="bike")
    with pytest.raises(ValueError, match="must not be empty"):
        maps.open(" ")


def test_a_canceled_requests_answer_is_dropped(monkeypatch):
    monkeypatch.setattr(maps, "_answers", [])
    maps._answer([], (10, "Canceled"))  # only a canceled request answers so: nobody waits for it
    assert maps._answers == []
    maps._answer([PLACE], None)
    assert maps._answers == [([PLACE], None)]


def test_an_answer_that_cant_be_read_raises_instead_of_timing_out(monkeypatch):
    made = []
    monkeypatch.setattr(maps._objc, "block", lambda function, *types: made.append(function) or 1)
    monkeypatch.setattr(maps, "_handler", maps._handler.__wrapped__)  # a fresh block, not the cached one

    def unreadable(placemarks):
        raise ValueError("a placemark macOS changed")

    monkeypatch.setattr(maps._objc, "nsarray", unreadable)
    monkeypatch.setattr(maps, "_answers", [])
    maps._handler()
    made[0](1, None)  # what macOS calls: it must not raise back into Objective-C

    monkeypatch.setattr(maps._objc, "send", lambda *args, **kwargs: 1)
    monkeypatch.setattr(maps._objc, "cls", lambda name: 1)
    monkeypatch.setattr(maps._objc, "run_until", lambda done, timeout: done())  # answered: no timeout
    answers = list(maps._answers)
    monkeypatch.setattr(maps, "_answers", _Prefilled(answers))
    with pytest.raises(ValueError, match="placemark"):
        maps._ask("geocodeAddressString:completionHandler:", 1, 15)


def test_a_canceled_request_is_dropped_before_its_placemarks_are_read(monkeypatch):
    made = []
    monkeypatch.setattr(maps._objc, "block", lambda function, *types: made.append(function) or 1)
    monkeypatch.setattr(maps, "_handler", maps._handler.__wrapped__)

    def unreadable(placemarks):
        raise ValueError("a placemark macOS changed")

    monkeypatch.setattr(maps._objc, "nsarray", unreadable)
    monkeypatch.setattr(maps._objc, "send", lambda receiver, selector, *args, **kwargs: maps._CANCELED)
    monkeypatch.setattr(maps, "_answers", [])
    maps._handler()
    made[0](1, 2)  # late, canceled, and unreadable: it must not pass for the next request's answer
    assert maps._answers == []


class _Prefilled(list):
    """The answers list, whose ``del [:]`` at the start of a request keeps what the test put in."""

    def __delitem__(self, index):
        pass


def test_timeouts_are_checked():
    for timeout in (float("nan"), float("inf"), 0, -1):
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            maps.geocode("Paris", timeout=timeout)
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            maps.reverse_geocode(48.8584, 2.2945, timeout=timeout)


def test_coordinates_are_written_in_plain_decimals(fake_run):
    maps.open((0.00001, -0.00005))
    assert fake_run.args[-1] == "maps://?ll=0.00001%2C-0.00005&q=0.00001%2C-0.00005"
    maps.directions((-0.0, 2.0), start=(1e-09, 180))
    assert fake_run.args[-1] == "maps://?daddr=0%2C2&dirflg=d&saddr=0%2C180"
    for point in ((91, 0), (0, -181), (float("nan"), 0)):
        with pytest.raises(ValueError, match="latitude must be"):
            maps.open(point)


class _Geocoder:
    """``_objc``'s calls ``_ask`` makes, with ``run_until`` turning a run loop that delivers ``late`` answers."""

    def __init__(self, monkeypatch, wait):
        self.sent = []
        self.late = []  # answers macOS sends on the next turn of the run loop
        made = []
        monkeypatch.setattr(maps._objc, "block", lambda function, *types: made.append(function) or 1)
        monkeypatch.setattr(maps, "_handler", maps._handler.__wrapped__)
        monkeypatch.setattr(maps, "_answers", [])
        monkeypatch.setattr(maps, "_abandoned", [0])
        monkeypatch.setattr(maps._files, "require_main_thread", lambda what: None)
        monkeypatch.setattr(maps._objc, "cls", lambda name: 1)
        monkeypatch.setattr(maps._objc, "nsarray", lambda placemarks: [])
        monkeypatch.setattr(maps._objc, "send", self.send)
        monkeypatch.setattr(maps._objc, "run_until", lambda done, timeout: wait(self, done, timeout))
        maps._handler()
        self.done = made[0]

    def send(self, receiver, selector, *args, **kwargs):
        self.sent.append(selector)
        if selector == "cancelGeocode":
            self.late.append(maps._CANCELED)  # macOS answers a canceled request at once
        return maps._CANCELED if selector == "code" else 1

    def deliver(self):
        while self.late:
            error = self.late.pop(0)
            self.done(1, error or None)


def test_a_timeout_waits_only_for_the_canceled_answer(monkeypatch):
    waits = []

    def wait(geocoder, done, timeout):
        waits.append(timeout)
        geocoder.deliver()
        return done()

    geocoder = _Geocoder(monkeypatch, wait)
    with pytest.raises(macos.WaitTimeoutError, match="within 0.5 seconds"):
        maps._ask("geocodeAddressString:completionHandler:", 1, 0.5)
    assert "cancelGeocode" in geocoder.sent
    assert waits == [0.5, maps._DRAIN] and maps._abandoned == [0]  # the drain ended on the canceled answer


def test_an_interrupted_requests_answer_doesnt_pass_for_the_next(monkeypatch):
    calls = []

    def wait(geocoder, done, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise KeyboardInterrupt
        geocoder.deliver()
        return done()

    geocoder = _Geocoder(monkeypatch, wait)
    with pytest.raises(KeyboardInterrupt):
        maps._ask("geocodeAddressString:completionHandler:", 1, 15)
    assert "cancelGeocode" in geocoder.sent and maps._abandoned == [1]
    # The first request had answered already when it was canceled: a real answer, not "canceled".
    geocoder.late[:] = [0]
    found = []

    def wait_then_answer(geocoder, done, timeout):
        geocoder.deliver()  # the first request's answer, before the second is sent: dropped
        if maps._abandoned == [0] and timeout == 15:
            maps._answers.append((found, None))  # the second request's own answer
        return done()

    monkeypatch.setattr(maps._objc, "run_until", lambda done, timeout: wait_then_answer(geocoder, done, timeout))
    assert maps._ask("geocodeAddressString:completionHandler:", 1, 15) is found
    assert maps._abandoned == [0]
