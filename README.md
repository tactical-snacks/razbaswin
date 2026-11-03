# razbaswin

Open source CLI to control Razer Basilisk V3 features on Windows. Uses protocols from [OpenSnek](https://github.com/gh123man/OpenSnek).

## Install

```sh
pip install -e .
```

Requires Python 3.10+ and [`hidapi`](https://pypi.org/project/hidapi/). No Razer Synapse needed.

## Usage

```sh
razbaswin info                             # firmware, serial, poll rate, DPI
razbaswin profile                          # everything in the active profile
razbaswin effect static ff0000 --zone logo # lighting, saved to the active profile
razbaswin backup                           # save all profiles to JSON
razbaswin reset                            # preview a factory reset (--yes to apply)
```

See [docs/USAGE.md](docs/USAGE.md) for all commands: lighting, profiles, backup/restore and factory reset.

## TODO

- [x] Hello world: read device info (firmware, serial, poll rate, DPI)
- [x] Read LEDs
- [x] Write LEDs
- [x] Read profiles
- [x] Back up profiles
- [x] Reset to factory defaults
- [x] Write profiles
- [ ] Basic settings (commands to change one setting directly, like `brightness`/`effect`)
  - [ ] DPI and DPI stages
  - [ ] Button mappings
  - [ ] Scroll mode, acceleration, smart reel
  - [ ] Poll rate
- [ ] Advanced settings
  - [ ] Hypershift layer (second button mapping while the Hypershift button is held)
  - [ ] Sleep timeout (`0x07:0x83` / `0x07:0x03`, factory 300 s)
  - [ ] Per-LED colors across all 11 LEDs (`0x0F:0x03`), for software effects like Synapse's wave
  - [ ] Lighting power: lights off when the display sleeps or the mouse is idle
  - [ ] Sensor calibration: lift-off / landing distance, surface calibration
- [ ] UI (maybe)

## How it talks to the mouse

For the memory model (profiles, slots, what a write touches), see [docs/PROTOCOL.md](docs/PROTOCOL.md).

Commands are 90-byte HID feature reports (report ID 0, transaction ID `0x1F`, XOR checksum over bytes 2–87), as documented in OpenSnek's `USBHIDProtocol.swift`. On Windows, the mouse and keyboard HID collections are locked by the OS. The control channel is reached through the consumer-control collection on **interface 3**.

| Setting | Read | Write |
|---|---|---|
| Firmware / serial | `0x00:0x81` / `0x00:0x82` | — |
| Poll rate | `0x00:0x85` | `0x00:0x05` |
| Current DPI | `0x04:0x85` | `0x04:0x05` |
| DPI stages | `0x04:0x86` | `0x04:0x06` |
| Scroll mode / acceleration / smart reel | `0x02:0x94` / `0x02:0x96` / `0x02:0x97` | `0x02:0x14` / `0x02:0x16` / `0x02:0x17` |
| Button binding | `0x02:0x8C` | `0x02:0x0C` |
| LED effect | `0x0F:0x82` | `0x0F:0x02` |
| LED brightness | `0x0F:0x84` | `0x0F:0x04` |
| Profile list / active profile | `0x05:0x81` / `0x05:0x84` | — |
| Create / select / delete profile | — | `0x05:0x02` / `0x05:0x04` / `0x05:0x03` |

LED zones: scroll wheel `0x01`, logo `0x04`, underglow `0x0A`.

## AI disclosure

This project was written with the help of AI (Claude Code). Protocol details come from OpenSnek and were checked against a real Basilisk V3.
