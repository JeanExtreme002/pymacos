# Menu Bar

{mod}`macos.menubar` puts an icon or a short text in the menu bar, with a menu
of actions: a timer counting down, a status always in view, or your scripts
one click away.

```python
import macos

timer = macos.menubar.Item("☕")

@timer.action("Start 25 minutes")
def start():
    timer.title = "25:00"

timer.add("Reset", lambda: setattr(timer, "title", "☕"))
macos.menubar.run()   # until Quit, macos.menubar.quit() or Ctrl-C
```

It needs no permission and no dependency. The script doesn't show in the Dock
or the app switcher; its items show in the menu bar while
{func}`~macos.menubar.run` runs.

## Items

An {class}`~macos.menubar.Item` shows as soon as it's created. It can have a
`title`, an `icon` (a file path or the bytes of an image), or both, and a
`tooltip` shown when the pointer rests on it. Changing `title` updates the
menu bar at once:

```python
status = macos.menubar.Item(icon="~/icons/bolt.png", tooltip="Battery")
battery = macos.power.battery()                     # None on a Mac without one
status.title = "{}%".format(battery.percent) if battery else None
```

Icons are drawn at the menu bar's height, as a *template* by default: in the
menu bar's color, in light and dark mode alike, so a black PNG with
transparency works best. Pass `template=False` to keep an icon's colors.
{meth}`~macos.menubar.Item.set_icon` changes the icon, or removes it with
`None`, and {meth}`~macos.menubar.Item.remove` takes the item out of the menu
bar.

## Menus

{meth}`~macos.menubar.Item.add` adds an entry that calls a function when it's
clicked, and returns a {class}`~macos.menubar.MenuItem`;
{meth}`~macos.menubar.Item.action` does the same as a decorator.
{meth}`~macos.menubar.Item.separator` adds a line between entries:

```python
item = macos.menubar.Item("Backup")
item.add("Back up now", back_up, key="b")        # ⌘B while the menu is open
item.separator()
paused = item.add("Pause", checked=False)

def pause():
    paused.checked = not paused.checked             # an option that turns on and off

paused.callback = pause
item.add("Last backup: never", enabled=False)       # greyed out: just information
```

A {class}`~macos.menubar.MenuItem`'s `title`, `enabled` and `checked` can be
changed at any time. The menu ends with a *Quit* entry that makes
{func}`~macos.menubar.run` return; `quit=None` leaves it out, and any other
text renames it.

## Running

{func}`~macos.menubar.run` keeps the items responsive until *Quit*,
{func}`~macos.menubar.quit` or `timeout` seconds. Call it on the main thread,
after creating the items. Menu actions run there, one at a time; an exception
in one stops {func}`~macos.menubar.run` and propagates.

{func}`~macos.menubar.every` calls a function every so many seconds while
{func}`~macos.menubar.run` runs, to keep a title current:

```python
import time

countdown = macos.menubar.Item("25:00")
end = time.monotonic() + 25 * 60

def tick():
    left = max(0, int(end - time.monotonic()))
    countdown.title = "{:02d}:{:02d}".format(left // 60, left % 60)
    if not left:
        macos.notify("Time for a break", title="Pomodoro")
        macos.menubar.quit()

macos.menubar.every(1, tick)
macos.menubar.run()
```

Timers pause while a menu is open. Work that takes long belongs in a thread, so
the menu stays responsive: titles and entries can be changed from any thread,
and the change shows when {func}`~macos.menubar.run` next turns, within a
tenth of a second.
