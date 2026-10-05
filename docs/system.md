# System

{mod}`macos.system` tells you about the Mac your code runs on.

```python
import macos

macos.system.version()            # '15.6.1'
macos.system.build()              # '24G90'
macos.system.model()              # 'MacBook Pro'
macos.system.model_identifier()   # 'Mac14,9'
macos.system.processor()          # 'Apple M2 Pro'
macos.system.memory()             # 17179869184 (bytes)
macos.system.computer_name()      # "Alice's MacBook Pro"
macos.system.uptime()             # datetime.timedelta(days=3, seconds=7200)
macos.system.idle_time()          # datetime.timedelta(seconds=312)
```

{func}`~macos.system.memory` is in bytes: divide by `2**30` for GB.
{func}`~macos.system.model` raises {class}`~macos.MacOSError` when macOS
doesn't say, as in some virtual machines.
{func}`~macos.system.uptime` counts from the last restart, including the time
the Mac spent asleep.

## Volumes

{func}`~macos.system.volumes` lists the mounted volumes that Finder shows, and {func}`~macos.system.eject` ejects one:

```python
for volume in macos.system.volumes():
    print(volume.name, volume.free // 2**30, "GB free")

macos.system.eject("Backup")         # by name, by path, or a Volume
```

Each {class}`~macos.system.Volume` has its `name`, mount `path`, `total` and
`free` space in bytes, and whether it `is_internal`, `is_removable` (USB sticks,
SD cards) or `is_ejectable`.

{func}`~macos.system.eject` only accepts ejectable
volumes; when two share a name, pass the path.

A volume that's busy is retried for a few seconds, since macOS can hold one
briefly right after it mounts. If it stays busy, the error carries `diskutil`'s
message, which often names the process that refused. To look yourself,
{func}`~macos.system.who_uses` lists this user's processes using it (system
services such as Spotlight don't show up there). A disk that doesn't answer
for a minute raises {class}`~macos.CommandTimeoutError`.

## Disk images

{func}`~macos.system.mount_image` mounts a `.dmg` (or `.iso`) without opening a
Finder window, and returns where; {func}`~macos.system.unmount_image` unmounts it:

```python
mounted = macos.system.mount_image("~/Downloads/Tool.dmg")   # PosixPath('/Volumes/Tool')
print(list(mounted.iterdir()))
macos.system.unmount_image(mounted)
```

A license the image shows first is accepted. `hdiutil` checks a large image
before mounting it: past `timeout` seconds (5 minutes by default) it's stopped
and {class}`~macos.CommandTimeoutError` raised. An answer from `hdiutil` that
can't be read detaches the image again, and raises {class}`~macos.MacOSError`
with that answer. To install the app it holds, see
{func}`macos.apps.install_from_dmg`.

## Software updates

{func}`~macos.system.available_updates` lists the updates Software Update offers,
as {class}`~macos.system.Update` objects:

```python
for update in macos.system.available_updates():
    print(update.title, update.version, "(restart)" if update.restart else "")
```

It asks Apple's servers, so it takes a while (often 10 to 30 seconds); past
`timeout` seconds (5 minutes by default) it gives up with
{class}`~macos.CommandTimeoutError`. A title with a comma in it stays whole.

## Processor and memory

{func}`~macos.system.cpu_usage` measures how busy the processor is over a short
`interval`, from 0.0 to 1.0, all cores together, and
{func}`~macos.system.memory_usage` how the memory is used, as Activity Monitor
counts it:

```python
macos.system.cpu_usage()            # 0.23
memory = macos.system.memory_usage()
print("{:.0%} used:".format(memory.percent), memory.used // 2**30, "GB of", memory.total // 2**30)
```

`percent` is a fraction, from 0.0 to 1.0, like {func}`~macos.system.cpu_usage`.

## Fonts

{func}`~macos.system.fonts` lists the installed font families, sorted, as apps
show them in their font menus:

```python
families = macos.system.fonts()   # ['Academy Engraved LET', 'American Typewriter', ...]
font = "Avenir" if "Avenir" in families else "Helvetica"
```

## Heat and lid

```python
macos.system.thermal_state()   # 'nominal', 'fair', 'serious' or 'critical' ('unknown' if macOS adds a state)
macos.system.lid_closed()      # True in clamshell mode
```

At `'serious'`, macOS slows the processor down to cool it, so a long job can
wait for it to cool:

```python
import time

while macos.system.thermal_state() in ("serious", "critical"):
    time.sleep(60)
```

{func}`~macos.system.lid_closed` tells whether a MacBook runs with its lid
closed, on an external display. On a Mac without a lid it raises
{class}`~macos.NotSupportedError`.

## Camera and microphone in use

```python
macos.system.camera_in_use()       # True during a video call
macos.system.microphone_in_use()   # True while an app records
```

