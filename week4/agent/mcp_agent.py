import ast
import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack

import requests
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
MAIN_MODEL = os.environ.get("PROXY_API_MODEL") or os.environ.get("PROXYAPI_MODEL") or "gpt-4o-mini"
NAMESPACE_SEP = "__"
CONNECT_TIMEOUT = 25
MCP_TOOL_TIMEOUT_SECONDS = 30
ASK_MAX_STEPS = 50
SCRIPTED_FLOW_MAX_CALLS = 50
WIKI_CITY_ALIASES = [
    ("Мехико", ["мехико", "mexico city", "estadio azteca", "стадион ацтека", "ацтека"]),
    ("Гвадалахара", ["гвадалахара", "guadalajara", "estadio akron", "стадион акрон"]),
    ("Монтеррей", ["монтеррей", "monterrey", "estadio bbva", "bbva"]),
    ("Торонто", ["торонто", "toronto", "bmo field", "би-мо филд"]),
    ("Ванкувер", ["ванкувер", "vancouver", "bc place", "би-си плейс"]),
    ("Атланта", ["атланта", "atlanta", "mercedes-benz stadium", "мерседес-бенц"]),
    ("Бостон", ["бостон", "boston", "foxborough", "gillette stadium", "джиллетт"]),
    ("Даллас", ["даллас", "dallas", "arlington", "at&t stadium"]),
    ("Хьюстон", ["хьюстон", "houston", "nrg stadium"]),
    ("Канзас-Сити", ["канзас-сити", "kansas city", "arrowhead"]),
    ("Лос-Анджелес", ["лос-анджелес", "los angeles", "sofi stadium"]),
    ("Майами", ["майами", "miami", "hard rock stadium"]),
    ("Нью-Йорк", ["нью-йорк", "new york", "new jersey", "metlife stadium", "метлайф"]),
    ("Филадельфия", ["филадельфия", "philadelphia", "lincoln financial field"]),
    ("Сан-Франциско", ["сан-франциско", "san francisco", "santa clara", "levi's stadium"]),
    ("Сиэтл", ["сиэтл", "seattle", "lumen field"]),
]

SERVERS = [
    {"name": "wiki", "transport": "stdio", "module": "agent.server.wiki_app",
     "title": "Википедия — поиск и статьи"},
    {"name": "pipeline", "transport": "stdio", "module": "agent.server.pipeline_app",
     "title": "Обработка — суммаризация и сохранение"},
    {"name": "scheduler", "transport": "stdio", "module": "agent.server.scheduler_app",
     "title": "Планировщик — напоминания 24/7"},
    {"name": "weather", "transport": "stdio", "module": "agent.server.weather_app",
     "title": "Погода — Open-Meteo прогноз"},
    {"name": "worldcup", "transport": "stdio", "module": "agent.server.worldcup_app",
     "title": "ЧМ-2026 — матчи, таблицы и сетка"},
]

ASK_SYSTEM = (
    "Ты — агент-оркестратор с инструментами от НЕСКОЛЬКИХ MCP-серверов: "
    "wiki (поиск и статьи Википедии), pipeline (суммаризация и сохранение в файл), scheduler (напоминания), weather (геокодинг и прогноз Open-Meteo), worldcup (матчи, таблицы и сетка ЧМ-2026). "
    "Имя инструмента имеет вид server__tool. Выполни цель пользователя: выбирай нужные "
    "инструменты с разных серверов, вызывай их по порядку и передавай данные от одного "
    "к другому. Когда цель достигнута — дай краткий итог на русском."
)


def _stdio_params(module):
    return StdioServerParameters(command=sys.executable, args=["-m", module], env=dict(os.environ))


def _proxy_api_key():
    api_key = os.environ.get("PROXY_API_KEY") or os.environ.get("PROXYAPI_KEY")
    if not api_key:
        raise RuntimeError("Укажи PROXY_API_KEY или PROXYAPI_KEY для LLM-команд")
    return api_key


def _raise_for_status(response):
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        body = response.text.strip()
        detail = f": {body[:1000]}" if body else ""
        raise RuntimeError(f"{error}{detail}") from error


