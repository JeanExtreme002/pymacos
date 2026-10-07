"""Unit tests for the charger, USB devices, startup items, network interfaces, DNS, proxies and the largest files."""

import sys

import pytest

import macos
from macos import finder, network, power, system

darwin = pytest.mark.skipif(sys.platform != "darwin", reason="reads this Mac's own state")


def test_adapter_from_its_description():
    assert power._adapter(None) is None and power._adapter({}) is None  # on battery
    described = {"Watts": 96, "Name": "96W USB-C Power Adapter", "Manufacturer": "Apple Inc.", "Voltage": 20000, "Current": 4700}
    assert power._adapter(described) == power.Adapter(96, "96W USB-C Power Adapter", "Apple Inc.", 20.0, 4.7)
    assert power._adapter({"Watts": 30}) == power.Adapter(30, None, None, None, None)


def test_usb_device_from_its_properties():
    assert system._usb_device(
        {"USB Product Name": "Portable SSD T7", "USB Vendor Name": "Samsung", "idVendor": 1256, "idProduct": 16749,
         "USB Serial Number": "S5TR", "Device Speed": 3, "bDeviceClass": 0}
    ) == system.USBDevice("Portable SSD T7", "Samsung", 1256, 16749, "S5TR", "super", False)  # fmt: skip
    hub = system._usb_device({"kUSBProductString": "USB2.0 Hub", "Device Speed": 2, "bDeviceClass": 9})
    assert (hub.name, hub.speed, hub.is_hub, hub.vendor) == ("USB2.0 Hub", "high", True, None)


def test_proxies_from_the_settings():
    assert network._proxies({
        "HTTPSEnable": 1, "HTTPSProxy": "proxy.example.com", "HTTPSPort": 8080,
        "HTTPEnable": 0, "HTTPProxy": "ignored.example.com", "HTTPPort": 80,
        "ProxyAutoConfigEnable": 1, "ProxyAutoConfigURLString": "http://wpad/proxy.pac",
        "ExceptionsList": ["*.local", "169.254/16"],
    }) == network.Proxies(None, "proxy.example.com:8080", None, "http://wpad/proxy.pac", ("*.local", "169.254/16"))  # fmt: skip
    assert network._proxies({}) == network.Proxies(None, None, None, None, ())


