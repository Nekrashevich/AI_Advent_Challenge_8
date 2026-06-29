import unittest

from agent.mcp_agent import McpAgent


class StringReturningAgent(McpAgent):
    def __init__(self, city="Worldcup City", wiki_extract="Матч пройдет в Мехико на стадионе Ацтека."):
        self.calls = []
        self.city = city
        self.wiki_extract = wiki_extract

    def call_tool(self, server, name, arguments):
        self.calls.append((server, name, arguments))
        if server == "worldcup" and name == "wc_matches":
            return str({
                "matches": [{
                    "id": 101,
                    "home": "Argentina",
                    "away": "Mexico",
                    "kickoff": "2026-06-28T18:00:00",
                    "stage": "Round of 32",
                    "city": self.city,
                    "stadium": "Estadio Azteca" if self.city else "",
                }]
            })
        if server == "worldcup" and name == "wc_match_detail":
            if not isinstance(arguments["match_id"], str):
                raise AssertionError("match_id must be passed as str")
            return str({
                "match": {
                    "id": 101,
                    "home": "Argentina",
                    "away": "Mexico",
                    "kickoff": "2026-06-28T18:00:00",
                    "stage": "Round of 32",
                    "city": self.city,
                    "stadium": "Estadio Azteca" if self.city else "",
                }
            })
        if server == "weather" and name == "weather_geocode":
            return str({"name": "Mexico City", "latitude": 19.4326, "longitude": -99.1332})
        if server == "weather" and name == "weather_forecast":
            return str({"daily": [{"summary": "ясно", "temp_min": 20, "temp_max": 28}]})
        if server == "wiki" and name == "wiki_search":
            return str({"results": [{"title": "Чемпионат мира по футболу 2026", "snippet": "турнир", "url": "https://ru.wikipedia.org/wiki/..."}]})
        if server == "wiki" and name == "wiki_fetch":
            return str({"title": arguments["title"], "extract": self.wiki_extract})
        if server == "pipeline" and name == "summarize":
            return str({"summary": "- Argentina сыграет с Mexico. Контекст найден в Википедии."})
        if server == "pipeline" and name == "save_to_file":
            name = arguments.get("name", "")
            if "full" in name:
                suffix = "worldcup_full_today.md"
            elif "wiki" in name:
                suffix = "worldcup_wiki_today.md"
            else:
                suffix = "worldcup_today.md"
            return str({"path": f"/tmp/store/{suffix}"})
        return {}


class FallbackAgent(StringReturningAgent):
    def __init__(self):
        super().__init__()
        self.provider = "api"

    def call_tool(self, server, name, arguments):
        self.calls.append((server, name, arguments))
        if server == "worldcup" and name == "wc_data_source":
            self.provider = arguments.get("mode", self.provider)
            return {"provider": "mock" if self.provider == "mock" else "football_data"}
        if server == "worldcup" and name == "wc_matches":
            if self.provider != "mock":
                return {"provider": "football_data", "matches": []}
            return {
                "provider": "mock",
                "matches": [{
                    "id": "match-86",
                    "home": "Argentina",
                    "away": "Cape Verde",
                    "kickoff": "2026-07-03T18:00:00",
                    "stage": "Round of 32",
                    "city": "Miami Gardens",
                    "stadium": "Hard Rock Stadium",
                }],
            }
        if server == "worldcup" and name == "wc_match_detail":
            return {
                "provider": "mock",
                "match": {
                    "id": "match-86",
                    "home": "Argentina",
                    "away": "Cape Verde",
                    "kickoff": "2026-07-03T18:00:00",
                    "stage": "Round of 32",
                    "city": "Miami Gardens",
                    "stadium": "Hard Rock Stadium",
                },
            }
        return super().call_tool(server, name, arguments)


class McpAgentFlowTests(unittest.TestCase):
    def test_matchday_wiki_report_uses_wikipedia_context(self):
        agent = StringReturningAgent()

        stages, result = agent.run_matchday_wiki_report("today")

        self.assertEqual(len(stages), 6)
        self.assertEqual(stages[2], ("wiki", "wiki_search_context", "найдено статей: 1"))
        self.assertIn(("wiki", "wiki_fetch", {"title": "Чемпионат мира по футболу 2026"}), agent.calls)
        self.assertEqual(result["title"], "Matchday Wiki · today")
        self.assertEqual(result["path"], "/tmp/store/worldcup_wiki_today.md")

    def test_matchday_full_report_uses_wiki_city_for_weather(self):
        agent = StringReturningAgent()

        stages, result = agent.run_matchday_full_report("today")

        self.assertEqual(len(stages), 8)
        self.assertEqual(stages[2], ("wiki", "wiki_search_city", "найдено статей: 1"))
        self.assertEqual(stages[4], ("weather", "weather_geocode", "город из wiki: Mexico City"))
        self.assertIn(("weather", "weather_geocode", {"city": "Мехико"}), agent.calls)
        self.assertNotIn(("weather", "weather_geocode", {"city": "Worldcup City"}), agent.calls)
        self.assertEqual(result["title"], "Matchday Full · today")
        self.assertEqual(result["path"], "/tmp/store/worldcup_full_today.md")

    def test_matchday_full_report_falls_back_to_wiki_then_mock(self):
        agent = FallbackAgent()

        stages, result = agent.run_matchday_full_report("2026-07-03")

        self.assertIn(("worldcup", "wc_matches", "найдено матчей: 0"), stages)
        self.assertIn(("wiki", "wiki_search_matches", "fallback: найдено статей: 1"), stages)
        self.assertIn(("worldcup", "wc_matches_mock", "fallback mock: найдено матчей: 1"), stages)
        self.assertIn(("worldcup", "wc_data_source", {"mode": "mock"}), agent.calls)
        self.assertIn(("worldcup", "wc_data_source", {"mode": "api"}), agent.calls)
        self.assertEqual(result["path"], "/tmp/store/worldcup_full_today.md")


if __name__ == "__main__":
    unittest.main()
