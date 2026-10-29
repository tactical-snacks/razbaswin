"""Whole-profile snapshots built from the per-register reads.

There is no single "read profile" command: a profile is a set of independent
registers addressed by slot (0 = live, 1-5 = profile banks). Snapshots keep raw
values (stage IDs, effect bytes, button blocks) so they can be written back.
"""

from .device import BasiliskV3
from .protocol import BUTTON_SLOTS, LED_ZONES, ZONE_IDS

ZONE_KEYS = {led_id: key for key, led_id in ZONE_IDS.items()}


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
