import struct
import unittest

from flat import FlatCollector


def f32_regs(value):
    raw = struct.unpack(">I", struct.pack(">f", value))[0]
    return [raw & 0xFFFF, (raw >> 16) & 0xFFFF]


class FakeModbus:
    def __init__(self, registers=None, failing=()):
        self.registers = registers or {}
        self.failing = set(failing)
        self.reads = []

    def read_holding(self, address, count):
        self.reads.append((address, count))
        if address in self.failing:
            raise IOError("read failed")
        return [self.registers.get(address + i, 0) for i in range(count)]


class FlatCollectorTest(unittest.TestCase):
    def test_no_registers_reads_nothing(self):
        modbus = FakeModbus()
        self.assertEqual(FlatCollector(modbus, []).collect(), [])
        self.assertEqual(modbus.reads, [])

    def test_close_registers_share_a_batch(self):
        regs = [{"name": "a", "address": 106}, {"name": "b", "address": 108}, {"name": "c", "address": 114}]
        modbus = FakeModbus()
        FlatCollector(modbus, regs).collect()
        self.assertEqual(modbus.reads, [(106, 10)])

    def test_distant_registers_get_separate_batches(self):
        regs = [{"name": "a", "address": 106}, {"name": "b", "address": 113}]
        modbus = FakeModbus()
        FlatCollector(modbus, regs).collect()
        self.assertEqual(modbus.reads, [(106, 2), (113, 2)])

    def test_batch_size_is_limited(self):
        regs = [{"name": f"r{a}", "address": a} for a in range(0, 100, 2)]
        modbus = FakeModbus()
        FlatCollector(modbus, regs).collect()
        self.assertTrue(all(count <= 50 for _, count in modbus.reads))
        self.assertEqual(sum(count for _, count in modbus.reads), 100)

    def test_decodes_value_and_unit(self):
        low, high = f32_regs(-250.5)
        modbus = FakeModbus({252: low, 253: high})
        regs = [{"name": "netzleistung_gesamt_w", "address": 252, "unit": "W"}]
        point = FlatCollector(modbus, regs).collect()[0]
        self.assertEqual((point.model, point.point, point.value, point.unit),
                         ("flat", "netzleistung_gesamt_w", -250.5, "W"))

    def test_gross_capacity_register_has_high_word_first(self):
        modbus = FakeModbus({512: 0x0000, 513: 0x0031, 514: 53})
        regs = [
            {"name": "batterie_bruttokapazitaet_ah", "address": 512, "type": "u32_abcd", "unit": "Ah"},
            {"name": "batterie_soc_prozent_int", "address": 514, "type": "u16"},
        ]
        points = FlatCollector(modbus, regs).collect()
        self.assertEqual(modbus.reads, [(512, 3)])
        self.assertEqual([p.value for p in points], [49, 53])

    def test_enum_map(self):
        regs = [{"name": "status", "address": 56, "type": "u16", "enum_map": {"6": "Einspeisen"}}]
        point = FlatCollector(FakeModbus({56: 6}), regs).collect()[0]
        self.assertEqual(point.value, "Einspeisen")

    def test_failed_batch_only_drops_its_own_points(self):
        regs = [{"name": "a", "address": 106}, {"name": "b", "address": 252}]
        points = FlatCollector(FakeModbus(failing={106}), regs).collect()
        self.assertEqual([p.point for p in points], ["b"])


if __name__ == "__main__":
    unittest.main()
