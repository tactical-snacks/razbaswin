# How the Basilisk V3 stores its settings

Settings memory layout and write behavior.

Sources: [OpenSnek](https://github.com/gh123man/OpenSnek)'s `USB_PROTOCOL.md` and `USB_PROFILE_CRUD_SPEC.md`, plus probes of a wired Basilisk V3 (PID `0x0099`, firmware 1.2). OpenSnek validated most of this on the **Basilisk V3 Pro** and treats the wired V3 as the same firmware family. Items confirmed on the test V3 are marked ✅. Items carried over from the V3 Pro are marked ⚠️.

## Transport in one paragraph

The mouse enumerates as a composite USB HID device. Settings go through a vendor channel: a **90-byte feature report**, exchanged with `SET_REPORT` followed by `GET_REPORT` (report ID 0). Bytes 6–7 select a command (class, ID). The ID's top bit marks a read (`0x0F:0x82` reads an LED effect, `0x0F:0x02` writes it). Arguments go in bytes 8–87. Byte 88 is an XOR checksum over bytes 2–87, and byte 0 of the reply is a status (`0x02` ok, `0x01` busy, `0x03` rejected, `0x05` unsupported). On Windows only interface 3 accepts it, because the OS holds the mouse and keyboard collections exclusively. ✅

In effect, a register file behind an RPC: no memory-mapped access, only typed get/set commands.

## The memory model

```
            ┌──────────────────────────── device-global ────────────────────────────┐
            │ poll rate · sleep timeout · low-battery threshold · device mode       │
            │ serial · firmware                    (no slot byte, not in profiles)  │
            └───────────────────────────────────────────────────────────────────────┘

 slot 0  ── "effective" / direct layer: what the sensor and LEDs are running RIGHT NOW
    ▲        (a working copy; volatile)
    │  05:04 select profile → firmware loads that bank into slot 0
    │
 slot 1  ── base profile bank   ┐
 slot 2  ── profile bank        │  persistent; each bank holds:
 slot 3  ── profile bank        │   name/UUID/owner · DPI + DPI stages · button bindings
 slot 4  ── profile bank        │   · per-zone LED effect + brightness · scroll settings
 slot 5  ── profile bank        ┘

 05:84 → active profile ID (a pointer)    05:81 → which banks are "assigned" (in the cycle ring)
```

Every profile-scoped command takes a **slot byte as its first argument**. That one byte decides which bank a read or write touches. ✅

| Slot | Meaning |
|---|---|
| `0` | Effective active state, mirroring the selected profile. Writes apply immediately but don't persist. |
| `1` | Base profile bank. Normally the active one. |
| `2`–`5` | Stored profile banks. |

Current state of the test unit: max profile ID 5, assigned = `[1]`, active = `1`. Banks 2–5 still answer reads, with what look like factory defaults. ✅

### What's in a profile, and what isn't

| Setting | Where it lives |
|---|---|
| DPI (current) and DPI stage table | Per bank, mirrored in slot 0 ✅ |
| LED effect and brightness, per zone | Per bank, mirrored in slot 0 ✅ (reads) |
| Button bindings (incl. Hypershift layer) | Per bank, mirrored in slot 0 ⚠️ |
| Scroll mode, acceleration, smart reel | Per bank ⚠️ |
| Profile name / UUID / owner (250-byte metadata) | Per bank ⚠️ |
| Poll rate, sleep timeout, device mode | **Global**, not part of any profile ⚠️ |
| Per-LED custom frames (underglow animation) | **Neither.** A RAM frame buffer that's lost on restart ⚠️ |
| Macros, Synapse "cloud" profiles | Not mapped. Synapse keeps most of its profiles on the PC, and only the onboard ones live here. |

So **profiles don't cover everything.** Poll rate in particular sits outside them: switching profiles won't change it, and a profile backup won't include it.

## What a write actually touches

A write changes **exactly one setting, in one bank, for one zone or button**. There's no "write whole profile" command and no transaction. A profile is a set of independent registers, and backup or restore means reading or writing each one in turn. ⚠️

**Writing just the LEDs:**

| Write target | Effect |
|---|---|
| Slot `0` | Visible immediately. No bank changes. Reverts when the mouse reloads its profile (replug, sleep/wake, profile switch). ⚠️ |
| The **active** bank (usually `1`) | Persists, and is what OpenSnek's own lighting controls do. Other settings in that bank (DPI, buttons) are untouched. ⚠️ |
| An **inactive** bank (e.g. `2`) | Persists in that bank only. Nothing visible changes until that profile is selected with `05:04`. On the V3 Pro, selecting it then made slot 0 show the new colors. ⚠️ |
| Custom frame (`0x0F:0x03`) | Switches the addressed LEDs to a "custom" effect, fed from a 14-cell buffer (logo + scroll wheel + 12 underglow). Never persisted: after a restart the bank's stored effect comes back. ⚠️ |

So an LED write **won't corrupt other profile data**. Two common surprises:

- **Writing slot 0 and expecting it to stick.** It won't survive a profile reload.
- **Writing bank 1 while another profile is active.** Profile 1's lighting changes, but the LEDs show the active profile's, so nothing appears to happen.

Safe pattern for a persistent change: read `05:84` for the active profile ID, write to that bank, then read back slot 0 to confirm.

## LED registers

Three zones per bank: `0x01` scroll wheel, `0x04` logo, `0x0A` underglow. ✅

| Register | Read | Write | Args |
|---|---|---|---|
| Brightness | `0F:84` | `0F:04` | `<slot> <zone> <0–255>` |
| Effect | `0F:82` (size `0C`) | `0F:02` (size varies) | `<slot> <zone> <effect> <mode> <speed> <n_colors> <RGB>…` |

Effect IDs: `00` off, `01` static, `02` breathing (mode `0` random / `1` single / `2` dual), `03` spectrum, `04` wave (mode = direction), `05` reactive (speed 1–4).

Real read from the test unit (slot 0, scroll wheel): `00 01 03 01 28 01 ff ff ff`. That's spectrum, with a white placeholder color that spectrum ignores. ✅

## Gotchas

- **The effect reply's slot byte always reads `00`**, whatever slot was requested, so replies must be matched to requests by the caller. The brightness reply does echo the slot. ✅
- **Readable doesn't mean assigned.** All banks 0–5 answer reads, but only banks listed by `05:81` are real, selectable profiles. Selecting an unassigned bank returns status `0x03`. ✅ (reads) ⚠️ (select)
- **Deleting a profile (`05:03`) only unassigns it.** Its data stays readable and is reused if the bank is recreated. ⚠️
- **`0x01` is overloaded.** Other Razer tools (OpenRazer) call `0x01` "VARSTORE / save to device". On this family it is simply bank 1, which is only "the live one" while profile 1 is active.
- **Write order for DPI:** write the stage table before the current-DPI value, because a stage write can re-project the current DPI. ⚠️
