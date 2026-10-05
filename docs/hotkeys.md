# Hotkeys

{mod}`macos.hotkeys` runs a function when a keyboard shortcut is pressed, in
any app: global hotkeys for your scripts.

```python
import macos

def take_screenshot():
    macos.screenshot("~/Desktop/shot.png")

macos.hotkeys.register("ctrl+option+s", take_screenshot)
macos.hotkeys.run()   # until macos.hotkeys.stop() or Ctrl-C
```

Listening to the keyboard needs the [Input Monitoring
permission](permissions.md#input-monitoring), and keeping the shortcut from
reaching the app in front needs [Accessibility](permissions.md#accessibility).

## Registering shortcuts

Shortcuts are written as for {func}`macos.keyboard.press`: `"ctrl+option+s"`,
`"cmd+shift+k"`, `"f5"`... Pick ones apps don't use: while
{func}`~macos.hotkeys.run` or {func}`~macos.hotkeys.wait` listens, the app in
front doesn't get them.

```python
macos.hotkeys.register("ctrl+option+p", pause_music)
macos.hotkeys.register("ctrl+option+q", macos.hotkeys.stop)   # a shortcut to quit
macos.hotkeys.run()
```

{func}`~macos.hotkeys.run` calls the callbacks on the thread that called it,
one at a time, until {func}`~macos.hotkeys.stop` or `timeout` seconds; an
exception in a callback stops it and propagates. Holding the keys down doesn't
repeat the call, and registering a shortcut again replaces its callback.
{func}`~macos.hotkeys.unregister` removes a shortcut.

Function keys, arrows, Home, End, Page Up and Down and Forward Delete match
whether or not macOS flags them with Fn, as it does on its own: `"f5"` is
F5 however it's pressed. Write `"fn+f5"` for a shortcut of its own.

{func}`~macos.hotkeys.stop` stops every {func}`~macos.hotkeys.run` and
{func}`~macos.hotkeys.wait` in progress, on any thread, including one still
starting. Several may listen at once: each {func}`~macos.hotkeys.wait` gets
its shortcut, and a callback is called once. An error inside the listener
itself doesn't swallow the keystroke: the key goes on to the app, and the
error comes out of {func}`~macos.hotkeys.run`.

## Waiting for a shortcut

{func}`~macos.hotkeys.wait` blocks until a shortcut is pressed, to start or
pause a script from anywhere:

```python
print("Press Ctrl-Option-S to start")
macos.hotkeys.wait("ctrl+option+s")

if not macos.hotkeys.wait("ctrl+option+y", timeout=10):
    print("No answer")
```

## Reference

- {func}`macos.hotkeys.register`
- {func}`macos.hotkeys.unregister`
- {func}`macos.hotkeys.run`
- {func}`macos.hotkeys.stop`
- {func}`macos.hotkeys.wait`
- {class}`macos.hotkeys.Hotkey`
- {func}`macos.hotkeys.has_permission`
- {func}`macos.hotkeys.request_permission`
