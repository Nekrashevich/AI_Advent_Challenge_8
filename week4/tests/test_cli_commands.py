import io
import os
import unittest
from unittest.mock import patch

from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import to_plain_text
from rich.console import Console

import agent.cli as cli


class FakeAgent:
    def __init__(self):
        self.calls = []

    def servers(self):
        return [
            {"name": "wiki", "transport": "stdio", "title": "Википедия — поиск и статьи", "ok": True, "tools": 2, "error": ""},
            {"name": "pipeline", "transport": "stdio", "title": "Обработка — суммаризация и сохранение", "ok": True, "tools": 2, "error": ""},
            {"name": "scheduler", "transport": "stdio", "title": "Планировщик — напоминания 24/7", "ok": True, "tools": 3, "error": ""},
            {"name": "weather", "transport": "stdio", "title": "Погода — Open-Meteo прогноз", "ok": True, "tools": 3, "error": ""},
            {"name": "worldcup", "transport": "stdio", "title": "ЧМ-2026 — матчи, таблицы и сетка", "ok": True, "tools": 6, "error": ""},
        ]

    def list_tools(self):
        names = [
            ("wiki", "wiki_search"), ("wiki", "wiki_fetch"),
            ("pipeline", "summarize"), ("pipeline", "save_to_file"),
            ("scheduler", "remind_add"), ("scheduler", "reminders_list"), ("scheduler", "summary_run"),
            ("weather", "weather_geocode"), ("weather", "weather_forecast"), ("weather", "weather_brief"),
            ("worldcup", "wc_matches"), ("worldcup", "wc_match_detail"), ("worldcup", "wc_team_next_match"),
            ("worldcup", "wc_group_table"), ("worldcup", "wc_bracket"), ("worldcup", "wc_data_source"),
        ]
        return [{"server": s, "name": n, "qualified": f"{s}__{n}", "description": n} for s, n in names]

    def ask(self, goal):
        self.calls.append(("ask", goal))
        return [
            {"server": "worldcup", "tool": "wc_team_next_match", "arguments": {"team": "Argentina"}},
            {"server": "weather", "tool": "weather_brief", "arguments": {"city": "Miami"}},
            {"server": "pipeline", "tool": "save_to_file", "arguments": {"name": "argentina_match"}},
            {"server": "scheduler", "tool": "remind_add", "arguments": {"run_at": "+30"}},
        ], "Готово: превью сохранено, напоминание поставлено."

    def call_tool(self, server, name, arguments):
        self.calls.append((server, name, arguments))
        if server == "worldcup" and name == "wc_matches":
            return {"date": arguments.get("date", "today"), "matches": [
                {"id": 101, "home": "Argentina", "away": "Mexico", "kickoff": "2026-06-28T18:00:00", "stage": "Round of 32", "city": "Mexico City"}
            ]}
        if server == "worldcup" and name == "wc_team_next_match":
            return {"match": {"id": "demo-101", "home": "Argentina", "away": "Mexico", "kickoff": "2026-06-28T18:00:00", "stage": "Round of 32", "city": "Mexico City"}}
        if server == "worldcup" and name == "wc_data_source":
            if arguments.get("mode") == "api":
                return {"provider": "football_data", "mode": "real_api", "command_mode": "api", "source": "football-data.org API", "api_url": "https://api.football-data.org/v4", "token_configured": False, "note": "Будут использоваться реальные данные API; нужен FOOTBALL_DATA_TOKEN."}
            return {"provider": "mock", "mode": "mock", "command_mode": "mock", "source": "local JSON fixture", "data_file": "/tmp/worldcup_data.json", "demo_today": "2026-06-28", "token_configured": False, "note": "Используются замоканные данные из worldcup_data.json."}
        if server == "worldcup" and name == "wc_group_table":
            return {"group": "A", "table": [{"position": 1, "team": "Argentina", "played": 3, "points": 6, "goals_for": 6, "goals_against": 3}]}
        if server == "weather" and name == "weather_brief":
            return {"location": {"name": arguments.get("city", "Москва"), "country": "Russia"}, "timezone": "Europe/Moscow", "daily": [
                {"date": "2026-06-28", "temp_min": 18, "temp_max": 24, "summary": "облачно", "precipitation_probability": 20}
            ]}
        if server == "wiki" and name == "wiki_search":
            return {"results": [{"title": "Чемпионат мира по футболу 2026", "snippet": "Argentina — Mexico 2026-06-28T18:00:00", "url": "https://ru.wikipedia.org/wiki/..."}]}
        if server == "wiki" and name == "wiki_fetch":
            return {"title": arguments["title"], "extract": "Argentina — Mexico 2026-06-28T18:00:00"}
        if server == "scheduler" and name == "remind_add":
            return {"id": 42, "text": arguments["text"], "run_at": arguments["run_at"], "fired": 0}
        return {}

    def run_matchday_wiki_report(self, target):
        self.calls.append(("run_matchday_wiki_report", target))
        return [
            ("worldcup", "wc_matches", "найдено матчей: 1"),
            ("worldcup", "wc_match_detail", "Argentina — Mexico · Round of 32"),
            ("wiki", "wiki_search_context", "найдено статей: 1"),
            ("wiki", "wiki_fetch_context", "статья «Чемпионат мира по футболу 2026», символов: 1000"),
            ("pipeline", "summarize", "превью символов: 150"),
            ("pipeline", "save_to_file", "/tmp/store/worldcup_wiki_today.md"),
        ], {"title": f"Matchday Wiki · {target}", "summary": "- Контекст найден в Википедии.", "path": "/tmp/store/worldcup_wiki_today.md"}

    def run_matchday_full_report(self, target):
        self.calls.append(("run_matchday_full_report", target))
        return [
            ("worldcup", "wc_matches", "найдено матчей: 1"),
            ("worldcup", "wc_match_detail", "Argentina — Mexico · Round of 32"),
            ("wiki", "wiki_search_city", "найдено статей: 1"),
            ("wiki", "wiki_fetch_city", "статья «Чемпионат мира по футболу 2026», символов: 1000"),
            ("weather", "weather_geocode", "город из wiki: Мехико"),
            ("weather", "weather_forecast", "прогноз на день матча получен"),
            ("pipeline", "summarize", "превью символов: 180"),
            ("pipeline", "save_to_file", "/tmp/store/worldcup_full_today.md"),
        ], {"title": f"Matchday Full · {target}", "summary": "- Полный отчет готов.", "path": "/tmp/store/worldcup_full_today.md"}


