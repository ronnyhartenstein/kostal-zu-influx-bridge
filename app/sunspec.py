import logging
from typing import Any, Dict, List, Optional, Tuple

from decoders import DecodedPoint, decode_i16, decode_string, decode_typed, is_not_implemented, sanitize_topic_part
from modbus import ModbusConnection

logger = logging.getLogger("kostal_bridge.sunspec")


class SunSpecCollector:
    def __init__(self, modbus: ModbusConnection, models_config: Dict[str, Any]) -> None:
        self.modbus = modbus
        self.models_config = models_config
        self._base: Optional[int] = None
        self._models: List[Tuple[int, int, int]] = []

    def invalidate(self) -> None:
        self._base = None
        self._models = []

    def collect(self) -> List[DecodedPoint]:
        self._discover()
        points: List[DecodedPoint] = []
        for model_id, data_address, model_len in self._models:
            try:
                regs = self.modbus.read_holding(data_address, model_len)
                points.extend(self._decode_model(model_id, regs))
            except Exception as exc:
                logger.warning("Failed to read SunSpec model %s: %s", model_id, exc)
        return points

    def _discover(self) -> None:
        if self._base is not None and self._models:
            return

        logger.info("Running SunSpec discovery")
        found_base = None
        for base in [40000, 39999, 50000, 0]:
            try:
                regs = self.modbus.read_holding(base, 2)
                if regs == [0x5375, 0x6E53]:
                    found_base = base
                    break
            except Exception:
                continue

        if found_base is None:
            raise RuntimeError("SunSpec marker not found on known base addresses")

        self._base = found_base
        logger.info("SunSpec marker found at base %s", found_base)

        models: List[Tuple[int, int, int]] = []
        cursor = found_base + 2
        for _ in range(512):
            header = self.modbus.read_holding(cursor, 2)
            model_id, model_len = int(header[0]), int(header[1])

            if model_id == 0xFFFF:
                break
            if model_len <= 0 or model_len > 2048:
                raise RuntimeError(f"Invalid model length for model {model_id}: {model_len}")

            data_address = cursor + 2
            models.append((model_id, data_address, model_len))
            cursor = data_address + model_len

        if not models:
            raise RuntimeError("No SunSpec models discovered")

        self._models = models
        logger.info("Discovered %d SunSpec models", len(models))

    def _decode_model(self, model_id: int, regs: List[int]) -> List[DecodedPoint]:
        model_cfg = self.models_config.get(str(model_id), {})
        configured_points = model_cfg.get("points", [])
        decoded: List[DecodedPoint] = []

        if not isinstance(configured_points, list):
            return decoded

        for item in configured_points:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            offset = item.get("offset")
            dtype = item.get("type")
            unit = item.get("unit", "")
            scale_from = item.get("scale_from")
            enum_map = item.get("enum_map", {})
            if name is None or offset is None or dtype is None:
                continue

            try:
                dtype_value = str(dtype)
                if dtype_value == "string":
                    text_len = int(item.get("length", 0))
                    value = decode_string(regs=regs, offset=int(offset), length=text_len)
                else:
                    value = decode_typed(regs=regs, offset=int(offset), dtype=dtype_value)

                if is_not_implemented(value, dtype_value):
                    logger.debug("Skipping unimplemented point model=%s name=%s", model_id, name)
                    continue

                if scale_from is not None and isinstance(value, (int, float)):
                    sf = decode_i16(regs, int(scale_from))
                    if sf == -32768:
                        logger.debug("Skipping point without scale factor model=%s name=%s", model_id, name)
                        continue
                    value = float(value) * (10 ** sf)

                if isinstance(enum_map, dict):
                    value = enum_map.get(str(value), value)

                decoded.append(DecodedPoint(
                    model=f"m{model_id}",
                    point=sanitize_topic_part(str(name)),
                    value=value,
                    unit=str(unit),
                ))
            except Exception as exc:
                logger.debug("Skipping configured point model=%s name=%s due to %s", model_id, name, exc)

        return decoded
