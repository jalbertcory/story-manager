"""Identify the current macOS Kindle USB attachment."""

import plistlib
import subprocess


def kindle_connections(tree):
    """Registry entry IDs change on reattachment, even in the same USB port."""
    nodes = list(tree) if isinstance(tree, list) else [tree]
    devices = set()
    while nodes:
        device = nodes.pop()
        nodes.extend(device.get("IORegistryEntryChildren", []))
        name = device.get("USB Product Name") or device.get("IORegistryEntryName", "")
        if device.get("idVendor") == 0x1949 and (device.get("idProduct") == 0x9981 or "kindle" in name.lower()):
            devices.add(device["IORegistryEntryID"])
    return frozenset(devices)


def connected():
    data = subprocess.check_output(["/usr/sbin/ioreg", "-a", "-p", "IOUSB", "-l"], timeout=15)
    return kindle_connections(plistlib.loads(data))
