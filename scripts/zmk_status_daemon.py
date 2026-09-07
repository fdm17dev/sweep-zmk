#!/usr/bin/env python3
"""ZMK status daemon for the Sweep split keyboard, over BlueZ D-Bus.

Extends check-battery.sh (bluetoothctl scripting) into an event-driven daemon
using dbus-python. Reads, over the same BLE GATT connection already used by
check-battery.sh:

  - battery level, left (central) and right (peripheral, proxied) — via
    GATT notifications on the standard Battery Level characteristic
    (0x2A19), instead of polling.
  - active BLE profile (best-effort) — inferred from a static MAC-address to
    `&bt BT_SEL` slot table you provide, cross-referenced against
    `org.bluez.Device1.Connected`. ZMK does not expose the active-profile
    index over a standard GATT characteristic, so this is a heuristic, not a
    firmware-reported value. See ZMK-STATUS/research-sweep-hardware-
    integration.md (Câu hỏi 5, Phương án A) for why this approach was chosen
    over ZMK Studio RPC (which has no battery/profile/output messages).
  - output endpoint (BLE vs USB) — inferred from whether a USB CDC ACM
    serial device (/dev/ttyACM*) is present. Also a heuristic: ZMK does not
    expose `zmk,output` state over GATT or Studio RPC either.

Requires: same firmware config as check-battery.sh (CONFIG_ZMK_SPLIT_BLE_
CENTRAL_BATTERY_LEVEL_FETCHING/PROXY=y), keyboard already paired/connected,
and the `dbus`/`gi` Python packages (dbus-python + PyGObject) available
system-wide (no extra pip install needed on most distros).

Usage:
    ./scripts/zmk_status_daemon.py [--device NAME] [--profiles FILE] [--once]

  --device NAME    Substring of the BLE device name (default: SweepPlus,
                    i.e. CONFIG_ZMK_KEYBOARD_NAME in boards/shields/Sweep/
                    Sweep.conf).
  --profiles FILE  JSON file mapping `&bt BT_SEL` slot index to the MAC
                    address paired in that slot, e.g.:
                        {"0": "AA:BB:CC:DD:EE:01", "1": "AA:BB:CC:DD:EE:02"}
                    Optional — without it, active-profile detection is
                    skipped (battery + output still work).
  --once           Print one JSON snapshot and exit, instead of running as
                    an event-driven daemon. Useful to diff against
                    check-battery.sh's output while validating this script.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

BLUEZ_SERVICE = "org.bluez"
DEVICE_IFACE = "org.bluez.Device1"
GATT_CHAR_IFACE = "org.bluez.GattCharacteristic1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"


class ZmkStatus:
    def __init__(self, device_name: str, profiles: dict[str, str]):
        self.device_name = device_name
        # slot (str) -> MAC ; also build the reverse MAC -> slot map.
        self.profiles = profiles
        self.mac_to_slot = {mac.upper(): slot for slot, mac in profiles.items()}

        self.bus = dbus.SystemBus()
        self.state = {
            "device": device_name,
            "battery": {},  # e.g. {"left": 91, "right": 82}
            "active_profile": None,
            "output": None,
            "timestamp": None,
        }

    # -- discovery ---------------------------------------------------

    def _objects(self):
        manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE, "/"),
            "org.freedesktop.DBus.ObjectManager",
        )
        return manager.GetManagedObjects()

    def find_keyboard_device_path(self) -> str:
        for path, ifaces in self._objects().items():
            dev = ifaces.get(DEVICE_IFACE)
            if dev and self.device_name in str(dev.get("Name", "")):
                return path
        raise RuntimeError(
            f"No connected device matching '{self.device_name}' found. "
            "Make sure the keyboard is powered on, paired, and connected."
        )

    def find_battery_char_paths(self, device_path: str) -> list[str]:
        paths = []
        for path, ifaces in self._objects().items():
            char = ifaces.get(GATT_CHAR_IFACE)
            if (
                char
                and path.startswith(device_path + "/")
                and str(char.get("UUID", "")).lower() == BATTERY_LEVEL_UUID
            ):
                paths.append(path)
        return sorted(paths)

    # -- battery -------------------------------------------------------

    def _battery_label(self, index: int, total: int) -> str:
        if total <= 1:
            return "left"
        return "left" if index == 0 else "right"

    def start_battery_notify(self, char_paths: list[str]):
        for i, path in enumerate(char_paths):
            label = self._battery_label(i, len(char_paths))
            obj = self.bus.get_object(BLUEZ_SERVICE, path)
            char = dbus.Interface(obj, GATT_CHAR_IFACE)
            props = dbus.Interface(obj, PROPS_IFACE)

            # Seed initial value (characteristic already cached by BlueZ).
            try:
                value = props.Get(GATT_CHAR_IFACE, "Value")
                self._on_battery_value(label, value)
            except dbus.exceptions.DBusException:
                pass

            props.connect_to_signal(
                "PropertiesChanged",
                lambda iface, changed, invalidated, label=label: (
                    self._on_battery_value(label, changed["Value"])
                    if iface == GATT_CHAR_IFACE and "Value" in changed
                    else None
                ),
            )
            try:
                char.StartNotify()
            except dbus.exceptions.DBusException as exc:
                print(
                    f"warning: StartNotify failed for {label} battery "
                    f"({path}): {exc}",
                    file=sys.stderr,
                )

    def _on_battery_value(self, label: str, value):
        level = int(bytes(value)[0]) if len(value) else None
        self.state["battery"][label] = level
        self.emit()

    # -- active profile (heuristic) -------------------------------------

    def start_profile_tracking(self):
        if not self.mac_to_slot:
            return
        for path, ifaces in self._objects().items():
            dev = ifaces.get(DEVICE_IFACE)
            if not dev:
                continue
            mac = str(dev.get("Address", "")).upper()
            if mac not in self.mac_to_slot:
                continue
            self._on_profile_connected(mac, bool(dev.get("Connected", False)))

            props = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE, path), PROPS_IFACE
            )
            props.connect_to_signal(
                "PropertiesChanged",
                lambda iface, changed, invalidated, mac=mac: (
                    self._on_profile_connected(mac, bool(changed["Connected"]))
                    if iface == DEVICE_IFACE and "Connected" in changed
                    else None
                ),
            )

    def _on_profile_connected(self, mac: str, connected: bool):
        slot = self.mac_to_slot.get(mac)
        if slot is None:
            return
        if connected:
            self.state["active_profile"] = {
                "slot": int(slot),
                "mac": mac,
            }
            self.emit()
        elif (
            self.state["active_profile"]
            and self.state["active_profile"]["mac"] == mac
        ):
            self.state["active_profile"] = None
            self.emit()

    # -- output endpoint (heuristic) -------------------------------------

    def refresh_output(self):
        usb_present = bool(glob.glob("/dev/ttyACM*"))
        self.state["output"] = "USB" if usb_present else "BLE"

    # -- emit -------------------------------------------------------------

    def emit(self):
        self.state["timestamp"] = time.time()
        print(json.dumps(self.state), flush=True)

    def snapshot(self) -> dict:
        self.refresh_output()
        self.state["timestamp"] = time.time()
        return self.state


def load_profiles(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="SweepPlus")
    parser.add_argument("--profiles", default=None)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    profiles = load_profiles(args.profiles)
    status = ZmkStatus(args.device, profiles)

    device_path = status.find_keyboard_device_path()
    char_paths = status.find_battery_char_paths(device_path)
    if not char_paths:
        print(
            "warning: no Battery Level (0x2A19) characteristics found — "
            "is CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING/PROXY "
            "enabled and flashed?",
            file=sys.stderr,
        )

    status.start_battery_notify(char_paths)
    status.start_profile_tracking()
    status.refresh_output()

    if args.once:
        print(json.dumps(status.snapshot()))
        return

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
