import sys
import types
import unittest


playwright = types.ModuleType("playwright")
async_api = types.ModuleType("playwright.async_api")
async_api.TimeoutError = TimeoutError
async_api.async_playwright = lambda: None
playwright.async_api = async_api
sys.modules.setdefault("playwright", playwright)
sys.modules.setdefault("playwright.async_api", async_api)

import hilton_award_finder as finder


class SearchConfigTests(unittest.TestCase):
    def test_expected_hotels_are_configured(self) -> None:
        self.assertTrue(finder.SEARCHES)
        self.assertEqual(
            {search["hotel"] for search in finder.SEARCHES},
            {"SJOTTLX", "PPTBNCI"},
        )
        self.assertTrue(
            all(search["alert_group"] is None for search in finder.SEARCHES)
        )

    def test_sjottlx_covers_every_one_to_five_night_segment(self) -> None:
        searches = [
            search for search in finder.SEARCHES if search["hotel"] == "SJOTTLX"
        ]
        segments = {
            (arrival, search["nights"])
            for search in searches
            for arrival in search["target_dates"]
        }

        self.assertEqual(len(segments), 15)
        self.assertEqual({nights for _, nights in segments}, {1, 2, 3, 4, 5})
        self.assertIn(("2026-12-28", 5), segments)
        self.assertIn(("2027-01-01", 1), segments)

    def test_pptbnci_has_one_consolidated_five_night_search(self) -> None:
        searches = [
            search for search in finder.SEARCHES if search["hotel"] == "PPTBNCI"
        ]

        self.assertEqual(len(searches), 1)
        self.assertEqual(searches[0]["arrival"], "2027-07-03")
        self.assertEqual(
            searches[0]["target_dates"],
            ["2027-07-03", "2027-07-04", "2027-07-05"],
        )
        self.assertEqual(searches[0]["nights"], 5)
        self.assertEqual(searches[0]["adults"], 1)
        self.assertIsNone(searches[0]["alert_group"])


if __name__ == "__main__":
    unittest.main()
