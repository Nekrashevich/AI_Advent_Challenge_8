import os
import unittest
from unittest.mock import patch

from agent.server import worldcup


class WorldcupSourceTests(unittest.TestCase):
    def setUp(self):
        self.provider_override = worldcup._PROVIDER_OVERRIDE

    def tearDown(self):
        worldcup._PROVIDER_OVERRIDE = self.provider_override

    def test_default_provider_is_api(self):
        worldcup._PROVIDER_OVERRIDE = None
        with patch.dict(os.environ, {"WORLDCUP_PROVIDER": "mock"}, clear=True):
            self.assertEqual(worldcup._provider(), "football_data")

    def test_wc_data_source_switches_between_api_and_mock(self):
        with patch.dict(os.environ, {}, clear=True):
            api = worldcup.wc_data_source("api")
            mock = worldcup.wc_data_source("mock")

        self.assertEqual(api["provider"], "football_data")
        self.assertEqual(api["command_mode"], "api")
        self.assertEqual(mock["provider"], "mock")
        self.assertEqual(mock["command_mode"], "mock")

    def test_wc_data_source_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            worldcup.wc_data_source("csv")

    def test_auth_headers_reject_non_ascii_placeholder(self):
        with patch.dict(os.environ, {"FOOTBALL_API_KEY": "твой_ключ"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "FOOTBALL_API_KEY"):
                worldcup._auth_headers()

    def test_auth_headers_accept_football_api_key(self):
        with patch.dict(os.environ, {"FOOTBALL_API_KEY": "abc123"}, clear=True):
            headers = worldcup._auth_headers()

        self.assertEqual(headers["X-Auth-Token"], "abc123")

    def test_football_match_enriches_venue_from_mock_fixture(self):
        row = {
            "id": 101,
            "utcDate": "2026-07-03T18:00:00Z",
            "homeTeam": {"name": "Argentina"},
            "awayTeam": {"name": "Cape Verde"},
            "stage": "LAST_32",
            "score": {"fullTime": {"home": None, "away": None}},
        }

        match = worldcup._football_match(row)

        self.assertEqual(match["city"], "Miami Gardens")
        self.assertEqual(match["stadium"], "Hard Rock Stadium")

    def test_mock_has_complete_round_of_32_schedule(self):
        matches = [match for match in worldcup._data()["matches"] if match["stage"] == "Round of 32"]

        self.assertEqual(len(matches), 16)

        argentina = next(match for match in matches if match["home"] == "Argentina")
        self.assertEqual(argentina["away"], "Cape Verde")
        self.assertEqual(argentina["kickoff"], "2026-07-03T18:00:00")
        self.assertEqual(argentina["city"], "Miami Gardens")
        self.assertEqual(argentina["stadium"], "Hard Rock Stadium")

        colombia = next(match for match in matches if match["home"] == "Colombia")
        self.assertEqual(colombia["away"], "Ghana")
        self.assertEqual(colombia["kickoff"], "2026-07-03T20:30:00")
        self.assertEqual(colombia["city"], "Kansas City")
        self.assertEqual(colombia["stadium"], "Arrowhead Stadium")


if __name__ == "__main__":
    unittest.main()
