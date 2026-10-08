# Keyboard

{mod}`macos.keyboard` types text and presses keys and shortcuts in the app in
front, as if typed on the keyboard. It also switches keyboard layouts and
controls the keyboard backlight.

```python
import macos

macos.keyboard.type("Hello, world!")
macos.keyboard.press("enter")
macos.keyboard.press("cmd+shift+4")   # the screenshot shortcut
```

Typing and pressing keys need the [Accessibility permission](permissions.md#accessibility).
Layouts and the backlight need none.

## Typing text

{func}`~macos.keyboard.type` types any text, accents and emoji included,
whatever the keyboard layout. New lines press Enter and tabs press Tab. The
keys {func}`~macos.keyboard.hold` holds down don't apply, so text typed in a
`with hold("cmd")` block comes out as written:

```python
macos.keyboard.type("Hello! 👋\nSecond line")
```

Some apps (remote desktops, games, web forms with autocomplete) lose
keystrokes that arrive too fast. `interval` sets a pause between characters,
in seconds:

```python
macos.keyboard.type("slow and steady", interval=0.05)
```

## Keys and shortcuts

{func}`~macos.keyboard.press` presses a key, or a shortcut with modifiers
joined by `+`:

```python
macos.keyboard.press("cmd+c")          # copy
macos.keyboard.press("cmd+tab")        # switch apps
macos.keyboard.press("down", times=3)
macos.keyboard.press("cmd+plus")       # zoom in
```

- **Modifiers**: `cmd`, `shift`, `option` (or `alt`), `ctrl` and `fn`.
- **Characters** are found on the current keyboard layout, so `"cmd+z"` is
  undo on an AZERTY or Dvorak keyboard too. Letters work in either case:
  add `shift` for Shift.
- **Names**: `enter`, `tab`, `space`, `delete` (backspace), `forward_delete`,
  `escape`, `left`, `right`, `up`, `down`, `home`, `end`, `page_up`,
  `page_down`, `f1` to `f20`, `plus` and `minus`.

The keystrokes go to the app in front: bring one forward first with
{meth}`App.activate() <macos.apps.App.activate>` or {func}`macos.apps.open`.

```python
macos.apps.open("TextEdit")
macos.keyboard.press("cmd+n")
macos.keyboard.type("Written by Python")
```

## Holding keys

{func}`~macos.keyboard.hold` keeps keys down while a `with` block runs, for
Shift-clicks, Cmd-clicks, Option-drags, or a key held in a game:

```python
with macos.keyboard.hold("shift"):
    macos.mouse.click(100, 200)
    macos.mouse.click(100, 400)   # selects everything in between

with macos.keyboard.hold("cmd", "option"):
    macos.mouse.drag(600, 300)
```

Keys are written as for {func}`~macos.keyboard.press`. They are released at
the end of the block, even when it raises, each one even if another fails to
come up. They apply to the clicks and keys of the thread that holds them:
other threads' don't carry them.

## Watching keys

{func}`~macos.keyboard.watch` yields a {class}`~macos.keyboard.KeyPress` for each
key pressed, in any app. Its `shortcut` is written as {func}`~macos.keyboard.press`
takes it:

```python
for key in macos.keyboard.watch():
    print(key.shortcut, repr(key.text))   # cmd+shift+k 'K'
```

A {class}`~macos.keyboard.KeyPress` also has the `key`, its `modifiers`, the
virtual key `code` and whether it's a `repeat` from holding the key down. It
goes on until you `break` out of the loop, or `timeout` seconds pass.

It only listens: the keys still reach the app in front. To take a shortcut for
yourself, see [Hotkeys](hotkeys.md). It needs the [Input Monitoring
permission](permissions.md#input-monitoring), and macOS hides what's typed in
password fields.

## Caps Lock

```python
macos.keyboard.caps_lock()   # True when on
```

Handy to warn before typing a password. It needs no permission.

## Keyboard layouts

```python
macos.keyboard.layouts()          # ['ABC', 'French']
macos.keyboard.layout()           # 'French'
macos.keyboard.set_layout("ABC")
```

{func}`~macos.keyboard.layouts` lists the layouts and input methods enabled in
the menu bar's input menu; add more in System Settings › Keyboard › Text
Input. {func}`~macos.keyboard.set_layout` takes a name from that list, its
identifier (such as `'com.apple.keylayout.ABC'`), or part of its name when
only one layout matches. macOS allows these three on the main thread only:
elsewhere they raise {class}`~macos.errors.MacOSError`.

The same restriction decides which key types each character in
{func}`~macos.keyboard.press` and the [Hotkeys](hotkeys.md) shortcuts.
({func}`~macos.keyboard.type` doesn't depend on it: it sends the text itself,
and works on any thread with any layout.) On another thread, they use the layout the main
thread last read, or the US positions when the layout in use is US-compatible
(US, ABC...). With any other layout they raise
{class}`~macos.errors.MacOSError` instead of pressing the wrong keys: on an
AZERTY keyboard, Cmd+A sent at the US position would be Cmd+Q. Call
{func}`~macos.keyboard.layout` once from the main thread before starting the
thread:

```python
macos.keyboard.layout()      # read on the main thread: other threads can now use it
threading.Thread(target=macos.hotkeys.run).start()
```

## Keyboard backlight

On Macs with a backlit keyboard:

```python
macos.keyboard.brightness()                # 0.4, from 0.0 (off) to 1.0
macos.keyboard.set_brightness(1.0)
macos.keyboard.auto_brightness()           # True: follows the room's light
macos.keyboard.set_auto_brightness(False)
```

With automatic brightness on, macOS keeps adjusting the backlight after
{func}`~macos.keyboard.set_brightness`. On a Mac without a backlit keyboard
these functions raise {class}`~macos.NotSupportedError`.

{func}`~macos.keyboard.set_backlight_timeout` turns the backlight off after some
seconds without use, or never (`None`):

```python
macos.keyboard.set_backlight_timeout(30)
macos.keyboard.backlight_timeout()   # 30.0
```

They use a private macOS framework, since there's no public one.

## Keyboard settings

The settings of System Settings › Keyboard, each with its reader:

| Read | Change | Values |
|---|---|---|
| {func}`~macos.keyboard.key_repeat` | {func}`~macos.keyboard.set_key_repeat` | seconds between repeats of a held key, and before the first |
| {func}`~macos.keyboard.press_and_hold` | {func}`~macos.keyboard.set_press_and_hold` | `True` shows the accents menu (é, ê...) instead of repeating |
| {func}`~macos.keyboard.standard_function_keys` | {func}`~macos.keyboard.set_standard_function_keys` | `True` makes F1, F2... act as function keys without Fn |
| {func}`~macos.keyboard.autocorrect` | {func}`~macos.keyboard.set_autocorrect` | spelling corrected as you type |
| {func}`~macos.keyboard.smart_quotes` | {func}`~macos.keyboard.set_smart_quotes` | `"` typed as “ ” |
| {func}`~macos.keyboard.smart_dashes` | {func}`~macos.keyboard.set_smart_dashes` | `--` typed as — |
| {func}`~macos.keyboard.auto_capitalization` | {func}`~macos.keyboard.set_auto_capitalization` | the first letter of sentences capitalized |
| {func}`~macos.keyboard.fn_key_action` | {func}`~macos.keyboard.set_fn_key_action` | `"emoji"`, `"input_source"`, `"dictation"` or `None`: what Fn (🌐) does alone |
| {func}`~macos.keyboard.inline_predictions` | {func}`~macos.keyboard.set_inline_predictions` | the end of words suggested in gray as you type (macOS 14+) |
| {func}`~macos.keyboard.double_space_period` | {func}`~macos.keyboard.set_double_space_period` | two spaces typed as a period and a space |
| {func}`~macos.keyboard.full_keyboard_access` | {func}`~macos.keyboard.set_full_keyboard_access` | `True` lets Tab reach every control, buttons included |

```python
macos.keyboard.set_key_repeat(0.03, delay=0.225)   # System Settings' fastest
macos.keyboard.set_press_and_hold(False)           # hold j in Vim to move down
macos.keyboard.set_smart_quotes(False)             # code pasted in Notes stays code
```

The function keys and what Fn does apply at once. The key repeat waits for
the next login; the other settings reach apps when they're reopened. No permission is needed.

## Shortcuts for menu items

{func}`~macos.keyboard.set_app_shortcut` gives a menu item a shortcut, as System
Settings › Keyboard › Keyboard Shortcuts › App Shortcuts does, without its
dialog:

```python
macos.keyboard.set_app_shortcut("Safari", "Export as PDF…", "cmd+shift+e")
macos.keyboard.set_app_shortcut("Preview", "File > Export…", "cmd+e")     # the one in the File menu
macos.keyboard.set_app_shortcut(None, "Show Tab Bar", "cmd+option+t")     # in every app
macos.keyboard.app_shortcuts("Safari")    # {'Export as PDF…': 'cmd+shift+e'}
macos.keyboard.set_app_shortcut("Safari", "Export as PDF…", None)         # remove it
```

The title must be exactly the menu's, in the system's language, the
ellipsis (…) included. Keys are written as for
{func}`~macos.keyboard.press`. Apps pick it up when they're reopened.

## macOS's shortcuts

{func}`~macos.keyboard.set_system_shortcut` turns macOS's own shortcuts on and
off, to free them for another app, such as ⌘Space for Raycast or Alfred:

```python
macos.keyboard.set_system_shortcut("spotlight", False)
macos.keyboard.system_shortcuts()   # {'spotlight': False, 'screenshot': True, ...}
```

The names are in {data}`~macos.keyboard.SYSTEM_SHORTCUTS`: `spotlight`,
`finder_search`, the `screenshot` ones, `mission_control`,
`application_windows`, `show_desktop`, `move_left_a_space`,
`move_right_a_space`, the input sources and `dock_hiding`. It applies at once.

## Remapping keys

{func}`~macos.keyboard.remap` makes a key act as another, on every keyboard,
without an app such as Karabiner:

```python
macos.keyboard.remap("caps_lock", "escape")   # a favorite of Vim users
macos.keyboard.remap("right_option", "ctrl")
macos.keyboard.remappings()                   # {'caps_lock': 'escape', 'right_option': 'ctrl'}
macos.keyboard.remap("caps_lock", None)       # Caps Lock again
macos.keyboard.clear_remappings()
```

Keys are named as for {func}`~macos.keyboard.press`, plus the right-hand
modifiers: letters, digits, `f1` to `f20`, the modifiers (`cmd`, `right_cmd`,
`option`, `right_option`, `ctrl`, `right_ctrl`, `shift`, `right_shift`, `fn`), `caps_lock`, `escape`, `enter`,
`tab`, `space`, `delete`, the arrows... It applies at once, with no
permission, and lasts until the Mac restarts: to keep it, run it at login
with [`macos.schedule`](schedule.md).

## Reference

- {func}`macos.keyboard.type`
- {func}`macos.keyboard.press`
- {func}`macos.keyboard.hold`
- {func}`macos.keyboard.caps_lock`
- {func}`macos.keyboard.layouts`
- {func}`macos.keyboard.layout`
- {func}`macos.keyboard.set_layout`
- {func}`macos.keyboard.has_permission`
- {func}`macos.keyboard.request_permission`
- {func}`macos.keyboard.brightness`
- {func}`macos.keyboard.set_brightness`
- {func}`macos.keyboard.auto_brightness`
- {func}`macos.keyboard.set_auto_brightness`
- {func}`macos.keyboard.watch`
- {class}`macos.keyboard.KeyPress`
- {func}`macos.keyboard.key_repeat`
- {func}`macos.keyboard.set_key_repeat`
- {func}`macos.keyboard.press_and_hold`
- {func}`macos.keyboard.set_press_and_hold`
- {func}`macos.keyboard.standard_function_keys`
- {func}`macos.keyboard.set_standard_function_keys`
- {func}`macos.keyboard.autocorrect`
- {func}`macos.keyboard.set_autocorrect`
- {func}`macos.keyboard.smart_quotes`
- {func}`macos.keyboard.set_smart_quotes`
- {func}`macos.keyboard.smart_dashes`
- {func}`macos.keyboard.set_smart_dashes`
- {func}`macos.keyboard.auto_capitalization`
- {func}`macos.keyboard.set_auto_capitalization`
- {func}`macos.keyboard.double_space_period`
- {func}`macos.keyboard.set_double_space_period`
- {func}`macos.keyboard.full_keyboard_access`
- {func}`macos.keyboard.set_full_keyboard_access`
- {func}`macos.keyboard.remap`
- {func}`macos.keyboard.remappings`
- {func}`macos.keyboard.clear_remappings`
- {func}`macos.keyboard.fn_key_action`
- {func}`macos.keyboard.set_fn_key_action`
- {func}`macos.keyboard.inline_predictions`
- {func}`macos.keyboard.set_inline_predictions`
- {func}`macos.keyboard.app_shortcuts`
- {func}`macos.keyboard.set_app_shortcut`
- {data}`macos.keyboard.SYSTEM_SHORTCUTS`
- {func}`macos.keyboard.system_shortcuts`
- {func}`macos.keyboard.set_system_shortcut`
- {func}`macos.keyboard.backlight_timeout`
- {func}`macos.keyboard.set_backlight_timeout`
