"""Unit tests for the trackpad's settings that share a key or keep a copy for this Mac."""

import pytest

from macos import defaults, dock, trackpad

G = defaults.GLOBAL
T, B = trackpad._TRACKPADS
DOCK = "com.apple.dock"


@pytest.fixture
def store(monkeypatch):
    """The preferences in a dict keyed by (domain, key, current_host)."""
    found = {}

    def read(domain, key=None, *, default=None, current_host=False):
        return found.get((domain, key, current_host), default)

    def write(domain, key, value, *, current_host=False):
        found[(domain, key, current_host)] = value

    monkeypatch.setattr(defaults, "read", read)
    monkeypatch.setattr(defaults, "write", write)
    monkeypatch.setattr(trackpad, "apply_input_settings", lambda: None)
    monkeypatch.setattr(dock, "restart", lambda: None)
    return found


def test_mission_control_off_keeps_app_expose_swipe(store):
    trackpad.set_gesture("mission_control", False)
    assert (T, "TrackpadThreeFingerVertSwipeGesture", False) not in store  # App Exposé still swipes down on it
    assert store[(DOCK, "showMissionControlGestureEnabled", False)] is False
    found = trackpad.gestures()
    assert found["mission_control"] is False and found["app_expose"] is True

    trackpad.set_gesture("app_expose", False)  # both off: the swipe goes
    for domain in (T, B):
        assert store[(domain, "TrackpadThreeFingerVertSwipeGesture", False)] == 0
        assert store[(domain, "TrackpadFourFingerVertSwipeGesture", False)] == 0
    assert store[(G, "com.apple.trackpad.threeFingerVertSwipeGesture", True)] == 0
    assert not trackpad.gestures()["app_expose"]

    trackpad.set_gesture("app_expose", True)  # brings the swipe back, with three fingers
    assert store[(T, "TrackpadThreeFingerVertSwipeGesture", False)] == 2
    assert store[(B, "TrackpadFourFingerVertSwipeGesture", False)] == 2
    found = trackpad.gestures()
    assert found["app_expose"] is True and found["mission_control"] is False


def test_app_expose_reads_off_without_a_vertical_swipe(store):
    for domain in (T, B):  # as left by Mission Control turned off before App Exposé was kept
        store[(domain, "TrackpadThreeFingerVertSwipeGesture", False)] = 0
        store[(domain, "TrackpadFourFingerVertSwipeGesture", False)] = 0
    assert trackpad.gestures()["app_expose"] is False
    trackpad.set_gesture("app_expose", True)
    assert trackpad.gestures()["app_expose"] is True


def test_mission_control_off_with_app_expose_off_drops_the_swipe(store):
    store[(DOCK, "showAppExposeGestureEnabled", False)] = False
    trackpad.set_gesture("mission_control", False)
    assert store[(T, "TrackpadThreeFingerVertSwipeGesture", False)] == 0
    assert store[(T, "TrackpadFourFingerVertSwipeGesture", False)] == 0


def test_full_screen_apps_leave_a_three_finger_page_swipe_alone(store):
    for domain in (T, B):  # "swipe between pages" with three fingers, full-screen apps with four
        store[(domain, "TrackpadThreeFingerHorizSwipeGesture", False)] = 1
        store[(domain, "TrackpadFourFingerHorizSwipeGesture", False)] = 2
    trackpad.set_gesture("swipe_between_full_screen_apps", 4)
    assert store[(T, "TrackpadThreeFingerHorizSwipeGesture", False)] == 1
    trackpad.set_gesture("swipe_between_full_screen_apps", False)
    assert store[(B, "TrackpadThreeFingerHorizSwipeGesture", False)] == 1
    assert store[(B, "TrackpadFourFingerHorizSwipeGesture", False)] == 0
    trackpad.set_gesture("swipe_between_full_screen_apps", 3)  # takes three fingers, as System Settings does
    assert store[(T, "TrackpadThreeFingerHorizSwipeGesture", False)] == 2

    trackpad.set_gesture("swipe_between_full_screen_apps", 4)  # a three-finger gesture of its own is cleared
    assert store[(T, "TrackpadThreeFingerHorizSwipeGesture", False)] == 0


