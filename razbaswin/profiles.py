"""Whole-profile snapshots, backups and writes built from the per-register commands.

There is no single "read profile" command: a profile is a set of independent
registers addressed by slot (0 = live, 1-5 = profile banks). Snapshots keep raw
values (stage IDs, effect bytes, button blocks) so they can be written back.
"""

from datetime import datetime

from . import __version__
from .device import BasiliskV3
from .protocol import BUTTON_SLOTS, LED_ZONES, SLOT_LIVE, ZONE_IDS

ZONE_KEYS = {led_id: key for key, led_id in ZONE_IDS.items()}

# Synapse's factory defaults for PID 0x0099 (Defaults/153/*.xml), with raw blocks
# as read from the unassigned banks of a test unit. Same shape as read_profile().
FACTORY_PROFILE = {
    "dpi": [1600, 1600],
    "dpi_stages": {
        "active_index": 2,
        "stage_ids": [1, 2, 3, 4, 5],
        "stages": [[400, 400], [800, 800], [1600, 1600], [3200, 3200], [6400, 6400]],
    },
    "lighting": {key: {"effect": "03 01 28 01 ff ff ff", "brightness": 179} for key in ZONE_IDS},
    "scroll": {"mode": 0, "acceleration": False, "smart_reel": False},
    "buttons": {
        "0x01": "01 01 01 00 00 00 00",
        "0x02": "01 01 02 00 00 00 00",
        "0x03": "01 01 03 00 00 00 00",
        "0x04": "01 01 04 00 00 00 00",
        "0x05": "01 01 05 00 00 00 00",
        "0x09": "01 01 09 00 00 00 00",
        "0x0a": "01 01 0a 00 00 00 00",
        "0x34": "0e 01 68 00 14 00 00",
        "0x35": "0e 01 69 00 14 00 00",
        "0x0f": "06 01 05 01 90 01 90",
        "0x60": "06 01 06 00 00 00 00",
        "0x0e": "07 01 04 00 00 00 00",
        "0x6a": "12 01 01 00 00 00 00",
    },
}
FACTORY_POLL_RATE = 1000


def read_profile(mouse: BasiliskV3, slot: int) -> dict:
    stages = mouse.dpi_stages(slot)
    return {
        "slot": slot,
        "dpi": list(mouse.dpi(slot)),
        "dpi_stages": {
            "active_index": stages.active_index,
            "stage_ids": stages.stage_ids,
            "stages": [list(s) for s in stages.stages],
        },
        "lighting": {
            ZONE_KEYS[led_id]: {
                "effect": mouse.led_effect(led_id, slot).payload[2:].hex(" "),
                "brightness": mouse.led_brightness(led_id, slot),
            }
            for led_id in LED_ZONES
        },
        "scroll": {
            "mode": mouse.scroll_mode(slot),
            "acceleration": mouse.scroll_acceleration(slot),
            "smart_reel": mouse.smart_reel(slot),
        },
        "buttons": {f"{b:#04x}": mouse.button_block(b, slot).hex(" ") for b in BUTTON_SLOTS},
    }


def read_backup(mouse: BasiliskV3) -> dict:
    max_id, assigned = mouse.profile_inventory()
    return {
        "format": "razbaswin-backup",
        "version": 1,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "razbaswin": __version__,
        "device": {"pid": f"{mouse.pid:#06x}", "firmware": mouse.firmware(), "serial": mouse.serial()},
        "global": {"poll_rate": mouse.poll_rate()},
        "profiles": {"max_id": max_id, "assigned": assigned, "active": mouse.active_profile()},
        "slots": {str(slot): read_profile(mouse, slot) for slot in range(0, max_id + 1)},
    }


def effect_core(effect_hex: str) -> bytes:
    """Meaningful effect bytes: [effect, mode, speed, count] + count colors. Readback pads the rest."""
    b = bytes.fromhex(effect_hex)
    return b[: 4 + 3 * b[3]] if len(b) >= 4 else b


def profile_diff(current: dict, target: dict) -> list[tuple[str, object, object]]:
    """(setting, current, target) for every setting that differs."""
    diffs = []
    if current["dpi_stages"] != target["dpi_stages"]:
        diffs.append(("dpi_stages", current["dpi_stages"], target["dpi_stages"]))
    if current["dpi"] != target["dpi"]:
        diffs.append(("dpi", current["dpi"], target["dpi"]))
    for zone, t in target["lighting"].items():
        c = current["lighting"][zone]
        if effect_core(c["effect"]) != effect_core(t["effect"]):
            diffs.append((f"lighting.{zone}.effect", c["effect"], t["effect"]))
        if c["brightness"] != t["brightness"]:
            diffs.append((f"lighting.{zone}.brightness", c["brightness"], t["brightness"]))
    for key, value in target["scroll"].items():
        if current["scroll"][key] != value:
            diffs.append((f"scroll.{key}", current["scroll"][key], value))
    for button, block in target["buttons"].items():
        if current["buttons"][button] != block:
            diffs.append((f"buttons.{button}", current["buttons"][button], block))
    return diffs


def write_setting(mouse: BasiliskV3, slot: int, setting: str, value: object) -> None:
    """Write one setting, named as in profile_diff(), to `slot`."""
    parts = setting.split(".")
    if setting == "dpi_stages":
        mouse.set_dpi_stages([tuple(s) for s in value["stages"]], value["stage_ids"], value["active_index"], slot)
    elif setting == "dpi":
        mouse.set_dpi(value[0], value[1], slot)
    elif parts[0] == "lighting" and parts[2] == "effect":
        mouse.set_led_effect(ZONE_IDS[parts[1]], effect_core(value), slot)
    elif parts[0] == "lighting":
        mouse.set_led_brightness(ZONE_IDS[parts[1]], value, slot)
    elif setting == "scroll.mode":
        mouse.set_scroll_mode(value, slot)
    elif setting == "scroll.acceleration":
        mouse.set_scroll_acceleration(value, slot)
    elif setting == "scroll.smart_reel":
        mouse.set_smart_reel(value, slot)
    elif parts[0] == "buttons":
        mouse.set_button_block(int(parts[1], 16), bytes.fromhex(value), slot)
    else:
        raise ValueError(f"unknown setting {setting!r}")


def write_profile(mouse: BasiliskV3, slot: int, target: dict, dry_run: bool = False) -> list[tuple[str, object, object]]:
    """Write only the settings of `slot` that differ from `target`. Returns the differences."""
    diffs = profile_diff(read_profile(mouse, slot), target)
    if not dry_run:
        # profile_diff lists stages before the scalar DPI: a stage write can re-project the current DPI.
        for setting, _, value in diffs:
            write_setting(mouse, slot, setting, value)
    return diffs


def reset_slot(mouse: BasiliskV3, slot: int, dry_run: bool = False) -> list[tuple[str, object, object]]:
    """Reset one slot (0 = live, 1-5 = profile bank) to factory. Returns the differences found."""
    return write_profile(mouse, slot, FACTORY_PROFILE, dry_run)


def reset_slots(mouse: BasiliskV3) -> list[int]:
    """Every profile bank, then live state (usually already synced by the active bank's writes).

    Unassigned banks are included: they accept writes, and a deleted profile's data
    stays in its bank and can be reused when a profile is created there.
    """
    max_id, _ = mouse.profile_inventory()
    return [*range(1, max_id + 1), SLOT_LIVE]