They match the green camera light and the orange microphone dot in the menu
bar. They don't tell which app, and need no permission. An "on air" light in a
few lines:

```python
import time

while True:
    busy = macos.system.camera_in_use() or macos.system.microphone_in_use()
    set_light(busy)   # your smart plug, LED...
    time.sleep(5)
```

## Running while the user is away

{func}`~macos.system.idle_time` is the time since the last keyboard, mouse or
trackpad input. It lets a script do heavy work only when nobody is using the
Mac:

```python
import time
from datetime import timedelta

while True:
    if macos.system.idle_time() > timedelta(minutes=10):
        run_heavy_job()
    time.sleep(60)
```

{func}`~macos.system.wait_for_idle` waits until nobody has touched the Mac for a
while, and {func}`~macos.system.wait_for_activity` until someone does:

```python
macos.system.wait_for_idle(timedelta(minutes=10))
run_heavy_job()

macos.system.wait_for_activity()
macos.say("Welcome back")
```

Both wait as long as it takes, or return `False` once `timeout` seconds pass.

## System settings

| Read | Change | Values |
|---|---|---|
| {func}`~macos.system.ds_store_on_network` | {func}`~macos.system.set_ds_store_on_network` | `False` stops Finder leaving `.DS_Store` files on network shares |
| {func}`~macos.system.ds_store_on_usb` | {func}`~macos.system.set_ds_store_on_usb` | the same on USB drives and other external disks |
| {func}`~macos.system.keep_windows_on_quit` | {func}`~macos.system.set_keep_windows_on_quit` | `True` makes apps reopen the windows they had |
| {func}`~macos.system.save_to_icloud_by_default` | {func}`~macos.system.set_save_to_icloud_by_default` | iCloud Drive offered first when saving a new document |
| {func}`~macos.system.expanded_save_dialog` | {func}`~macos.system.set_expanded_save_dialog` | the Save dialog opened with the sidebar and every folder |
| {func}`~macos.system.measurement_units` | {func}`~macos.system.set_measurement_units` | `"metric"` or `"us"` |
| {func}`~macos.system.temperature_unit` | {func}`~macos.system.set_temperature_unit` | `"celsius"` or `"fahrenheit"` |
| {func}`~macos.system.open_photos_on_device_connect` | {func}`~macos.system.set_open_photos_on_device_connect` | `False` stops Photos opening when an iPhone or a camera is connected |
| {func}`~macos.system.battery_percentage_shown` | {func}`~macos.system.set_show_battery_percentage` | the percentage next to the battery in the menu bar |

```python
macos.system.set_ds_store_on_network(False)      # colleagues on the share will thank you
macos.system.set_show_battery_percentage(True)
```

The `.DS_Store` settings take effect at the next login; the others at once or
when apps are reopened. No permission is needed.

{func}`~macos.system.set_clock_format` changes the menu bar's clock; the
options left out stay as they are:

```python
macos.system.set_clock_format(seconds=True, date="always")   # date: "auto", "always" or "never"
macos.system.clock_format()   # {'seconds': True, 'day_of_week': True, 'am_pm': True, 'analog': False, 'date': 'always'}
```

It also takes `day_of_week`, `am_pm` and `analog`. Whether it's 12 or 24 hours
follows System Settings › General › Date & Time.

## The menu bar

{func}`~macos.system.set_menu_bar_items` shows or hides Control Center's icons
in the menu bar, and {func}`~macos.system.set_menu_bar_spacing` puts them
closer together, so more fit beside the notch:

```python
macos.system.set_menu_bar_items(bluetooth=True, now_playing=False, focus=False)
macos.system.menu_bar_items()            # {'wifi': True, 'bluetooth': True, 'now_playing': False, ...}
macos.system.set_menu_bar_spacing(6)     # at the next login; None for macOS's own
```

The icons are in {data}`~macos.system.MENU_BAR_ITEMS`, and apply at once.

## Security

{func}`~macos.system.security_status` tells whether the Mac's protections are
on, without an administrator's password, to check a fleet of Macs against
a security policy:

```python
macos.system.security_status()
# SecurityStatus(filevault=True, firewall=False, gatekeeper=True, sip=True)
```

Each is `None` when macOS doesn't say.

## Processes

{func}`~macos.system.processes` lists the running processes, like Activity
Monitor, and {func}`~macos.system.kill` ends one:

```python
biggest = sorted(macos.system.processes(), key=lambda p: p.memory or 0, reverse=True)[:3]
[(p.name, p.memory // 2**20) for p in biggest]   # [('Safari', 1840), ('Code Helper', 950), ...]

macos.system.process(1234).kill()                # asks it to quit, as `kill` does
```

`cpu=True` also measures each process's `cpu_percent` over half a second,
like Activity Monitor's % CPU (over 100 when it uses several cores):

