import argparse
import colorsys
import json
import random
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .device import BASILISK_V3_PID, BasiliskV3, DeviceError, enumerate_devices
from .profiles import (
    FACTORY_POLL_RATE,
    FACTORY_PROFILE,
    load_backup,
    profile_diff,
    read_backup,
    read_profile,
    reset_slot,
    reset_slots,
    write_profile,
)
from .protocol import (
    BUTTON_SLOTS,
    EFFECT_CUSTOM,
    FRAME_CELLS,
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


def change_profiles(mouse: BasiliskV3, args: argparse.Namespace) -> bool:
    """Apply --create/--delete/--activate. Returns False (after printing why) if refused or unverified."""
    _, assigned = mouse.profile_inventory()
    active = mouse.active_profile()

    if args.create is not None:
        p = args.create
        if p in assigned:
            print(f"error: profile {p} already exists", file=sys.stderr)
            return False
        # Read the source first: creating resets part of the bank's content.
        content = FACTORY_PROFILE if args.source is None else read_profile(mouse, args.source)
        source = "factory defaults" if args.source is None else f"slot {args.source}"
        mouse.create_profile(p)
        write_profile(mouse, p, content)
        if p not in mouse.profile_inventory()[1] or profile_diff(read_profile(mouse, p), content):
            print(f"Verify: profile {p} was not created with {source}", file=sys.stderr)
            return False
        print(f"Created profile {p} from {source}.")

    if args.delete is not None:
        p = args.delete
        if p not in assigned:
            print(f"error: profile {p} doesn't exist", file=sys.stderr)
            return False
        if p == active:
            print(f"error: profile {p} is active; switch first with --activate", file=sys.stderr)
            return False
        if len(assigned) == 1:
            print(f"error: profile {p} is the only profile", file=sys.stderr)
            return False
        mouse.delete_profile(p)
        if p in mouse.profile_inventory()[1]:
            print(f"Verify: profile {p} is still listed", file=sys.stderr)
            return False
        print(f"Deleted profile {p} (its settings stay in the slot).")

    if args.activate is not None:
        p = args.activate
        if p not in mouse.profile_inventory()[1]:
            print(f"error: profile {p} doesn't exist", file=sys.stderr)
            return False
        mouse.set_active_profile(p)
        if mouse.active_profile() != p:
            print(f"Verify: active profile is {mouse.active_profile()}, not {p}", file=sys.stderr)
            return False
        print(f"Activated profile {p}.")
    return True


def cmd_profiles(args: argparse.Namespace) -> int:
    if args.source is not None and args.create is None:
        print("error: --from only applies with --create", file=sys.stderr)
        return 2
    with BasiliskV3(args.pid) as mouse:
        if not change_profiles(mouse, args):
            return 1
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


def save_backup(mouse: BasiliskV3, file: str | None) -> Path:
    data = read_backup(mouse)
    path = Path(file or f"razbaswin-backup-{datetime.now():%Y%m%d-%H%M%S}.json")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    p = data["profiles"]
    print(f"Backed up slots 0-{p['max_id']} (assigned {p['assigned']}, active {p['active']}) to {path}")
    return path


def cmd_backup(args: argparse.Namespace) -> int:
    with BasiliskV3(args.pid) as mouse:
        save_backup(mouse, args.file)
    return 0


def format_value(setting: str, value: object) -> str:
    if setting == "dpi_stages":
        stages = "/".join(str(x) if x == y else f"{x}x{y}" for x, y in value["stages"])
        return f"{stages}, active {value['active_index'] + 1}"
    if setting.startswith("buttons."):
        return f"{describe_function_block(bytes.fromhex(value))} [{value}]"
    if setting.endswith(".effect"):
        return led_effect_from_payload(bytes(2) + bytes.fromhex(value)).describe()
    return str(value)


def print_diffs(diffs: list[tuple[str, object, object]]) -> None:
    for setting, current, target in diffs:
        print(f"    {setting}: {format_value(setting, current)} -> {format_value(setting, target)}")


def verify_slots(mouse: BasiliskV3, targets: dict[int, dict]) -> bool:
    """Re-read each slot and report any setting that doesn't match its target."""
    ok = True
    for slot, target in targets.items():
        diffs = profile_diff(read_profile(mouse, slot), target)
        if diffs:
            ok = False
            print(f"Verify: slot {slot} still differs", file=sys.stderr)
            print_diffs(diffs)
    if ok:
        print("Verified: all written slots read back as expected.")
    return ok


def print_slot_diffs(slot: int, diffs: list[tuple[str, object, object]], same: str) -> None:
    label = "Live state" if slot == SLOT_LIVE else f"Profile {slot}"
    print(f"  {label}: {same if not diffs else f'{len(diffs)} setting(s)'}")
    print_diffs(diffs)


def cmd_restore(args: argparse.Namespace) -> int:
    try:
        backup = load_backup(args.file)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    apply = args.yes
    with BasiliskV3(args.pid) as mouse:
        if backup["device"]["pid"] != f"{mouse.pid:#06x}":
            print(f"error: backup is from PID {backup['device']['pid']}, not {mouse.pid:#06x}", file=sys.stderr)
            return 2
        if apply and not args.no_backup:
            save_backup(mouse, None)
        print(f"Restoring {args.file}" if apply else f"Dry run: changes restoring {args.file} would make")
        changed = False

        if args.slot is not None:
            dst = args.slot if args.to is None else args.to
            targets = {dst: backup["slots"][str(args.slot)]}
            if dst != args.slot:
                print(f"  (backup slot {args.slot} -> mouse slot {dst})")
            diffs = write_profile(mouse, dst, targets[dst], dry_run=not apply)
            changed |= bool(diffs)
            print_slot_diffs(dst, diffs, "already matches")
        else:
            # Order matters: create before writing (create resets bank content), select the
            # active profile before writing live state (selecting reloads it), delete last.
            max_id, assigned = mouse.profile_inventory()
            want = backup["profiles"]["assigned"]
            for p in (p for p in want if p not in assigned):
                changed = True
                print(f"  Create profile {p}")
                if apply:
                    mouse.create_profile(p)
            targets = {slot: backup["slots"][str(slot)] for slot in range(1, max_id + 1)}
            for slot, target in targets.items():
                diffs = write_profile(mouse, slot, target, dry_run=not apply)
                changed |= bool(diffs)
                print_slot_diffs(slot, diffs, "already matches")
            if mouse.active_profile() != backup["profiles"]["active"]:
                changed = True
                print(f"  Active profile: {mouse.active_profile()} -> {backup['profiles']['active']}")
                if apply:
                    mouse.set_active_profile(backup["profiles"]["active"])
            if apply:
                targets[SLOT_LIVE] = backup["slots"][str(SLOT_LIVE)]
                diffs = write_profile(mouse, SLOT_LIVE, targets[SLOT_LIVE])
                print_slot_diffs(SLOT_LIVE, diffs, "already matches")
            else:
                print("  Live state: re-checked after the profile writes (it follows the active profile)")
            for p in (p for p in assigned if p not in want):
                changed = True
                print(f"  Delete profile {p} (not in the backup)")
                if apply:
                    mouse.delete_profile(p)
            poll = backup["global"]["poll_rate"]
            if mouse.poll_rate() != poll:
                changed = True
                print(f"  Poll rate: {mouse.poll_rate()} -> {poll} Hz")
                if apply:
                    mouse.set_poll_rate(poll)

        if apply:
            if args.slot is None and (
                mouse.profile_inventory()[1] != backup["profiles"]["assigned"]
                or mouse.active_profile() != backup["profiles"]["active"]
                or mouse.poll_rate() != backup["global"]["poll_rate"]
            ):
                print("Verify: profile list, active profile or poll rate doesn't match the backup", file=sys.stderr)
                return 1
            if not verify_slots(mouse, targets):
                return 1

    if not apply and changed:
        print("Re-run with --yes to apply (a backup of the current state is saved first).")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    apply = args.yes
    whole = args.slot is None
    with BasiliskV3(args.pid) as mouse:
        if apply and not args.no_backup:
            save_backup(mouse, None)
        print("Resetting to factory defaults" if apply else "Dry run: changes a factory reset would make")

        slots = reset_slots(mouse) if whole else [args.slot]
        changed = False
        for slot in slots:
            label = "Live state" if slot == SLOT_LIVE else f"Profile {slot}"
            if whole and slot == SLOT_LIVE and not apply:
                print(f"  {label}: re-checked after the profile writes (it follows the active profile)")
                continue
            diffs = reset_slot(mouse, slot, dry_run=not apply)
            changed |= bool(diffs)
            print(f"  {label}: {'already factory' if not diffs else f'{len(diffs)} setting(s)'}")
            print_diffs(diffs)

        if whole:
            poll = mouse.poll_rate()
            if poll != FACTORY_POLL_RATE:
                changed = True
                print(f"  Poll rate: {poll} -> {FACTORY_POLL_RATE} Hz")
                if apply:
                    mouse.set_poll_rate(FACTORY_POLL_RATE)
            else:
                print("  Poll rate: already factory")

        if apply:
            if whole and mouse.poll_rate() != FACTORY_POLL_RATE:
                print("Verify: poll rate did not change", file=sys.stderr)
                return 1
            if not verify_slots(mouse, {slot: FACTORY_PROFILE for slot in slots}):
                return 1

    not_reset = "Hypershift layer, which profiles are assigned/active, sleep timeout, sensor calibration"
    print(f"Not reset: {not_reset}." if whole else f"Not reset: other slots, poll rate, {not_reset}.")
    if not apply and changed:
        print("Re-run with --yes to apply (a backup is saved first).")
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
    instant = args.trans == "instant"
    if instant and args.effect not in ("static", "off"):
        print("error: --trans instant only applies to static and off", file=sys.stderr)
        return 2
    if instant and args.profile is not None:
        print("error: --trans instant can't be saved to a profile; it changes the live state only", file=sys.stderr)
        return 2
    is_random = None in args.colors
    if is_random:
        # 'random' is a try-it-out color: live state only unless a profile is named.
        args.colors = [random_color() if c is None else c for c in args.colors]
        if args.profile is None:
            args.temp = True
    try:
        payload = effect_payload(args.effect, args.colors, args.speed, args.direction)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if is_random:
        print("Random color: " + ", ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in args.colors))
    zones = selected_zones(args)
    with BasiliskV3(args.pid) as mouse:
        if instant:
            print("Writing live state only (reverts on replug).")
            rgb = args.colors[0] if args.effect == "static" else (0, 0, 0)
            set_instant_color(mouse, zones, rgb)
        else:
            slot = resolve_write_slot(mouse, args)
            for led_id in zones:
                mouse.set_led_effect(led_id, payload, slot)
        print_leds(mouse, SLOT_LIVE, zones)
    return 0


def set_instant_color(mouse: BasiliskV3, zones: list[int], rgb: tuple[int, int, int]) -> None:
    """Effect writes crossfade; custom frame writes don't. Paint the zones' frame
    cells, then switch any zone not already showing the frame to the custom effect."""
    for led_id in zones:
        first, last = FRAME_CELLS[led_id]
        mouse.set_custom_frame(first, last, [rgb] * (last - first + 1))
    for led_id in zones:
        if mouse.led_effect(led_id, SLOT_LIVE).effect_id != EFFECT_CUSTOM:
            mouse.set_led_effect(led_id, bytes([EFFECT_CUSTOM]) + bytes(9), SLOT_LIVE)


def brightness_value(s: str) -> int:
    """'70%' -> 0-100 percent of 255; '179' -> raw 0-255."""
    try:
        value = round(float(s[:-1]) * 255 / 100) if s.endswith("%") else int(s, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid brightness {s!r}")
    if not 0 <= value <= 255:
        raise argparse.ArgumentTypeError("brightness must be 0-255 or 0%-100%")
    return value


def random_color() -> tuple[int, int, int]:
    """A random hue at full saturation and value, so it's never dull or near-black."""
    r, g, b = colorsys.hsv_to_rgb(random.random(), 1.0, 1.0)
    return (round(r * 255), round(g * 255), round(b * 255))


def color(s: str) -> tuple[int, int, int] | None:
    """RRGGBB hex, or 'random' (returned as None and resolved by the command)."""
    if s.lower() == "random":
        return None
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

    profiles = sub.add_parser(
        "profiles",
        help="List, create, delete or activate onboard profiles",
        description="Lists the profile slots, after applying any --create/--delete/--activate.",
    )
    profiles.add_argument("--create", type=profile_number, metavar="N", help="Create profile N (factory settings)")
    profiles.add_argument("--from", dest="source", type=slot_number, metavar="SLOT", help="With --create: copy settings from SLOT (0-5)")
    profiles.add_argument("--delete", type=profile_number, metavar="N", help="Delete profile N (settings stay in the slot)")
    profiles.add_argument("--activate", type=profile_number, metavar="N", help="Make profile N active")
    profiles.set_defaults(func=cmd_profiles)

    profile = sub.add_parser("profile", help="Read everything stored in one profile")
    profile.add_argument("slot", nargs="?", type=slot_number, help="1-5, or 0 for live state (default: active profile)")
    profile.add_argument("--raw", action="store_true", help="Also print raw button function blocks")
    profile.add_argument("--json", action="store_true", help="Print the snapshot as JSON")
    profile.set_defaults(func=cmd_profile)

    backup = sub.add_parser("backup", help="Save all profile slots and global settings to a JSON file")
    backup.add_argument("file", nargs="?", help="Output file (default razbaswin-backup-<timestamp>.json)")
    backup.set_defaults(func=cmd_backup)

    restore = sub.add_parser(
        "restore",
        help="Write a backup file back to the mouse",
        description="Shows what would change unless --yes is given. Only settings that differ are written. "
        "A full restore also restores which profiles exist, the active profile and the poll rate.",
    )
    restore.add_argument("file", help="Backup file from 'razbaswin backup'")
    restore.add_argument("--slot", type=slot_number, help="Restore only this slot from the backup (0-5)")
    restore.add_argument("--to", type=slot_number, help="With --slot: write it into this mouse slot instead")
    restore.add_argument("--yes", action="store_true", help="Apply the restore")
    restore.add_argument("--no-backup", action="store_true", help="Skip the automatic backup before applying")
    restore.set_defaults(func=cmd_restore)

    reset = sub.add_parser(
        "reset",
        help="Reset mapped settings to factory defaults",
        description="Shows what would change unless --yes is given. Only settings that differ are written.",
    )
    reset.add_argument("--slot", type=slot_number, help="Reset only this slot (1-5, or 0 for live state)")
    reset.add_argument("--yes", action="store_true", help="Apply the reset")
    reset.add_argument("--no-backup", action="store_true", help="Skip the automatic backup before applying")
    reset.set_defaults(func=cmd_reset)

    brightness = sub.add_parser("brightness", help="Set LED brightness")
    brightness.add_argument("value", type=brightness_value, help="0-255, or a percentage like 70%%")
    add_write_options(brightness)
    brightness.set_defaults(func=cmd_brightness)

    effect = sub.add_parser(
        "effect",
        help="Set LED effect",
        description="static takes one RRGGBB hex color, or 'random' (a random vivid color, live state "
        "only unless --profile is given); off, spectrum and wave take none.",
    )
    effect.add_argument("effect", choices=WRITABLE_EFFECTS)
    effect.add_argument("colors", nargs="*", type=color, metavar="COLOR")
    effect.add_argument("--speed", type=int, help="wave only: speed 1-255, lower is faster (default 40)")
    effect.add_argument("--direction", type=int, choices=[1, 2], default=1, help="wave direction")
    effect.add_argument(
        "--trans",
        choices=["slow", "instant"],
        default="slow",
        help="static/off color change: slow crossfade (default), or instant (live state only, implies --temp)",
    )
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
