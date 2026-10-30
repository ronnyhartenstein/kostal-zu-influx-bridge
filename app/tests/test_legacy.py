import logging
import math
import unittest
from unittest import mock

from influxdb.line_protocol import make_lines

import main
import sinks
from decoders import DecodedPoint
from legacy import LEGACY_SERIES, legacy_values


def flat(point, value):
    return DecodedPoint(model="flat", point=point, value=value)


ALL_POINTS = [
    flat("ac_wirkleistung_gesamt_w", 536.0),
    flat("hausverbrauch_pv_w", 300.0),
    flat("hausverbrauch_batterie_w", 200.0),
    flat("hausverbrauch_netz_w", 36.5),
    flat("netzleistung_gesamt_w", -1234.56),
    flat("batterie_soc_prozent_int", 16),
]


class LegacyValuesTest(unittest.TestCase):
    def test_all_seven_series(self):
        self.assertEqual(legacy_values(ALL_POINTS), {
            "pv_production": 0.536,
            "own_use_from_pv": 0.3,
            "own_use_from_battery": 0.2,
            "own_use_from_grid": 0.0365,
            "total_power": -1.2346,
            "total_home_consumption": -1.2346,
            "battery_capacity": 1.52,
        })

    def test_values_are_always_float(self):
        points = [flat("ac_wirkleistung_gesamt_w", 0), flat("batterie_soc_prozent_int", 0)]
        for value in legacy_values(points).values():
            self.assertIs(type(value), float)

    def test_missing_value_writes_nothing_for_that_series(self):
        points = [p for p in ALL_POINTS if p.point != "netzleistung_gesamt_w"]
        values = legacy_values(points)
        self.assertEqual(len(values), 5)
        self.assertNotIn("total_power", values)
        self.assertNotIn("total_home_consumption", values)

    def test_non_finite_and_non_numeric_values_are_skipped(self):
        for bad in (math.nan, math.inf, -math.inf, "n/a", None, True):
            self.assertEqual(legacy_values([flat("hausverbrauch_pv_w", bad)]), {})

    def test_only_flat_points_are_used(self):
        point = DecodedPoint(model="m103", point="hausverbrauch_pv_w", value=100.0)
        self.assertEqual(legacy_values([point]), {})


class LegacyHausSinkTest(unittest.TestCase):
    def _written(self, env=None):
        with mock.patch.dict("os.environ", env or {}), mock.patch.object(sinks, "InfluxDBClient") as client:
            sinks.LegacyHausSink().write(ALL_POINTS)
        return client

    def test_defaults_target_haus_without_creating_the_database(self):
        client = self._written()
        self.assertEqual(client.call_args.kwargs["database"], "haus")
        client.return_value.create_database.assert_not_called()

    def test_line_protocol(self):
        write_points = self._written().return_value.write_points
        body = write_points.call_args.args[0]
        lines = make_lines({"points": body}).splitlines()

        self.assertEqual(len(lines), len(LEGACY_SERIES))
        self.assertEqual(len(LEGACY_SERIES), 7)
        self.assertRegex(lines[0], r"^strom,site_name=pv_production value=0\.536 \d+$")
        self.assertRegex(lines[-1], r"^strom,site_name=battery_capacity value=1\.52 \d+$")
        self.assertNotIn("retention_policy", write_points.call_args.kwargs)

    def test_measurement_is_configurable(self):
        write_points = self._written({"LEGACY_HAUS_MEASUREMENT": "x"}).return_value.write_points
        self.assertEqual(write_points.call_args.args[0][0]["measurement"], "x")

    def test_nothing_to_write(self):
        with mock.patch.object(sinks, "InfluxDBClient") as client:
            sinks.LegacyHausSink().write([])
        client.return_value.write_points.assert_not_called()


class WriteLegacyTest(unittest.TestCase):
    def test_disabled_sink_is_a_noop(self):
        main._write_legacy(None, ALL_POINTS)

    def test_write_error_does_not_propagate(self):
        legacy = mock.Mock()
        legacy.write.side_effect = RuntimeError("influx down")
        with self.assertLogs("kostal_bridge", logging.WARNING):
            main._write_legacy(legacy, ALL_POINTS)


if __name__ == "__main__":
    unittest.main()
