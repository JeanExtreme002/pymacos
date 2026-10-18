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


def test_bluetooth_odd_report(commands):
    for odd in ("[1, 2]", '{"SPBluetoothDataType": "none"}', "not json"):
        commands.answers["SPBluetoothDataType"] = (0, odd, "")
        with pytest.raises(macos.MacOSError, match="something unexpected"):
            macos.bluetooth.devices()


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
    with pytest.raises(macos.WaitTimeoutError, match="within 10.0 seconds"):
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


def test_bluetooth_set_power_times_out_with_a_timeout_error(monkeypatch):
    from types import SimpleNamespace

    from macos import bluetooth

    switched = []
    fake = SimpleNamespace(
        IOBluetoothPreferenceSetControllerPowerState=switched.append,
        IOBluetoothPreferenceGetControllerPowerState=lambda: 1,  # never goes off
    )
    clock = {"now": 0.0}
    monkeypatch.setattr(bluetooth, "_bluetooth", lambda: fake)
    monkeypatch.setattr(bluetooth, "_require_controller", lambda: None)
    monkeypatch.setattr(bluetooth.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(bluetooth.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds))
    with pytest.raises(macos.WaitTimeoutError, match="didn't turn off within 1.0 seconds"):
        macos.bluetooth.set_power(False, timeout=1.0)
    assert switched == [0]


def test_bluetooth_refuses_to_connect_a_device_listed_without_an_address(fake_bluetooth, monkeypatch):
    from macos import bluetooth

    pencil = bluetooth.Device("Pencil", "", False, "pen")  # listed without an address: see devices()
    monkeypatch.setattr(bluetooth, "_find", lambda target: pencil)

    with pytest.raises(macos.MacOSError, match="lists 'Pencil' without a Bluetooth address, so it can't be connected"):
        macos.bluetooth.connect("Pencil")
    with pytest.raises(macos.MacOSError, match="can't be disconnected from here"):
        macos.bluetooth.disconnect("Pencil")
    assert fake_bluetooth.requests == []  # IOBluetoothDevice was never asked about ""


def test_bluetooth_several_matches_list_only_the_matching_devices(commands):
    import json

    commands.answers["SPBluetoothDataType"] = (0, json.dumps(_BLUETOOTH), "")

    with pytest.raises(ValueError, match="several") as raised:
        macos.bluetooth._find("Magic")
    message = str(raised.value)
    assert "AA:BB:CC:DD:EE:02" in message and "AA:BB:CC:DD:EE:03" in message
    assert "AirPods" not in message and "Speaker" not in message


def _two_pairs(commands, names=("AirPods Pro", "AirPods Pro")):
    import json

    listed = {
        "SPBluetoothDataType": [
            {
                "device_connected": [{names[0]: {"device_address": "AA:BB:CC:DD:EE:01"}}],
                "device_not_connected": [
                    {names[1]: {"device_address": "AA:BB:CC:DD:EE:02"}},
                    {names[1]: {"device_address": "AA:BB:CC:DD:EE:02"}},  # listed twice, still one device
                ],
            }
        ]
    }
    commands.answers["SPBluetoothDataType"] = (0, json.dumps(listed), "")


def test_bluetooth_refuses_a_name_two_devices_share(commands):
    _two_pairs(commands)

    with pytest.raises(ValueError, match="several paired Bluetooth devices are named") as raised:
        macos.bluetooth.connect("AirPods Pro")
    assert "AA:BB:CC:DD:EE:01" in str(raised.value) and "AA:BB:CC:DD:EE:02" in str(raised.value)
    assert macos.bluetooth._find("AA:BB:CC:DD:EE:02").address == "AA:BB:CC:DD:EE:02"


def test_bluetooth_names_match_whatever_the_apostrophe(commands):
    _two_pairs(commands, ("Jean’s AirPods", "Ana's Mouse"))
    find = macos.bluetooth._find

    assert find("Jean's AirPods").address == "AA:BB:CC:DD:EE:01"
    assert find("jean's airpods").address == "AA:BB:CC:DD:EE:01"
    assert find("Ana’s Mouse").address == "AA:BB:CC:DD:EE:02"


def test_bluetooth_names_match_whatever_the_unicode_form(commands):
    import unicodedata

    # One name stored composed (NFC), the other decomposed (NFD), so each
    # lookup only matches if _fold normalizes both sides.
    stored = unicodedata.normalize("NFD", "Zoë Keyboard")
    assert stored != "Zoë Keyboard"
    _two_pairs(commands, ("José’s Mouse", stored))
    find = macos.bluetooth._find

    query = unicodedata.normalize("NFD", "José's Mouse")
    assert query != unicodedata.normalize("NFC", query)
    assert find(query).address == "AA:BB:CC:DD:EE:01"
    assert find(unicodedata.normalize("NFC", "Zoë Keyboard")).address == "AA:BB:CC:DD:EE:02"


def test_bluetooth_exact_name_wins_over_a_folded_one(commands):
    _two_pairs(commands, ("Desk Mouse", "desk mouse"))
    find = macos.bluetooth._find

    assert find("Desk Mouse").address == "AA:BB:CC:DD:EE:01"
    assert find("desk mouse").address == "AA:BB:CC:DD:EE:02"
    with pytest.raises(ValueError, match="several paired Bluetooth devices are named"):
        find("DESK MOUSE")


def test_bluetooth_odd_sections_and_device_lists(commands):
    import json

    listed = {
        "SPBluetoothDataType": [
            "not a section",
            {
                "device_connected": {"AirPods": {"device_address": "AA:BB:CC:DD:EE:01"}},
                "device_not_connected": "none",
            },
        ]
    }
    commands.answers["SPBluetoothDataType"] = (0, json.dumps(listed), "")

    assert [device.name for device in macos.bluetooth.devices()] == ["AirPods"]


@pytest.mark.parametrize("target", [None, 123])
def test_bluetooth_refuses_a_device_that_is_not_a_name(commands, target):
    with pytest.raises(TypeError, match="Device or a str"):
        macos.bluetooth.connect(target)
    with pytest.raises(TypeError, match="Device or a str"):
        macos.bluetooth.disconnect(target)
    assert commands.calls == []


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1])
def test_bluetooth_refuses_a_timeout_that_never_ends(commands, timeout):
    with pytest.raises(ValueError, match="timeout"):
        macos.bluetooth.connect("AirPods", timeout=timeout)
    with pytest.raises(ValueError, match="timeout"):
        macos.bluetooth.set_power(False, timeout=timeout)
    assert commands.calls == []


@pytest.mark.parametrize("timeout", [None, "10", True])
def test_bluetooth_refuses_a_timeout_that_is_not_a_number(timeout):
    with pytest.raises(TypeError, match="timeout"):
        macos.bluetooth.disconnect("AirPods", timeout=timeout)
    with pytest.raises(TypeError, match="timeout"):
        macos.bluetooth.set_power(True, timeout=timeout)
