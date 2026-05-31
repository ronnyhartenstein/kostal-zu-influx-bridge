import logging
from typing import Any, Dict, List

from decoders import DecodedPoint, decode_typed, sanitize_topic_part
from modbus import ModbusConnection

logger = logging.getLogger("kostal_bridge.flat")

_MAX_BATCH = 50


class FlatCollector:
    def __init__(self, modbus: ModbusConnection, registers_config: List[Dict[str, Any]]) -> None:
        self.modbus = modbus
        self.registers = registers_config

    def collect(self) -> List[DecodedPoint]:
        if not self.registers:
            return []

        regs_sorted = sorted(self.registers, key=lambda r: int(r["address"]))
        batches = self._make_batches(regs_sorted)

        points: List[DecodedPoint] = []
        for batch_address, batch_count, batch_regs in batches:
            try:
                raw = self.modbus.read_holding(batch_address, batch_count)
            except Exception as exc:
                logger.warning("Flat batch read failed at %s count=%s: %s", batch_address, batch_count, exc)
                continue

            for reg in batch_regs:
                name = reg.get("name")
                address = int(reg["address"])
                dtype = str(reg.get("type", "f32_cdab"))
                unit = str(reg.get("unit", ""))

                if not name:
                    continue

                enum_map = reg.get("enum_map", {})
                offset = address - batch_address
                try:
                    value = decode_typed(raw, offset, dtype)
                    if isinstance(enum_map, dict) and enum_map:
                        value = enum_map.get(str(value), value)
                    points.append(DecodedPoint(
                        model="flat",
                        point=sanitize_topic_part(str(name)),
                        value=value,
                        unit=unit,
                    ))
                except Exception as exc:
                    logger.debug("Skipping flat register %s (%s): %s", name, address, exc)

        return points

    def _make_batches(self, regs_sorted):
        batches = []
        i = 0
        while i < len(regs_sorted):
            batch_start = int(regs_sorted[i]["address"])
            batch_regs = [regs_sorted[i]]
            j = i + 1
            while j < len(regs_sorted):
                addr = int(regs_sorted[j]["address"])
                reg_width = 2 if regs_sorted[j].get("type", "f32_cdab") in {"f32_cdab", "u32_cdab", "i32_cdab"} else 1
                end_of_current = int(regs_sorted[j - 1]["address"]) + (
                    2 if regs_sorted[j - 1].get("type", "f32_cdab") in {"f32_cdab", "u32_cdab", "i32_cdab"} else 1
                )
                if addr <= end_of_current + 4 and (addr + reg_width - batch_start) <= _MAX_BATCH:
                    batch_regs.append(regs_sorted[j])
                    j += 1
                else:
                    break

            last = batch_regs[-1]
            last_addr = int(last["address"])
            last_width = 2 if last.get("type", "f32_cdab") in {"f32_cdab", "u32_cdab", "i32_cdab"} else 1
            batch_count = last_addr + last_width - batch_start

            batches.append((batch_start, batch_count, batch_regs))
            i = j

        return batches
