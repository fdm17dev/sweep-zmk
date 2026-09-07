# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This repo is **both** a ZMK user config (`config/`) and a Zephyr module shipping a
custom shield (`boards/shields/Sweep/`, wired up by `zephyr/module.yml`).

## Common Development Commands

**Build (CI)**
Normal workflow is to push and let `.github/workflows/build.yml` build via
`zmkfirmware/zmk/.github/workflows/build-user-config.yml@v0.3`; the matrix comes
from `build.yaml`. Firmware `.uf2` files land in the run's `firmware` artifact.

**Build (local)**
Requires a west workspace initialised from `config/west.yml`. Because
`zephyr/module.yml` exists, the repo root must be passed as an extra module:

```
west init -l config && west update && west zephyr-export
west build -s zmk/app -d build/left  -b nice_nano_v2 -S studio-rpc-usb-uart -- \
    -DSHIELD=Sweep_left  -DZMK_CONFIG="$PWD/config" -DZMK_EXTRA_MODULES="$PWD" \
    -DCONFIG_ZMK_STUDIO=y
west build -s zmk/app -d build/right -b nice_nano_v2 -- \
    -DSHIELD=Sweep_right -DZMK_CONFIG="$PWD/config" -DZMK_EXTRA_MODULES="$PWD"
```

**Flash**
Double-tap reset to expose the nice!nano bootloader as a USB mass-storage
device, then copy `build/<side>/zephyr/zmk.uf2` onto it. Both halves must be
flashed after any change to `config/Sweep.conf`. There is no `west flash` path
for these boards, and ZMK has no `west test` command.

**Keymap**
`config/Sweep.keymap` is the source of truth. `keymap-drawer/Sweep.yaml` and
`keymap-drawer/Sweep.svg` are generated from it by the "Draw Layout" workflow -
do not hand-edit them.

## Key Architecture Elements

1. **Config resolution** - ZMK picks up `config/<name>.conf` for names derived
   from the shield: for `Sweep_left` it loads `config/Sweep.conf` (shield
   directory name) *and* `config/Sweep_left.conf`, both. Shared settings go in
   `Sweep.conf`; anything gated behind `ZMK_SPLIT_ROLE_CENTRAL` must go in
   `Sweep_left.conf` or it will warn on the peripheral build.
   The keymap is resolved the same way, first match wins: `config/Sweep.keymap`.

2. **Shield definition** - `boards/shields/Sweep/` holds `Kconfig.shield`
   (declares `SHIELD_Sweep_LEFT`/`SHIELD_Sweep_RIGHT`), `Kconfig.defconfig`
   (sets `ZMK_SPLIT`, and `ZMK_SPLIT_ROLE_CENTRAL` for the left half),
   `Sweep.dtsi` + `Sweep-layouts.dtsi` (matrix, encoders, physical layout) and
   the two `Sweep_{left,right}.overlay` files. `Sweep.yml` is metadata only,
   validated against ZMK's `schema/hardware-metadata.schema.json`.

3. **Version pinning** - `config/west.yml` pins ZMK to `v0.3`. Do not move to
   `main`: the Zephyr 4.1 / HWMv2 migration lands in v0.4 and carries a known
   ZMK Studio + sleep regression on split nRF52840 (zmkfirmware/zmk#3195).

4. **Battery over BLE** - the left half proxies the right half's battery level
   as a second GATT Battery Service instance (`Sweep_left.conf`). Host-side
   tooling lives in the `tech-docs` repo under `ZMK-STATUS/scripts/`.
