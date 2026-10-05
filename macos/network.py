# -*- coding: utf-8 -*-

"""
Network information, Wi-Fi power, VPNs and how fast data flows.

::

    macos.network.is_online()           # True
    macos.network.ip()                  # '192.168.0.8'
    macos.network.wifi_power()          # True
    macos.network.set_wifi_power(False)
    macos.network.connect_vpn("Office")
    macos.network.bandwidth()           # [Bandwidth(interface='en0', display_name='Wi-Fi', download=42.1, ...)]

The Wi-Fi network's name (SSID) isn't here: since macOS 14 reading it needs
the Location permission.
"""

import ctypes
import json
import re
import socket
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from . import _cf, _libc, _objc
from ._libc import IfAddrs as _IfAddrs
from ._system import framework, require_macos, run as _run
from .errors import CommandError, MacOSError, NotSupportedError

__all__ = [
    "is_online",
    "ip",
    "interface",
    "wifi_power",
    "set_wifi_power",
    "SpeedTest",
    "speed_test",
    "WiFiSignal",
    "wifi_signal",
    "NetworkInterface",
    "interfaces",
    "dns_servers",
    "Proxies",
    "proxies",
    "VPN",
    "vpns",
    "connect_vpn",
    "disconnect_vpn",
    "Bandwidth",
    "bandwidth",
]

_REACHABLE = 1 << 1  # kSCNetworkReachabilityFlagsReachable
_CONNECTION_REQUIRED = 1 << 2  # kSCNetworkReachabilityFlagsConnectionRequired


class _SockaddrIn(ctypes.Structure):
    _fields_ = [
        ("sin_len", ctypes.c_uint8),
        ("sin_family", ctypes.c_uint8),
        ("sin_port", ctypes.c_uint16),
        ("sin_addr", ctypes.c_uint32),
        ("sin_zero", ctypes.c_char * 8),
    ]


@lru_cache(maxsize=None)
def _configuration() -> ctypes.CDLL:
    config = framework("SystemConfiguration")
    config.SCNetworkReachabilityCreateWithAddress.argtypes = (ctypes.c_void_p, ctypes.POINTER(_SockaddrIn))
    config.SCNetworkReachabilityCreateWithAddress.restype = ctypes.c_void_p
    config.SCNetworkReachabilityGetFlags.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
    config.SCNetworkReachabilityGetFlags.restype = ctypes.c_bool
    return config


def is_online() -> bool:
    """
    Whether the Mac has a network connection that can reach the internet.

    Checked locally, without contacting any server, the same way apps decide to
    show "you're offline". A captive portal (hotel Wi-Fi login page) still
    counts as online.
    """
    config = _configuration()
    # 0.0.0.0 stands for "any address": is there a route out at all?
    anywhere = _SockaddrIn(ctypes.sizeof(_SockaddrIn), socket.AF_INET, 0, 0, b"")
    target = config.SCNetworkReachabilityCreateWithAddress(None, ctypes.byref(anywhere))
    if not target:
        return False
    with _cf.owned(target):
        flags = ctypes.c_uint32()
        if not config.SCNetworkReachabilityGetFlags(target, ctypes.byref(flags)):
            return False
    return bool(flags.value & _REACHABLE) and not flags.value & _CONNECTION_REQUIRED


def interface() -> Optional[str]:
    """The network interface internet traffic goes through, e.g. ``'en0'``, or ``None`` when offline."""
    try:
        output = _run(["route", "-n", "get", "default"])
    except CommandError:  # no default route
        return None
    found = re.search(r"interface:\s*(\S+)", output)
    return found.group(1) if found else None


def ip() -> Optional[str]:
    """The Mac's IPv4 address on the local network (e.g. ``'192.168.0.8'``), or ``None`` when offline."""
    name = interface()
    if name is None:
        return None
    try:
        address = _run(["ipconfig", "getifaddr", name]).strip()
    except CommandError:  # the interface has no IPv4 address (e.g. a VPN tunnel)
        return None
    return address or None


