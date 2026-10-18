"""Unit tests for :mod:`macos.mouse`. They run on any platform."""

import pytest

import macos


def test_click_and_double_click(fake_events):
    macos.mouse.click(100, 200, count=2)
    macos.mouse.click(button="right")

    clicks = [(event["kind"], event["x"], event["y"], event["clicks"]) for event in fake_events.posted]
    assert clicks == [
        (5, 100, 200, 0),  # moved there first
        (1, 100, 200, 1),
        (2, 100, 200, 1),
        (1, 100, 200, 2),
        (2, 100, 200, 2),
        (3, 10.0, 20.0, 1),  # where the pointer is
        (4, 10.0, 20.0, 1),
    ]


def test_drag_releases_the_button_at_the_end(fake_events, monkeypatch):
    monkeypatch.setattr(macos.mouse.time, "sleep", lambda seconds: None)

    macos.mouse.drag(40, 80, duration=0.05)

    kinds = [event["kind"] for event in fake_events.posted]
    assert kinds[0] == 1 and kinds[-1] == 2
    assert set(kinds[1:-1]) == {6}
    assert (fake_events.posted[-2]["x"], fake_events.posted[-2]["y"]) == (40, 80)


def test_a_glide_takes_its_duration_and_not_a_third_more(fake_events, monkeypatch):
    from macos import _events

    # post() pauses after every event: counted in the pacing, or a 1 s move would take 1.3 s.
    clock = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(macos.mouse.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(macos.mouse.time, "sleep", sleep)
    monkeypatch.setattr(_events, "post", lambda event: clock.__setitem__(0, clock[0] + _events.PAUSE))

    macos.mouse.move(70, 80, duration=1.0)

    assert len(sleeps) == 60 and clock[0] == pytest.approx(101.0)
    assert all(0 <= seconds < 1 / 60 for seconds in sleeps)  # each step short of 1/60 s by the pause post() took

    sleeps.clear()
    macos.mouse.move(0, 0)  # at once: no pacing at all
    assert sleeps == []


def test_scroll_directions(fake_events):
    macos.mouse.scroll(3)
    macos.mouse.scroll(-2, horizontal=True)
    macos.mouse.scroll(0)

    # Core Graphics counts a wheel turned up (or left) as positive.
    assert [(event["vertical"], event["sideways"]) for event in fake_events.posted] == [(-3, 0), (0, 2)]


def test_mouse_argument_checks():
    with pytest.raises(ValueError, match="button"):
        macos.mouse.click(button="side")
    with pytest.raises(ValueError, match="count"):
        macos.mouse.click(count=0)
    with pytest.raises(ValueError, match="both x and y"):
        macos.mouse.click(10)
    with pytest.raises(ValueError, match="duration"):
        macos.mouse.move(1, 1, duration=-1)


def test_click_text_clicks_the_middle_of_the_first_match(monkeypatch):
    from macos import screen

    clicks = []
    monkeypatch.setattr(macos.mouse, "click", lambda x, y, **kwargs: clicks.append((x, y, kwargs)))
    monkeypatch.setattr(screen, "find_text", lambda text, **kwargs: [screen.TextMatch("Send", 10, 20, 40, 10)])

    assert macos.mouse.click_text("send", button="right").center == (30, 25)
    assert clicks == [(30, 25, {"button": "right", "count": 1})]

    waited = []
    monkeypatch.setattr(screen, "wait_for_text", lambda text, timeout, **kwargs: waited.append(timeout))
    with pytest.raises(macos.MacOSError, match="'Send' isn't on the screen"):
        macos.mouse.click_text("Send", timeout=5)
    assert waited == [5]


def test_ctrl_c_after_the_button_goes_down_lets_it_up(fake_events, monkeypatch):
    from macos import _events

    posted = []

    def post(event):
        posted.append(fake_events.events[event]["kind"])
        if posted[-1] == 1 and posted.count(1) == 1:
            raise KeyboardInterrupt  # in the pause after the press

    monkeypatch.setattr(_events, "post", post)
    with pytest.raises(KeyboardInterrupt):
        macos.mouse.click(5, 5)
    assert posted == [5, 1, 2]  # moved, pressed, and let go all the same

    posted.clear()
    with pytest.raises(KeyboardInterrupt):
        post.__dict__.clear()
        macos.mouse.drag(9, 9, duration=0)
    assert posted[0] == 1 and posted[-1] == 2


def test_an_interrupted_drag_lets_go_where_it_stopped(fake_events, monkeypatch):
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt  # in the pause after the third step

    monkeypatch.setattr(macos.mouse.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        macos.mouse.drag(1000, 1000, duration=1.0)

    posted = fake_events.posted
    steps = [event for event in posted if event["kind"] == 6]
    assert len(steps) == 3
    assert posted[-1]["kind"] == 2
    # Released at the last step posted, not at the target, where it would drop what is dragged.
    assert (posted[-1]["x"], posted[-1]["y"]) == (steps[-1]["x"], steps[-1]["y"]) != (1000, 1000)


def test_an_interrupt_in_the_pause_after_a_step_lets_go_at_that_step(fake_events, monkeypatch):
    from macos import _events

    posted = []
    post = _events.post

    def interrupted(event):
        post(event)  # the event is out; post() then pauses, and the interrupt lands there
        posted.append(fake_events.events[event])
        if fake_events.events[event]["kind"] == 6 and sum(e["kind"] == 6 for e in posted) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(macos.mouse.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(_events, "post", interrupted)
    with pytest.raises(KeyboardInterrupt):
        macos.mouse.drag(1000, 1000, duration=1.0)

    steps = [event for event in posted if event["kind"] == 6]
    assert len(steps) == 2
    assert posted[-1]["kind"] == 2
    # Released where the pointer is, at the second step, not one step back.
    assert (posted[-1]["x"], posted[-1]["y"]) == (steps[-1]["x"], steps[-1]["y"])


def test_a_failing_release_does_not_hide_the_interruption(fake_events, monkeypatch):
    from macos import _events

    def post(event):
        raise KeyboardInterrupt if fake_events.events[event]["kind"] == 1 else OSError("release failed")

    monkeypatch.setattr(_events, "post", post)
    with pytest.raises(KeyboardInterrupt):
        macos.mouse.drag(9, 9, duration=0)


def test_non_finite_durations_are_refused_before_anything_is_posted(fake_events):
    for duration in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="duration"):
            macos.mouse.move(1, 1, duration=duration)
        with pytest.raises(ValueError, match="duration"):
            macos.mouse.drag(1, 1, duration=duration)
    assert fake_events.posted == []


def test_scroll_carries_the_keys_held(fake_events):
    with macos.keyboard.hold("cmd"):
        macos.mouse.scroll(3)

    scrolls = [event for event in fake_events.posted if event["kind"] == "scroll"]
    assert [event.get("flags") for event in scrolls] == [1 << 20]  # Cmd-scroll, to zoom


def test_scroll_refuses_lines_that_would_wrap_around(fake_events):
    for lines in (-(2**31), 2**31, 2**33 + 5):
        with pytest.raises(ValueError, match="lines"):
            macos.mouse.scroll(lines)
    assert fake_events.posted == []

    macos.mouse.scroll(-(2**31 - 1))  # the most there is, upwards
    assert fake_events.posted[-1]["vertical"] == 2**31 - 1


def test_settings_refuse_non_finite_values(monkeypatch):
    from macos import defaults

    written = []
    monkeypatch.setattr(defaults, "write", lambda *args: written.append(args))
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="speed"):
            macos.mouse.set_scroll_speed(value)
        with pytest.raises(ValueError, match="seconds"):
            macos.mouse.set_double_click_speed(value)
    assert written == []


@pytest.mark.parametrize("scaling, speed", [(-1, 0.0), (5.0, 1.0), (1.5, 0.5)])
def test_a_hand_set_tracking_speed_reads_within_the_slider(monkeypatch, scaling, speed):
    from macos import _system, defaults

    written = []
    monkeypatch.setattr(defaults, "read", lambda domain, key, default=None: scaling)
    monkeypatch.setattr(defaults, "write", lambda *args: written.append(args[-1]))
    monkeypatch.setattr(_system, "apply_input_settings", lambda: None)

    assert macos.mouse.tracking_speed() == speed
    macos.mouse.set_tracking_speed(macos.mouse.tracking_speed())  # saved and put back, as is
    assert written == [round(speed * 3, 3)]


@pytest.mark.parametrize("stored, on", [("NO", True), ("false", True), ("0", True), (0, True), ("YES", False), (True, False)])
def test_acceleration_reads_a_hand_written_linear_setting_as_macos_does(monkeypatch, stored, on):
    from macos import defaults

    monkeypatch.setattr(defaults, "read", lambda domain, key, default=None: stored)
    assert macos.mouse.acceleration() is on