def test_startup_items(tmp_path, monkeypatch):
    import plistlib

    agents, daemons = tmp_path / "LaunchAgents", tmp_path / "LaunchDaemons"
    agents.mkdir()
    daemons.mkdir()
    (agents / "com.example.sync.plist").write_bytes(plistlib.dumps(
        {"Label": "com.example.sync", "ProgramArguments": ["/usr/local/bin/sync", "--quiet"], "RunAtLoad": True}
    ))  # fmt: skip
    (daemons / "com.example.helper.plist").write_bytes(plistlib.dumps(
        {"Label": "com.example.helper", "Program": "/Library/Helper/helper", "KeepAlive": {"SuccessfulExit": False}}
    ))  # fmt: skip
    (agents / "broken.plist").write_text("not a plist")
    monkeypatch.setattr(system, "_STARTUP_FOLDERS", ((str(agents), "agent", False), (str(daemons), "daemon", True)))
    monkeypatch.setattr(system, "require_macos", lambda: None)
    monkeypatch.setattr(system.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(system, "launchd_disabled", lambda domain: {"com.example.helper": True} if domain == "system" else {})
    monkeypatch.setattr(system, "_launchd_state", lambda domain, label: domain == "gui/501")

    found = {item.label: item for item in system.startup_items()}
    sync, helper = found["com.example.sync"], found["com.example.helper"]
    assert (sync.kind, sync.for_all_users, sync.program) == ("agent", False, "/usr/local/bin/sync")
    assert sync.arguments == ("/usr/local/bin/sync", "--quiet")
    assert (sync.run_at_load, sync.keep_alive, sync.enabled, sync.running) == (True, False, True, True)
    assert (helper.kind, helper.program, helper.keep_alive) == ("daemon", "/Library/Helper/helper", True)
    assert (helper.enabled, helper.running) == (False, False)  # turned off by launchctl
    assert len(found) == 2  # the broken file skipped


def test_largest_walks_a_folder_spotlight_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(macos.spotlight, "search", lambda query, folder=None: [])
    monkeypatch.setattr(finder, "require_macos", lambda: None)  # Spotlight is faked: any platform will do
    (tmp_path / "sub").mkdir()
    for name, size in (("small.txt", 10), ("big.bin", 3000), ("sub/bigger.bin", 5000), ("sub/mid.bin", 2000)):
        (tmp_path / name).write_bytes(b"x" * size)
    found = finder.largest(tmp_path, 2, at_least=1000)
    assert [(path.name, size) for path, size in found] == [("bigger.bin", 5000), ("big.bin", 3000)]
    assert finder.largest(tmp_path, at_least=100_000) == []
    with pytest.raises(ValueError, match="count must be 1 or more"):
        finder.largest(tmp_path, 0)
    with pytest.raises(NotADirectoryError):
        finder.largest(tmp_path / "small.txt")


@darwin
def test_interfaces_dns_and_startup_items_read():
    found = network.interfaces()
    assert found and all(item.name != "lo0" for item in found)
    for item in found:
        if item.active:
            assert item.up and (item.ipv4 or item.ipv6)
    assert all(isinstance(server, str) for server in network.dns_servers())
    assert isinstance(network.proxies(), network.Proxies)
    for item in system.startup_items():
        assert item.label and item.kind in ("agent", "daemon") and item.path.suffix == ".plist"
    for device in system.usb_devices():  # CI's VM may have none
        assert device.speed in (None, "low", "full", "high", "super", "super_plus")
    charger = power.adapter()  # read once: it may change between reads
    assert charger is None or charger.watts is None or charger.watts > 0


def test_largest_also_walks_what_spotlight_leaves_out(tmp_path, monkeypatch):
    visible, hidden = tmp_path / "Movies", tmp_path / ".cache"
    visible.mkdir()
    hidden.mkdir()
    (visible / "film.mov").write_bytes(b"x" * 3000)
    (hidden / "huge.bin").write_bytes(b"x" * 9000)  # Spotlight never indexes a hidden folder
    monkeypatch.setattr(finder, "require_macos", lambda: None)
    monkeypatch.setattr(macos.spotlight, "search", lambda query, folder=None: [visible / "film.mov"])
    found = finder.largest(tmp_path, at_least=1000)
    assert [(path.name, size) for path, size in found] == [("huge.bin", 9000), ("film.mov", 3000)]


def test_disabled_jobs_in_words_or_booleans(monkeypatch):
    output = """
    disabled services = {
        "com.example.one" => disabled
        "com.example.two" => enabled
        "com.example.three" => true
        "com.example.four" => false
    }
    """
    from macos import _system

    monkeypatch.setattr(_system, "run", lambda args, **kwargs: output)
    assert _system.launchd_disabled("gui/501") == {
        "com.example.one": True, "com.example.two": False, "com.example.three": True, "com.example.four": False
    }  # fmt: skip


def test_startup_item_with_broken_arguments(tmp_path, monkeypatch):
    import plistlib

    for label, arguments in (("com.example.number", 42), ("com.example.text", "/usr/bin/true")):
        (tmp_path / (label + ".plist")).write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": arguments}))
    monkeypatch.setattr(system, "_STARTUP_FOLDERS", ((str(tmp_path), "agent", False),))
    monkeypatch.setattr(system, "require_macos", lambda: None)
    monkeypatch.setattr(system.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(system, "launchd_disabled", lambda domain: {})
    monkeypatch.setattr(system, "_launchd_state", lambda domain, label: None)
    found = {item.label: (item.program, item.arguments) for item in system.startup_items()}
    assert found == {"com.example.number": (None, ()), "com.example.text": (None, ())}  # listed, not split into letters


def test_launchctl_switches_win_over_the_plist(tmp_path, monkeypatch):
    import plistlib

    for label, disabled in (("com.example.overridden", True), ("com.example.turned_off", False), ("com.example.plain", True)):
        described = {"Label": label, "Program": "/bin/true", "Disabled": disabled}
        (tmp_path / (label + ".plist")).write_bytes(plistlib.dumps(described))
    switches = {"com.example.overridden": False, "com.example.turned_off": True}  # launchctl enable / disable
    monkeypatch.setattr(system, "_STARTUP_FOLDERS", ((str(tmp_path), "agent", False),))
    monkeypatch.setattr(system, "require_macos", lambda: None)
    monkeypatch.setattr(system.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(system, "launchd_disabled", lambda domain: switches)
    monkeypatch.setattr(system, "_launchd_state", lambda domain, label: None)
    found = {item.label: item.enabled for item in system.startup_items()}
    assert found == {"com.example.overridden": True, "com.example.turned_off": False, "com.example.plain": False}