def _wifi_device() -> str:
    ports = _run(["networksetup", "-listallhardwareports"])
    found = re.search(r"Hardware Port: (?:Wi-Fi|AirPort)\s*\nDevice: (\S+)", ports)
    if not found:
        raise NotSupportedError("this Mac has no Wi-Fi")
    return found.group(1)


def wifi_power() -> bool:
    """Whether Wi-Fi is turned on. Raises :class:`~macos.errors.NotSupportedError` on a Mac without Wi-Fi."""
    output = _run(["networksetup", "-getairportpower", _wifi_device()])
    return output.strip().lower().endswith("on")


def set_wifi_power(on: bool) -> None:
    """Turn Wi-Fi on or off, like the switch in Control Center."""
    _run(["networksetup", "-setairportpower", _wifi_device(), "on" if on else "off"])


# --- Speed test -------------------------------------------------------------------


@dataclass(frozen=True)
class SpeedTest:
    """How fast the internet connection is, as :func:`speed_test` measured it."""

    download: float
    """In megabits per second, as internet plans are sold."""
    upload: float
    latency: Optional[float]
    """Round trip to the test server when idle, in milliseconds."""
    loaded_latency: Optional[float]
    """Round trip while the connection is busy, in milliseconds: how laggy calls and games get under load."""
    responsiveness: Optional[float]
    """The same under load as a score, in round trips per minute (RPM): the higher, the better."""
    interface: Optional[str]
    """The network interface measured, such as ``'en0'``."""
    server: Optional[str]
    """Apple's test server that answered."""


def _speed(result: Dict[str, Any]) -> SpeedTest:
    def megabits(key: str) -> float:
        return round(float(result.get(key) or 0) / 1e6, 2)

    idle = result.get("base_rtt")
    # "responsiveness" is a score in round trips per minute, not a time: 60,000 ms / RPM.
    rpm = float(result["responsiveness"]) if result.get("responsiveness") else None
    return SpeedTest(
        download=megabits("dl_throughput"),  # bits per second, as its text summary's Mbps show
        upload=megabits("ul_throughput"),
        latency=round(float(idle), 1) if idle is not None else None,
        loaded_latency=round(60000 / rpm, 1) if rpm else None,
        responsiveness=round(rpm, 1) if rpm else None,
        interface=result.get("interface_name"),
        server=result.get("test_endpoint"),
    )


def speed_test(*, sequential: bool = False, timeout: float = 180.0) -> SpeedTest:
    """
    Measure the internet connection's download and upload speed, and its latency, against Apple's servers.

    ::

        result = macos.network.speed_test()
        result.download, result.upload   # (43.61, 39.42): megabits per second
        result.latency                   # 54.6 ms, idle
        result.loaded_latency            # 1126.6 ms while busy: calls lag

    It takes 15 to 60 seconds and moves a few hundred megabytes: mind a
    metered connection. ``sequential=True`` measures download and upload
    one after the other instead of together, which reads each more exactly
    (and takes about twice as long). Goes through ``networkQuality``, which
    comes with macOS; past ``timeout`` seconds (a server that stopped
    answering) it's stopped and :class:`~macos.errors.CommandTimeoutError`
    raised.
    """
    require_macos()
    output = _run(["networkQuality", "-c", *(["-s"] if sequential else [])], timeout=timeout)
    try:
        return _speed(json.loads(output))
    except ValueError:
        raise MacOSError("networkQuality gave an answer that isn't JSON: {!r}".format(output[:200])) from None


# --- Wi-Fi signal -------------------------------------------------------------------

_BANDS = {1: "2.4GHz", 2: "5GHz", 3: "6GHz"}  # CWChannelBand
_WIDTHS = {1: 20, 2: 40, 3: 80, 4: 160}  # CWChannelWidth, in MHz
_SECURITY = {  # CWSecurity
    0: "none",
    1: "wep",
    2: "wpa_personal",
    3: "wpa_personal",
    4: "wpa2_personal",
    5: "personal",
    6: "dynamic_wep",
    7: "wpa_enterprise",
    8: "wpa_enterprise",
    9: "wpa2_enterprise",
    10: "enterprise",
    11: "wpa3_personal",
    12: "wpa3_enterprise",
    13: "wpa3_transition",
    14: "owe",
    15: "owe_transition",
}


