"""
The kernel structures the package reads by offset, checked against the SDK's headers.

:mod:`macos.system` and :mod:`macos.network` read ``proc_pidfdinfo``, ``proc_pid_rusage`` and ``sysctl``
answers at offsets declared as plain numbers: a layout that moved in a macOS release would give wrong
numbers, not an error. This compiles a small C program against the installed SDK and compares.
"""

import shutil
import subprocess
import sys

import pytest

from macos import network, system

PROBE = r"""
#include <stdio.h>
#include <stddef.h>
#include <sys/proc_info.h>
#include <sys/resource.h>
#include <net/if_mib.h>
#include <net/if_dl.h>
#include <sys/param.h>
#define SHOW(name, value) printf("%s %zu\n", name, (size_t)(value))
int main(void) {
  SHOW("socket", offsetof(struct socket_fdinfo, psi));
  SHOW("socket_type", offsetof(struct socket_fdinfo, psi) + offsetof(struct socket_info, soi_type));
  SHOW("socket_family", offsetof(struct socket_fdinfo, psi) + offsetof(struct socket_info, soi_family));
  SHOW("socket_kind", offsetof(struct socket_fdinfo, psi) + offsetof(struct socket_info, soi_kind));
  SHOW("proto", offsetof(struct socket_fdinfo, psi) + offsetof(struct socket_info, soi_proto));
  SHOW("remote_port", offsetof(struct in_sockinfo, insi_fport));
  SHOW("local_port", offsetof(struct in_sockinfo, insi_lport));
  SHOW("remote_address", offsetof(struct in_sockinfo, insi_faddr));
  SHOW("local_address", offsetof(struct in_sockinfo, insi_laddr));
  SHOW("tcp_state", offsetof(struct tcp_sockinfo, tcpsi_state));
  SHOW("socket_fdinfo_size", sizeof(struct socket_fdinfo));
  SHOW("file_path", offsetof(struct vnode_fdinfowithpath, pvip) + offsetof(struct vnode_info_path, vip_path));
  SHOW("vnode_info", offsetof(struct vnode_info_path, vip_path));
  SHOW("folders_info_size", sizeof(struct proc_vnodepathinfo));
  SHOW("maxpathlen", MAXPATHLEN);
  SHOW("rusage_size", sizeof(struct rusage_info_v6));
  SHOW("energy", offsetof(struct rusage_info_v6, ri_energy_nj));
  SHOW("started", offsetof(struct rusage_info_v6, ri_proc_start_abstime));
  SHOW("disk_read", offsetof(struct rusage_info_v6, ri_diskio_bytesread));
  SHOW("disk_written", offsetof(struct rusage_info_v6, ri_diskio_byteswritten));
  SHOW("ifmd_flags", offsetof(struct ifmibdata, ifmd_flags));
  SHOW("ifmd_received", offsetof(struct ifmibdata, ifmd_data) + offsetof(struct if_data64, ifi_ibytes));
  SHOW("ifmd_sent", offsetof(struct ifmibdata, ifmd_data) + offsetof(struct if_data64, ifi_obytes));
  SHOW("sdl_nlen", offsetof(struct sockaddr_dl, sdl_nlen));
  SHOW("sdl_alen", offsetof(struct sockaddr_dl, sdl_alen));
  SHOW("sdl_data", offsetof(struct sockaddr_dl, sdl_data));
  return 0;
}
"""


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("cc") is None, reason="needs the macOS SDK and a C compiler"
)
def test_the_offsets_read_from_kernel_structures_match_the_sdk(tmp_path):
    source, binary = tmp_path / "probe.c", tmp_path / "probe"
    source.write_text(PROBE)
    subprocess.run(["cc", "-o", str(binary), str(source)], check=True, capture_output=True)
    printed = subprocess.run([str(binary)], capture_output=True, text=True, check=True).stdout
    found = {name: int(value) for name, value in (line.split() for line in printed.splitlines())}

    assert found["socket"] == system._SOCKET
    assert found["socket_type"] == system._SOCKET_TYPE
    assert found["socket_family"] == system._SOCKET_FAMILY
    assert found["socket_kind"] == system._SOCKET_KIND
    assert found["proto"] == system._PROTO
    assert found["remote_port"] == system._REMOTE_PORT - system._PROTO
    assert found["local_port"] == system._LOCAL_PORT - system._PROTO
    assert found["remote_address"] == system._REMOTE_ADDRESS - system._PROTO
    assert found["local_address"] == system._LOCAL_ADDRESS - system._PROTO
    assert found["tcp_state"] == system._TCP_STATE - system._PROTO
    assert found["socket_fdinfo_size"] <= system._SOCKET_INFO_SIZE  # read whole, whatever the protocol's part
    assert found["vnode_info"] == system._VNODE_INFO
    assert found["file_path"] == system._FILE_PATH
    assert found["maxpathlen"] == system._MAXPATHLEN
    assert found["folders_info_size"] == system._FOLDERS_INFO_SIZE
    assert found["rusage_size"] == system._RUSAGE_INFO_SIZE
    assert found["energy"] == system._ENERGY_NJ
    assert found["started"] == system._STARTED
    assert found["disk_read"] == system._DISK_READ
    assert found["disk_written"] == system._DISK_WRITTEN
    assert found["ifmd_flags"] == network._IFMD_FLAGS
    assert found["ifmd_received"] == network._IFMD_RECEIVED
    assert found["ifmd_sent"] == network._IFMD_SENT
    # network.interfaces() reads a sockaddr_dl as raw[5], raw[6] and raw[8:].
    assert (found["sdl_nlen"], found["sdl_alen"], found["sdl_data"]) == (5, 6, 8)
