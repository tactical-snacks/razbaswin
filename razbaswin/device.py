"""HID transport for the Razer Basilisk V3 on Windows."""

import time

import hid

from . import protocol
from .protocol import Response

RAZER_VID = 0x1532
BASILISK_V3_PID = 0x0099

# On Windows the mouse/keyboard collections are owned by the OS; the vendor
# feature report is reachable through the consumer-control collection on
# interface 3. Other collections are still tried as a fallback.
PREFERRED_INTERFACE = 3


class DeviceError(Exception):
    pass


def enumerate_devices(pid: int = BASILISK_V3_PID) -> list[dict]:
    return hid.enumerate(RAZER_VID, pid)


def _candidate_paths(pid: int) -> list[bytes]:
    devices = enumerate_devices(pid)
    devices.sort(key=lambda d: d["interface_number"] != PREFERRED_INTERFACE)
    return [d["path"] for d in devices]


class BasiliskV3:
    def __init__(self, pid: int = BASILISK_V3_PID, txn: int = protocol.TRANSACTION_ID):
        self.pid = pid
        self.txn = txn
        self._dev: hid.device | None = None
        self.path: bytes | None = None

    def __enter__(self) -> "BasiliskV3":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        paths = _candidate_paths(self.pid)
        if not paths:
            raise DeviceError(f"No Razer device with PID {self.pid:#06x} found")
        for path in paths:
            dev = hid.device()
            try:
                dev.open_path(path)
            except OSError:
                continue
            self._dev = dev
            try:
                self.transact(0x00, 0x81, 0x02)  # firmware read as a liveness probe
            except (OSError, DeviceError):
                dev.close()
                self._dev = None
                continue
            self.path = path
            return
        raise DeviceError("Found the device, but no HID collection accepted the control report")

    def close(self) -> None:
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    def transact(
        self,
        class_id: int,
        cmd_id: int,
        size: int,
        args: bytes = b"",
        attempts: int = 6,
        delay: float = 0.035,
    ) -> Response:
        if self._dev is None:
            raise DeviceError("Device is not open")
        report = protocol.build_report(class_id, cmd_id, size, args, self.txn)
        # hidapi expects the report ID as the first byte; Razer uses report ID 0.
        self._dev.send_feature_report(b"\x00" + report)

        last: Response | None = None
        for _ in range(max(1, attempts)):
            time.sleep(delay)
            raw = bytes(self._dev.get_feature_report(0x00, protocol.REPORT_LEN + 1))
            if len(raw) == protocol.REPORT_LEN + 1:
                raw = raw[1:]
            if len(raw) < protocol.REPORT_LEN:
                continue
            resp = Response(raw)
            last = resp
            if resp.status in (protocol.STATUS_NEW, protocol.STATUS_BUSY):
                continue
            if not resp.matches(self.txn, class_id, cmd_id):
                continue
            if resp.status != protocol.STATUS_OK:
                name = protocol.STATUS_NAMES.get(resp.status, f"{resp.status:#04x}")
                raise DeviceError(f"Command {class_id:#04x}:{cmd_id:#04x} returned status {name}")
            return resp
        detail = f" (last status {last.status:#04x})" if last else ""
        raise DeviceError(f"No response to command {class_id:#04x}:{cmd_id:#04x}{detail}")

    # --- Reads -----------------------------------------------------------------

    def firmware(self) -> str:
        return protocol.parse_firmware(self.transact(0x00, 0x81, 0x02))

    def serial(self) -> str:
        return protocol.parse_serial(self.transact(0x00, 0x82, 0x16))

    def poll_rate(self) -> int | None:
        return protocol.parse_poll_rate(self.transact(0x00, 0x85, 0x01))

    def dpi(self, storage: int = protocol.SLOT_LIVE) -> tuple[int, int]:
        return protocol.parse_dpi(self.transact(0x04, 0x85, 0x07, bytes([storage])))

    def dpi_stages(self, storage: int = protocol.SLOT_LIVE) -> protocol.DpiStages:
        return protocol.parse_dpi_stages(self.transact(0x04, 0x86, 0x26, bytes([storage])))

    def active_profile(self) -> int:
        # 0x05:0x84 reports size 0 but still carries the profile ID in args[0]
        return self.transact(0x05, 0x84, 0x00).raw[8]

    def profile_inventory(self) -> tuple[int, list[int]]:
        """(max profile ID, assigned profile IDs) from 0x05:0x81."""
        return protocol.parse_profile_inventory(self.transact(0x05, 0x81, 0x00))

    def scroll_mode(self, storage: int = protocol.SLOT_LIVE) -> int:
        return self.transact(0x02, 0x94, 0x02, bytes([storage, 0])).raw[9]

    def scroll_acceleration(self, storage: int = protocol.SLOT_LIVE) -> bool:
        return self.transact(0x02, 0x96, 0x02, bytes([storage, 0])).raw[9] == 0x01

    def smart_reel(self, storage: int = protocol.SLOT_LIVE) -> bool:
        return self.transact(0x02, 0x97, 0x02, bytes([storage, 0])).raw[9] == 0x01

    def button_block(self, button: int, storage: int = protocol.SLOT_LIVE, hypershift: int = 0) -> bytes:
        """7-byte function block bound to a button slot (0x02:0x8C)."""
        r = self.transact(0x02, 0x8C, 0x0A, bytes([storage, button, hypershift]) + bytes(7))
        if r.raw[8] != storage or r.raw[9] != button:
            raise DeviceError(f"Button read for {button:#04x} echoed the wrong profile/slot")
        return r.raw[11:18]

    def led_effect(self, led_id: int, storage: int = protocol.SLOT_LIVE) -> protocol.LedEffect:
        args = bytes([storage, led_id]) + bytes(10)
        return protocol.parse_led_effect(self.transact(0x0F, 0x82, 0x0C, args))

    def led_brightness(self, led_id: int, storage: int = protocol.SLOT_LIVE) -> int:
        return protocol.parse_led_brightness(self.transact(0x0F, 0x84, 0x03, bytes([storage, led_id, 0x00])))

    # --- Writes ----------------------------------------------------------------

    def set_led_brightness(self, led_id: int, value: int, storage: int) -> None:
        self.transact(0x0F, 0x04, 0x03, bytes([storage, led_id, value]))

    def set_led_effect(self, led_id: int, payload: bytes, storage: int) -> None:
        args = bytes([storage, led_id]) + payload
        self.transact(0x0F, 0x02, len(args), args)

    def set_custom_frame(self, first: int, last: int, colors: list[tuple[int, int, int]]) -> None:
        """Fill frame cells first..last (row 0). Shown at once by zones in the custom effect."""
        args = bytes([0x00, 0x00, 0x00, first, last]) + bytes(c for rgb in colors for c in rgb)
        self.transact(0x0F, 0x03, len(args), args)

    def set_dpi(self, x: int, y: int, storage: int) -> None:
        self.transact(0x04, 0x05, 0x07, bytes([storage, x >> 8, x & 0xFF, y >> 8, y & 0xFF, 0, 0]))

    def set_dpi_stages(self, stages: list[tuple[int, int]], stage_ids: list[int], active_index: int, storage: int) -> None:
        # Rows: <id> <X be16> <Y be16> 00 00. The active stage is given by its ID token.
        args = bytes([storage, stage_ids[active_index], len(stages)])
        for stage_id, (x, y) in zip(stage_ids, stages):
            args += bytes([stage_id, x >> 8, x & 0xFF, y >> 8, y & 0xFF, 0, 0])
        self.transact(0x04, 0x06, 0x26, args)

    def set_scroll_mode(self, mode: int, storage: int) -> None:
        self.transact(0x02, 0x14, 0x02, bytes([storage, mode]))

    def set_scroll_acceleration(self, enabled: bool, storage: int) -> None:
        self.transact(0x02, 0x16, 0x02, bytes([storage, int(enabled)]))

    def set_smart_reel(self, enabled: bool, storage: int) -> None:
        self.transact(0x02, 0x17, 0x02, bytes([storage, int(enabled)]))

    def set_button_block(self, button: int, block: bytes, storage: int, hypershift: int = 0) -> None:
        self.transact(0x02, 0x0C, 0x0A, bytes([storage, button, hypershift]) + block)

    def _profile_command(self, cmd_id: int, profile: int) -> None:
        r = self.transact(0x05, cmd_id, 0x01, bytes([profile]))
        if r.raw[8] != profile:
            raise DeviceError(f"Profile command {cmd_id:#04x} echoed profile {r.raw[8]}, expected {profile}")

    def create_profile(self, profile: int) -> None:
        """Assign a bank as a profile (05:02). Resets at least part of the bank's content."""
        self._profile_command(0x02, profile)

    def delete_profile(self, profile: int) -> None:
        """Unassign a profile (05:03). Its bank content stays readable."""
        self._profile_command(0x03, profile)

    def set_active_profile(self, profile: int) -> None:
        """Select an assigned profile (05:04); live state reloads from its bank."""
        self._profile_command(0x04, profile)

    def set_poll_rate(self, hz: int) -> None:
        raw = {rate: code for code, rate in protocol.POLL_RATES.items()}[hz]
        self.transact(0x00, 0x05, 0x01, bytes([raw]))