```python
busiest = sorted(macos.system.processes(cpu=True), key=lambda p: p.cpu_percent or 0)[-1]
busiest.name, busiest.cpu_percent   # ('Xcode', 187.5)
```

Each {class}`~macos.system.Process` has its `pid`, `name`, `path`, `user`,
`parent_pid`, `started`, `memory` (in bytes) and `cpu_time`. Other users'
processes, the system's included, come without their memory, processor
time and start, which macOS keeps from this user. `kill(force=True)` ends a
process at once, without letting it save; to quit an app, prefer
{meth}`App.quit() <macos.apps.App.quit>`.

macOS hands a quitted process's pid to a new one sooner or later. So killing
a {class}`~macos.system.Process` checks first that its pid still belongs to
it, by its start time and executable, and raises `ProcessLookupError` if
another process took it. {func}`~macos.system.kill` given a bare pid signals
whatever has that pid now.

## Ports

{func}`~macos.system.ports` lists the ports processes listen on, TCP servers
and bound UDP sockets, and {func}`~macos.system.port_owner` answers "what's
using port 8000?":

```python
for port in macos.system.ports():
    print(port.port, port.protocol, port.address, port.process)   # 5432 tcp 127.0.0.1 postgres

owner = macos.system.port_owner(8000)
if owner:
    owner.kill()   # free the port
```

{func}`~macos.system.port_owner` looks at TCP ports, or UDP ones with
`protocol="udp"`. Like `lsof -i` without `sudo`, other users' processes,
the system's included, are left out.

{func}`~macos.system.connections` lists the connections in progress: which
address and port each process is talking to. Servers waiting for
connections are in {func}`~macos.system.ports`:

```python
for connection in macos.system.connections():
    print(connection.process, connection.remote_address, connection.remote_port, connection.state)
    # Google Chrome 142.250.79.46 443 established
```

## Open files

{func}`~macos.system.who_uses` finds the processes using a file, a folder or
a disk: with it open, or something inside it, working in it, or run from
it. It answers "the disk can't be ejected because it's in use":

```python
for process in macos.system.who_uses("/Volumes/Backup"):
    print(process.name, process.pid)   # Preview 4123
```

{func}`~macos.system.open_files` lists what one process has open. Both see
only this user's processes, like `lsof` without `sudo`.

## Network, energy and disk use

{func}`~macos.system.network_usage` tells how much each process received and
sent over the network, the busiest first, and
{func}`~macos.system.energy_usage` how much power each drew and how much it
read and wrote on disk:

```python
for use in macos.system.network_usage(interval=2)[:5]:
    print(use.process, use.received, use.sent)            # bytes in those 2 seconds

for use in macos.system.energy_usage()[:5]:
    print(use.process, "{:.2f} W".format(use.watts))      # Google Chrome Helper 1.84 W
```

Without `interval`, {func}`~macos.system.network_usage` gives the totals since
each process started, for every user's processes, the system's included.
{func}`~macos.system.energy_usage` measures over one second by default; only
Apple silicon Macs measure power (Intel Macs read 0), and it sees only this
user's processes. A macOS too old to report it raises
{class}`~macos.NotSupportedError`. A `nettop` that doesn't answer within 30
seconds past the interval raises {class}`~macos.CommandTimeoutError`.

## The GPU and the disks

```python
macos.system.gpu_usage()     # [GPUUsage(name='AGXAcceleratorG14X', percent=37, memory=406667264)]

for disk in macos.system.disk_health():
    if disk.smart == "failing":
        print("Back up", disk.name, "now")
```

{func}`~macos.system.gpu_usage` tells how busy each graphics processor is,
as Activity Monitor's GPU History does. {func}`~macos.system.disk_health`
gives each physical disk's SMART status, which warns when a disk is about
to fail: `"verified"`, `"failing"`, or `None` for disks that don't report
one, as most USB disks. A disk that doesn't answer `diskutil` within a minute
raises {class}`~macos.CommandTimeoutError`.

## Crashes and the system log

{func}`~macos.system.crash_reports` lists the crashes macOS recorded, the
latest first, and {func}`~macos.system.logs` reads the system log that
Console shows:

```python
from datetime import datetime, timedelta

for crash in macos.system.crash_reports(since=datetime.now() - timedelta(days=7)):
    print(crash.date, crash.app, crash.reason)   # 2026-09-29 13:55 Safari EXC_BAD_ACCESS (SIGSEGV)

for entry in macos.system.logs(process="Safari", level="error", last="1h"):
    print(entry.date, entry.message)
```

