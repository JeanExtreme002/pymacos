"""Unit tests for :mod:`macos.network`. They run on any platform."""

import pytest

import macos


def test_network_ip_from_the_configuration_daemon(monkeypatch):
    values = {
        "State:/Network/Global/IPv4": {"PrimaryInterface": "en7", "Router": "10.0.0.1"},
        "State:/Network/Interface/en7/IPv4": {"Addresses": ["10.0.0.5"], "SubnetMasks": ["255.255.255.0"]},
    }
    monkeypatch.setattr(macos.network, "_dynamic_store", values.get)
    assert macos.network.interface() == "en7"
    assert macos.network.ip() == "10.0.0.5"
    values["State:/Network/Interface/en7/IPv4"] = {"Addresses": []}  # a tunnel without an IPv4 address
    assert macos.network.ip() is None
    values["State:/Network/Global/IPv4"] = None  # offline: no primary interface
    assert macos.network.interface() is None and macos.network.ip() is None


def _no_store(key):
    raise macos.MacOSError("could not read the network configuration")


def test_network_ip_follows_the_default_route(commands, monkeypatch):
    monkeypatch.setattr(macos.network, "_dynamic_store", _no_store)  # then the commands are asked
    commands.answers["-n"] = (0, "   route to: default\n   interface: en7\n", "")
    commands.answers["getifaddr"] = (0, "10.0.0.5\n", "")

    assert macos.network.interface() == "en7"
    assert macos.network.ip() == "10.0.0.5"
    assert commands.calls[-1] == ["ipconfig", "getifaddr", "en7"]


def test_network_offline(commands, monkeypatch):
    monkeypatch.setattr(macos.network, "_dynamic_store", _no_store)
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
    with pytest.raises(macos.WaitTimeoutError, match="isn't connected after 0 seconds"):
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


# --- Kernel buffers, built by hand -------------------------------------------------------


def _ifmibdata(name, flags, received, sent):
    """A ``struct ifmibdata`` as ``sysctl`` fills it: the name, five counters (the flags second), filler, an ``if_data64``."""
    import struct

    header = struct.pack("=16sIIIII16x", name, 0, flags, 0, 0, 0)
    if_data64 = struct.pack("=8BIIQQQQQQQQ", *([0] * 8), 1500, 0, 0, 10, 0, 20, 0, 0, received, sent)
    return header + if_data64


def test_interface_counters_are_read_where_the_kernel_puts_them(monkeypatch):
    import ctypes

    from macos import _libc, network

    answers = {1: _ifmibdata(b"en0", 0x18863, 5 * 2 ** 32 + 7, 2 ** 40), 2: _ifmibdata(b"lo0", 0x8049, 123, 456)}

    class Libc:
        def sysctl(self, mib, count, data, size, new, new_size):
            assert count == 6 and list(mib[:4]) == list(network._IFMIB_IFDATA) and mib[5] == network._IFDATA_GENERAL
            answer = answers.get(mib[4])
            if answer is None:
                return -1  # the interface went away since it was listed
            ctypes.memmove(data, answer, len(answer))
            size._obj.value = len(answer)
            return 0

    monkeypatch.setattr(_libc, "lib", lambda: Libc())
    monkeypatch.setattr(network.socket, "if_nameindex", lambda: [(1, "en0"), (2, "lo0"), (3, "utun9")])

    assert network._interface_counters() == {
        "en0": (0x8863, 5 * 2 ** 32 + 7, 2 ** 40),  # the flags are a short, widened; 64-bit byte counters
        "lo0": (0x8049, 123, 456),
    }
    assert struct_offsets() == (network._IFMD_FLAGS, network._IFMD_RECEIVED, network._IFMD_SENT)


def struct_offsets():
    """Where the buffer above puts the flags, ``ifi_ibytes`` and ``ifi_obytes``, by the C layout."""
    import struct

    header = struct.calcsize("=16sIIIII16x")
    return struct.calcsize("=16sI"), header + struct.calcsize("=8BIIQQQQQQ"), header + struct.calcsize("=8BIIQQQQQQQ")