def test_full_screen_apps_move_off_three_fingers_on_a_fresh_mac(store):
    # Unset, the three-finger key is the macOS default: full-screen apps with three fingers.
    assert trackpad.gestures()["swipe_between_full_screen_apps"] == 3
    trackpad.set_gesture("swipe_between_full_screen_apps", 4)
    assert store[(T, "TrackpadThreeFingerHorizSwipeGesture", False)] == 0
    assert trackpad.gestures()["swipe_between_full_screen_apps"] == 4
    trackpad.set_gesture("swipe_between_full_screen_apps", False)
    assert store[(B, "TrackpadThreeFingerHorizSwipeGesture", False)] == 0
    assert trackpad.gestures()["swipe_between_full_screen_apps"] is False


def test_secondary_click_and_notification_center_update_this_macs_copy(store):
    trackpad.set_secondary_click(None)
    assert store[(T, "TrackpadRightClick", False)] is False and store[(B, "TrackpadCornerSecondaryClick", False)] == 0
    assert store[(G, "com.apple.trackpad.enableSecondaryClick", True)] == 0
    trackpad.set_secondary_click("two_fingers")
    assert store[(G, "com.apple.trackpad.enableSecondaryClick", True)] == 1

    trackpad.set_gesture("notification_center", False)
    assert store[(B, "TrackpadTwoFingerFromRightEdgeSwipeGesture", False)] == 0
    assert store[(G, "com.apple.trackpad.twoFingerFromRightEdgeSwipeGesture", True)] == 0
    trackpad.set_gesture("notification_center", True)
    assert store[(G, "com.apple.trackpad.twoFingerFromRightEdgeSwipeGesture", True)] == 3


@pytest.mark.parametrize("scaling, speed", [(5.0, 1.0), (-1, 0.0), (1.5, 0.5)])
def test_tracking_speed_set_by_hand_stays_in_range(store, scaling, speed):
    store[(G, "com.apple.trackpad.scaling", False)] = scaling
    assert trackpad.tracking_speed() == speed
    trackpad.set_tracking_speed(trackpad.tracking_speed())  # the round trip doesn't raise


@pytest.mark.parametrize("off", ["NO", "false", "0", 0, False])
def test_switches_written_by_hand_as_no_read_as_off(store, off):
    store[(T, "Clicking", False)] = off
    store[(G, "com.apple.swipescrolldirection", False)] = off
    store[(T, "TrackpadThreeFingerDrag", False)] = off
    store[(T, "TrackpadRightClick", False)] = off
    store[(G, "AppleEnableSwipeNavigateWithScrolls", False)] = off
    store[(T, "TrackpadPinch", False)] = off
    store[(DOCK, "showLaunchpadGestureEnabled", False)] = off
    store[(DOCK, "showMissionControlGestureEnabled", False)] = off
    assert trackpad.tap_to_click() is False
    assert trackpad.natural_scrolling() is False
    assert trackpad.three_finger_drag() is False
    assert trackpad.secondary_click() is None
    found = trackpad.gestures()
    assert found["swipe_between_pages"] is False and found["pinch_to_zoom"] is False
    assert found["launchpad"] is False and found["mission_control"] is False


def test_switches_written_by_hand_as_yes_read_as_on(store):
    store[(T, "Clicking", False)] = "YES"
    store[(G, "com.apple.swipescrolldirection", False)] = "1"
    store[(T, "TrackpadTwoFingerDoubleTapGesture", False)] = "nonsense"  # unreadable: the default, on
    assert trackpad.tap_to_click() is True
    assert trackpad.natural_scrolling() is True
    assert trackpad.gestures()["smart_zoom"] is True
