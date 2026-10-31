import asyncio
import unittest
from datetime import datetime, timedelta, timezone

import server

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


class CheckQuery(unittest.TestCase):
    def test_erlaubt_select_und_show(self):
        self.assertEqual(server.check_query(" SELECT * FROM strom ; "), "SELECT * FROM strom")
        self.assertEqual(server.check_query("show measurements"), "show measurements")

    def test_semikolon_und_into_im_string_sind_harmlos(self):
        q = "SELECT value FROM strom WHERE site_name = 'a;INTO b'"
        self.assertEqual(server.check_query(q), q)

    def test_lehnt_schreibendes_ab(self):
        for q in ("DROP DATABASE kostal", "DELETE FROM strom", "CREATE DATABASE x",
                  "SELECT * INTO kopie FROM strom", "select *\ninto kopie from strom",
                  "SELECT 1; DROP DATABASE kostal", 'SELECT value FROM "a"; DROP DATABASE kostal'):
            with self.assertRaises(server.ToolError, msg=q):
                server.check_query(q)


MINI = {"autogen": 7 * 86400, "downsample": float("inf")}
REPO = {"autogen": 86400, "rp_1min": 7 * 86400, "rp_5min": float("inf")}


class HistoryQuery(unittest.TestCase):
    def query(self, days, interval, aggregate="mean", points=("netzfrequenz_hz",), retention=MINI):
        return server.history_query(list(points), NOW - timedelta(days=days), NOW, interval, aggregate, NOW, retention)

    def test_fein_und_jung_liest_rohdaten(self):
        q = self.query(1, "1m")
        self.assertIn('mean("value")', q)
        self.assertIn('"autogen"."kostal_plenticore"', q)

    def test_grob_liest_downsample(self):
        q = self.query(1, "1h", "max")
        self.assertIn('max("max_value_5m")', q)
        self.assertIn('"downsample"."kostal_plenticore"', q)

    def test_repo_stack_nutzt_seine_stufen(self):
        self.assertIn('"rp_1min"', self.query(1.2, "1m", retention=REPO))
        q = self.query(30, "1h", "max", retention=REPO)
        self.assertIn('max("value") AS "value" FROM "rp_5min"', q)

    def test_nur_rohdaten_ohne_bekanntes_layout(self):
        self.assertIn('"autogen"', self.query(1, "1h", retention={"autogen": float("inf")}))

    def test_fein_und_alt_gibt_es_nicht(self):
        with self.assertRaisesRegex(server.ToolError, "300 Sekunden"):
            self.query(30, "1m")

    def test_aelter_als_jede_stufe(self):
        with self.assertRaisesRegex(server.ToolError, "keine Daten"):
            self.query(30, "1h", retention={"autogen": 86400})

    def test_zu_viele_werte(self):
        with self.assertRaisesRegex(server.ToolError, "Intervall"):
            self.query(365, "5m")

    def test_lehnt_einschleusen_ab(self):
        with self.assertRaises(server.ToolError):
            self.query(1, "1h", points=("x' OR '1'='1",))
        with self.assertRaises(server.ToolError):
            self.query(1, "1h; DROP DATABASE kostal")
        with self.assertRaises(server.ToolError):
            self.query(1, "1h", "sum")


class Retention(unittest.TestCase):
    def test_dauer(self):
        self.assertEqual(server.retention_seconds("168h0m0s"), 7 * 86400)
        self.assertEqual(server.retention_seconds("0s"), float("inf"))


class Tools(unittest.TestCase):
    def test_alle_tools_sind_read_only(self):
        tools = asyncio.run(server.create().list_tools())
        self.assertEqual({t.name for t in tools},
                         {"get_overview", "list_points", "get_latest", "get_history", "query_influxql"})
        self.assertTrue(all(t.annotations.read_only_hint for t in tools))


if __name__ == "__main__":
    unittest.main()