class CliWeek4WfTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.console = Console(file=self.output, force_terminal=False, color_system=None, width=140, legacy_windows=False)
        self.console_patch = patch.object(cli, "console", self.console)
        self.env_patch = patch.dict(os.environ, {"WORLDCUP_PROVIDER": "mock"})
        self.console_patch.start()
        self.env_patch.start()
        self.addCleanup(self.console_patch.stop)
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(setattr, cli, "agent", cli.agent)
        cli.agent = FakeAgent()

    def text(self):
        return self.output.getvalue()

    def test_mcp_commands_and_toolbar_counts(self):
        cli.dispatch("/mcp-servers")
        cli.dispatch("/mcp-tools")
        toolbar = to_plain_text(cli._bottom_toolbar())
        output = self.text()
        self.assertIn("MCP-agent", toolbar)
        self.assertIn("5/5 online", toolbar)
        self.assertIn("16 capabilities", toolbar)
        self.assertIn("worldcup: mock", toolbar)
        self.assertIn("MCP BOARD", output)
        self.assertIn("MCP CAPABILITY REGISTRY", output)
        self.assertNotIn("stdio", output)
        self.assertNotIn("http", output)
        self.assertIn("weather", output)
        self.assertIn("worldcup", output)
        self.assertIn("16 callable capabilities", output)

    def test_matchday_demo_and_report(self):
        cli.dispatch("/demo day16")
        cli.dispatch("/weather Москва")
        cli.dispatch("/wc today")
        cli.dispatch("/wc-source")
        cli.dispatch("/wc-remind Argentina")
        output = self.text()
        self.assertIn("MCP BOARD", output)
        self.assertIn("MCP CAPABILITY REGISTRY", output)
        self.assertIn("wc_matches", output)
        self.assertIn("WORLDCUP DATA SOURCE", output)
        self.assertIn("mock", output)
        self.assertIn("weather_brief", output)
        self.assertIn("MATCH REMINDER", output)

    def test_demo_day_commands(self):
        cli.dispatch("/demo day17")
        cli.dispatch("/demo day18")
        cli.dispatch("/demo day19")
        cli.dispatch("/demo day20")

        self.assertIn(("worldcup", "wc_matches", {"date": "today"}), cli.agent.calls)
        self.assertIn(("worldcup", "wc_team_next_match", {"team": "Argentina"}), cli.agent.calls)
        self.assertIn(("run_matchday_full_report", "today"), cli.agent.calls)
        self.assertIn(("ask", "найди ближайший матч Аргентины на ЧМ-2026, проверь погоду в городе матча, сохрани превью и поставь напоминание"), cli.agent.calls)
        output = self.text()
        self.assertIn("день 17: выполнить /wc today", output)
        self.assertIn("MATCH REMINDER", output)
        self.assertIn("Matchday Full · today", output)
        self.assertIn("AGENT TRACE", output)

    def test_dispatch_accepts_colon_before_command(self):
        cli.dispatch(": /wc today")

        self.assertIn(("worldcup", "wc_matches", {"date": "today"}), cli.agent.calls)
        self.assertNotIn("unknown command", self.text())

    def test_tab_completion_returns_single_replacement(self):
        completions = list(cli.CommandCompleter().get_completions(Document("/mcp-"), None))
        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0].text, "/mcp-servers")
        self.assertEqual(completions[0].start_position, -5)

        demo_completions = list(cli.CommandCompleter().get_completions(Document("/demo d"), None))
        self.assertEqual(len(demo_completions), 1)
        self.assertEqual(demo_completions[0].text, "/demo day")

    def test_matchday_wiki_report_command(self):
        cli.dispatch("/matchday-report-wiki today")

        self.assertIn(("run_matchday_wiki_report", "today"), cli.agent.calls)
        output = self.text()
        self.assertIn("RUN /matchday-report-wiki", output)
        self.assertIn("wiki_search_context", output)
        self.assertIn("Matchday Wiki · today", output)

    def test_matchday_full_report_command(self):
        cli.dispatch("/matchday-report-full today")

        self.assertIn(("run_matchday_full_report", "today"), cli.agent.calls)
        output = self.text()
        self.assertIn("RUN /matchday-report-full", output)
        self.assertIn("wiki_search_city", output)
        self.assertIn("weather_geocode", output)
        self.assertIn("Matchday Full · today", output)

    def test_wc_remind_accepts_utc_date_without_kickoff(self):
        original_call_tool = cli.agent.call_tool

        def call_tool(server, name, arguments):
            if server == "worldcup" and name == "wc_team_next_match":
                cli.agent.calls.append((server, name, arguments))
                return {"match": {"id": 101, "home": "Argentina", "away": "Mexico", "utcDate": "2026-06-28T18:00:00Z"}}
            return original_call_tool(server, name, arguments)

        cli.agent.call_tool = call_tool
        cli.dispatch("/wc-remind Argentina")

        self.assertIn(("scheduler", "remind_add", {"text": "Argentina — Mexico начнётся через 30 минут", "run_at": "2026-06-28T17:30:00"}), cli.agent.calls)
        output = self.text()
        self.assertIn("MATCH REMINDER", output)
        self.assertIn("2026-06-28T18:00:00", output)

    def test_wc_remind_falls_back_to_wiki_for_kickoff(self):
        original_call_tool = cli.agent.call_tool

        def call_tool(server, name, arguments):
            if server == "worldcup" and name == "wc_team_next_match":
                cli.agent.calls.append((server, name, arguments))
                return {"match": {"id": 101, "home": "Argentina", "away": "Mexico"}}
            return original_call_tool(server, name, arguments)

        cli.agent.call_tool = call_tool
        cli.dispatch("/wc-remind Argentina")

        self.assertIn(("wiki", "wiki_search", {"query": "Чемпионат мира по футболу 2026 Argentina Mexico время матча дата", "limit": 5}), cli.agent.calls)
        self.assertIn(("scheduler", "remind_add", {"text": "Argentina — Mexico начнётся через 30 минут", "run_at": "2026-06-28T17:30:00"}), cli.agent.calls)
        output = self.text()
        self.assertIn("wiki_search", output)
        self.assertIn("MATCH REMINDER", output)

    def test_wc_source_selects_api_or_mock(self):
        cli.dispatch("/wc-source api")
        cli.dispatch("/wc-source Football-Data-Api")
        cli.dispatch("/wc-source mock")

        self.assertIn(("worldcup", "wc_data_source", {"mode": "api"}), cli.agent.calls)
        self.assertIn(("worldcup", "wc_data_source", {"mode": "mock"}), cli.agent.calls)
        output = self.text()
        self.assertIn("Football-Data-Api", output)
        self.assertNotIn("football_data", output)
        self.assertIn("mock", output)

    def test_wc_date_falls_back_to_wiki_then_mock(self):
        original_provider = cli.worldcup_provider_state
        self.addCleanup(setattr, cli, "worldcup_provider_state", original_provider)
        cli.worldcup_provider_state = "api"
        provider = {"mode": "api"}

        def call_tool(server, name, arguments):
            cli.agent.calls.append((server, name, arguments))
            if server == "worldcup" and name == "wc_data_source":
                provider["mode"] = arguments.get("mode", provider["mode"])
                return {"provider": "mock" if provider["mode"] == "mock" else "football_data"}
            if server == "worldcup" and name == "wc_matches":
                if provider["mode"] != "mock":
                    return {"provider": "football_data", "date": arguments.get("date"), "matches": []}
                return {"provider": "mock", "date": arguments.get("date"), "matches": [
                    {"id": "match-87", "home": "Colombia", "away": "Ghana", "kickoff": "2026-07-03T20:30:00", "stage": "Round of 32", "city": "Kansas City"}
                ]}
            if server == "wiki" and name == "wiki_search":
                return {"results": [{"title": "2026 FIFA World Cup round of 32", "snippet": "Colombia — Ghana", "url": "https://en.wikipedia.org/wiki/..."}]}
            if server == "wiki" and name == "wiki_fetch":
                return {"title": arguments["title"], "extract": "Colombia — Ghana"}
            return {}

        cli.agent.call_tool = call_tool
        cli.dispatch("/wc 2026-07-03")

        self.assertIn(("wiki", "wiki_search", {"query": "2026 FIFA World Cup round of 32 2026-07-03  ", "limit": 5}), cli.agent.calls)
        self.assertIn(("worldcup", "wc_data_source", {"mode": "mock"}), cli.agent.calls)
        self.assertIn(("worldcup", "wc_data_source", {"mode": "api"}), cli.agent.calls)
        output = self.text()
        self.assertIn("Colombia", output)
        self.assertIn("fallback=worldcup -> wiki -> mock", output)


if __name__ == "__main__":
    unittest.main()
