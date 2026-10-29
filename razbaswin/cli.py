import argparse
import sys

from . import __version__
from .device import BASILISK_V3_PID, BasiliskV3, DeviceError, enumerate_devices
from .protocol import LED_ZONES


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


def cmd_leds(args: argparse.Namespace) -> int:
    with BasiliskV3(args.pid) as mouse:
        print("LED zones")
        for led_id, zone in LED_ZONES.items():
            effect = mouse.led_effect(led_id)
            brightness = mouse.led_brightness(led_id)
            percent = round(brightness * 100 / 255)
            print(f"  {zone:<13} [{led_id:#04x}]  {effect.describe():<28} brightness {brightness} ({percent}%)")
            if args.raw:
                print(f"      raw: {effect.payload.hex(' ')}")
    return 0


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
    leds.add_argument("--raw", action="store_true", help="Also print the raw effect payload bytes")
    leds.set_defaults(func=cmd_leds)
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
