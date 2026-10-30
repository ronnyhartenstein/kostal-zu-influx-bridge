import struct
import unittest

from decoders import cdab_u32, decode_i16, decode_string, decode_typed, sanitize_topic_part


def cdab_regs(raw):
    return [raw & 0xFFFF, (raw >> 16) & 0xFFFF]


class DecodeTypedTest(unittest.TestCase):
    def test_cdab_u32_puts_low_word_first(self):
        self.assertEqual(cdab_u32(0x5678, 0x1234), 0x12345678)

    def test_u16_and_i16(self):
        self.assertEqual(decode_typed([65535], 0, "u16"), 65535)
        self.assertEqual(decode_typed([65535], 0, "i16"), -1)
        self.assertEqual(decode_i16([65535], 0), -1)

    def test_u32_and_i32(self):
        regs = cdab_regs(0xFFFFFFFE)
        self.assertEqual(decode_typed(regs, 0, "u32_cdab"), 0xFFFFFFFE)
        self.assertEqual(decode_typed(regs, 0, "i32_cdab"), -2)

    def test_f32_keeps_sign(self):
        raw = struct.unpack(">I", struct.pack(">f", -1234.5))[0]
        self.assertEqual(decode_typed(cdab_regs(raw), 0, "f32_cdab"), -1234.5)

    def test_offset_errors(self):
        with self.assertRaises(IndexError):
            decode_typed([1], 1, "u16")
        with self.assertRaises(IndexError):
            decode_typed([1], 0, "f32_cdab")

    def test_unknown_type(self):
        with self.assertRaises(ValueError):
            decode_typed([1], 0, "f64")


class DecodeStringTest(unittest.TestCase):
    def test_strips_padding(self):
        self.assertEqual(decode_string([0x4142, 0x4300], 0, 4), "ABC")

    def test_range_error(self):
        with self.assertRaises(IndexError):
            decode_string([0x4142], 0, 4)


class SanitizeTopicPartTest(unittest.TestCase):
    def test_replaces_special_characters(self):
        self.assertEqual(sanitize_topic_part("Netz/Leistung W"), "netz_leistung_w")

    def test_empty_falls_back(self):
        self.assertEqual(sanitize_topic_part("///"), "unknown")


if __name__ == "__main__":
    unittest.main()
