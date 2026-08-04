#!/usr/bin/env bash
# Manually read battery levels for both halves of the Sweep split keyboard
# over BLE GATT, using bluetoothctl (BlueZ) - no extra packages required.
#
# Requires: config/Sweep.conf built with CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING
# and CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_PROXY enabled, flashed, and the keyboard
# already paired/connected to this machine.
#
# Usage: ./scripts/check-battery.sh [device-name-substring]
#   Default device name substring: "SweepPlus" (CONFIG_ZMK_KEYBOARD_NAME in config/Sweep.conf)

set -euo pipefail

DEVICE_NAME="${1:-SweepPlus}"

MAC=$(bluetoothctl devices | awk -v name="$DEVICE_NAME" 'index($0, name) { print $2; exit }')
if [[ -z "${MAC:-}" ]]; then
  echo "No paired device matching '$DEVICE_NAME' found in 'bluetoothctl devices'." >&2
  echo "Make sure the keyboard is powered on, paired, and connected first." >&2
  exit 1
fi

DEVICE_PATH="/org/bluez/hci0/dev_${MAC//:/_}"
echo "Device: $DEVICE_NAME ($MAC)"

# Battery Level characteristic UUID is 00002a19-...; there should be one instance
# per proxied Battery Service (central's own + the peripheral's proxied one).
# list-attributes/select-attribute/read live under the "gatt" submenu on
# BlueZ >= 5.6x - they are not top-level bluetoothctl commands.
mapfile -t CHAR_PATHS < <(
  bluetoothctl <<EOF | grep -B1 '00002a19-' | grep "$DEVICE_PATH" | sort -u
menu gatt
list-attributes "$MAC"
back
EOF
)

if [[ ${#CHAR_PATHS[@]} -eq 0 ]]; then
  echo "No Battery Level (0x2A19) characteristics found. Is the device connected," >&2
  echo "and was it flashed with battery proxying enabled?" >&2
  exit 1
fi

echo "Found ${#CHAR_PATHS[@]} Battery Level characteristic(s):"

i=0
for CHAR_PATH in "${CHAR_PATHS[@]}"; do
  i=$((i + 1))
  echo "--- Battery service #$i ($CHAR_PATH) ---"
  OUTPUT=$(bluetoothctl <<EOF
menu gatt
select-attribute $CHAR_PATH
read
back
EOF
)
  HEX_BYTE=$(echo "$OUTPUT" | grep -A1 'Value:' | tail -n1 | awk '{print $1}')
  if [[ -n "$HEX_BYTE" ]]; then
    DEC=$((16#$HEX_BYTE))
    echo "Battery level: ${DEC}%"
  else
    echo "Could not parse value. Raw output:"
    echo "$OUTPUT"
  fi
done
