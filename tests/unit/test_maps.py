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
    assert failures == ["geocoding answers on the main thread: call it from there"]


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
