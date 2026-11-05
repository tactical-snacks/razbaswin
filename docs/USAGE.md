# Usage

Every command talks to the first Razer Basilisk V3 it finds. Run `razbaswin <command> -h` for all options. Without installing, use `python -m razbaswin <command>` from the repo folder.

## Slots and profiles

The mouse keeps its settings in **slots**:

| Slot | What it is |
|---|---|
| `0` | Live state: what the mouse is doing right now. Changes here are lost on replug. |
| `1`–`5` | Onboard profile banks. Each holds DPI, lighting, scroll settings and button mappings. |

A bank only becomes a **profile** (one the profile button cycles through) once it's created. Out of the box only profile 1 exists. Poll rate is global and not part of any profile. See [PROTOCOL.md](PROTOCOL.md) for details.

## Reading

```sh
razbaswin info                 # firmware, serial, poll rate, DPI stages
razbaswin leds                 # effect and brightness of each LED zone (live state)
razbaswin leds --slot 2        # ...of profile bank 2 instead (--raw adds the bytes)
razbaswin profiles             # the 5 slots: which are profiles, which is active
razbaswin profile              # everything in the active profile
razbaswin profile 2            # ...in slot 2 (0 = live state)
razbaswin profile 2 --json     # as JSON (--raw adds button bytes)
razbaswin list                 # the mouse's USB HID interfaces (troubleshooting)
```

## Lighting

```sh
razbaswin brightness 50%                         # or a raw value 0-255
razbaswin effect static ff0000 --zone logo
razbaswin effect static random                   # a random vivid color, live state only
razbaswin effect spectrum                        # the factory rainbow cycle (fixed rate)
razbaswin effect wave --speed 20 --direction 2   # speed 1-255, lower is faster (default 40)
razbaswin effect off
```

Effects: `off`, `static RRGGBB`, `spectrum`, `wave`. The mouse rejects breathing and reactive; Synapse draws those on the PC.

`static random` picks a random hue at full saturation and brightness and prints its hex value. It's for trying colors out, so it only changes the live state, like `--temp`. To keep one, re-run with the printed value, or add `--profile N` to save the random color to profile N. It works with `--zone` and `--trans instant`.

Options for both commands:

| Option | Meaning |
|---|---|
| *(none)* | Write the active profile. Saved, and shown immediately. |
| `--temp` | Change only the live state. Lost on replug. |
| `--profile N` | Write profile bank N. Only visible once profile N is active. |
| `--zone Z` | `scroll`, `logo`, `underglow`, or `all` (default). |

Effect changes crossfade slowly; that fade is built into the mouse. `--trans instant` skips it for `static` and `off` by painting the LEDs directly:

```sh
razbaswin effect static 0000ff --trans instant   # switches at once, live state only
```

An instant color can't be saved, so `--trans instant` implies `--temp` and can't be combined with `--profile`. While it's showing, `leds` reports the zone as `custom`. Spectrum and wave always fade in.

## Profiles

```sh
razbaswin profiles --create 2               # new profile 2 with factory settings
razbaswin profiles --create 2 --from 1      # ...or a copy of slot 1 (any slot 0-5)
razbaswin profiles --activate 2             # switch profile, like the profile button
razbaswin profiles --delete 2               # remove it from the profile button's cycle
```

Creating a profile resets part of its bank, so `--create` always writes the full settings and checks them. Deleting keeps the bank's settings, but they're no longer a profile. The active profile and the last remaining profile can't be deleted.

## Backup and restore

```sh
razbaswin backup                            # razbaswin-backup-<timestamp>.json in the current folder
razbaswin backup backup/before-changes.json # or a file of your choice

razbaswin restore backup/before-changes.json          # preview what would change
razbaswin restore backup/before-changes.json --yes    # apply it
razbaswin restore FILE --slot 1 --yes                 # restore one slot only
razbaswin restore FILE --slot 1 --to 3 --yes          # copy backed-up slot 1 into slot 3
```

A backup holds every slot, which profiles exist, the active profile, the poll rate and the device's firmware and serial. A full restore brings all of that back, creating or deleting profiles as needed. Only settings that differ are written, and everything is read back afterwards to confirm.

Backups contain the mouse's serial number. In this repo, `backup/` and `razbaswin-backup-*.json` are git-ignored.

## Factory reset

```sh
razbaswin reset                  # preview what would change
razbaswin reset --yes            # reset all slots and the poll rate
razbaswin reset --slot 5 --yes   # reset one slot only (0 = live state)
```

Factory values come from Synapse's defaults for this mouse: spectrum at 70%, DPI stages 400/800/1600/3200/6400 with 1600 active, tactile scroll, the stock button mapping, 1000 Hz.

Not reset: which profiles exist and which is active, the Hypershift layer, the sleep timeout and sensor calibration.

## Run at login

[`bat/random-color.bat`](../bat/random-color.bat) runs `effect static random`, retrying for about 30 seconds in case the mouse isn't ready yet. To run it hidden at every login, put a shortcut in the Startup folder (Win+R, `shell:startup`) with:

| Field | Value |
|---|---|
| Target | `pythonw.exe "<repo>\bat\run-hidden.pyw" "<repo>\bat\random-color.bat"` |
| Start in | `<repo>` |

[`bat/run-hidden.pyw`](../bat/run-hidden.pyw) runs any `.bat` without a console window. The shortcut holds the repo's path, so recreate it if the repo moves. Delete the shortcut to stop it.

## Safety

- `reset` and `restore` only preview unless given `--yes`, and save a backup first (`--no-backup` to skip).
- `brightness` and `effect` write immediately. Use `--temp` to try something out without saving it.
- A replug always brings the live state back to the active profile.