@dataclass(frozen=True)
class WiFiSignal:
    """How good the Wi-Fi connection is right now."""

    rssi: int
    """Signal strength, in dBm: -55 and up is excellent, below -75 poor (see :attr:`quality`)."""
    noise: int
    """Background noise, in dBm: the lower, the better."""
    transmit_rate: float
    """The speed the link runs at, in megabits per second: an upper bound, not the internet's speed."""
    channel: Optional[int]
    band: Optional[str]
    """``'2.4GHz'``, ``'5GHz'`` or ``'6GHz'``."""
    channel_width: Optional[int]
    """In MHz: 20, 40, 80 or 160."""
    security: Optional[str]
    """Such as ``'wpa2_personal'`` or ``'wpa3_personal'``."""

    @property
    def snr(self) -> int:
        """Signal-to-noise ratio, in dB: above 25 is good, below 15 unreliable."""
        return self.rssi - self.noise

    @property
    def quality(self) -> str:
        """
        ``'excellent'``, ``'good'``, ``'fair'`` or ``'poor'``, from the signal strength.

        From :attr:`rssi`: -55 dBm and up is excellent, -67 and up good, -75
        and up fair, lower poor.
        """
        if self.rssi >= -55:
            return "excellent"
        if self.rssi >= -67:
            return "good"
        if self.rssi >= -75:
            return "fair"
        return "poor"


def wifi_signal() -> Optional[WiFiSignal]:
    """
    The current Wi-Fi connection's signal, noise, speed and channel; ``None`` when not connected to Wi-Fi.

    ::

        signal = macos.network.wifi_signal()
        signal.rssi, signal.quality      # (-62, 'good')
        signal.band, signal.channel      # ('5GHz', 157)

    Handy to find the room's dead spots, or tell a weak signal from a slow
    internet. It needs no permission; the network's name, which macOS keeps
    behind the Location permission, isn't part of it.
    """
    framework("CoreWLAN")
    with _objc.autorelease_pool():
        client = _objc.send(_objc.cls("CWWiFiClient"), "sharedWiFiClient")
        interface = _objc.send(client, "interface")
        if not interface or not _objc.send(interface, "powerOn", restype=_objc.BOOL):
            return None
        rssi = int(_objc.send(interface, "rssiValue", restype=ctypes.c_long))
        if rssi == 0:
            return None  # powered on, but not connected
        channel = _objc.send(interface, "wlanChannel")

        def number(selector: str) -> Optional[int]:
            return int(_objc.send(channel, selector, restype=ctypes.c_long)) if channel else None

        security = int(_objc.send(interface, "security", restype=ctypes.c_long))
        return WiFiSignal(
            rssi=rssi,
            noise=int(_objc.send(interface, "noiseMeasurement", restype=ctypes.c_long)),
            transmit_rate=float(_objc.send(interface, "transmitRate", restype=ctypes.c_double)),
            channel=number("channelNumber") or None,
            band=_BANDS.get(number("channelBand") or 0),
            channel_width=_WIDTHS.get(number("channelWidth") or 0),
            security=_SECURITY.get(security),
        )


# --- Interfaces, DNS and proxies ---------------------------------------------------------

_AF_INET, _AF_INET6, _AF_LINK = 2, 30, 18
_IFF_UP, _IFF_LOOPBACK = 0x1, 0x8


@dataclass(frozen=True)
class NetworkInterface:
    """A network interface: Wi-Fi, Ethernet, a VPN tunnel..."""

    name: str
    """The system's name for it, such as ``'en0'``."""
    display_name: Optional[str]
    """As System Settings names it, such as ``'Wi-Fi'``; ``None`` for virtual ones (VPN tunnels...)."""
    mac: Optional[str]
    """Its hardware address, such as ``'a4:83:e7:12:34:56'``."""
    ipv4: Tuple[str, ...]
    ipv6: Tuple[str, ...]
    up: bool
    """Turned on."""
    active: bool
    """Up, with an address to talk with: an IPv4 one, or an IPv6 one beyond its own link.

    Ports without a cable, and tunnels of a VPN that's off, aren't."""


