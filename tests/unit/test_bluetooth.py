"""Unit tests for :mod:`macos.bluetooth`. They run on any platform."""

import pytest

import macos


_BLUETOOTH = {
    "SPBluetoothDataType": [
        {
            "controller_properties": {"controller_state": "attrib_on"},
            "device_connected": [
                {
                    "AirPods Pro": {
                        "device_address": "aa:bb:cc:dd:ee:01",
                        "device_minorType": "Headphones",
                        "device_batteryLevelLeft": "90%",
                        "device_batteryLevelRight": "85%",
                        "device_batteryLevelCase": "40%",
                    }
                }
            ],
            "device_not_connected": [
                {"Magic Mouse": {"device_address": "AA:BB:CC:DD:EE:02", "device_minorType": "Mouse"}},
                {"Magic Mouse": {"device_address": "AA:BB:CC:DD:EE:02", "device_minorType": "Mouse"}},
                {"Magic Keyboard": {"device_address": "AA:BB:CC:DD:EE:03", "device_batteryLevelMain": "n/a"}},
                # A flat entry, as other macOS versions may write, and junk to skip.
                {"device_name": "Speaker", "device_address": "AA:BB:CC:DD:EE:05", "device_minorType": "Speaker"},
                {"Broken": "not a dictionary"},
                "not an entry",
            ],
        }
    ]
}


def test_bluetooth_devices(commands):
    import json

    commands.answers["SPBluetoothDataType"] = (0, json.dumps(_BLUETOOTH), "")

    found = macos.bluetooth.devices()

    assert found == [
        macos.bluetooth.Device(
            "AirPods Pro", "AA:BB:CC:DD:EE:01", True, "headphones", {"left": 90, "right": 85, "case": 40}
        ),
        macos.bluetooth.Device("Magic Mouse", "AA:BB:CC:DD:EE:02", False, "mouse", {}),
        macos.bluetooth.Device("Magic Keyboard", "AA:BB:CC:DD:EE:03", False, "unknown", {}),
        macos.bluetooth.Device("Speaker", "AA:BB:CC:DD:EE:05", False, "speaker", {}),
    ]
    assert commands.calls[-1] == ["system_profiler", "SPBluetoothDataType", "-json"]


def test_bluetooth_device_matching(commands):
    import json

    commands.answers["SPBluetoothDataType"] = (0, json.dumps(_BLUETOOTH), "")
    find = macos.bluetooth._find

    assert find("AirPods").name == "AirPods Pro"
    assert find("aa-bb-cc-dd-ee-02").name == "Magic Mouse"
    assert find("Magic Keyboard").address == "AA:BB:CC:DD:EE:03"
    with pytest.raises(ValueError, match="several"):
        find("Magic")
    with pytest.raises(ValueError, match="no paired"):
        find("Headset")


def test_bluetooth_without_devices(commands):
    commands.answers["SPBluetoothDataType"] = (0, '{"SPBluetoothDataType": []}', "")

    assert macos.bluetooth.devices() == []


class _FakeBluetoothDevice:
    """Answers the IOBluetoothDevice messages; the link changes a few checks after the request."""

    def __init__(self, connected, status=0, delay=3):
        self.connected, self.status, self.delay = connected, status, delay
        self.requests, self.checks = [], 0

    def send(self, receiver, selector, *args, **kwargs):
        if selector == "deviceWithAddressString:":
            return 1
        if selector in ("openConnection", "closeConnection"):
            self.requests.append(selector)
            self.target, self.checks = selector == "openConnection", 0
            return self.status
        if selector == "isConnected":
            self.checks += 1
            if self.requests and self.checks > self.delay:
                self.connected = self.target
            return self.connected
        return 0


@pytest.fixture
def fake_bluetooth(monkeypatch):
    from contextlib import nullcontext

    from macos import bluetooth

    device = bluetooth.Device("JBL Tune", "AA:BB:CC:DD:EE:04", True, "headphones", {"main": 80})
    fake = _FakeBluetoothDevice(connected=True)
    monkeypatch.setattr(bluetooth, "_find", lambda target: device)
    monkeypatch.setattr(bluetooth, "power", lambda: True)
    monkeypatch.setattr(bluetooth._objc, "send", fake.send)
    monkeypatch.setattr(bluetooth._objc, "cls", lambda name: 1)
    monkeypatch.setattr(bluetooth._objc, "nsstring", lambda text: 1)
    monkeypatch.setattr(bluetooth._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(bluetooth.time, "sleep", lambda seconds: None)
    return fake


def test_disconnect_waits_until_the_link_is_down(fake_bluetooth):
    # closeConnection returns at once; a script exiting then kept the device connected.
    result = macos.bluetooth.disconnect("JBL")

    assert fake_bluetooth.requests == ["closeConnection"]
    assert fake_bluetooth.connected is False and fake_bluetooth.checks > fake_bluetooth.delay
    assert result.connected is False and result.name == "JBL Tune"

    assert macos.bluetooth.connect("JBL").connected is True
    assert fake_bluetooth.connected is True


def test_bluetooth_connection_failures(fake_bluetooth, monkeypatch):
    fake_bluetooth.status = -536870212  # kIOReturnError
    with pytest.raises(macos.MacOSError, match="could not disconnect 'JBL Tune' \\(IOReturn 0xe00002bc\\)"):
        macos.bluetooth.disconnect("JBL")

    fake_bluetooth.status, fake_bluetooth.delay = 0, 10**9  # the link never changes
    clock = iter(range(0, 100, 5))
    monkeypatch.setattr(macos.bluetooth.time, "monotonic", lambda: next(clock))
    with pytest.raises(macos.MacOSError, match="within 10.0 seconds"):
        macos.bluetooth.disconnect("JBL")

    with pytest.raises(ValueError, match="timeout"):
        macos.bluetooth.connect("JBL", timeout=0)


def test_bluetooth_argument_checks():
    # Rejected before switching anything.
    with pytest.raises(ValueError, match="timeout"):
        macos.bluetooth.set_power(False, timeout=0)


def test_bluetooth_devices_without_an_address_stay_apart(commands):
    import json

    listed = {
        "SPBluetoothDataType": [
            {
                "device_not_connected": [
                    {"Pencil": {"device_minorType": "Pen"}},
                    {"Remote": {"device_minorType": "Remote"}},
                    {"Remote": {"device_minorType": "Remote"}},
                ]
            }
        ]
    }
    commands.answers["SPBluetoothDataType"] = (0, json.dumps(listed), "")

    assert [(device.name, device.address) for device in macos.bluetooth.devices()] == [("Pencil", ""), ("Remote", "")]
    assert macos.bluetooth._find("Pencil").name == "Pencil"


@pytest.mark.parametrize("name", ["", "   "])
def test_bluetooth_refuses_an_empty_name(commands, name):
    import json

    single = {"SPBluetoothDataType": [{"device_connected": [{"AirPods": {"device_address": "AA:BB:CC:DD:EE:01"}}]}]}
    commands.answers["SPBluetoothDataType"] = (0, json.dumps(single), "")

    with pytest.raises(ValueError, match="name a Bluetooth device"):
        macos.bluetooth.connect(name)
    assert commands.calls == []  # refused before listing anything
