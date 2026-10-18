# Trackpad

{mod}`macos.trackpad` changes the trackpad settings of System Settings ›
Trackpad: tap to click, the scroll direction and the pointer speed.

```python
import macos

macos.trackpad.set_tap_to_click(True)
macos.trackpad.set_natural_scrolling(False)   # the classic direction
macos.trackpad.set_tracking_speed(0.7)        # from 0.0 to 1.0
```

## Settings

| Read | Change | Values |
|---|---|---|
| {func}`~macos.trackpad.tap_to_click` | {func}`~macos.trackpad.set_tap_to_click` | `True` clicks with a tap, without pressing |
| {func}`~macos.trackpad.natural_scrolling` | {func}`~macos.trackpad.set_natural_scrolling` | `True` moves the content with the fingers; mice follow it too |
| {func}`~macos.trackpad.secondary_click` | {func}`~macos.trackpad.set_secondary_click` | `"two_fingers"`, `"bottom_right"`, `"bottom_left"` (a corner) or `None` |
| {func}`~macos.trackpad.three_finger_drag` | {func}`~macos.trackpad.set_three_finger_drag` | drag windows and text with three fingers, without pressing |
| {func}`~macos.trackpad.click_pressure` | {func}`~macos.trackpad.set_click_pressure` | `"light"`, `"medium"` or `"firm"`, like the Click slider |
| {func}`~macos.trackpad.tracking_speed` | {func}`~macos.trackpad.set_tracking_speed` | 0.0 (slowest) to 1.0 (fastest), like the slider; a speed set by hand past its ends reads as 0.0 or 1.0 |

Tap to click and the scroll direction apply at once; the pointer speed at the
next login. Three-finger dragging clashes with the three-finger swipes: set
those to four fingers in System Settings › Trackpad › More Gestures. They cover the built-in trackpad and a Magic Trackpad alike. No
permission is needed. For a mouse's speed, see
{func}`macos.mouse.set_tracking_speed`.

## Gestures

{func}`~macos.trackpad.set_gesture` turns each gesture of System Settings ›
Trackpad › Scroll & Zoom and More Gestures on or off:

```python
macos.trackpad.set_gesture("pinch_to_zoom", False)
macos.trackpad.set_gesture("mission_control", 4)   # swipe up with four fingers
macos.trackpad.gestures()   # {'pinch_to_zoom': False, 'mission_control': 4, 'launchpad': True, ...}
```

The names are in {data}`~macos.trackpad.GESTURES`: `swipe_between_pages`,
`pinch_to_zoom`, `rotate`, `smart_zoom`, `notification_center`,
`swipe_between_full_screen_apps`, `mission_control`, `app_expose`,
`launchpad` and `show_desktop`. The swipes between full-screen apps and up
to Mission Control take the number of fingers, `3` or `4` (`True` is 3), or
`False` to turn them off: four frees
three fingers for three-finger drag. App Exposé swipes down with the fingers
Mission Control swipes up with, as in System Settings: moving one moves the
other, and the swipe stays while either is on. Moving the full-screen apps off
three fingers leaves a three-finger "swipe between pages" alone. Changing the
Dock's gestures restarts the Dock.

## Reference

- {func}`macos.trackpad.tap_to_click`
- {func}`macos.trackpad.set_tap_to_click`
- {func}`macos.trackpad.natural_scrolling`
- {func}`macos.trackpad.set_natural_scrolling`
- {func}`macos.trackpad.tracking_speed`
- {func}`macos.trackpad.set_tracking_speed`
- {func}`macos.trackpad.three_finger_drag`
- {func}`macos.trackpad.set_three_finger_drag`
- {func}`macos.trackpad.secondary_click`
- {func}`macos.trackpad.set_secondary_click`
- {func}`macos.trackpad.click_pressure`
- {func}`macos.trackpad.set_click_pressure`
- {data}`macos.trackpad.GESTURES`
- {func}`macos.trackpad.gestures`
- {func}`macos.trackpad.set_gesture`
