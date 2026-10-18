# Mouse

{mod}`macos.mouse` reads where the pointer is, moves it, clicks, drags and
scrolls.

```python
import macos

macos.mouse.position()                       # (512.0, 384.0)
macos.mouse.move(100, 200)

macos.mouse.click()                          # where the pointer is
macos.mouse.click(300, 400, button="right")

macos.mouse.scroll(5)                        # 5 lines down
```

Positions are in points from the top-left corner of the main display, the
same as {func}`macos.screenshot`'s `region` and {class}`macos.screen.Display`.
Moving, clicking, dragging and scrolling need the
[Accessibility permission](permissions.md#accessibility); reading the position
and the mouse settings needs none.

## Moving and clicking

```python
macos.mouse.move(800, 600, duration=0.5)   # glide there in half a second
macos.mouse.click(button="middle")
macos.mouse.click(400, 300, count=2)       # double-click
```

Apps see a real mouse: hover effects and tooltips react. `button` is `"left"`
(the default), `"right"` or `"middle"`. For a Shift-click or a Cmd-click, hold
the key with {func}`macos.keyboard.hold`:

```python
with macos.keyboard.hold("cmd"):
    macos.mouse.click(200, 300)
```

## Clicking on text

{func}`~macos.mouse.click_text` finds some text on the screen, ignoring case,
clicks the middle of the first match from the top, and returns it as a
{class}`~macos.screen.TextMatch`, so a script doesn't depend on where a button
is:

```python
macos.mouse.click_text("Accept")
macos.mouse.click_text("Download", timeout=30)   # wait for it to show up first
```

It raises {class}`~macos.MacOSError` when the text isn't on the screen. It needs
the [Screen Recording permission](permissions.md#screen-recording) too.
`button` and `count` work as in {func}`~macos.mouse.click`; `region`, `display`
and `languages` as in {func}`macos.screen.find_text`, which tells how the text
is found; `languages` is a list, such as `["en-US"]`, and a single string raises
`TypeError`.

## Dragging

{func}`~macos.mouse.drag` holds a button from where the pointer is to another
point, to move windows, select text or drop files:

```python
macos.mouse.move(100, 100)
macos.mouse.drag(500, 100, duration=0.5)
```

The button is always released at the end. If the drag is interrupted (Ctrl-C),
it is released where the pointer stopped, so nothing is dropped at the target.

## Scrolling

{func}`~macos.mouse.scroll` scrolls what is under the pointer by a number of
lines. Positive values scroll down, towards the end, and negative values up;
`horizontal=True` scrolls right (positive) or left (negative):

```python
macos.mouse.scroll(10)
macos.mouse.scroll(-3, horizontal=True)
```

Keys held with {func}`macos.keyboard.hold` apply, as they do to clicks:

```python
with macos.keyboard.hold("cmd"):
    macos.mouse.scroll(-3)                   # Cmd-scroll: zooms in many apps
```

## Watching clicks

{func}`~macos.mouse.watch` yields a {class}`~macos.mouse.Click` each time a mouse
button goes down, in any app, with where, which button, and whether it's a
double-click:

```python
for click in macos.mouse.watch():
    print(click.x, click.y, click.button, click.count)
```

It only listens: the clicks still reach the apps. It needs the [Input Monitoring
permission](permissions.md#input-monitoring). It goes on until you `break` out of
the loop or `timeout` seconds pass (a negative or NaN `timeout` raises
`ValueError`); another thread can stop it by calling `close()` on what
`watch()` returned.

## Mouse settings

{func}`~macos.mouse.set_tracking_speed` sets how fast the pointer moves with a
mouse, from 0.0 to 1.0, like the slider in System Settings › Mouse; it takes
effect at the next login. A speed set by hand beyond the slider (such as `-1`
with `defaults write`) reads as the nearer end, 0.0 or 1.0. For the trackpad,
see [Trackpad](trackpad.md).

```python
macos.mouse.tracking_speed()        # 0.333
macos.mouse.set_tracking_speed(0.8)
```

{func}`~macos.mouse.set_scroll_speed` sets how fast the wheel scrolls, as
macOS keeps it: 0.3125 by default, higher is faster; it too waits for the
next login. {func}`~macos.mouse.set_double_click_speed` sets how many seconds
apart two clicks can be and still count as a double click, 0.5 by default,
for the mouse and the trackpad; apps pick it up when they're reopened:

```python
macos.mouse.set_scroll_speed(1.0)
macos.mouse.set_double_click_speed(0.3)   # quicker clicks
```

{func}`~macos.mouse.set_acceleration` turns pointer acceleration off, so the
pointer moves in proportion to the mouse, as gamers and designers like, or
on again. It needs macOS 14 or later, applies at once, and stays after a
restart:

```python
macos.mouse.set_acceleration(False)
```

## Reference

- {func}`macos.mouse.position`
- {func}`macos.mouse.move`
- {func}`macos.mouse.click`
- {func}`macos.mouse.drag`
- {func}`macos.mouse.scroll`
- {func}`macos.mouse.has_permission`
- {func}`macos.mouse.request_permission`
- {func}`macos.mouse.has_listen_permission`
- {func}`macos.mouse.request_listen_permission`
- {func}`macos.mouse.click_text`
- {func}`macos.mouse.watch`
- {class}`macos.mouse.Click`
- {func}`macos.mouse.tracking_speed`
- {func}`macos.mouse.set_tracking_speed`
- {func}`macos.mouse.scroll_speed`
- {func}`macos.mouse.set_scroll_speed`
- {func}`macos.mouse.double_click_speed`
- {func}`macos.mouse.set_double_click_speed`
- {func}`macos.mouse.acceleration`
- {func}`macos.mouse.set_acceleration`