def _display_names() -> Dict[str, str]:
    sc = framework("SystemConfiguration")
    pointer = ctypes.c_void_p
    sc.SCNetworkInterfaceCopyAll.argtypes = ()
    sc.SCNetworkInterfaceCopyAll.restype = pointer
    sc.SCNetworkInterfaceGetBSDName.argtypes = (pointer,)
    sc.SCNetworkInterfaceGetBSDName.restype = pointer
    sc.SCNetworkInterfaceGetLocalizedDisplayName.argtypes = (pointer,)
    sc.SCNetworkInterfaceGetLocalizedDisplayName.restype = pointer
    names = {}
    with _cf.owned(sc.SCNetworkInterfaceCopyAll()) as every:
        for item in _cf.items(every):
            name = _cf.to_str(sc.SCNetworkInterfaceGetBSDName(item))
            shown = _cf.to_str(sc.SCNetworkInterfaceGetLocalizedDisplayName(item))
            if name and shown:
                names[name] = shown
    return names


def interfaces() -> List[NetworkInterface]:
    """
    Every network interface, with its addresses: Wi-Fi, Ethernet, Thunderbolt, VPN tunnels...

    ::

        for found in macos.network.interfaces():
            if found.active and found.ipv4:
                print(found.display_name or found.name, found.ipv4)   # Wi-Fi ('192.168.0.8',)

    The loopback (``lo0``) is left out. For the one internet traffic goes
    through, see :func:`interface` and :func:`ip`.
    """
    require_macos()
    libc = _libc.lib()
    head = ctypes.POINTER(_IfAddrs)()
    if libc.getifaddrs(ctypes.byref(head)) != 0:
        raise MacOSError("could not list the network interfaces")
    found: Dict[str, Dict[str, Any]] = {}
    try:
        entry = head
        while entry:
            item = entry.contents
            name = (item.name or b"").decode("utf-8", "replace")
            record = found.setdefault(name, {"flags": item.flags, "mac": None, "ipv4": [], "ipv6": []})
            record["flags"] |= item.flags
            if item.address:
                family = item.address.contents.family
                raw = ctypes.string_at(ctypes.addressof(item.address.contents), item.address.contents.len)
                if family == _AF_INET and len(raw) >= 8:
                    record["ipv4"].append(socket.inet_ntop(socket.AF_INET, raw[4:8]))
                elif family == _AF_INET6 and len(raw) >= 24:
                    record["ipv6"].append(socket.inet_ntop(socket.AF_INET6, raw[8:24]))
                elif family == _AF_LINK and len(raw) >= 8:
                    # sockaddr_dl: 8 header bytes, then the name, then the address.
                    name_length, address_length = raw[5], raw[6]
                    mac = raw[8 + name_length:8 + name_length + address_length]
                    if address_length == 6 and any(mac):
                        record["mac"] = ":".join("{:02x}".format(byte) for byte in mac)
            entry = item.next
    finally:
        libc.freeifaddrs(head)
    names = _display_names()
    return [
        NetworkInterface(
            name=name,
            display_name=names.get(name),
            mac=record["mac"],
            ipv4=tuple(record["ipv4"]),
            ipv6=tuple(record["ipv6"]),
            up=bool(record["flags"] & _IFF_UP),
            # The kernel's "running" flag stays set on a port without a cable: an address says more.
            active=bool(record["flags"] & _IFF_UP)
            and bool(record["ipv4"] or any(not address.startswith("fe80:") for address in record["ipv6"])),
        )
        for name, record in found.items()
        if not record["flags"] & _IFF_LOOPBACK
    ]


