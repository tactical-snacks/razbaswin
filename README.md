# razbaswin

Open source CLI to control Razer Basilisk V3 featuers on Windows. Uses protocols from [OpenSnek](https://github.com/gh123man/OpenSnek)

## Install

```sh
pip install -e .
```

Requires Python 3.10+ and [`hidapi`](https://pypi.org/project/hidapi/). No Razer Synapse needed.

## Usage

```sh
razbaswin list   # show the mouse's HID interfaces
razbaswin info   # read firmware, serial, poll rate and DPI stages
```

You can also run it without installing: `python -m razbaswin info`.

## TODO

- [x] Hello world: read device info (firmware, serial, poll rate, DPI)
- [ ] Read LEDs
- [ ] Write LEDs
- [ ] Read profiles
- [ ] Back up profiles
- [ ] Write profiles
- [ ] UI (maybe)

## How it talks to the mouse

Commands are 90-byte HID feature reports (report ID 0, transaction ID `0x1F`, XOR checksum over bytes 2–87), as documented in OpenSnek's `USBHIDProtocol.swift`. On Windows, the mouse and keyboard HID collections are locked by the OS. The control channel is reached through the consumer-control collection on **interface 3**.

| Read           | Class:Cmd   |
|----------------|-------------|
| Firmware       | `0x00:0x81` |
| Serial         | `0x00:0x82` |
| Poll rate      | `0x00:0x85` |
| Current DPI    | `0x04:0x85` |
| DPI stages     | `0x04:0x86` |

## AI disclosure

This project was written with the help of AI (Claude Code). Protocol details come from OpenSnek and were checked against a real Basilisk V3.
