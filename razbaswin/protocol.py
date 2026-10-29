"""Razer USB vendor protocol framing.

Ported from OpenSnek (https://github.com/gh123man/OpenSnek), see
OpenSnekProtocols/USBHIDProtocol.swift and Bridge/BridgeClient+USB.swift.

Every command is a 90-byte feature report:

    [0]     status (0x00 on requests)
    [1]     transaction ID (0x1F for the Basilisk V3 family)
    [2:5]   remaining packets / protocol type (unused, zero)
    [5]     data size
    [6]     command class
    [7]     command ID (bit 7 set = read)
    [8:88]  arguments
    [88]    CRC: XOR of bytes 2..87
    [89]    reserved
"""

from dataclasses import dataclass

REPORT_LEN = 90
TRANSACTION_ID = 0x1F

STATUS_NEW = 0x00
STATUS_BUSY = 0x01
STATUS_OK = 0x02
STATUS_FAIL = 0x03
STATUS_TIMEOUT = 0x04
STATUS_NOT_SUPPORTED = 0x05

STATUS_NAMES = {
    STATUS_NEW: "new",
    STATUS_BUSY: "busy",
    STATUS_OK: "ok",
    STATUS_FAIL: "failure",
    STATUS_TIMEOUT: "timeout",
    STATUS_NOT_SUPPORTED: "not supported",
}


def crc(report: bytes) -> int:
    value = 0
    for b in report[2:88]:
        value ^= b
    return value


def build_report(class_id: int, cmd_id: int, size: int, args: bytes = b"", txn: int = TRANSACTION_ID) -> bytes:
    report = bytearray(REPORT_LEN)
    report[1] = txn
    report[5] = size
    report[6] = class_id
    report[7] = cmd_id
    args = bytes(args[:80])
    report[8 : 8 + len(args)] = args
    report[88] = crc(report)
    return bytes(report)


@dataclass(frozen=True)
class Response:
    raw: bytes

    @property
    def status(self) -> int:
        return self.raw[0]

    @property
    def txn(self) -> int:
        return self.raw[1]

    @property
    def size(self) -> int:
        return self.raw[5]

    @property
    def class_id(self) -> int:
        return self.raw[6]

    @property
    def cmd_id(self) -> int:
        return self.raw[7]

    @property
    def args(self) -> bytes:
        return self.raw[8:88]

    def matches(self, txn: int, class_id: int, cmd_id: int) -> bool:
        return (
            len(self.raw) >= REPORT_LEN
            and self.txn == txn
            and self.class_id == class_id
            and (self.cmd_id & 0x7F) == (cmd_id & 0x7F)
            and self.raw[88] == crc(self.raw)
        )


# --- Parsers for read commands -------------------------------------------------


def parse_firmware(r: Response) -> str:
    # 0x00:0x81
    return f"{r.raw[8]}.{r.raw[9]}"


def parse_serial(r: Response) -> str:
    # 0x00:0x82, 22 bytes of ASCII
    return r.raw[8:30].split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


POLL_RATES = {0x01: 1000, 0x02: 500, 0x08: 125}


def parse_poll_rate(r: Response) -> int | None:
    # 0x00:0x85
    return POLL_RATES.get(r.raw[8])


def parse_dpi(r: Response) -> tuple[int, int]:
    # 0x04:0x85 -> [8]=storage, [9:11]=X, [11:13]=Y (big-endian)
    return (r.raw[9] << 8 | r.raw[10], r.raw[11] << 8 | r.raw[12])


@dataclass(frozen=True)
class DpiStages:
    active_index: int
    stages: list[tuple[int, int]]
    stage_ids: list[int]


def parse_dpi_stages(r: Response) -> DpiStages:
    # 0x04:0x86 -> [8]=storage, [9]=active stage ID, [10]=count,
    # then 7-byte rows: id, X hi, X lo, Y hi, Y lo, 0, 0
    active_id = r.raw[9]
    count = max(1, min(5, r.raw[10]))
    stages: list[tuple[int, int]] = []
    ids: list[int] = []
    for i in range(count):
        off = 11 + i * 7
        if off + 6 >= len(r.raw):
            break
        ids.append(r.raw[off])
        stages.append((r.raw[off + 1] << 8 | r.raw[off + 2], r.raw[off + 3] << 8 | r.raw[off + 4]))
    # The active field is a stage ID token; fall back to treating it as a 1-based index.
    if active_id in ids:
        active = ids.index(active_id)
    else:
        active = max(0, min(len(stages) - 1, active_id - 1))
    return DpiStages(active_index=active, stages=stages, stage_ids=ids)
