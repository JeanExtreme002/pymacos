"""Unit tests for :mod:`macos.network`. They run on any platform."""

import pytest

import macos


def test_network_ip_follows_the_default_route(commands):
    commands.answers["-n"] = (0, "   route to: default\n   interface: en7\n", "")
    commands.answers["getifaddr"] = (0, "10.0.0.5\n", "")

    assert macos.network.interface() == "en7"
    assert macos.network.ip() == "10.0.0.5"
    assert commands.calls[-1] == ["ipconfig", "getifaddr", "en7"]


def test_network_offline(commands):
    commands.answers["-n"] = (1, "", "route: writing to routing socket: not in table")

    assert macos.network.interface() is None
    assert macos.network.ip() is None


def test_wifi_power(commands, monkeypatch):
    monkeypatch.setattr(macos.network, "_corewlan_device", lambda: None)  # networksetup's list, then
    commands.answers["-listallhardwareports"] = (
        0,
        "Hardware Port: Ethernet\nDevice: en1\n\nHardware Port: Wi-Fi\nDevice: en0\n",
        "",
    )
    commands.answers["-getairportpower"] = (0, "Wi-Fi Power (en0): Off\n", "")

    assert macos.network.wifi_power() is False
    macos.network.set_wifi_power(True)
    assert commands.calls[-1] == ["networksetup", "-setairportpower", "en0", "on"]


def test_no_wifi(commands, monkeypatch):
    monkeypatch.setattr(macos.network, "_corewlan_device", lambda: None)
    commands.answers["-listallhardwareports"] = (0, "Hardware Port: Ethernet\nDevice: en1\n", "")

    with pytest.raises(macos.NotSupportedError, match="no Wi-Fi"):
        macos.network.wifi_power()


def test_wifi_device_is_found_on_a_mac_in_another_language(commands, monkeypatch):
    # networksetup names the port "WLAN" on a German Mac: CoreWLAN's answer doesn't depend on it.
    monkeypatch.setattr(macos.network, "_corewlan_device", lambda: "en0")
    commands.answers["-listallhardwareports"] = (0, "Hardware Port: WLAN\nDevice: en0\n", "")
    commands.answers["-getairportpower"] = (0, "Wi-Fi Power (en0): On\n", "")

    assert macos.network.wifi_power() is True
    assert ["networksetup", "-listallhardwareports"] not in commands.calls


_VPN_LIST = """Available network connection services in the current set (*=enabled):
* ({office})   5E3C8DF5-5B2D-4F5E-9F1A-3A2B1C4D5E6F PPP --> L2TP       "Office"     [PPP:L2TP]
* (Connected)      4E3C8DF5-5B2D-4F5E-9F1A-3A2B1C4D5E6F VPN (com.paloaltonetworks.GlobalProtect.client) "Home lab"
* (Disconnected)   9E918907-9C9E-4100-87C9-70A755670C57 PPP --> J-Link "J-Link 2" [PPP:Modem]
  (Disconnected)   3E3C8DF5-5B2D-4F5E-9F1A-3A2B1C4D5E6F IPSec              "Branch"     [IPSec]
"""


def _scutil(monkeypatch, statuses):
    """A fake scutil whose "Office" VPN goes through ``statuses``, one per listing."""
    import subprocess

    from macos import _system

    calls = []

    def run(args, **kwargs):
        calls.append(list(args))
        if args[2] != "list":
            return subprocess.CompletedProcess(args, 0, "", "")
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        return subprocess.CompletedProcess(args, 0, _VPN_LIST.format(office=status), "")

    monkeypatch.setattr(_system.subprocess, "run", run)
    monkeypatch.setattr(macos.network.time, "sleep", lambda seconds: None)
    return calls


def test_vpns(fake_run, monkeypatch):
    _scutil(monkeypatch, ["Disconnected"])
    office, home, branch = macos.network.vpns()  # the modem isn't a VPN
    assert (office.name, office.kind, office.status) == ("Office", "L2TP", "disconnected")
    assert (home.name, home.kind, home.status) == ("Home lab", "com.paloaltonetworks.GlobalProtect.client", "connected")
    assert (branch.name, branch.kind, branch.id) == ("Branch", "IPSec", "3E3C8DF5-5B2D-4F5E-9F1A-3A2B1C4D5E6F")
    with pytest.raises(macos.MacOSError, match="no VPN named 'Work'.*'Office'"):
        macos.network.connect_vpn("Work")


