import ast
import json
import os
import re
from datetime import datetime, timedelta

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box

from agent.mcp_agent import McpAgent, SCRIPTED_FLOW_MAX_CALLS

SURFACE = "#30363d"
SURFACE_DIM = "#21262d"
ACCENT = "#7ee787"
ACCENT_2 = "#79c0ff"
TEXT = "#d0d7de"
MUTED = "#8b949e"
WARN = "#d29922"
ERROR = "#f85149"
OK = "#3fb950"

# Compatibility names for the older renderers that are still used by a few
# simple commands. They now point to the control-room palette.
NAVY = SURFACE
NAVY_BRIGHT = ACCENT
NAVY_PALE = TEXT
NAVY_DIM = MUTED

COMMANDS = {
    "/mcp-servers": "список MCP-подключений и их статус",
    "/mcp-tools": "список MCP-возможностей",
    "/demo": "демо по дням: /demo day16 | day17 | day18 | day19 | day20",
    "/demo day16": "день 16: показать MCP-подключения и возможности",
    "/demo day17": "день 17: выполнить /wc today",
    "/demo day18": "день 18: выполнить /wc-remind Argentina",
    "/demo day19": "день 19: выполнить /matchday-report-full today",
    "/demo day20": "день 20: выполнить автономный LLM-сценарий ЧМ + погода + файл + напоминание",
    "/weather": "погода: прогноз по городу. Пример: /weather Москва",
    "/wc": "ЧМ-2026: матчи по today/дате/команде/group. Пример: /wc Argentina",
    "/wc-source": "ЧМ-2026: показать/выбрать источник данных. Пример: /wc-source mock или /wc-source Football-Data-Api",
    "/wc-remind": "ЧМ-2026: напомнить перед ближайшим матчем команды. Пример: /wc-remind Argentina",
    "/matchday-report-wiki": "ЧМ + Википедия: worldcup→wiki→pipeline. Пример: /matchday-report-wiki today",
    "/matchday-report-full": "полный матчдэй: worldcup→wiki→weather→pipeline. Пример: /matchday-report-full today",
    "/search": "поиск в Википедии (MCP wiki). Пример: /search Python",
    "/note": "добавить заметку-напоминание. Пример: /note +30 проверить почту",
    "/notes": "список заметок-напоминаний",
    "/help": "справка по командам",
    "/exit": "выйти",
}

COMMAND_GROUPS = [
    ("Матчи", ["/wc", "/wc-source", "/wc-remind"]),
    ("Матчдэй", ["/matchday-report-wiki", "/matchday-report-full"]),
    ("Погода", ["/weather"]),
    ("MCP", ["/mcp-servers", "/mcp-tools"]),
    ("Демо", ["/demo day16", "/demo day17", "/demo day18", "/demo day19", "/demo day20"]),
    ("Планировщик", ["/note", "/notes"]),
    ("Система", ["/help", "/exit"]),
]

MENU_STYLE = Style.from_dict({
    "prompt": f"{ACCENT} bold",
    "bottom-toolbar": "bg:#161b22 #8b949e",
    "completion-menu": "bg:#0d1117",
    "completion-menu.completion": "bg:#0d1117 #8b949e",
    "completion-menu.completion.current": "bg:#30363d #d0d7de bold",
    "completion-menu.meta.completion": "bg:#161b22 #8b949e",
    "completion-menu.meta.completion.current": "bg:#30363d #7ee787",
    "scrollbar.background": "bg:#161b22",
    "scrollbar.button": "bg:#30363d",
})

console = Console()
agent = None
worldcup_provider_state = "api"


def _wc_provider():
    return worldcup_provider_state


def _wc_provider_label(value=None):
    provider = value if value is not None else _wc_provider()
    if provider in {"api", "football_data", "real_api", "Football-Data-Api"}:
        return "Football-Data-Api"
    return "mock" if provider == "mock" else str(provider or "—")


def _without_url_scheme(value):
    text = str(value or "—")
    return re.sub(r"^https?://", "", text)


