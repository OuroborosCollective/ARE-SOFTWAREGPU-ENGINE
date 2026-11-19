"""Fail-closed 'new tests first' leaderboard contract; never invent CPU timings."""
import copy
import unittest

from software_gpu.benchmarks import test_series_catalog as catalog
from software_gpu.benchmarks import spherepop_rankings


class TestSeriesCatalogTests(unittest.TestCase):
    def test_newest_tests_render_first_and_historical_board_is_separate(self):
        records = catalog.load_catalog()
        rendered = catalog.render_catalog(records)
        first = rendered.index("2026-11-19")
        last = rendered.index("2026-11-07")
        self.assertLess(first, last)
        self.assertIn("nicht gemessen", rendered.lower())
        self.assertIn("Visual Asset Lab", rendered)
        self.assertIn("## CAG/SpherePop/Doppler", spherepop_rankings.render(
            spherepop_rankings.assemble(
                __import__("json").loads(spherepop_rankings.WAVE.read_text()),
                __import__("json").loads(spherepop_rankings.WINDOW.read_text()))))

    def test_sorting_does_not_depend_on_input_order(self):
        doc = catalog.load_catalog()
        shuffled = dict(doc, tests=list(reversed(doc["tests"])))
        self.assertEqual(catalog.render_catalog(doc), catalog.render_catalog(shuffled))

    def test_duplicate_id_and_malformed_date_fail_closed(self):
        doc = catalog.load_catalog()
        modified = copy.deepcopy(doc)
        modified["tests"].append(dict(modified["tests"][0]))
        with self.assertRaisesRegex(ValueError, "CATALOG_DUPLICATE"):
            catalog.validate_catalog(modified)
        modified = copy.deepcopy(doc)
        modified["tests"][0]["introduced"] = "2026-19-77"
        with self.assertRaisesRegex(ValueError, "CATALOG_DATE"):
            catalog.validate_catalog(modified)

    def test_cannot_promote_an_unverified_test_to_measured_rank(self):
        doc = catalog.load_catalog()
        modified = copy.deepcopy(doc)
        modified["tests"][0]["fps"] = 9999
        with self.assertRaisesRegex(ValueError, "CATALOG_FIELDS"):
            catalog.validate_catalog(modified)
        modified = copy.deepcopy(doc)
        modified["tests"][0]["status"] = "success"
        with self.assertRaisesRegex(ValueError, "CATALOG_STATUS"):
            catalog.validate_catalog(modified)

    def test_leaderboard_snapshot_matches_generator_and_readme_points_to_it(self):
        board = spherepop_rankings.assemble(
            __import__("json").loads(spherepop_rankings.WAVE.read_text()),
            __import__("json").loads(spherepop_rankings.WINDOW.read_text()))
        rendered = spherepop_rankings.render(board)
        self.assertEqual((catalog.ROOT / "docs/CPU_WAVE_RANGLISTEN.md").read_text(),
                         rendered)
        readme = (catalog.ROOT / "README.md").read_text()
        self.assertIn("Visual Asset Lab", readme)
        self.assertIn("Neue Testreihen zuerst", readme)


if __name__ == "__main__":
    unittest.main()
