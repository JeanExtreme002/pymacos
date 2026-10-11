# Appearance

{mod}`macos.appearance` tells you whether the system is in Light or Dark mode,
and which accent color the user picked.

```python
import macos

macos.appearance.is_dark()        # True
macos.appearance.mode()           # 'dark' or 'light'
macos.appearance.is_auto()        # True if set to Auto
macos.appearance.accent_color()   # '#007aff'
```

The value is read fresh on every call, so a long-running program sees the user
switching modes, or *Auto* switching at sunset, without restarting.

## Matching your output to the system theme

```python
import matplotlib.pyplot as plt
import macos

plt.style.use("dark_background" if macos.appearance.is_dark() else "default")
```

## Switching modes

{func}`~macos.appearance.set_mode` switches the whole system to `"dark"` or
`"light"`:

```python
macos.appearance.set_mode("dark")
```

It goes through System Events, so the first time macOS asks to allow the app
running Python to control it (see [Permissions](permissions.md#automation)).

## Accent color

{func}`~macos.appearance.accent_color` returns the accent color chosen in
System Settings › Appearance, as a hex string. It's the color of buttons,
checkboxes and selections, so a web view or a plot can use it to look at home:

```python
accent = macos.appearance.accent_color()   # '#007aff'
plt.plot(x, y, color=accent)
```

With *Multicolor* selected, it returns the default blue.

{func}`~macos.appearance.set_accent_color` changes it, by name: one of
{data}`~macos.appearance.ACCENT_COLORS`, `"multicolor"`, `"blue"`, `"purple"`,
`"pink"`, `"red"`, `"orange"`, `"yellow"`, `"green"` or `"graphite"`. Running
apps update at once; a few only when reopened.

```python
macos.appearance.set_accent_color("purple")
```

## Auto mode, the menu bar and scroll bars

{func}`~macos.appearance.set_auto_mode` switches between Light and Dark by the
time of day, like *Auto* in System Settings › Appearance; macOS may apply it
at the next login. {func}`~macos.appearance.set_hide_menu_bar` hides the menu
bar until the pointer reaches the top of the screen:

```python
macos.appearance.set_auto_mode(True)
macos.appearance.set_hide_menu_bar(True)
macos.appearance.menu_bar_hidden()   # True
```

{func}`~macos.appearance.set_scroll_bars` shows scroll bars `"always"`,
`"when_scrolling"`, or `"automatic"`-ally, by the mouse or trackpad:

```python
macos.appearance.set_scroll_bars("always")
```

{func}`~macos.appearance.set_font_smoothing` draws text thinner (`False`), which
some find sharper on external displays that aren't Retina; apps pick it up
when they're reopened.

None of them needs a permission.

## Waiting for a switch

{func}`~macos.appearance.wait_for_change` blocks until the system switches
between Light and Dark mode, and returns the new mode:

```python
while True:
    theme = macos.appearance.wait_for_change()   # 'dark' or 'light'
    restyle(theme)
```

With `timeout`, it raises {class}`~macos.WaitTimeoutError` (a `TimeoutError`) if
nothing changes in time.

## Reference

- {func}`macos.appearance.is_dark`
- {func}`macos.appearance.mode`
- {func}`macos.appearance.set_mode`
- {func}`macos.appearance.is_auto`
- {func}`macos.appearance.accent_color`
- {func}`macos.appearance.wait_for_change`
- {func}`macos.appearance.set_auto_mode`
- {func}`macos.appearance.set_accent_color`
- {data}`macos.appearance.ACCENT_COLORS`
- {func}`macos.appearance.menu_bar_hidden`
- {func}`macos.appearance.set_hide_menu_bar`
- {func}`macos.appearance.scroll_bars`
- {func}`macos.appearance.set_scroll_bars`
- {func}`macos.appearance.font_smoothing`
- {func}`macos.appearance.set_font_smoothing`