Crash reports keep each report's `path`, to read it whole or send it to the
app's developers. The log is large, thousands of messages a minute: filter
it by `process`, `subsystem`, text (`contains`) or `level`, and `limit`
stops at that many messages (1000 by default). `last` is how far back it
reads: the last 10 minutes by default, or `"30s"`, `"2h"`, `"1d"` or a
{class}`~datetime.timedelta`. Some messages hide private
data as `<private>`. Reading days of an unfiltered log takes long: past
`timeout` seconds (2 minutes by default, `None` for no limit) `log show` is
stopped and {class}`~macos.CommandTimeoutError` raised. With an `app`,
{func}`~macos.system.crash_reports` reads only the first line of other apps'
reports.

## Startup items and USB devices

{func}`~macos.system.startup_items` lists what macOS starts by itself besides
the apps opened at login: launch agents (in the user's session) and
daemons (for the whole system), with what each runs and whether it's
running now:

```python
for item in macos.system.startup_items():
    print(item.kind, item.label, item.running, item.program)
    # agent com.google.keystone.agent False /Library/Google/GoogleSoftwareUpdate/...
```

It leaves out Apple's own, in `/System`. For the apps opened at login, see
{func}`macos.apps.login_items`.

{func}`~macos.system.usb_devices` lists the devices connected over USB, with
their maker, IDs and speed (`"low"` and `"full"` are USB 1, `"high"` USB 2,
`"super"` and `"super_plus"` USB 3):

```python
[(device.name, device.speed) for device in macos.system.usb_devices()]   # [('Portable SSD T7', 'super')]
```

## Reference

- {func}`macos.system.version`
- {func}`macos.system.build`
- {func}`macos.system.model`
- {func}`macos.system.model_identifier`
- {func}`macos.system.processor`
- {func}`macos.system.memory`
- {func}`macos.system.computer_name`
- {func}`macos.system.uptime`
- {func}`macos.system.idle_time`
- {func}`macos.system.volumes`
- {func}`macos.system.eject`
- {func}`macos.system.fonts`
- {func}`macos.system.thermal_state`
- {func}`macos.system.lid_closed`
- {func}`macos.system.camera_in_use`
- {func}`macos.system.microphone_in_use`
- {class}`macos.system.Volume`
- {func}`macos.system.wait_for_idle`
- {func}`macos.system.wait_for_activity`
- {func}`macos.system.mount_image`
- {func}`macos.system.unmount_image`
- {func}`macos.system.available_updates`
- {class}`macos.system.Update`
- {func}`macos.system.cpu_usage`
- {func}`macos.system.memory_usage`
- {class}`macos.system.MemoryUsage`
- {func}`macos.system.ds_store_on_network`
- {func}`macos.system.set_ds_store_on_network`
- {func}`macos.system.ds_store_on_usb`
- {func}`macos.system.set_ds_store_on_usb`
- {func}`macos.system.keep_windows_on_quit`
- {func}`macos.system.set_keep_windows_on_quit`
- {func}`macos.system.battery_percentage_shown`
- {func}`macos.system.set_show_battery_percentage`
- {func}`macos.system.save_to_icloud_by_default`
- {func}`macos.system.set_save_to_icloud_by_default`
- {func}`macos.system.expanded_save_dialog`
- {func}`macos.system.set_expanded_save_dialog`
- {func}`macos.system.clock_format`
- {func}`macos.system.set_clock_format`
- {func}`macos.system.measurement_units`
- {func}`macos.system.set_measurement_units`
- {func}`macos.system.temperature_unit`
- {func}`macos.system.set_temperature_unit`
- {func}`macos.system.open_photos_on_device_connect`
- {func}`macos.system.set_open_photos_on_device_connect`
- {func}`macos.system.menu_bar_spacing`
- {func}`macos.system.set_menu_bar_spacing`
- {data}`macos.system.MENU_BAR_ITEMS`
- {func}`macos.system.menu_bar_items`
- {func}`macos.system.set_menu_bar_items`
- {class}`macos.system.SecurityStatus`
- {func}`macos.system.security_status`
- {class}`macos.system.Process`
- {func}`macos.system.processes`
- {func}`macos.system.process`
- {func}`macos.system.kill`
- {class}`macos.system.Port`
- {func}`macos.system.ports`
- {func}`macos.system.port_owner`
- {class}`macos.system.Connection`
- {func}`macos.system.connections`
- {func}`macos.system.open_files`
- {func}`macos.system.who_uses`
- {class}`macos.system.NetworkUsage`
- {func}`macos.system.network_usage`
- {class}`macos.system.EnergyUsage`
- {func}`macos.system.energy_usage`
- {class}`macos.system.GPUUsage`
- {func}`macos.system.gpu_usage`
- {class}`macos.system.DiskHealth`
- {func}`macos.system.disk_health`
- {class}`macos.system.CrashReport`
- {func}`macos.system.crash_reports`
- {class}`macos.system.LogEntry`
- {func}`macos.system.logs`
- {class}`macos.system.StartupItem`
- {func}`macos.system.startup_items`
- {class}`macos.system.USBDevice`
- {func}`macos.system.usb_devices`
