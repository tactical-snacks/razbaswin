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


# --- Lighting --------------------------------------------------------------------

# Slot byte: 0 = live state of the active profile (lost on replug), 1-5 = profile banks.
SLOT_LIVE = 0x00

LED_ZONES = {
    0x01: "Scroll wheel",
    0x04: "Logo",
    0x0A: "Underglow",
}

ZONE_IDS = {"scroll": 0x01, "logo": 0x04, "underglow": 0x0A}

EFFECT_OFF = 0x00
EFFECT_STATIC = 0x01
EFFECT_BREATHING = 0x02
EFFECT_SPECTRUM = 0x03
EFFECT_WAVE = 0x04
EFFECT_REACTIVE = 0x05

EFFECT_NAMES = {
    EFFECT_OFF: "off",
    EFFECT_STATIC: "static",
    EFFECT_BREATHING: "breathing",
    EFFECT_SPECTRUM: "spectrum",
    EFFECT_WAVE: "wave",
    EFFECT_REACTIVE: "reactive",
}

BREATHING_MODES = {0x00: "random", 0x01: "single", 0x02: "dual"}

# Effects whose color bytes are meaningful; spectrum/wave report a placeholder.
COLOR_EFFECTS = {EFFECT_STATIC, EFFECT_BREATHING, EFFECT_REACTIVE}


@dataclass(frozen=True)
class LedEffect:
    led_id: int
    effect_id: int
    param: int
    speed: int
    colors: list[tuple[int, int, int]]
    payload: bytes

    @property
    def name(self) -> str:
        return EFFECT_NAMES.get(self.effect_id, f"unknown ({self.effect_id:#04x})")

    def describe(self) -> str:
        parts = [self.name]
        if self.effect_id == EFFECT_BREATHING:
            parts.append(BREATHING_MODES.get(self.param, f"mode {self.param:#04x}"))
        elif self.effect_id == EFFECT_WAVE:
            parts.append(f"direction {self.param}, speed {self.speed}")
        elif self.effect_id == EFFECT_REACTIVE:
            parts.append(f"speed {self.speed}")
        if self.effect_id in COLOR_EFFECTS or self.effect_id not in EFFECT_NAMES:
            parts.extend(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in self.colors)
        return " ".join(parts)


def parse_led_effect(r: Response) -> LedEffect:
    # 0x0F:0x82 -> [storage, led, effect, param, speed, color count, R, G, B, ...]
    payload = r.raw[8 : 8 + r.size]
    count = payload[5] if len(payload) > 5 else 0
    colors = [tuple(payload[6 + i * 3 : 9 + i * 3]) for i in range(count) if 9 + i * 3 <= len(payload)]
    return LedEffect(
        led_id=payload[1],
        effect_id=payload[2],
        param=payload[3],
        speed=payload[4],
        colors=colors,
        payload=bytes(payload),
    )


def parse_led_brightness(r: Response) -> int:
    # 0x0F:0x84 -> [storage, led, brightness 0-255]
    return r.raw[10]


WAVE_DEFAULT_SPEED = 0x28

Color = tuple[int, int, int]

# Breathing and reactive return status 0x05 (not supported) on the Basilisk V3,
# matching OpenSnek's effect list for this family.
WRITABLE_EFFECTS = ["off", "static", "spectrum", "wave"]


def effect_payload(
    effect: str,
    colors: list[Color] = (),
    speed: int | None = None,
    direction: int = 1,
) -> bytes:
    """Effect bytes that follow [slot, led] in a 0x0F:0x02 write (payload families from OpenSnek)."""

    def need(n: int) -> None:
        if len(colors) != n:
            raise ValueError(f"{effect} takes {n} color(s), got {len(colors)}")

    if effect == "off":
        need(0)
        return bytes([EFFECT_OFF, 0, 0, 0])
    if effect == "static":
        need(1)
        return bytes([EFFECT_STATIC, 0, 0, 1, *colors[0]])
    if effect == "spectrum":
        # Factory payload read from a new mouse. The speed byte is stored but the
        # cycle rate doesn't change, so it's fixed here.
        need(0)
        return bytes([EFFECT_SPECTRUM, 1, 0x28, 1, 0xFF, 0xFF, 0xFF])
    if effect == "wave":
        need(0)
        return bytes([EFFECT_WAVE, direction, WAVE_DEFAULT_SPEED if speed is None else speed, 0])
    raise ValueError(f"unknown effect {effect!r}")