class McpAgent:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._sessions = {}
        self._tools = []
        self._servers = []
        self._ready = threading.Event()
        self._stop = None

    def connect(self, timeout=90):
        asyncio.run_coroutine_threadsafe(self._serve(), self._loop)
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError("MCP-серверы не ответили за отведённое время")

    async def _open(self, stack, spec):
        read_stream, write_stream = await stack.enter_async_context(
            stdio_client(_stdio_params(spec["module"]))
        )
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        result = await session.list_tools()
        return session, result.tools

    async def _serve(self):
        self._stop = asyncio.Event()
        async with AsyncExitStack() as stack:
            for spec in SERVERS:
                status = {
                    "name": spec["name"],
                    "transport": spec["transport"],
                    "title": spec["title"],
                    "ok": False,
                    "tools": 0,
                    "error": "",
                }
                try:
                    session, tools = await asyncio.wait_for(
                        self._open(stack, spec), timeout=CONNECT_TIMEOUT
                    )
                    self._sessions[spec["name"]] = session
                    for tool in tools:
                        self._tools.append({
                            "server": spec["name"],
                            "name": tool.name,
                            "qualified": spec["name"] + NAMESPACE_SEP + tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
                        })
                    status["ok"] = True
                    status["tools"] = len(tools)
                except Exception as error:
                    status["error"] = f"{type(error).__name__}: {error}"
                self._servers.append(status)
            self._ready.set()
            await self._stop.wait()

    def list_tools(self):
        return self._tools

    def servers(self):
        return self._servers

    def _coerce_value(self, value):
        if isinstance(value, str):
            text = value.strip()
            for loader in (json.loads, ast.literal_eval):
                try:
                    parsed = loader(text)
                except (json.JSONDecodeError, SyntaxError, ValueError):
                    continue
                return self._coerce_value(parsed)
            return value
        if isinstance(value, dict):
            if set(value) == {"result"}:
                return self._coerce_value(value["result"])
            return {key: self._coerce_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._coerce_value(item) for item in value]
        return value

    def _as_dict(self, value, context):
        value = self._coerce_value(value)
        if isinstance(value, dict):
            return value
        preview = repr(value)
        if len(preview) > 200:
            preview = preview[:197] + "..."
        raise RuntimeError(f"{context}: ожидался dict, получен {type(value).__name__}: {preview}")

    def _extract(self, result):
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return self._coerce_value(structured)
        for block in result.content:
            text = getattr(block, "text", None)
            if text is not None:
                return self._coerce_value(text)
        return None

    def call_tool(self, server, name, arguments):
        session = self._sessions.get(server)
        if session is None:
            raise RuntimeError(f"Сервер '{server}' не подключён")
        print(f"MCP tool call: {server}.{name}", file=sys.stderr, flush=True)
        future = asyncio.run_coroutine_threadsafe(
            session.call_tool(name, arguments), self._loop
        )
        return self._extract(future.result(timeout=MCP_TOOL_TIMEOUT_SECONDS))

    def _budgeted_call(self, max_calls):
        counter = {"calls": 0}

        def call(server, name, arguments):
            counter["calls"] += 1
            if counter["calls"] > max_calls:
                raise RuntimeError(f"Достигнут лимит MCP-вызовов: {max_calls}")
            return self.call_tool(server, name, arguments)

        return call

    def _match_wiki_query(self, match):
        parts = [
            "Чемпионат мира по футболу 2026",
            str(match.get("home") or ""),
            str(match.get("away") or ""),
            str(match.get("kickoff") or "")[:10],
            "стадион город матч",
        ]
        return " ".join(part for part in parts if part.strip())

    def _city_from_wiki_text(self, text):
        lowered = text.lower()
        for city, aliases in WIKI_CITY_ALIASES:
            if any(alias in lowered for alias in aliases):
                return city
        return ""

    def _wiki_match_context(self, call, match, stages, purpose="context"):
        query = self._match_wiki_query(match)
        search = self._as_dict(call("wiki", "wiki_search", {"query": query, "limit": 5}), "wiki.wiki_search")
        results = search.get("results", [])
        stages.append(("wiki", f"wiki_search_{purpose}", f"найдено статей: {len(results)}"))

        article_title = ""
        extract = ""
        snippet_text = " ".join(
            f"{row.get('title', '')} {row.get('snippet', '')}" for row in results
        )
        if results:
            article_title = results[0]["title"]
            fetched = self._as_dict(call("wiki", "wiki_fetch", {"title": article_title}), "wiki.wiki_fetch")
            extract = fetched.get("extract", "")
            stages.append(("wiki", f"wiki_fetch_{purpose}", f"статья «{article_title}», символов: {len(extract)}"))
        else:
            stages.append(("wiki", f"wiki_fetch_{purpose}", "пропущено: статей не найдено"))

        city = self._city_from_wiki_text(f"{snippet_text}\n{extract}")
        return {"query": query, "results": results, "title": article_title, "extract": extract, "city": city}

    def _wiki_match_probe(self, call, stages, query, purpose="matches"):
        try:
            search = self._as_dict(call("wiki", "wiki_search", {"query": query, "limit": 5}), "wiki.wiki_search")
            results = search.get("results", [])
            stages.append(("wiki", f"wiki_search_{purpose}", f"fallback: найдено статей: {len(results)}"))
            if results:
                title = results[0].get("title")
                fetched = self._as_dict(call("wiki", "wiki_fetch", {"title": title}), "wiki.wiki_fetch")
                extract = fetched.get("extract", "")
                stages.append(("wiki", f"wiki_fetch_{purpose}", f"fallback: статья «{title}», символов: {len(extract)}"))
            else:
                stages.append(("wiki", f"wiki_fetch_{purpose}", "fallback: статей не найдено"))
        except Exception as error:
            stages.append(("wiki", f"wiki_search_{purpose}", f"fallback failed: {type(error).__name__}"))

    def _worldcup_mock_call(self, call, tool, arguments):
        source = self._as_dict(call("worldcup", "wc_data_source", {}), "worldcup.wc_data_source")
        previous = source.get("command_mode") or ("mock" if source.get("provider") == "mock" else "api")
        switched = previous != "mock"
        if switched:
            call("worldcup", "wc_data_source", {"mode": "mock"})
        try:
            data = self._as_dict(call("worldcup", tool, arguments), f"worldcup.{tool}.mock")
            data["fallback_chain"] = "worldcup -> wiki -> mock"
            return data
        finally:
            if switched:
                call("worldcup", "wc_data_source", {"mode": previous})

    def _mock_detail_or_current(self, call, match):
        match_id = str(match.get("id", ""))
        try:
            return self._worldcup_mock_call(call, "wc_match_detail", {"match_id": match_id})
        except Exception:
            date = str(match.get("date") or match.get("kickoff") or "")[:10]
            matches_data = self._worldcup_mock_call(call, "wc_matches", {"date": date or "today"})
            wanted = {str(match.get("home", "")).lower(), str(match.get("away", "")).lower()}
            for candidate in matches_data.get("matches", []):
                candidate_teams = {str(candidate.get("home", "")).lower(), str(candidate.get("away", "")).lower()}
                if candidate_teams == wanted or str(candidate.get("id")) == match_id:
                    return {"provider": "mock", "match": candidate, "fallback_chain": "worldcup -> wiki -> mock"}
        return {"provider": "worldcup", "match": match}

    def _worldcup_matches_with_fallback(self, call, stages, date_arg):
        arguments = {"date": date_arg}
        reason = ""
        try:
            matches_data = self._as_dict(call("worldcup", "wc_matches", arguments), "worldcup.wc_matches")
            matches = matches_data.get("matches", [])
            stages.append(("worldcup", "wc_matches", f"найдено матчей: {len(matches)}"))
            if matches:
                return matches_data, matches
            reason = "0 matches"
        except Exception as error:
            stages.append(("worldcup", "wc_matches", f"ошибка: {type(error).__name__}"))
            reason = f"{type(error).__name__}: {error}"

        self._wiki_match_probe(
            call,
            stages,
            f"2026 FIFA World Cup round of 32 {date_arg} matches",
            "matches",
        )
        mock_data = self._worldcup_mock_call(call, "wc_matches", arguments)
        matches = mock_data.get("matches", [])
        mock_data["fallback_reason"] = reason
        stages.append(("worldcup", "wc_matches_mock", f"fallback mock: найдено матчей: {len(matches)}"))
        return mock_data, matches

    def _worldcup_detail_with_fallback(self, call, stages, match, prefer_mock=False):
        match_id = str(match.get("id", ""))
        fixture = f"{match.get('home')} — {match.get('away')}"
        if not match_id:
            stages.append(("worldcup", "wc_match_detail", f"{fixture} · detail skipped: no id"))
            return match
        if prefer_mock:
            detail = self._mock_detail_or_current(call, match)
            detailed = self._as_dict(detail.get("match", match), "worldcup.wc_match_detail.mock.match")
            stages.append(("worldcup", "wc_match_detail_mock", f"{detailed.get('home')} — {detailed.get('away')} · {detailed.get('stage')}"))
            return detailed
        try:
            detail = self._as_dict(call("worldcup", "wc_match_detail", {"match_id": match_id}), "worldcup.wc_match_detail")
            detailed = self._as_dict(detail.get("match", match), "worldcup.wc_match_detail.match")
            stages.append(("worldcup", "wc_match_detail", f"{detailed.get('home')} — {detailed.get('away')} · {detailed.get('stage')}"))
            return detailed
        except Exception as error:
            stages.append(("worldcup", "wc_match_detail", f"ошибка: {type(error).__name__}"))
            self._wiki_match_probe(call, stages, f"2026 FIFA World Cup round of 32 {fixture}", "detail")
            detail = self._mock_detail_or_current(call, match)
            detailed = self._as_dict(detail.get("match", match), "worldcup.wc_match_detail.mock.match")
            stages.append(("worldcup", "wc_match_detail_mock", f"{detailed.get('home')} — {detailed.get('away')} · {detailed.get('stage')}"))
            return detailed

    def _worldcup_next_match_with_fallback(self, call, stages, team):
        try:
            next_match = self._as_dict(call("worldcup", "wc_team_next_match", {"team": team}), "worldcup.wc_team_next_match")
            match = self._as_dict(next_match.get("match", {}), "worldcup.wc_team_next_match.match")
            stages.append(("worldcup", "wc_team_next_match", f"{match.get('home')} — {match.get('away')}"))
            if match:
                return next_match, match
        except Exception as error:
            stages.append(("worldcup", "wc_team_next_match", f"ошибка: {type(error).__name__}"))

        self._wiki_match_probe(call, stages, f"2026 FIFA World Cup round of 32 {team} next match", "next_match")
        next_match = self._worldcup_mock_call(call, "wc_team_next_match", {"team": team})
        match = self._as_dict(next_match.get("match", {}), "worldcup.wc_team_next_match.mock.match")
        stages.append(("worldcup", "wc_team_next_match_mock", f"{match.get('home')} — {match.get('away')}"))
        return next_match, match

    def run_matchday_full_report(self, target="today", max_calls=SCRIPTED_FLOW_MAX_CALLS):
        stages = []
        call = self._budgeted_call(max_calls)
        date_arg = target if target else "today"
        matches_data, matches = self._worldcup_matches_with_fallback(call, stages, date_arg)
        if not matches:
            return stages, None
        match = self._worldcup_detail_with_fallback(
            call,
            stages,
            matches[0],
            prefer_mock=matches_data.get("provider") == "mock",
        )
        fixture = f"{match.get('home')} — {match.get('away')}"

        wiki = self._wiki_match_context(call, match, stages, "city")
        city = wiki["city"]
        if city:
            geo = self._as_dict(call("weather", "weather_geocode", {"city": city}), "weather.weather_geocode")
            stages.append(("weather", "weather_geocode", f"город из wiki: {geo.get('name')}"))
            forecast = self._as_dict(call(
                "weather",
                "weather_forecast",
                {"latitude": geo["latitude"], "longitude": geo["longitude"], "days": 1},
            ), "weather.weather_forecast")
            daily = forecast.get("daily", [])
            stages.append(("weather", "weather_forecast", "прогноз на день матча получен"))
            weather_line = daily[0] if daily else {}
            weather_text = (
                f"Погода: {weather_line.get('summary')}, температура "
                f"{weather_line.get('temp_min')}..{weather_line.get('temp_max')} C."
            )
        else:
            stages.append(("weather", "weather_geocode", "пропущено: город не найден через wiki"))
            stages.append(("weather", "weather_forecast", "пропущено: нет координат"))
            weather_text = "Погода: город матча не найден через Википедию."

        source = (
            f"Матч ЧМ-2026: {fixture}. "
            f"Стадия: {match.get('stage')}. Начало: {match.get('kickoff')}. "
            f"Город из wiki: {city or 'не найден'}, стадион: {match.get('stadium') or 'не указан'}. "
            f"{weather_text}\n\n"
            f"Википедия ({wiki['title'] or 'нет статьи'}):\n{wiki['extract'][:5000]}"
        )
        summarized = self._as_dict(call("pipeline", "summarize", {"text": source}), "pipeline.summarize")
        summary = summarized.get("summary", "")
        stages.append(("pipeline", "summarize", f"превью символов: {len(summary)}"))
        saved = self._as_dict(call("pipeline", "save_to_file", {"name": f"worldcup_full_{date_arg}", "content": summary}), "pipeline.save_to_file")
        path = saved.get("path", "")
        stages.append(("pipeline", "save_to_file", path))
        return stages, {"title": f"Matchday Full · {date_arg}", "summary": summary, "path": path}

    def run_matchday_wiki_report(self, target="today", max_calls=SCRIPTED_FLOW_MAX_CALLS):
        stages = []
        call = self._budgeted_call(max_calls)
        date_arg = target if target else "today"
        matches_data, matches = self._worldcup_matches_with_fallback(call, stages, date_arg)
        if not matches:
            return stages, None
        match = self._worldcup_detail_with_fallback(
            call,
            stages,
            matches[0],
            prefer_mock=matches_data.get("provider") == "mock",
        )
        fixture = f"{match.get('home')} — {match.get('away')}"

        wiki = self._wiki_match_context(call, match, stages, "context")

        source = (
            f"Матч ЧМ-2026: {fixture}. "
            f"Стадия: {match.get('stage')}. Начало: {match.get('kickoff')}. "
            f"Город из wiki: {wiki['city'] or 'не найден'}, стадион: {match.get('stadium') or 'не указан'}.\n\n"
            f"Википедия ({wiki['title'] or 'нет статьи'}):\n{wiki['extract'][:5000]}"
        )
        summarized = self._as_dict(call("pipeline", "summarize", {"text": source}), "pipeline.summarize")
        summary = summarized.get("summary", "")
        stages.append(("pipeline", "summarize", f"превью символов: {len(summary)}"))
        saved = self._as_dict(call("pipeline", "save_to_file", {"name": f"worldcup_wiki_{date_arg}", "content": summary}), "pipeline.save_to_file")
        path = saved.get("path", "")
        stages.append(("pipeline", "save_to_file", path))
        return stages, {"title": f"Matchday Wiki · {date_arg}", "summary": summary, "path": path}

    def _openai_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["qualified"],
                    "description": f"[сервер {tool['server']}] {tool['description']}",
                    "parameters": tool["input_schema"],
                },
            }
            for tool in self._tools
        ]

    def ask(self, goal, max_steps=ASK_MAX_STEPS):
        api_key = _proxy_api_key()
        headers = {"Authorization": f"Bearer {api_key}"}
        tools = self._openai_tools()
        messages = [
            {"role": "system", "content": ASK_SYSTEM},
            {"role": "user", "content": goal},
        ]
        transcript = []
        for _ in range(max_steps):
            response = requests.post(
                API_URL,
                headers=headers,
                json={"model": MAIN_MODEL, "messages": messages, "tools": tools, "tool_choice": "auto"},
                timeout=120,
            )
            _raise_for_status(response)
            message = response.json()["choices"][0]["message"]
            messages.append(message)
            calls = message.get("tool_calls")
            if not calls:
                return transcript, message.get("content", "")
            for call in calls:
                qualified = call["function"]["name"]
                server, _, name = qualified.partition(NAMESPACE_SEP)
                arguments = json.loads(call["function"]["arguments"] or "{}")
                output = self.call_tool(server, name, arguments)
                transcript.append({"server": server, "tool": name, "arguments": arguments, "output": output})
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(output, ensure_ascii=False),
                })
        return transcript, "(достигнут лимит шагов)"

    def close(self):
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
