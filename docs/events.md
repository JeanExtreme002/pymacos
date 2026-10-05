# Events

{mod}`macos.events` runs your functions when something happens on the Mac:
it goes to sleep or wakes up, the screen locks, an app opens or quits, a disk
is plugged in.

```python
import macos

macos.events.on("wake", lambda event: macos.notify("Welcome back"))
macos.events.on("app_launched", lambda event: print(event.app.name, "opened"))
macos.events.on("power_disconnected", lambda: macos.notify("Running on battery"))
macos.events.run()   # until macos.events.stop() or Ctrl-C
```

They are the notifications macOS sends apps, so no permission is needed.

## Events

| Name | When | Details |
|---|---|---|
| `sleep`, `wake` | The Mac goes to sleep, and wakes up | |
| `display_sleep`, `display_wake` | The displays turn off, and on | |
| `screen_locked`, `screen_unlocked` | The screen locks, and unlocks | |
| `space_changed` | Another Space (desktop) or full-screen app is shown | |
| `app_launched`, `app_quit`, `app_activated` | An app opens, quits, or comes to the front | `event.app`, an {class}`~macos.apps.App` |
| `app_hidden`, `app_unhidden` | An app is hidden (⌘H), or shown again | `event.app` |
| `volume_mounted`, `volume_unmounted` | A disk, USB drive or disk image is mounted or ejected | `event.path`, where it's mounted |
| `power_connected`, `power_disconnected` | The Mac starts, or stops, running on its charger (never on a Mac without a battery) | |
| `network_changed` | Another Wi-Fi network, a cable plugged in, offline or back online | |
| `usb_connected`, `usb_disconnected` | A USB device is plugged in, or removed | `event.device`, its name |
| `displays_changed` | A display is connected, removed, rearranged or set to another resolution | |

To wait for dark or light mode to switch, see
{func}`macos.appearance.wait_for_change`.

Each callback gets an {class}`~macos.events.Event`, or nothing if it takes no
arguments; the event's `name` tells events apart when one callback handles
several:

```python
def log(event):
    print(event.name, event.app.name if event.app else "")

for name in ("app_launched", "app_quit"):
    macos.events.on(name, log)

macos.events.run()
```

{func}`~macos.events.run` calls the callbacks one at a time, on the thread
that called it, which must be the main thread: macOS delivers these events
there. It returns after {func}`~macos.events.stop` or `timeout` seconds; an
exception in a callback stops it and propagates, as does one met while
reading an event. With no callbacks registered, it raises `ValueError`.
{func}`~macos.events.stop` stops every {func}`~macos.events.run` and
{func}`~macos.events.wait` in progress, including one still starting; each
of them gets every event, even when several run on different threads.
{func}`~macos.events.on` returns a {class}`~macos.events.Handler`, whose
`remove()` unregisters it; {func}`~macos.events.off` removes every callback of
an event.

## Waiting for an event

{func}`~macos.events.wait` blocks until an event happens, and returns it:

```python
macos.events.wait("screen_unlocked")
macos.say("Welcome back")

usb = macos.events.wait("volume_mounted", timeout=60)
if usb:
    print("Plugged in:", usb.path)
```

## Reference

- {func}`macos.events.on`
- {func}`macos.events.off`
- {func}`macos.events.run`
- {func}`macos.events.stop`
- {func}`macos.events.wait`
- {class}`macos.events.Event`
- {class}`macos.events.Handler`
- {data}`macos.events.NAMES`
