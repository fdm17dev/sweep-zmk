# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

**Build Process**  
Use Zephyr's `west` toolchain for builds:  
- Basic build: `west build -b nice_nano_v2 -d .output <project_name>`  
- With shields: `west build -b nice_nano_v2 -d .output -D CONFIG_ZMK_SPLIT_ROLE_CENTRAL=n`  
- Studio-enabled: `west build -b nice_nano_v2 -d .output -DCONFIG_ZMK_STUDIO=y`  

**Testing**  
- Run all tests: `west test`  
- Run specific test: `west test --test=test_file`  
- Flash to hardware: `west flash`  

**Keymap Management**  
- Modify keymaps: Edit `.yaml` files in `keymap-drawer/` or `boards/shields/Sweep/`  
- Validate layouts: Use `dtsi` files in `Sweep-layouts.dtsi`  

## Key Architecture Elements

1. **Zephyr-Based Modular Structure**  
   - Core project in `zephyr/` module with `module.yml` manifest  
   - `west.yml` manages project dependencies and module imports  

2. **Shield-Board Integration**  
   - Shields (`Sweep_left/Sweep_right`) are modular components in `boards/shields/`  
   - Keymaps defined in YAML files (e.g., `Sweep.keymap`) and rendered via SVG (`keymap-drawer/Sweep.svg`)  

3. **Build Configuration**  
   - `build.yaml` defines GitHub Actions matrix builds with optional snippets and CMake flags  
   - Common flags: `-DCONFIG_ZMK_STUDIO=y` for studio features, `-DCONFIG_ZMK_SPLIT_ROLE_CENTRAL` for split keyboard roles  

4. **Customization Workflow**  
   - Keymap changes require:  
     1. Edit `.yaml` definitions  
     2. Rebuild with `west build`  
     3. Flash to device with `west flash`  

This structure emphasizes Zephyr kernel integration with modular hardware components and configuration-driven customization.