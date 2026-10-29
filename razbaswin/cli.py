import argparse
import json
import sys

from . import __version__
from .device import BASILISK_V3_PID, BasiliskV3, DeviceError, enumerate_devices
from .profiles import read_profile
from .protocol import (
    BUTTON_SLOTS,
    LED_ZONES,
    SCROLL_MODES,
    SLOT_LIVE,
    WRITABLE_EFFECTS,
    ZONE_IDS,
    describe_function_block,
    effect_payload,
    led_effect_from_payload,
)


def cmd_list(args: argparse.Namespace) -> int:
    devices = enumerate_devices(args.pid)
    if not devices:
        print(f"No Razer devices with PID {args.pid:#06x} found.")
        return 1
    for d in devices:
        print(
            f"{d['product_string']}  if={d['interface_number']}  "
            f"usage_page={d['usage_page']:#06x} usage={d['usage']:#06x}"
        )
        print(f"    {d['path'].decode(errors='replace')}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    with BasiliskV3(args.pid) as mouse:
        poll = mouse.poll_rate()
        dpi_x, dpi_y = mouse.dpi()
        stages = mouse.dpi_stages()

        print("Razer Basilisk V3")
        print(f"  Firmware:   {mouse.firmware()}")
        print(f"  Serial:     {mouse.serial() or '(none)'}")
        print(f"  Poll rate:  {f'{poll} Hz' if poll else 'unknown'}")
        print(f"  DPI:        {dpi_x} x {dpi_y}")
        print(f"  DPI stages: (active = {stages.active_index + 1})")
        for i, (x, y) in enumerate(stages.stages):
            marker = "*" if i == stages.active_index else " "
            value = f"{x}" if x == y else f"{x} x {y}"
            print(f"   {marker} {i + 1}: {value}")
    return 0


def print_leds(mouse: BasiliskV3, slot: int, zones: list[int], raw: bool = False) -> None:
    label = "live" if slot == SLOT_LIVE else f"profile {slot}"
    print(f"LED zones ({label})")
    for led_id in zones:
        effect = mouse.led_effect(led_id, slot)
        brightness = mouse.led_brightness(led_id, slot)
        percent = round(brightness * 100 / 255)
        print(f"  {LED_ZONES[led_id]:<13} [{led_id:#04x}]  {effect.describe():<28} brightness {brightness} ({percent}%)")
        if raw:
            print(f"      raw: {effect.payload.hex(' ')}")


def cmd_leds(args: argparse.Namespace) -> int:
    with BasiliskV3(args.pid) as mouse:
        print_leds(mouse, args.slot, list(LED_ZONES), args.raw)
    return 0


def cmd_profiles(args: argparse.Namespace) -> int:
    with BasiliskV3(args.pid) as mouse:
        max_id, assigned = mouse.profile_inventory()
        active = mouse.active_profile()
        print(f"Onboard profiles (slots 1-{max_id})")
        for slot in range(1, max_id + 1):
            stages = mouse.dpi_stages(slot)
            effects = sorted({mouse.led_effect(led_id, slot).name for led_id in LED_ZONES})
            status = "active" if slot == active else "assigned" if slot in assigned else "empty"
            dpi = "/".join(str(x) for x, _ in stages.stages)
            print(f"  {'*' if slot == active else ' '} {slot}  {status:<8}  DPI {dpi}  lighting {', '.join(effects)}")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    with BasiliskV3(args.pid) as mouse:
        slot = mouse.active_profile() if args.slot is None else args.slot
        snap = read_profile(mouse, slot)
        _, assigned = mouse.profile_inventory()

    if args.json:
        print(json.dumps(snap, indent=2))
        return 0

    if slot == SLOT_LIVE:
        print("Live state (slot 0)")
    else:
        print(f"Profile {slot} ({'assigned' if slot in assigned else 'empty slot, factory defaults'})")

    x, y = snap["dpi"]
    print(f"  DPI:        {x}" if x == y else f"  DPI:        {x} x {y}")
    st = snap["dpi_stages"]
    print(f"  DPI stages: (active = {st['active_index'] + 1})")
    for i, (sx, sy) in enumerate(st["stages"]):
        marker = "*" if i == st["active_index"] else " "
        print(f"   {marker} {i + 1}: {sx}" if sx == sy else f"   {marker} {i + 1}: {sx} x {sy}")

    print("  Lighting:")
    for key, zone in snap["lighting"].items():
        effect = led_effect_from_payload(bytes(2) + bytes.fromhex(zone["effect"]))
        percent = round(zone["brightness"] * 100 / 255)
        print(f"    {key:<10} {effect.describe():<28} brightness {zone['brightness']} ({percent}%)")

    sc = snap["scroll"]
    mode = SCROLL_MODES.get(sc["mode"], f"unknown ({sc['mode']:#04x})")
    on = {True: "on", False: "off"}
    print(f"  Scroll:     {mode}, acceleration {on[sc['acceleration']]}, smart reel {on[sc['smart_reel']]}")

    print("  Buttons:")
    for button, block_hex in snap["buttons"].items():
        name = BUTTON_SLOTS[int(button, 16)]
        action = describe_function_block(bytes.fromhex(block_hex))
        raw = f"  [{block_hex}]" if args.raw else ""
        print(f"    {name:<19} {action}{raw}")
    return 0


def resolve_write_slot(mouse: BasiliskV3, args: argparse.Namespace) -> int:
    if args.temp:
        print("Writing live state only (reverts on replug).")
        return SLOT_LIVE
    if args.profile is not None:
        print(f"Writing profile {args.profile}.")
        return args.profile
    active = mouse.active_profile()
    print(f"Writing active profile {active} (saved on the mouse).")
    return active


def selected_zones(args: argparse.Namespace) -> list[int]:
    return list(LED_ZONES) if args.zone == "all" else [ZONE_IDS[args.zone]]


def cmd_brightness(args: argparse.Namespace) -> int:
    zones = selected_zones(args)
    with BasiliskV3(args.pid) as mouse:
        slot = resolve_write_slot(mouse, args)
        for led_id in zones:
            mouse.set_led_brightness(led_id, args.value, slot)
        print_leds(mouse, SLOT_LIVE, zones)
    return 0


def cmd_effect(args: argparse.Namespace) -> int:
    if args.effect != "wave" and args.speed is not None:
        print("error: --speed only applies to wave", file=sys.stderr)
        return 2
    try:
        payload = effect_payload(args.effect, args.colors, args.speed, args.direction)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    zones = selected_zones(args)
    with BasiliskV3(args.pid) as mouse:
        slot = resolve_write_slot(mouse, args)
        for led_id in zones:
            mouse.set_led_effect(led_id, payload, slot)
        print_leds(mouse, SLOT_LIVE, zones)
    return 0


def brightness_value(s: str) -> int:
    """'70%' -> 0-100 percent of 255; '179' -> raw 0-255."""
    try:
        value = round(float(s[:-1]) * 255 / 100) if s.endswith("%") else int(s, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid brightness {s!r}")
    if not 0 <= value <= 255:
        raise argparse.ArgumentTypeError("brightness must be 0-255 or 0%-100%")
    return value


def color(s: str) -> tuple[int, int, int]:
    h = s.removeprefix("#")
    if len(h) != 6:
        raise argparse.ArgumentTypeError(f"invalid color {s!r}, expected RRGGBB")
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid color {s!r}, expected RRGGBB")


def slot_number(s: str) -> int:
    value = int(s, 0)
    if not 0 <= value <= 5:
        raise argparse.ArgumentTypeError("slot must be 0-5")
    return value


def profile_number(s: str) -> int:
    value = int(s, 0)
    if not 1 <= value <= 5:
        raise argparse.ArgumentTypeError("profile must be 1-5")
    return value


def add_write_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--zone", choices=[*ZONE_IDS, "all"], default="all", help="LED zone (default all)")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--temp", action="store_true", help="Change live state only; reverts on replug")
    target.add_argument("--profile", type=profile_number, help="Write this profile bank (default: active profile)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="razbaswin", description="Control a Razer Basilisk V3 over USB.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--pid",
        type=lambda s: int(s, 0),
        default=BASILISK_V3_PID,
        help=f"USB product ID (default {BASILISK_V3_PID:#06x})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List matching HID interfaces").set_defaults(func=cmd_list)
    sub.add_parser("info", help="Read firmware, serial, poll rate and DPI").set_defaults(func=cmd_info)

    leds = sub.add_parser("leds", help="Read effect and brightness for each LED zone")
    leds.add_argument("--slot", type=slot_number, default=SLOT_LIVE, help="0 = live (default), 1-5 = profile bank")
    leds.add_argument("--raw", action="store_true", help="Also print the raw effect payload bytes")
    leds.set_defaults(func=cmd_leds)

    sub.add_parser("profiles", help="List onboard profile slots").set_defaults(func=cmd_profiles)

    profile = sub.add_parser("profile", help="Read everything stored in one profile")
    profile.add_argument("slot", nargs="?", type=slot_number, help="1-5, or 0 for live state (default: active profile)")
    profile.add_argument("--raw", action="store_true", help="Also print raw button function blocks")
    profile.add_argument("--json", action="store_true", help="Print the snapshot as JSON")
    profile.set_defaults(func=cmd_profile)

    brightness = sub.add_parser("brightness", help="Set LED brightness")
    brightness.add_argument("value", type=brightness_value, help="0-255, or a percentage like 70%%")
    add_write_options(brightness)
    brightness.set_defaults(func=cmd_brightness)

    effect = sub.add_parser(
        "effect",
        help="Set LED effect",
        description="static takes one RRGGBB hex color; off, spectrum and wave take none.",
    )
    effect.add_argument("effect", choices=WRITABLE_EFFECTS)
    effect.add_argument("colors", nargs="*", type=color, metavar="COLOR")
    effect.add_argument("--speed", type=int, help="wave only: speed 1-255, lower is faster (default 40)")
    effect.add_argument("--direction", type=int, choices=[1, 2], default=1, help="wave direction")
    add_write_options(effect)
    effect.set_defaults(func=cmd_effect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DeviceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