def test_interfaces_read_each_sockaddr_by_its_family(monkeypatch):
    import ctypes
    import socket
    import struct

    from macos import _libc, network

    def sockaddr(packed):
        buffer = ctypes.create_string_buffer(packed, len(packed))
        return buffer, ctypes.cast(buffer, ctypes.POINTER(_libc.SockAddr))

    def link(name, mac):
        # sockaddr_dl: len, family, index, type, nlen, alen, slen, then the name and the address.
        data = name + mac
        return sockaddr(struct.pack("=BBHBBBB", 8 + len(data), network._AF_LINK, 4, 6, len(name), len(mac), 0) + data)

    def inet(address, port=0):
        return sockaddr(struct.pack("=BBH4s8x", 16, network._AF_INET, port, socket.inet_pton(socket.AF_INET, address)))

    def inet6(address):
        packed = socket.inet_pton(socket.AF_INET6, address)
        return sockaddr(struct.pack("=BBHI16sI", 28, network._AF_INET6, 0, 0, packed, 0))

    longest = b"thunderbolt1234"  # IFNAMSIZ - 1: the longest name an interface can have
    addresses = [
        (longest, 0x8863, link(longest, bytes.fromhex("a483e7123456"))),
        (longest, 0x8863, inet("192.168.0.8")),
        (longest, 0x8863, inet6("fe80::1")),
        (longest, 0x8863, inet6("2001:db8::8")),
        (b"en1", 0x8822, link(b"en1", b"\x00" * 6)),  # a hardware address of zeros: none
        (b"utun3", 0x8051, link(b"utun3", b"")),  # a tunnel: no hardware address
        (b"utun3", 0x8051, inet6("fe80::2")),
        (b"lo0", 0x8049, inet("127.0.0.1")),
    ]
    nodes = [_libc.IfAddrs(name=name, flags=flags, address=pointer) for name, flags, (_, pointer) in addresses]
    for node, following in zip(nodes, nodes[1:]):
        node.next = ctypes.pointer(following)
    head = ctypes.pointer(nodes[0])

    class Libc:
        def getifaddrs(self, reference):
            reference._obj.contents = head.contents
            return 0

        def freeifaddrs(self, head):
            pass

    monkeypatch.setattr(_libc, "lib", lambda: Libc())
    monkeypatch.setattr(network, "require_macos", lambda: None)
    monkeypatch.setattr(network, "_display_names", lambda: {"thunderbolt1234": "Thunderbolt"})

    found = {interface.name: interface for interface in network.interfaces()}
    assert set(found) == {"thunderbolt1234", "en1", "utun3"}  # the loopback is left out
    assert found["thunderbolt1234"] == network.NetworkInterface(
        "thunderbolt1234", "Thunderbolt", "a4:83:e7:12:34:56", ("192.168.0.8",), ("fe80::1", "2001:db8::8"), True, True
    )
    assert (found["en1"].mac, found["en1"].ipv4, found["en1"].active) == (None, (), False)
    assert (found["utun3"].mac, found["utun3"].ipv6, found["utun3"].active) == (None, ("fe80::2",), False)


@pytest.mark.parametrize(
    "output, message",
    [
        ('{"error_code": -1009, "error_domain": "NSURLErrorDomain"}', r"not connected to the internet \(NSURLErrorDomain -1009"),
        ('{"error_code": -1004, "error_domain": "NSURLErrorDomain"}', r"can't reach Apple's test server \(NSURLError"),
        ('{"error_code": 7, "error_domain": "SomeDomain", "dl_throughput": 5}', r"could not run the test: SomeDomain 7$"),
        ("[]", "isn't a result"),
    ],
)
def test_speed_test_that_cant_run_raises(fake_run, output, message):
    # networkQuality exits 0 and gives only the error: it's no measure of 0 Mbps.
    fake_run.stdout = output
    with pytest.raises(macos.MacOSError, match=message):
        macos.network.speed_test()


def test_connect_vpn_waits_out_a_disconnect_first(fake_run, monkeypatch):
    office = "5E3C8DF5-5B2D-4F5E-9F1A-3A2B1C4D5E6F"
    calls = _scutil(monkeypatch, ["Disconnecting", "Disconnecting", "Disconnected", "Connecting", "Connected"])
    macos.network.connect_vpn("Office")  # the start goes once it's done disconnecting: macOS would drop it before
    start = calls.index(["scutil", "--nc", "start", office])
    assert calls[:start] == [["scutil", "--nc", "list"]] * 3
    assert calls[start + 1:] == [["scutil", "--nc", "list"]] * 2

    calls = _scutil(monkeypatch, ["Disconnecting", "Connected"])
    macos.network.connect_vpn("Office", wait=False)  # it got connected meanwhile: nothing to send
    assert ["scutil", "--nc", "start", office] not in calls

    _scutil(monkeypatch, ["Disconnecting"])
    with pytest.raises(macos.WaitTimeoutError, match="still disconnecting"):
        macos.network.connect_vpn("Office", timeout=0)


def test_disconnect_vpn_stops_a_connect_under_way(fake_run, monkeypatch):
    calls = _scutil(monkeypatch, ["Connecting", "Connecting", "Disconnecting", "Disconnected"])
    macos.network.disconnect_vpn("Office")
    assert calls[1] == ["scutil", "--nc", "stop", "5E3C8DF5-5B2D-4F5E-9F1A-3A2B1C4D5E6F"]
    assert calls[-1] == ["scutil", "--nc", "list"]


@pytest.mark.parametrize(
    "host, port, expected",
    [
        ("fd00::1", 3128, "[fd00::1]:3128"),
        ("fd00::1", None, "[fd00::1]"),
        ("[fd00::1]", 3128, "[fd00::1]:3128"),  # bracketed already
        ("proxy.example.com", 8080, "proxy.example.com:8080"),
    ],
)
def test_proxies_bracket_an_ipv6_host(host, port, expected):
    found = {"HTTPEnable": 1, "HTTPProxy": host, **({"HTTPPort": port} if port else {})}
    assert macos.network._proxies(found).http == expected
