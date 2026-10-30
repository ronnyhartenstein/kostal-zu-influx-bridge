import os
import unittest

import yaml

from sunspec import SunSpecCollector

CONFIG_PATH = os.getenv("BRIDGE_CONFIG", "/config/registers.yml")

# Rohdaten von Modell 802, gelesen am 30.10.2026.
M802_REGS = [
    49, 12614, 9344, 9344, 0, 0, 0, 0, 0, 53,
    0, 0, 0, 1038, 0, 0, 0, 0, 1, 4,
    3, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 2103, 2336, 0, 32, 0, 0, 32, 0,
    0, 0, 188, 4000, 4000, 389, 0, 0, 1, 0,
    0, 0, 0, 0, 0, 0, 0, 65535, 65535, 65534,
    65534, 0,
]


def collector(points):
    return SunSpecCollector(modbus=None, models_config={"1": {"points": points}})


class DecodeModelTest(unittest.TestCase):
    def test_skips_u16_marker(self):
        points = [{"name": "a", "offset": 0, "type": "u16"}, {"name": "b", "offset": 1, "type": "u16"}]
        decoded = collector(points)._decode_model(1, [0xFFFF, 7])
        self.assertEqual([(p.point, p.value) for p in decoded], [("b", 7)])

    def test_skips_i16_marker(self):
        points = [{"name": "a", "offset": 0, "type": "i16"}]
        self.assertEqual(collector(points)._decode_model(1, [0x8000]), [])

    def test_marker_is_not_mapped_through_enum(self):
        points = [{"name": "a", "offset": 0, "type": "u16", "enum_map": {"65535": "Unbekannt"}}]
        self.assertEqual(collector(points)._decode_model(1, [0xFFFF]), [])

    def test_skips_value_without_scale_factor(self):
        points = [{"name": "a", "offset": 0, "type": "u16", "scale_from": 1}]
        self.assertEqual(collector(points)._decode_model(1, [100, 0x8000]), [])

    def test_applies_negative_scale_factor(self):
        points = [{"name": "a", "offset": 0, "type": "u16", "scale_from": 1}]
        self.assertAlmostEqual(collector(points)._decode_model(1, [2103, 65535])[0].value, 210.3)


@unittest.skipUnless(os.path.exists(CONFIG_PATH), "registers.yml nicht gemountet")
class RegisterMappingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cls.config = yaml.safe_load(f)

    def test_m802_decodes_recorded_registers(self):
        decoded = SunSpecCollector(None, self.config["models"])._decode_model(802, M802_REGS)
        values = {p.point: p.value for p in decoded}
        self.assertEqual(values["batterie_ladezustand_soc_prozent"], 53)
        self.assertEqual(values["batterie_zyklenanzahl"], 1038)
        self.assertAlmostEqual(values["batteriespannung_v"], 210.3)
        self.assertAlmostEqual(values["batteriestrom_a"], 1.88)
        self.assertEqual(values["batterie_lade_entladeleistung_w"], 389)

    def test_m802_stays_within_model_length(self):
        for point in self.config["models"]["802"]["points"]:
            self.assertLess(point["offset"], len(M802_REGS), point["name"])

    def test_nameplate_is_no_battery_model(self):
        self.assertNotIn("120", self.config["models"])

    def test_misleading_capacity_is_not_exported(self):
        names = [r["name"] for r in self.config["flat_registers"]]
        self.assertNotIn("batterie_nutzbare_kapazitaet_wh", names)

    def test_gross_capacity_uses_high_word_first(self):
        register = next(r for r in self.config["flat_registers"] if r["address"] == 512)
        self.assertEqual(register["type"], "u32_abcd")


if __name__ == "__main__":
    unittest.main()