def _online_counts():
    if not agent:
        return 0, 0, 0
    mcps = agent.servers()
    return sum(1 for mcp in mcps if mcp["ok"]), len(mcps), len(agent.list_tools())


def _status_line():
    up, total, capabilities = _online_counts()
    return f"MCP-agent | {up}/{total} online | {capabilities} capabilities | worldcup: {_wc_provider_label()}"


def _section_title(title, subtitle=""):
    text = Text()
    text.append("■■ ", style="#3d3d3d")
    text.append(title.upper(), style=f"bold {ACCENT}")
    if subtitle:
        text.append(f"  {subtitle}", style=MUTED)
    text.append(" ■■", style="#3d3d3d")
    return text


def _section_rule(title, subtitle=""):
    plain = f"■■ {title.upper()}"
    if subtitle:
        plain += f"  {subtitle}"
    plain += " ■■"
    return Text("■" * len(plain), style="#3d3d3d")


def _control_panel(renderable, title, subtitle="", style=SURFACE):
    console.print()
    console.print(_section_rule(title, subtitle))
    console.print(_section_title(title, subtitle))
    console.print(_section_rule(title, subtitle))
    console.print(renderable)


def _status_badge(ok, label_ok="OK", label_bad="ERR"):
    return Text(label_ok if ok else label_bad, style=f"bold {OK if ok else ERROR}")