def _dynamic_store(key: str) -> Any:
    sc = framework("SystemConfiguration")
    pointer = ctypes.c_void_p
    sc.SCDynamicStoreCreate.argtypes = (pointer, pointer, pointer, pointer)
    sc.SCDynamicStoreCreate.restype = pointer
    sc.SCDynamicStoreCopyValue.argtypes = (pointer, pointer)
    sc.SCDynamicStoreCopyValue.restype = pointer
    with _cf.owned(_cf.string("pymacos")) as name:
        store = sc.SCDynamicStoreCreate(None, name, None, None)
    if not store:
        raise MacOSError("could not read the network configuration")
    try:
        with _cf.owned(_cf.string(key)) as wanted, _cf.owned(sc.SCDynamicStoreCopyValue(store, wanted)) as value:
            return _cf.to_python(value) if value else None
    finally:
        _cf.release(store)


def dns_servers() -> List[str]:
    """
    The DNS servers the Mac asks, in order: ``['192.168.0.1', '8.8.8.8']``.

    They're the ones in use now, whether set in System Settings or given by
    the network or a VPN. ``[]`` when offline.
    """
    require_macos()
    found = _dynamic_store("State:/Network/Global/DNS")
    servers = found.get("ServerAddresses") if isinstance(found, dict) else None
    return [str(server) for server in servers] if isinstance(servers, list) else []


@dataclass(frozen=True)
class Proxies:
    """The proxies in use; each is ``"host:port"``, or ``None`` when off."""

    http: Optional[str]
    https: Optional[str]
    socks: Optional[str]
    auto_config_url: Optional[str]
    """A PAC file's address, which decides the proxy for each site."""
    exceptions: Tuple[str, ...]
    """Hosts reached without a proxy, such as ``'*.local'``."""


def proxies() -> Proxies:
    """
    The proxies in use, as System Settings › Network › Details › Proxies sets them, or a profile does.

    ::

        macos.network.proxies()   # Proxies(http=None, https='proxy.example.com:8080', socks=None, ...)
    """
    require_macos()
    sc = framework("SystemConfiguration")
    sc.SCDynamicStoreCopyProxies.argtypes = (ctypes.c_void_p,)
    sc.SCDynamicStoreCopyProxies.restype = ctypes.c_void_p
    with _cf.owned(sc.SCDynamicStoreCopyProxies(None)) as settings:
        found = _cf.to_python(settings) if settings else {}
    return _proxies(found if isinstance(found, dict) else {})


def _proxies(found: Dict[str, Any]) -> Proxies:
    def proxy(prefix: str) -> Optional[str]:
        if not found.get(prefix + "Enable") or not found.get(prefix + "Proxy"):
            return None
        port = found.get(prefix + "Port")
        return "{}:{}".format(found[prefix + "Proxy"], port) if port else str(found[prefix + "Proxy"])

    auto = found.get("ProxyAutoConfigURLString") if found.get("ProxyAutoConfigEnable") else None
    return Proxies(
        http=proxy("HTTP"),
        https=proxy("HTTPS"),
        socks=proxy("SOCKS"),
        auto_config_url=str(auto) if auto else None,
        exceptions=tuple(str(host) for host in found.get("ExceptionsList") or ()),
    )


@dataclass(frozen=True)
class VPN:
    """A VPN set up in System Settings › VPN."""

    name: str
    kind: str
    """
    Such as ``'L2TP'`` or ``'IPSec'``, or the bundle ID of the app that made it,
    such as ``'com.paloaltonetworks.GlobalProtect.client'``.
    """
    status: str
    """``'connected'``, ``'connecting'``, ``'disconnecting'`` or ``'disconnected'``."""
    id: str
    """Its identifier, which stays the same when it's renamed."""


# scutil --nc list, one service a line; apps' VPNs have no [kind] at the end:
#   * (Disconnected)   <id> PPP --> L2TP   "Office"   [PPP:L2TP]
#   * (Connected)      <id> VPN (com.paloaltonetworks.GlobalProtect.client) "GlobalProtect"
_VPN_LINE = re.compile(r'^\s*\*?\s*\(([^)]*)\)\s+([0-9A-Fa-f-]{36})\s+(.*?)\s*"(.*)"(?:\s*\[([^\]]*)\])?\s*$')
_APP_VPN = re.compile(r"^VPN\s*\((.+)\)$")


