# Bluetooth

{mod}`macos.bluetooth` turns Bluetooth on and off, lists the paired devices
with their battery levels, and connects and disconnects them.

```python
import macos

macos.bluetooth.power()   # True

for device in macos.bluetooth.devices():
    print(device.name, device.connected, device.battery)

# AirPods Pro True {'left': 90, 'right': 85, 'case': 40}
# Magic Mouse False {}
```

## Devices

{func}`~macos.bluetooth.devices` returns the devices paired with the Mac,
connected ones first. Each {class}`~macos.bluetooth.Device` has:

- `name`: as shown in the Bluetooth menu.
- `address`: its hardware address, such as `'E4:61:F4:CC:49:B2'`.
- `connected`: whether it's connected now.
- `kind`: what it is, such as `'headphones'`, `'mouse'` or `'keyboard'`.
- `battery`: the levels in percent when the device reports them, such as
  `{'main': 80}`, or `left`, `right` and `case` for AirPods. Empty otherwise.

A low-battery warning in a few lines:

```python
for device in macos.bluetooth.devices():
    if device.connected and any(level < 20 for level in device.battery.values()):
        macos.notify("{} is running out of battery".format(device.name))
```

## Connecting

{func}`~macos.bluetooth.connect` and {func}`~macos.bluetooth.disconnect` take
a {class}`~macos.bluetooth.Device`, its address, its full name, or part of its
name when only one device matches:

```python
macos.bluetooth.connect("AirPods")
macos.audio.set_output("AirPods")      # and play through them
macos.bluetooth.disconnect("AirPods")  # still paired
```

A few accessories are listed without an `address`: they can't be connected
from here, and {func}`~macos.bluetooth.connect` and
{func}`~macos.bluetooth.disconnect` say so (use the Bluetooth menu for them).

Both wait until the device is connected (or disconnected) and return it, so
the next line can count on it. The device must be on and in range; after
`timeout` seconds (10 by default) they raise {class}`~macos.WaitTimeoutError`
(a `TimeoutError`), and {class}`~macos.MacOSError` when Bluetooth is off. Pairing a new device
isn't possible here; do it once in System Settings › Bluetooth.

## Power

```python
macos.bluetooth.set_power(False)
macos.bluetooth.set_power(True)
```

It waits until Bluetooth is really on or off, and raises
{class}`~macos.WaitTimeoutError` (a `TimeoutError`) after `timeout` seconds
(10 by default). Careful on
a desktop Mac: turning it off disconnects a wireless keyboard and mouse. On a
Mac without Bluetooth, {func}`~macos.bluetooth.power` and
{func}`~macos.bluetooth.set_power` raise {class}`~macos.NotSupportedError`.

Switching the power uses a private macOS framework, since there's no public one.

## Reference

- {func}`macos.bluetooth.power`
- {func}`macos.bluetooth.set_power`
- {func}`macos.bluetooth.devices`
- {func}`macos.bluetooth.connect`
- {func}`macos.bluetooth.disconnect`
- {class}`macos.bluetooth.Device`