def _kv_table(rows):
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("key", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("value", style=TEXT)
    for key, value in rows:
        table.add_row(str(key), str(value))
    return table


def _run_trace(stages):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("step", style=MUTED, justify="right", no_wrap=True)
    table.add_column("state", justify="center", no_wrap=True)
    table.add_column("mcp", style=ACCENT_2, no_wrap=True)
    table.add_column("tool", style=f"bold {TEXT}", no_wrap=True)
    table.add_column("result", style=MUTED)
    for i, (mcp, capability, info) in enumerate(stages, 1):
        table.add_row(f"{i:02}", Text("OK", style=f"bold {OK}"), mcp, capability, info)
    return table


def _source_from_mcp(mcp):
    if mcp["name"] == "worldcup":
        return _wc_provider_label()
    if mcp["name"] == "weather":
        return "Open-Meteo"
    return "local"


class CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return
        matches = [name for name in COMMANDS if name.startswith(text)]
        if not matches:
            return
        common = os.path.commonprefix(matches)
        replacement = common if len(common) > len(text) else matches[0]
        yield Completion(replacement, start_position=-len(text), display=replacement)


def _bottom_toolbar():
    if not agent:
        return HTML(" <b>MCP-agent</b> | control room | MCP offline ")
    up, total, capabilities = _online_counts()
    return HTML(f" <b>MCP-agent</b> | {up}/{total} online | {capabilities} capabilities | worldcup: {_wc_provider_label()} ")


def banner():
    title = Text()
    title.append("AGENT CONTROL ROOM\n", style=f"bold {ACCENT}")
    title.append("World Cup 2026 + Weather MCP", style=TEXT)
    _control_panel(title, "MCP-agent", "week 04 orchestration")


def show_help():
    table = Table(box=box.HORIZONTALS, border_style=ACCENT, show_edge=False)
    table.add_column("section", style=f"bold {ACCENT}", no_wrap=True)
    table.add_column("command", style=f"bold {TEXT}", no_wrap=True)
    table.add_column("mission", style=MUTED)
    for group_index, (section, commands) in enumerate(COMMAND_GROUPS):
        if group_index:
            table.add_section()
        for i, command in enumerate(commands):
            if i:
                table.add_row("", "", "")
            table.add_row(section if i == 0 else "", command, COMMANDS[command])
    _control_panel(table, "command deck", "grouped by workflow")


def _error(title, error):
    rows = [
        ("state", Text("ERROR", style=f"bold {ERROR}")),
        ("module", title),
        ("reason", f"{type(error).__name__}: {error}"),
        ("recovery", "run /mcp-servers, /mcp-tools or /wc-source"),
    ]
    _control_panel(_kv_table(rows), "incident", "action required", ERROR)


def _need_agent():
    if agent is None:
        console.print(Text("agent offline: MCP-подключения не готовы.", style=WARN))
        return False
    return True


def cmd_mcp_servers():
    if not _need_agent():
        return
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("state", no_wrap=True)
    table.add_column("mcp", style=f"bold {TEXT}", no_wrap=True)
    table.add_column("capabilities", style=ACCENT_2, justify="right")
    table.add_column("source", style=MUTED, no_wrap=True)
    table.add_column("role", style=MUTED)
    for srv in agent.servers():
        status = _status_badge(srv["ok"], "ONLINE", "DOWN")
        source = _source_from_mcp(srv) if srv["ok"] else srv["error"] or "—"
        table.add_row(status, srv["name"], str(srv["tools"]), source, srv["title"])
    _control_panel(table, "mcp board", _status_line())


def show_mcp_tools():
    if not _need_agent():
        return
    table = Table(box=box.HORIZONTALS, border_style=ACCENT, show_edge=False)
    table.add_column("mcp", style=f"bold {ACCENT}", no_wrap=True)
    table.add_column("capability", style=f"bold {TEXT}", no_wrap=True)
    table.add_column("namespace", style=MUTED, no_wrap=True)
    table.add_column("description", style=MUTED)
    last_mcp = None
    capabilities = sorted(agent.list_tools(), key=lambda item: (item["server"], item["name"]))
    for capability in capabilities:
        description = (capability["description"] or "").strip().splitlines()
        if last_mcp is not None and capability["server"] != last_mcp:
            table.add_section()
        elif last_mcp is not None:
            table.add_row("", "", "", "")
        mcp = capability["server"] if capability["server"] != last_mcp else ""
        table.add_row(mcp, capability["name"], capability["qualified"], description[0] if description else "")
        last_mcp = capability["server"]
    _control_panel(table, "mcp capability registry", f"{len(capabilities)} callable capabilities")


def _render_flow(stages, result, title):
    _control_panel(_run_trace(stages), f"run {title}", "tool execution trace")
    if result and result.get("summary"):
        head = result.get("title") or result.get("repo") or ""
        rows = [
            ("result", head),
            ("saved", result.get("path", "—")),
            ("summary", result["summary"]),
        ]
        _control_panel(_kv_table(rows), "result", "saved artifact", OK)


def cmd_search(query):
    if not _need_agent():
        return
    if not query:
        console.print(Text("Укажи запрос: /search <текст>", style=WARN))
        return
    try:
        result = agent.call_tool("wiki", "wiki_search", {"query": query, "limit": 5})
    except Exception as error:
        _error("Ошибка вызова MCP-tool wiki_search", error)
        return
    rows = result.get("results", []) if isinstance(result, dict) else []
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("#", style=MUTED, justify="right")
    table.add_column("article", style=f"bold {TEXT}")
    table.add_column("snippet", style=MUTED)
    for i, row in enumerate(rows, 1):
        table.add_row(str(i), row["title"], row["snippet"])
    _control_panel(table, f"wiki search {query}", f"{len(rows)} articles")


def cmd_note(rest):
    if not _need_agent():
        return
    parts = rest.split(maxsplit=1)
    if len(parts) < 2:
        console.print(Text("Формат: /note <+секунды|ISO> <текст>. Пример: /note +30 позвонить", style=WARN))
        return
    run_at, text = parts[0], parts[1]
    try:
        result = agent.call_tool("scheduler", "remind_add", {"text": text, "run_at": run_at})
    except Exception as error:
        _error("Ошибка вызова MCP-tool remind_add", error)
        return
    rows = [
        ("state", "scheduled"),
        ("id", f"#{result['id']}"),
        ("text", result["text"]),
        ("run_at", result["run_at"]),
    ]
    _control_panel(_kv_table(rows), "note", "scheduled", OK)


def cmd_notes():
    if not _need_agent():
        return
    result = agent.call_tool("scheduler", "reminders_list", {})
    rows = result.get("reminders", []) if isinstance(result, dict) else []
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("id", style=MUTED, justify="right")
    table.add_column("text", style=f"bold {TEXT}")
    table.add_column("run_at", style=MUTED)
    table.add_column("state", style=MUTED)
    for row in rows:
        status = "FIRED " + (row["fired_at"] or "") if row["fired"] else "PENDING"
        table.add_row(str(row["id"]), row["text"], row["run_at"], status)
    _control_panel(table, "notes", f"{len(rows)} scheduled notes")


def cmd_ask(goal):
    if not _need_agent():
        return
    if not goal:
        console.print(Text("Укажи цель для demo day20.", style=WARN))
        return
    console.print(Text("RUN demo day20  planner=LLM capability_choice=auto", style=MUTED))
    try:
        transcript, answer = agent.ask(goal)
    except Exception as error:
        _error("Ошибка LLM-режима (проверь PROXYAPI_KEY и поддержку function calling)", error)
        return
    if transcript:
        table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
        table.add_column("step", style=MUTED, justify="right")
        table.add_column("mcp", style=ACCENT_2, no_wrap=True)
        table.add_column("capability", style=f"bold {TEXT}", no_wrap=True)
        table.add_column("arguments", style=MUTED)
        for i, step in enumerate(transcript, 1):
            table.add_row(f"{i:02}", step["server"], step["tool"], json.dumps(step["arguments"], ensure_ascii=False))
        _control_panel(table, "agent trace", "LLM selected capabilities")
    _control_panel(Text(answer, style=TEXT), "agent answer", "final response", OK)


def cmd_weather(city):
    if not _need_agent():
        return
    if not city:
        console.print(Text("Укажи город: /weather <город>", style=WARN))
        return
    try:
        data = agent.call_tool("weather", "weather_brief", {"city": city, "days": 3})
    except Exception as error:
        _error("Ошибка вызова MCP-tool weather_brief", error)
        return
    location = data.get("location", {})
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("date", style=MUTED, no_wrap=True)
    table.add_column("temp", style=f"bold {TEXT}", no_wrap=True)
    table.add_column("forecast", style=MUTED)
    table.add_column("rain", style=ACCENT_2, no_wrap=True)
    for row in data.get("daily", []):
        table.add_row(
            row["date"],
            f"{row['temp_min']}..{row['temp_max']} C",
            row["summary"],
            f"{row['precipitation_probability']}%",
        )
    _control_panel(table, f"weather {location.get('name', city)}", f"{location.get('country','')} | {data.get('timezone','')}")


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(value)
            except (json.JSONDecodeError, SyntaxError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def _is_iso_date(value):
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _match_line(match):
    return f"{match.get('home')} — {match.get('away')} · {match.get('kickoff')} · {match.get('stage')} · {match.get('city')}"


def _remind_time(kickoff, minutes=30):
    return (datetime.fromisoformat(kickoff) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _match_kickoff(match):
    for key in ("kickoff", "utcDate", "date"):
        value = match.get(key)
        if value:
            return str(value).replace("Z", "")
    return ""


def _extract_kickoff_from_text(text):
    patterns = [
        r"\b(20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)Z?\b",
        r"\b(20\d{2}-\d{2}-\d{2})\s+(\d{2}:\d{2})(?::\d{2})?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        if len(match.groups()) == 1:
            return match.group(1).replace("Z", "")
        return f"{match.group(1)}T{match.group(2)}:00"
    return ""


def _wiki_kickoff_for_match(match, team):
    fixture = f"{match.get('home', '')} {match.get('away', '')}".strip()
    query = f"Чемпионат мира по футболу 2026 {fixture or team} время матча дата"
    search = _as_dict(agent.call_tool("wiki", "wiki_search", {"query": query, "limit": 5}))
    results = search.get("results", [])
    combined = " ".join(f"{row.get('title', '')} {row.get('snippet', '')}" for row in results)
    kickoff = _extract_kickoff_from_text(combined)
    if kickoff:
        return kickoff, "wiki_search"
    for row in results[:2]:
        title = row.get("title")
        if not title:
            continue
        fetched = _as_dict(agent.call_tool("wiki", "wiki_fetch", {"title": title}))
        kickoff = _extract_kickoff_from_text(fetched.get("extract", ""))
        if kickoff:
            return kickoff, f"wiki_fetch:{title}"
    return "", "wiki"


def _wc_wiki_probe(query):
    try:
        search = _as_dict(agent.call_tool("wiki", "wiki_search", {"query": query, "limit": 5}))
        results = search.get("results", [])
        if results:
            title = results[0].get("title")
            if title:
                agent.call_tool("wiki", "wiki_fetch", {"title": title})
        return {"ok": True, "results": len(results)}
    except Exception as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def _wc_mock_call(tool, arguments):
    previous = _wc_provider()
    switched = previous != "mock"
    if switched:
        agent.call_tool("worldcup", "wc_data_source", {"mode": "mock"})
    try:
        data = _as_dict(agent.call_tool("worldcup", tool, arguments))
        data["fallback_chain"] = "worldcup -> wiki -> mock"
        return data
    finally:
        if switched:
            agent.call_tool("worldcup", "wc_data_source", {"mode": previous})


def _wc_matches_with_fallback(arguments):
    query = (
        "2026 FIFA World Cup round of 32 "
        f"{arguments.get('date', '')} {arguments.get('team', '')} {arguments.get('stage', '')}"
    )
    reason = ""
    try:
        data = _as_dict(agent.call_tool("worldcup", "wc_matches", arguments))
        if data.get("matches"):
            return data
        reason = "worldcup returned 0 matches"
    except Exception as error:
        reason = f"{type(error).__name__}: {error}"
    wiki = _wc_wiki_probe(query)
    data = _wc_mock_call("wc_matches", arguments)
    data["fallback_reason"] = reason
    data["wiki_probe"] = wiki
    return data


def _wc_next_match_with_fallback(team):
    reason = ""
    try:
        data = _as_dict(agent.call_tool("worldcup", "wc_team_next_match", {"team": team}))
        if data.get("match"):
            return data
        reason = "worldcup returned no match"
    except Exception as error:
        reason = f"{type(error).__name__}: {error}"
    wiki = _wc_wiki_probe(f"2026 FIFA World Cup round of 32 {team} next match")
    data = _wc_mock_call("wc_team_next_match", {"team": team})
    data["fallback_reason"] = reason
    data["wiki_probe"] = wiki
    return data


def cmd_wc(rest):
    if not _need_agent():
        return
    target = rest.strip() or "today"
    try:
        if target.lower().startswith("group "):
            data = _as_dict(agent.call_tool("worldcup", "wc_group_table", {"group": target.split(maxsplit=1)[1]}))
            table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
            table.add_column("#", style=MUTED, justify="right")
            table.add_column("team", style=f"bold {TEXT}")
            table.add_column("played", style=MUTED, justify="right")
            table.add_column("points", style=ACCENT, justify="right")
            table.add_column("goals", style=MUTED)
            for row in data.get("table", []):
                table.add_row(str(row["position"]), row["team"], str(row["played"]), str(row["points"]), f"{row['goals_for']}:{row['goals_against']}")
            _control_panel(table, f"group {data.get('group')}", f"source={data.get('provider', _wc_provider())}")
        elif target == "today" or _is_iso_date(target):
            data = _wc_matches_with_fallback({"date": target})
            table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
            table.add_column("#", style=MUTED, justify="right")
            table.add_column("match_id", style=ACCENT_2, no_wrap=True)
            table.add_column("fixture", style=f"bold {TEXT}")
            table.add_column("stage", style=MUTED)
            table.add_column("city", style=MUTED)
            for i, match in enumerate(data.get("matches", []), 1):
                table.add_row(
                    str(i),
                    str(match.get("id", "—")),
                    f"{match.get('home', '—')} — {match.get('away', '—')} · {match.get('kickoff', '—')}",
                    str(match.get("stage", "—")),
                    str(match.get("city", "—")),
                )
            subtitle = f"source={data.get('provider', _wc_provider())}"
            if data.get("fallback_chain"):
                subtitle += f" · fallback={data['fallback_chain']}"
            _control_panel(table, f"fixtures {data.get('date')}", subtitle)
        else:
            data = _wc_next_match_with_fallback(target)
            match = data.get("match", {})
            rows = [
                ("team", target),
                ("fixture", f"{match.get('home')} — {match.get('away')}"),
                ("kickoff", match.get("kickoff", "—")),
                ("stage", match.get("stage", "—")),
                ("venue", f"{match.get('stadium', '—')} · {match.get('city', '—')}"),
                ("source", data.get("provider", _wc_provider())),
            ]
            if data.get("fallback_chain"):
                rows.append(("fallback", data["fallback_chain"]))
            _control_panel(_kv_table(rows), "next match", "worldcup.wc_team_next_match")
    except Exception as error:
        _error("Ошибка worldcup", error)


def cmd_wc_source(mode=""):
    global worldcup_provider_state
    if not _need_agent():
        return
    mode = mode.strip().lower()
    if mode == "football-data-api":
        mode = "api"
    if mode not in {"", "api", "mock"}:
        console.print(Text("Формат: /wc-source [Football-Data-Api|mock]", style=WARN))
        return
    arguments = {"mode": mode} if mode else {}
    try:
        data = _as_dict(agent.call_tool("worldcup", "wc_data_source", arguments))
    except Exception as error:
        _error("Ошибка wc-source", error)
        return
    if data.get("provider"):
        worldcup_provider_state = "api" if data["provider"] == "football_data" else "mock"
    mode = _wc_provider_label(data.get("mode") or data.get("provider") or "unknown")
    source = _without_url_scheme(data.get("data_file") or data.get("api_url") or data.get("source") or "—")
    token = "есть" if data.get("token_configured") else "нет"
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("field", style=f"bold {ACCENT_2}")
    table.add_column("value", style=TEXT)
    table.add_row("команда", _wc_provider_label(data.get("command_mode", _wc_provider())))
    table.add_row("режим", mode)
    table.add_row("provider", _wc_provider_label(data.get("provider", "—")))
    table.add_row("источник", source)
    if data.get("demo_today"):
        table.add_row("demo today", data["demo_today"])
    if data.get("api_url"):
        table.add_row("Football-Data-Api url", _without_url_scheme(data["api_url"]))
    table.add_row("FOOTBALL_API_KEY", token)
    table.add_row("комментарий", data.get("note", "—").replace("API", "Football-Data-Api"))
    _control_panel(table, "worldcup data source", "use /wc-source Football-Data-Api|mock")


def cmd_wc_remind(team):
    if not _need_agent():
        return
    if not team:
        console.print(Text("Укажи команду: /wc-remind <команда>", style=WARN))
        return
    try:
        data = _wc_next_match_with_fallback(team)
        match = data.get("match", {})
        kickoff = _match_kickoff(match)
        time_source = "worldcup"
        if not kickoff:
            kickoff, time_source = _wiki_kickoff_for_match(match, team)
        if not kickoff:
            fallback = _wc_mock_call("wc_team_next_match", {"team": team})
            match = fallback.get("match", match)
            kickoff = _match_kickoff(match)
            time_source = "mock"
        if not kickoff:
            raise RuntimeError("worldcup, wiki и mock не нашли время начала матча")
        fixture = f"{match.get('home', '—')} — {match.get('away', '—')}"
        run_at = _remind_time(kickoff, 30)
        result = agent.call_tool("scheduler", "remind_add", {"text": f"{fixture} начнётся через 30 минут", "run_at": run_at})
    except Exception as error:
        _error("Ошибка wc-remind", error)
        return
    rows = [
        ("state", "scheduled"),
        ("id", f"#{result['id']}"),
        ("fixture", fixture),
        ("kickoff", kickoff),
        ("time source", time_source),
        ("run_at", result["run_at"]),
    ]
    if data.get("fallback_chain"):
        rows.append(("fallback", data["fallback_chain"]))
    _control_panel(_kv_table(rows), "match reminder", "scheduler.remind_add", OK)


def cmd_matchday_wiki_report(target):
    if not _need_agent():
        return
    target = target or "today"
    console.print(Text(f"RUN /matchday-report-wiki  route=worldcup -> wiki -> pipeline  budget={SCRIPTED_FLOW_MAX_CALLS} MCP calls", style=MUTED))
    try:
        stages, result = agent.run_matchday_wiki_report(target)
    except Exception as error:
        _error("Ошибка matchday-report-wiki", error)
        return
    _render_flow(stages, result, f"Matchday Wiki · {target}")


def cmd_matchday_full_report(target):
    if not _need_agent():
        return
    target = target or "today"
    console.print(Text(f"RUN /matchday-report-full  route=worldcup -> wiki -> weather -> pipeline  budget={SCRIPTED_FLOW_MAX_CALLS} MCP calls", style=MUTED))
    try:
        stages, result = agent.run_matchday_full_report(target)
    except Exception as error:
        _error("Ошибка matchday-report-full", error)
        return
    _render_flow(stages, result, f"Matchday Full · {target}")


def cmd_demo(day):
    day = (day or "").strip().lower()
    aliases = {
        "16": "day16",
        "17": "day17",
        "18": "day18",
        "19": "day19",
        "20": "day20",
    }
    day = aliases.get(day, day)
    command_key = f"/demo {day}"
    description = COMMANDS.get(command_key)
    if description:
        console.print(Text(description, style=MUTED))
    if day == "day16":
        cmd_mcp_servers()
        show_mcp_tools()
    elif day == "day17":
        cmd_wc("today")
    elif day == "day18":
        cmd_wc_remind("Argentina")
    elif day == "day19":
        cmd_matchday_full_report("today")
    elif day == "day20":
        cmd_ask("найди ближайший матч Аргентины на ЧМ-2026, проверь погоду в городе матча, сохрани превью и поставь напоминание")
    else:
        _control_panel(_kv_table([
            ("state", "unknown demo"),
            ("format", "/demo day16|day17|day18|day19|day20"),
            ("examples", "/demo day17"),
        ]), "demo router", "choose day", WARN)


def dispatch(line):
    line = line.strip()
    if line.startswith(":"):
        line = line[1:].strip()
    if not line:
        return
    parts = line.split(maxsplit=1)
    command = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""
    if command == "/mcp-servers":
        cmd_mcp_servers()
    elif command == "/mcp-tools":
        show_mcp_tools()
    elif command == "/demo":
        cmd_demo(rest)
    elif command == "/weather":
        cmd_weather(rest)
    elif command == "/wc":
        cmd_wc(rest)
    elif command == "/wc-source":
        cmd_wc_source(rest)
    elif command == "/wc-remind":
        cmd_wc_remind(rest)
    elif command == "/matchday-report-wiki":
        cmd_matchday_wiki_report(rest)
    elif command == "/matchday-report-full":
        cmd_matchday_full_report(rest)
    elif command == "/search":
        cmd_search(rest)
    elif command == "/note":
        cmd_note(rest)
    elif command == "/notes":
        cmd_notes()
    elif command == "/help":
        show_help()
    else:
        _control_panel(_kv_table([
            ("state", "unknown command"),
            ("command", command),
            ("hint", "run /help"),
        ]), "command router", "no route", WARN)


def _connect_agent():
    global agent
    try:
        candidate = McpAgent()
        candidate.connect()
        agent = candidate
        up = sum(1 for s in agent.servers() if s["ok"])
        rows = [
            ("mcp", f"{up}/{len(agent.servers())} online"),
            ("capabilities", len(agent.list_tools())),
            ("worldcup source", _wc_provider_label()),
        ]
        _control_panel(_kv_table(rows), "boot", "MCP connections established", OK)
    except Exception as error:
        _error("Не удалось поднять MCP-подключения", error)


def main():
    banner()
    _connect_agent()
    show_help()
    session = PromptSession(
        completer=CommandCompleter(),
        complete_while_typing=False,
        complete_style=CompleteStyle.READLINE_LIKE,
        style=MENU_STYLE,
    )
    while True:
        try:
            line = session.prompt(HTML("<prompt>Ты:</prompt> ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            break
        dispatch(line)
    if agent is not None:
        agent.close()
    console.print(Text("control room offline", style=MUTED))


if __name__ == "__main__":
    main()
