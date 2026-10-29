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

Slot 0 test (scroll-wheel brightness): writing `64` to slot 0 left bank 1 at `179`. After a USB replug, slot 0 read `179` again, reloaded from the active bank. ✅

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
| Slot `0` | Visible immediately. No bank changes. Reverts to the active bank on replug ✅. Sleep/wake and profile switch assumed to revert too ⚠️. |
| The **active** bank (usually `1`) | Persists, and slot 0 picks up the new value immediately ✅. Only the written register syncs: a bank brightness write leaves a temporary slot-0 effect in place ✅. Other settings in the bank (DPI, buttons) are untouched ⚠️. |
| An **inactive** bank (e.g. `2`) | Persists in that bank only. Nothing visible changes until that profile is selected with `05:04`. On the V3 Pro, selecting it then made slot 0 show the new colors. ⚠️ |
| Custom frame (`0x0F:0x03`) | Switches the addressed LEDs to a "custom" effect, fed from a per-LED buffer. OpenSnek uses 14 cells on the V3 Pro. The wired V3 has 11 LEDs (see below), so its cell count likely differs. Never persisted: after a restart the bank's stored effect comes back. ⚠️ |

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

Effect IDs: `00` off, `01` static, `02` breathing, `03` spectrum, `04` wave (mode = direction 1/2, speed default `0x28`), `05` reactive.

Write payloads accepted by the test unit ✅:

| Effect | Bytes after `<slot> <zone>` |
|---|---|
| off | `00 00 00 00` |
| static | `01 00 00 01 R G B` |
| spectrum | `03 01 28 01 ff ff ff` (factory payload) |
| wave | `04 <dir> <speed> 00` |

Wave speed behaves like a step interval: `0x01` is very fast, and `0xFF` is slow with visible color steps ✅ (observed). Spectrum's third byte (`0x28`) is stored but ignored: values `0x01`, `0x28` and `0xFF` cycled at the same rate ✅ (observed). Its color list is ignored too: a 4-color white/red/white/red payload was accepted but still showed the full rainbow ✅ (observed). Spectrum is a fixed hue cycle. The firmware stores effect payloads verbatim, including out-of-range directions and extra trailing bytes, so readback can't show which bytes an effect actually uses ✅.

The factory look is spectrum on all three zones at brightness `179` (70%). A per-zone wave can't reproduce Synapse's smooth wave; see below.

Breathing (`02`) and reactive (`05`) writes return status `0x05` (not supported) on the wired V3 ✅, consistent with OpenSnek's off/static/spectrum/wave list for this family.

Real read from the test unit (slot 0, scroll wheel): `00 01 03 01 28 01 ff ff ff`. That's spectrum, with a white placeholder color that spectrum ignores. ✅

## Synapse device package

The Synapse 3 installer for this mouse (`Razer_153_0_Setup`, device codename "Daria") contains factory defaults and lighting metadata. Its data files were extracted with 7-Zip, without running anything.

**Factory defaults** (`Defaults/153/*.xml`):

| Setting | Default | Matches test unit |
|---|---|---|
| LED brightness | 70% | `179` ✅ |
| DPI stages | 400 / 800 / 1600 / 3200 / 6400, active index 2 (1600) | Unassigned banks report active stage 3 ✅ |
| Poll rate | 1000 Hz | ✅ |
| Sleep timeout | 300 s | not read |
| Scroll wheel | Notched, no acceleration, no smart reel | not read |

**LED layout** (`LedLayout/PID0099/PID0099_EID00_00.dat`): 3 zones with 11 LEDs in total. Zone `0x01` (scroll wheel) has 1 LED, `0x04` (logo) has 1, and `0x0A` (underglow) has 9. This matches the manual's "11 Razer Chroma lighting zones".

**Effects Synapse offers** (`DeviceInstance.json`): static, breathing, spectrum, reactive, audiometer, starlight, fire, wave. Only off, static, spectrum and wave are accepted as onboard effects, so the rest must be rendered by Synapse on the PC while it runs.

**Synapse wave** (`QuickEffectsData.xml`): speed `25`, **width** `100`, circular direction (clock / anticlock). The onboard wave payload has no width byte, so Synapse's wave is most likely software-rendered across the 11 LEDs. Reproducing it means streaming per-LED frames.

## Gotchas

- **The effect reply's slot byte always reads `00`**, whatever slot was requested, so replies must be matched to requests by the caller. The brightness reply does echo the slot. ✅
- **Readable doesn't mean assigned.** All banks 0–5 answer reads, but only banks listed by `05:81` are real, selectable profiles. Selecting an unassigned bank returns status `0x03`. ✅ (reads) ⚠️ (select)
- **Deleting a profile (`05:03`) only unassigns it.** Its data stays readable and is reused if the bank is recreated. ⚠️
- **`0x01` is overloaded.** Other Razer tools (OpenRazer) call `0x01` "VARSTORE / save to device". On this family it is simply bank 1, which is only "the live one" while profile 1 is active.
- **Write order for DPI:** write the stage table before the current-DPI value, because a stage write can re-project the current DPI. ⚠️
