# razbaswin

Open source CLI to control Razer Basilisk V3 features on Windows. Uses protocols from [OpenSnek](https://github.com/gh123man/OpenSnek)

## Install

```sh
pip install -e .
```

Requires Python 3.10+ and [`hidapi`](https://pypi.org/project/hidapi/). No Razer Synapse needed.

## Usage

```sh
razbaswin list   # show the mouse's HID interfaces
razbaswin info   # read firmware, serial, poll rate and DPI stages
razbaswin leds   # read effect and brightness for each LED zone (--raw for bytes)
razbaswin leds --slot 2                          # read a stored profile bank instead of live state
razbaswin profiles                               # list the 5 onboard profile slots
razbaswin profile                                # DPI, lighting, scroll and buttons of the active profile
razbaswin profile 2 --json                       # one slot (0 = live) as JSON; --raw shows button bytes

razbaswin brightness 50%                         # all zones, saved to the active profile
razbaswin effect static ff0000 --zone logo       # off | static RRGGBB | spectrum | wave
razbaswin effect spectrum                        # factory rainbow cycle (fixed rate)
razbaswin effect wave --speed 20 --direction 2   # speed 1-255, lower is faster (default 40)
razbaswin effect off --temp                      # --temp: live only, reverts on replug
```

Writes default to the active onboard profile, so they persist. `--temp` changes only what's showing now. `--profile N` writes a specific profile bank. `--zone` is `scroll`, `logo`, `underglow` or `all` (default).

You can also run it without installing: `python -m razbaswin info`.

## TODO

- [x] Hello world: read device info (firmware, serial, poll rate, DPI)
- [x] Read LEDs
- [x] Write LEDs
- [x] Read profiles
- [ ] Back up profiles
- [ ] Reset to factory defaults
- [ ] Write profiles
- [ ] UI (maybe)

## How it talks to the mouse

For the memory model (profiles, slots, what a write touches), see [docs/PROTOCOL.md](docs/PROTOCOL.md).

Commands are 90-byte HID feature reports (report ID 0, transaction ID `0x1F`, XOR checksum over bytes 2–87), as documented in OpenSnek's `USBHIDProtocol.swift`. On Windows, the mouse and keyboard HID collections are locked by the OS. The control channel is reached through the consumer-control collection on **interface 3**.

| Command         | Class:Cmd   |
|-----------------|-------------|
| Firmware        | `0x00:0x81` |
| Serial          | `0x00:0x82` |
| Poll rate       | `0x00:0x85` |
| Current DPI     | `0x04:0x85` |
| DPI stages      | `0x04:0x86` |
| Active profile  | `0x05:0x84` |
| Profile list    | `0x05:0x81` |
| Scroll mode / acceleration / smart reel | `0x02:0x94` / `0x02:0x96` / `0x02:0x97` |
| Button binding  | `0x02:0x8C` |
| LED effect      | `0x0F:0x82` read, `0x0F:0x02` write |
| LED brightness  | `0x0F:0x84` read, `0x0F:0x04` write |

LED zones: scroll wheel `0x01`, logo `0x04`, underglow `0x0A`.

## AI disclosure

This project was written with the help of AI (Claude Code). Protocol details come from OpenSnek and were checked against a real Basilisk V3.
