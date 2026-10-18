# Power

{mod}`macos.power` reads the battery, keeps the Mac awake while your code
runs, and tells what else keeps it awake.

## Battery

```python
import macos

battery = macos.power.battery()
battery.percent          # 87
battery.charging         # True
battery.plugged_in       # True
battery.time_remaining   # datetime.timedelta(seconds=2700), or None
battery.cycle_count      # 532
battery.health           # 80 (percent of the original capacity)
```

{func}`~macos.power.battery` returns `None` on a Mac without a battery, such as
a Mac mini or an iMac.

`health` is the battery's maximum capacity compared with when it was new: the
full charge it holds now over its design capacity. System Settings › Battery ›
Battery Health applies its own correction to that, so it can show a point or
two more.

`time_remaining` is the time until the battery is empty, or until it's full
while charging. It's `None` while macOS is still estimating it, and when the
Mac is plugged in but not charging (full, or holding the charge).

## Low Power Mode

```python
macos.power.low_power_mode()   # True when on (System Settings › Battery)
```

Low Power Mode makes the Mac slower to save energy, so a long job can check
it and lighten its work, like {func}`macos.system.thermal_state`. It's always
`False` before macOS 12, which didn't have it.

## Keeping the Mac awake

{func}`~macos.power.keep_awake` stops the Mac from going to sleep while a block
runs, like the `caffeinate` command:

```python
with macos.power.keep_awake():
    train_model()   # takes hours; the Mac won't sleep meanwhile
```

It also works as an `async with` block, and as a decorator:

```python
@macos.power.keep_awake()
def backup():
    ...

@macos.power.keep_awake()
async def sync_photos():
    ...   # the Mac stays awake while the coroutine is awaited
```

A generator function can't be decorated (it raises `TypeError`); use a `with`
block inside it instead.

By default the display can still turn off. Pass `display=True` to keep it on
too, for example while showing a dashboard:

```python
with macos.power.keep_awake(display=True):
    run_dashboard()
```

The `reason` argument, a string, names the request in `pmset -g assertions`
and in Activity Monitor. Closing a laptop's lid still puts it to sleep.

## What keeps the Mac awake

{func}`~macos.power.sleep_blockers` answers "why doesn't my Mac sleep?": the
processes holding it awake, oldest first, as `pmset -g assertions` lists them.

```python
for blocker in macos.power.sleep_blockers():
    print(blocker.process, blocker.reason, blocker.display)
# powerd          Powerd - Prevent sleep while display is on   False
# Google Chrome   Video Wake Lock                               True
# caffeinate      caffeinate command-line tool                  False
```

Each {class}`~macos.power.SleepBlocker` has the process (`pid`, `process`),
what it says it's doing (`reason`), the macOS name of the request (`kind`),
whether it keeps the display on too (`display`), since when (`since`) and,
when it gives up by itself, until when (`until`). macOS itself shows up as
`powerd` while the display is on; apps playing sound or video,
{func}`~macos.power.keep_awake` and `caffeinate` are the usual others, and
File or Screen Sharing serving someone, or a Time Machine backup. Some of these
(Time Machine's among them) keep the Mac awake only on AC power: like `pmset`,
the list has them on battery too.

## Sleeping

```python
macos.power.sleep()           # put the Mac to sleep now
macos.power.sleep_display()   # turn the display off; the Mac keeps running
```

With the default setting (a password is required right after the display turns
off), {func}`~macos.power.sleep_display` also locks the screen.

## The charger

{func}`~macos.power.adapter` tells about the charger the Mac is plugged into,
or `None` on battery and on a desktop Mac:

```python
macos.power.adapter()   # Adapter(watts=96, name='96W USB-C Power Adapter', manufacturer='Apple Inc.', ...)
```

A charger weaker than the Mac's own charges it slowly, or not at all while
it's busy.

## Reference

- {func}`macos.power.battery`
- {func}`macos.power.low_power_mode`
- {class}`macos.power.Battery`
- {func}`macos.power.keep_awake`
- {func}`macos.power.sleep_blockers`
- {class}`macos.power.SleepBlocker`
- {func}`macos.power.sleep`
- {func}`macos.power.sleep_display`
- {class}`macos.power.Adapter`
- {func}`macos.power.adapter`
