import os
import struct
from dataclasses import dataclass
from typing import Any, List

NOT_IMPLEMENTED = {
    "u16": 0xFFFF,
    "i16": -0x8000,
    "u32_abcd": 0xFFFFFFFF,
    "u32_cdab": 0xFFFFFFFF,
    "i32_cdab": -0x80000000,
}


@dataclass
class DecodedPoint:
    model: str
    point: str
    value: Any
    unit: str = ""


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def sanitize_topic_part(value: str) -> str:
    out = []
    for ch in value.lower():
        if ch.isalnum() or ch in {"_", "-"}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_") or "unknown"


def is_not_implemented(value: Any, dtype: str) -> bool:
    """SunSpec-Marker für nicht belegte Punkte. Gilt nur für SunSpec-Modelle, nicht für flat_registers."""
    return dtype in NOT_IMPLEMENTED and value == NOT_IMPLEMENTED[dtype]


def cdab_u32(reg_hi: int, reg_lo: int) -> int:
    a = (reg_hi >> 8) & 0xFF
    b = reg_hi & 0xFF
    c = (reg_lo >> 8) & 0xFF
    d = reg_lo & 0xFF
    return (c << 24) | (d << 16) | (a << 8) | b


def decode_typed(regs: List[int], offset: int, dtype: str) -> Any:
    if offset < 0 or offset >= len(regs):
        raise IndexError(f"Offset {offset} out of range")

    if dtype == "u16":
        return int(regs[offset])
    if dtype == "i16":
        value = regs[offset]
        return value - 65536 if value > 32767 else value
    if dtype == "u32_abcd":
        if offset + 1 >= len(regs):
            raise IndexError(f"Offset {offset} requires 2 registers")
        return (int(regs[offset]) << 16) | int(regs[offset + 1])
    if dtype in {"u32_cdab", "i32_cdab", "f32_cdab"}:
        if offset + 1 >= len(regs):
            raise IndexError(f"Offset {offset} requires 2 registers")
        raw = cdab_u32(regs[offset], regs[offset + 1])
        if dtype == "u32_cdab":
            return raw
        if dtype == "i32_cdab":
            return struct.unpack(">i", raw.to_bytes(4, byteorder="big", signed=False))[0]
        return struct.unpack(">f", raw.to_bytes(4, byteorder="big", signed=False))[0]

    raise ValueError(f"Unsupported dtype: {dtype}")


def decode_i16(regs: List[int], offset: int) -> int:
    if offset < 0 or offset >= len(regs):
        raise IndexError(f"Offset {offset} out of range")
    value = int(regs[offset])
    return value - 65536 if value > 32767 else value


def decode_string(regs: List[int], offset: int, length: int) -> str:
    if length <= 0:
        return ""
    reg_count = (length + 1) // 2
    if offset < 0 or offset + reg_count > len(regs):
        raise IndexError(f"String at offset {offset} length {length} out of range")

    raw = bytearray()
    for i in range(reg_count):
        reg = int(regs[offset + i])
        raw.append((reg >> 8) & 0xFF)
        raw.append(reg & 0xFF)

    decoded = bytes(raw[:length]).decode("ascii", errors="ignore")
    return decoded.rstrip("\x00 ").strip()