def test_connect_vpn_waits_until_connected(fake_run, monkeypatch):
    calls = _scutil(monkeypatch, ["Disconnected", "Disconnected", "Connecting", "Connected"])
    macos.network.connect_vpn("Office")
    assert ["scutil", "--nc", "start", "5E3C8DF5-5B2D-4F5E-9F1A-3A2B1C4D5E6F"] in calls
    assert calls[-1] == ["scutil", "--nc", "list"]

    calls = _scutil(monkeypatch, ["Connected"])
    macos.network.connect_vpn("Office")  # already connected: nothing to do
    assert calls == [["scutil", "--nc", "list"]]

    calls = _scutil(monkeypatch, ["Connected", "Disconnecting", "Disconnected"])
    macos.network.disconnect_vpn("5E3C8DF5-5B2D-4F5E-9F1A-3A2B1C4D5E6F")  # by its id too
    assert ["scutil", "--nc", "stop", "5E3C8DF5-5B2D-4F5E-9F1A-3A2B1C4D5E6F"] in calls


def test_connect_vpn_fails(fake_run, monkeypatch):
    _scutil(monkeypatch, ["Disconnected", "Connecting", "Disconnected"])
    with pytest.raises(macos.MacOSError, match="didn't get connected"):
        macos.network.connect_vpn("Office")

    _scutil(monkeypatch, ["Disconnected"])
    with pytest.raises(macos.MacOSError, match="isn't connected after 0 seconds"):
        macos.network.connect_vpn("Office", timeout=0)

    calls = _scutil(monkeypatch, ["Disconnected"])
    macos.network.connect_vpn("Office", wait=False)
    assert calls[-1][:3] == ["scutil", "--nc", "start"]


def test_bandwidth_between_two_samples():
    from macos.network import _bandwidth

    up, down, loopback = 0x1, 0x0, 0x8 | 0x1
    before = {"en0": (up, 1_000, 500), "en5": (up, 9_000, 9_000), "lo0": (loopback, 0, 0), "awdl0": (up, 0, 0)}
    after = {
        "en0": (up, 1_000 + 2_500_000, 500 + 250_000),
        "en5": (up, 100, 50),  # reset: the adapter came back
        "lo0": (loopback, 10_000, 10_000),
        "awdl0": (up, 0, 0),  # never used
        "en9": (down, 5, 5),
        "utun4": (up, 7, 7),  # new since the first sample
    }

    found = _bandwidth(before, after, 2.0, {"en0": "Wi-Fi"})

    assert [use.interface for use in found] == ["en0", "en5"]
    wifi = found[0]
    assert (wifi.display_name, wifi.received, wifi.sent) == ("Wi-Fi", 2_500_000, 250_000)
    assert (wifi.download, wifi.upload) == (10.0, 1.0)  # megabits per second
    assert (found[1].received, found[1].sent, found[1].display_name) == (100, 50, None)


def test_bandwidth_checks_the_interval(fake_run):
    with pytest.raises(ValueError, match="interval must be positive"):
        macos.network.bandwidth(0)


def test_speed_test_and_vpns_give_up_on_a_stuck_command(monkeypatch, fake_run):
    import subprocess

    from macos import _system

    timeouts = []

    def stuck(args, **kwargs):
        timeouts.append((args[0], kwargs["timeout"]))
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(_system.subprocess, "run", stuck)
    with pytest.raises(macos.CommandTimeoutError) as raised:
        macos.network.speed_test(timeout=90)
    assert isinstance(raised.value, TimeoutError) and "networkQuality" in str(raised.value)
    with pytest.raises(macos.CommandTimeoutError):
        macos.network.vpns()
    assert timeouts == [("networkQuality", 90), ("scutil", macos.network._SCUTIL_TIMEOUT)]


def test_vpn_commands_have_a_timeout(fake_run, monkeypatch):
    import subprocess

    from macos import _system

    seen = []

    def run(args, **kwargs):
        seen.append((args[2], kwargs.get("timeout")))
        return subprocess.CompletedProcess(args, 0, _VPN_LIST.format(office="Disconnected"), "")

    monkeypatch.setattr(_system.subprocess, "run", run)
    macos.network.connect_vpn("Office", wait=False)
    assert seen == [("list", 30.0), ("start", 30.0)]


def test_system_configuration_is_declared_once_for_network_and_events():
    import sys

    if sys.platform != "darwin":
        pytest.skip("loads SystemConfiguration")
    from macos import _sc, _system

    sc = _sc.lib()
    assert sc is _system.framework("SystemConfiguration")  # one handle, its signatures set once
    declared = sc.SCDynamicStoreCreate.argtypes
    macos.network.dns_servers()  # network used to declare the callback as a plain pointer, events as a CFUNCTYPE
    assert macos.events._sc.lib() is sc
    assert sc.SCDynamicStoreCreate.argtypes is declared