def _vpn_kind(service: str, label: Optional[str]) -> str:
    if label:
        return re.split(r"[:/]", label)[-1].strip()  # "PPP:L2TP" -> "L2TP"
    app = _APP_VPN.match(service)
    if app:
        return app.group(1)
    return service.split("-->")[-1].strip()


def _vpns(output: str) -> List[VPN]:
    found = []
    for line in output.splitlines():
        match = _VPN_LINE.match(line)
        if not match:
            continue
        status, identifier, service, name, label = match.groups()
        kind = _vpn_kind(service, label)
        if kind == "Modem":
            continue  # a dial-up modem, the other kind of service scutil lists
        found.append(VPN(name=name, kind=kind, status=status.strip().lower(), id=identifier))
    return found


_SCUTIL_TIMEOUT = 30.0  # seconds: scutil answers at once, unless the network configuration daemon is stuck


def vpns() -> List[VPN]:
    """
    The VPNs set up in System Settings, with whether each is connected.

    ::

        macos.network.vpns()   # [VPN(name='Office', kind='L2TP', status='disconnected', ...)]

    VPN apps that don't add theirs to System Settings aren't here, and IKEv2
    VPNs may not be either: macOS has long left them out of what the command
    line sees.
    """
    require_macos()
    return _vpns(_run(["scutil", "--nc", "list"], timeout=_SCUTIL_TIMEOUT))


def _vpn(name: str) -> VPN:
    found = vpns()
    for vpn in found:
        if name in (vpn.name, vpn.id):
            return vpn
    known = ", ".join(repr(vpn.name) for vpn in found) or "none is set up"
    raise MacOSError("no VPN named {!r} (System Settings › VPN: {})".format(name, known))


def _wait_vpn(vpn: VPN, wanted: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    moved = False
    while True:
        status = _vpn(vpn.id).status
        if status == wanted:
            return
        if status in ("connected", "disconnected"):
            if moved:
                raise MacOSError("the VPN {!r} didn't get {}: it's {}".format(vpn.name, wanted, status))
        else:
            moved = True
        if time.monotonic() >= deadline:
            raise MacOSError("the VPN {!r} isn't {} after {} seconds: it's {}".format(vpn.name, wanted, timeout, status))
        time.sleep(0.25)


def connect_vpn(name: str, *, wait: bool = True, timeout: float = 30.0) -> None:
    """
    Connect the VPN ``name``, as set up in System Settings › VPN.

    Waits until it's connected (up to ``timeout`` seconds), and raises
    :class:`~macos.MacOSError` if it fails, unless ``wait=False``. It uses the
    password saved with it: a VPN that asks each time may show its prompt.
    Nothing to do when it's already connected. A ``scutil`` that doesn't
    answer within 30 seconds raises :class:`~macos.errors.CommandTimeoutError`.
    """
    vpn = _vpn(name)
    if vpn.status == "connected":
        return
    _run(["scutil", "--nc", "start", vpn.id], timeout=_SCUTIL_TIMEOUT)  # it only asks: the wait is below
    if wait:
        _wait_vpn(vpn, "connected", timeout)


def disconnect_vpn(name: str, *, wait: bool = True, timeout: float = 30.0) -> None:
    """Disconnect the VPN ``name``, waiting until it's done unless ``wait=False``. Nothing to do when it isn't connected."""
    vpn = _vpn(name)
    if vpn.status == "disconnected":
        return
    _run(["scutil", "--nc", "stop", vpn.id], timeout=_SCUTIL_TIMEOUT)
    if wait:
        _wait_vpn(vpn, "disconnected", timeout)


# --- Bandwidth --------------------------------------------------------------------

_IFMIB_IFDATA = (4, 18, 0, 2)  # CTL_NET, PF_LINK, NETLINK_GENERIC, IFMIB_IFDATA; then the index, IFDATA_GENERAL
_IFDATA_GENERAL = 1
# struct ifmibdata: a 16-byte name, five 32-bit numbers (the flags second), 16 bytes of filler, then an
# if_data64, whose 64-bit byte counters don't wrap at 4 GB as getifaddrs' 32-bit ones do.
_IFMD_FLAGS = 20
_IFMD_RECEIVED, _IFMD_SENT = 52 + 64, 52 + 72  # ifi_ibytes, ifi_obytes


@dataclass(frozen=True)
class Bandwidth:
    """How fast data went through a network interface, over an interval."""

    interface: str
    """The system's name for it, such as ``'en0'``."""
    display_name: Optional[str]
    """As System Settings names it, such as ``'Wi-Fi'``; ``None`` for virtual ones (VPN tunnels...)."""
    download: float
    """Megabits per second received, as :func:`speed_test` counts them."""
    upload: float
    """Megabits per second sent."""
    received: int
    """Bytes received in the interval."""
    sent: int
    """Bytes sent in the interval."""


def _interface_counters() -> Dict[str, Tuple[int, int, int]]:
    """Each interface's flags, and the bytes it received and sent since the Mac started."""
    libc = _libc.lib()
    found = {}
    for index, name in socket.if_nameindex():
        mib = (ctypes.c_int * 6)(*_IFMIB_IFDATA, index, _IFDATA_GENERAL)
        size = ctypes.c_size_t(512)
        data = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 6, data, ctypes.byref(size), None, 0) != 0 or size.value < _IFMD_SENT + 8:
            continue  # gone since it was listed
        flags = int.from_bytes(data.raw[_IFMD_FLAGS:_IFMD_FLAGS + 4], sys.byteorder) & 0xFFFF  # a short, widened
        received = int.from_bytes(data.raw[_IFMD_RECEIVED:_IFMD_RECEIVED + 8], sys.byteorder)
        sent = int.from_bytes(data.raw[_IFMD_SENT:_IFMD_SENT + 8], sys.byteorder)
        found[name] = (flags, received, sent)
    return found


