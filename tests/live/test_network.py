"""Tests of :mod:`macos.network` against the real system. Skipped outside macOS."""

import macos


def test_network():
    import re

    assert isinstance(macos.network.is_online(), bool)
    address = macos.network.ip()
    assert address is None or re.fullmatch(r"\d+\.\d+\.\d+\.\d+", address)
    try:
        assert isinstance(macos.network.wifi_power(), bool)
    except macos.NotSupportedError:
        pass  # no Wi-Fi, as on some CI runners


def test_vpns():
    import pytest

    found = macos.network.vpns()
    assert all(vpn.status in ("connected", "connecting", "disconnecting", "disconnected") for vpn in found)
    with pytest.raises(macos.MacOSError, match="no VPN named"):
        macos.network.connect_vpn("pymacos-missing-vpn")


def test_bandwidth():
    found = macos.network.bandwidth(0.5)
    assert found and all(use.download >= 0 and use.upload >= 0 and use.interface != "lo0" for use in found)
    assert [use.received + use.sent for use in found] == sorted((use.received + use.sent for use in found), reverse=True)


def test_wifi_signal():
    signal = macos.network.wifi_signal()
    if signal is not None:  # None on a Mac off Wi-Fi, as CI's
        assert signal.rssi < 0 and signal.transmit_rate > 0 and signal.band in ("2.4GHz", "5GHz", "6GHz", None)


def test_interfaces_dns_and_startup_items_read():
    found = macos.network.interfaces()
    assert found and all(item.name != "lo0" for item in found)
    for item in found:
        if item.active:
            assert item.up and (item.ipv4 or item.ipv6)
    assert all(isinstance(server, str) for server in macos.network.dns_servers())
    assert isinstance(macos.network.proxies(), macos.network.Proxies)
    for item in macos.system.startup_items():
        assert item.label and item.kind in ("agent", "daemon") and item.path.suffix == ".plist"
    for device in macos.system.usb_devices():  # CI's VM may have none
        assert device.speed in (None, "low", "full", "high", "super", "super_plus")
    charger = macos.power.adapter()  # read once: it may change between reads
    assert charger is None or charger.watts is None or charger.watts > 0
