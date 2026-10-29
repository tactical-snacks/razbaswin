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

    def dpi(self) -> tuple[int, int]:
        return protocol.parse_dpi(self.transact(0x04, 0x85, 0x07, b"\x00"))

    def dpi_stages(self) -> protocol.DpiStages:
        return protocol.parse_dpi_stages(self.transact(0x04, 0x86, 0x26, b"\x00"))