def _bandwidth(
    before: Dict[str, Tuple[int, int, int]], after: Dict[str, Tuple[int, int, int]], seconds: float, names: Dict[str, str]
) -> List[Bandwidth]:
    found = []
    for name, (flags, received, sent) in after.items():
        if name not in before or not flags & _IFF_UP or flags & _IFF_LOOPBACK or not received + sent:
            continue  # gone, down, the loopback, or never used (the Mac has many idle virtual ones)
        # A counter that went back was reset (the interface came back): count from zero.
        got = received - before[name][1] if received >= before[name][1] else received
        gave = sent - before[name][2] if sent >= before[name][2] else sent
        found.append(
            Bandwidth(
                interface=name,
                display_name=names.get(name),
                download=round(got * 8 / seconds / 1e6, 2),
                upload=round(gave * 8 / seconds / 1e6, 2),
                received=got,
                sent=gave,
            )
        )
    return sorted(found, key=lambda use: (-(use.received + use.sent), use.interface))


def bandwidth(interval: float = 1.0) -> List[Bandwidth]:
    """
    How fast data is going through each network interface now, the busiest first.

    ::

        for use in macos.network.bandwidth():
            print(use.display_name or use.interface, use.download, use.upload)   # Wi-Fi 42.1 3.5

    Measures for ``interval`` seconds: ``download`` and ``upload`` are in
    megabits per second, like an internet plan's speed; ``received`` and
    ``sent`` are the bytes in that time. The interfaces that are up and have
    carried data since the Mac started are listed, idle ones at 0; the
    loopback (``lo0``) is left out. For which process
    moves the data, see :func:`macos.system.network_usage`; for how fast the
    connection can go, :func:`speed_test`.
    """
    if interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    require_macos()
    before, started = _interface_counters(), time.monotonic()
    time.sleep(interval)
    after, seconds = _interface_counters(), time.monotonic() - started
    return _bandwidth(before, after, seconds, _display_names())
