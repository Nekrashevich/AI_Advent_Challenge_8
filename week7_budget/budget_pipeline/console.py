from __future__ import annotations

import os

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from budget_pipeline import data, developer, file_agent, project_tools, reporting, review, support
from budget_pipeline.config import PROXY_MODEL
from budget_pipeline.llm import ProxyAPIClient


SURFACE = "#30363d"
ACCENT = "#7ee787"
ACCENT_2 = "#79c0ff"
TEXT = "#d0d7de"
MUTED = "#8b949e"
WARN = "#d29922"
ERROR = "#f85149"
OK = "#3fb950"

COMMANDS = {
    "/demo day31": "ассистент разработчика: README/docs RAG + git через MCP",
    "/demo day32": "AI-review PR: diff + code/docs RAG + ProxyAPI",
    "/demo day33": "поддержка: FAQ RAG + пользователь и тикет через MCP",
    "/demo day34": "AI-план: читает 2–3 файла, пишет отчёт и показывает diff",
    "/demo day35": "реальный недельный pipeline: validate → analyze → RAG → AI → draft",
    "/help": "список команд; /help <вопрос> — вопрос о проекте",
    "/review": "локальное ревью текущего diff; без изменений запускает demo",
    "/support": "ответ по тикету, например /support ADVENT-101",
    "/files": "запустить воспроизводимый аудит файлов и данных",
    "/report": "создать черновик недельного бюджетного отчёта",
    "/reset": "показать, что BM25 строится заново и состояние не требуется",
    "/exit": "выход",
}

COMMAND_GROUPS = [
    ("День 31", ["/demo day31"]),
    ("День 32", ["/demo day32"]),
    ("День 33", ["/demo day33"]),
    ("День 34", ["/demo day34"]),
    ("День 35", ["/demo day35"]),
    ("Система", ["/help", "/review", "/support", "/files", "/report", "/reset", "/exit"]),
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


class CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return
        matches = [name for name in COMMANDS if name.startswith(text)]
        if not matches:
            return
        replacement = os.path.commonprefix(matches)
        if len(replacement) <= len(text):
            replacement = matches[0]
        yield Completion(replacement, start_position=-len(text), display=replacement)


def _section_title(title: str, subtitle: str = "") -> Text:
    text = Text()
    text.append("■■ ", style="#3d3d3d")
    text.append(title.upper(), style=f"bold {ACCENT}")
    if subtitle:
        text.append(f"  {subtitle}", style=MUTED)
    text.append(" ■■", style="#3d3d3d")
    return text


def _section_rule(title: str, subtitle: str = "") -> Text:
    plain = f"■■ {title.upper()}" + (f"  {subtitle}" if subtitle else "") + " ■■"
    return Text("■" * len(plain), style="#3d3d3d")


def _control_panel(renderable, title: str, subtitle: str = "") -> None:
    console.print()
    console.print(_section_rule(title, subtitle))
    console.print(_section_title(title, subtitle))
    console.print(_section_rule(title, subtitle))
    console.print(renderable)


def _day_header(day: int, title: str, points: list[str]) -> None:
    lines = Text()
    for point in points:
        lines.append("- ", style=MUTED)
        lines.append(point + "\n", style=TEXT)
    _control_panel(lines, f"day {day}", title)


def _kv_table(rows: list[tuple]) -> Table:
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("key", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("value", style=TEXT)
    for key, value in rows:
        table.add_row(str(key), str(value))
    return table


def _metric_table(rows: list[tuple]) -> Table:
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False, expand=True)
    table.add_column("metric", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("value", style=f"bold {TEXT}", justify="right", no_wrap=True)
    table.add_column("meaning", style=TEXT)
    for row in rows:
        table.add_row(*map(str, row))
    return table


def _answer(title: str, answer: str, llm=None) -> None:
    subtitle = ""
    if llm:
        cost = f" · ~{llm.cost_rub:.4f} ₽" if llm.cost_rub is not None else ""
        subtitle = f"{llm.seconds}s · {llm.completion_tokens} tokens · {llm.model}{cost}"
    _control_panel(Text(answer, style=TEXT), title, subtitle)


def _sources(hits) -> Table:
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("#", style=MUTED, justify="right")
    table.add_column("BM25", style=TEXT, justify="right")
    table.add_column("source", style=f"bold {ACCENT_2}")
    table.add_column("title", style=TEXT)
    for number, hit in enumerate(hits, 1):
        table.add_row(str(number), f"{hit.score:.3f}", hit.document.id, hit.document.title)
    return table


def _error(title: str, error: Exception) -> None:
    _control_panel(_kv_table([
        ("state", "ERROR"),
        ("module", title),
        ("reason", f"{type(error).__name__}: {error}"),
        ("recovery", "проверь PROXY_API_KEY, сеть и установленные зависимости"),
    ]), "incident", "ошибка")


def banner() -> None:
    title = Text()
    title.append("BUDGET PIPELINE AI\n", style=f"bold {ACCENT}")
    title.append("Week 07: MCP, BM25 RAG, PR review, support, files, production pipeline", style=TEXT)
    _control_panel(title, "budget-pipeline", "анализатор расходов")
    state = "configured" if ProxyAPIClient().configured else "missing PROXY_API_KEY"
    console.print(Text(f"ProxyAPI · {PROXY_MODEL} · {state}", style=OK if state == "configured" else WARN))


def show_commands() -> None:
    table = Table(box=box.HORIZONTALS, border_style=ACCENT, show_edge=False)
    table.add_column("section", style=f"bold {ACCENT}", no_wrap=True)
    table.add_column("command", style=f"bold {TEXT}", no_wrap=True)
    table.add_column("mission", style=TEXT)
    for group_index, (section, commands) in enumerate(COMMAND_GROUPS):
        if group_index:
            table.add_section()
        for index, command in enumerate(commands):
            table.add_row(section if index == 0 else "", command, COMMANDS[command])
    _control_panel(table, "command deck", "команды демонстрации")


def demo31(question: str = "Как устроен импорт transactions.csv и где описан Canonical spending filter?") -> None:
    _day_header(31, "Ассистент разработчика", [
        "RAG: README + docs + schema данных",
        "MCP project server: git branch, список и чтение файлов",
        "генерация: gpt-4.1-mini через ProxyAPI",
    ])
    result = developer.ask_project(question)
    status = result["mcp_status"][0]
    _control_panel(_metric_table([
        ("MCP project", "online" if status["connected"] else "error", f"tools={status['tools']}"),
        ("branch", result["git"]["branch"], f"HEAD {result['git']['head']}"),
        ("working tree", "dirty" if result["git"]["dirty"] else "clean", "контекст получен через MCP"),
    ]), "project context", "MCP + git")
    _control_panel(_sources(result["hits"]), "retrieved context", "BM25 topK")
    _answer("Ответ ассистента", result["answer"], result["llm"])


def demo32(use_demo_diff: bool = True) -> None:
    _day_header(32, "Автоматическое ревью PR", [
        "trigger: GitHub pull_request_target; выполняется только код base branch",
        "diff + изменённые файлы → BM25 по docs/code → ProxyAPI",
        "детерминированные security checks работают даже при недоступной LLM",
    ])
    if use_demo_diff:
        diff = review.DEMO_DIFF
        files = ["week7_budget/budget_pipeline/broken_demo.py"]
    else:
        payload = project_tools.git_diff()
        diff, files = payload["diff"], payload["files"]
        if not diff:
            diff = review.DEMO_DIFF
            files = ["week7_budget/budget_pipeline/broken_demo.py"]
    result = review.review_diff(diff, files, title="Demo: unsafe expense calculation")
    markdown = review.render_review(result, files)
    _control_panel(_metric_table([
        ("changed files", len(files), ", ".join(files)),
        ("findings", len(result["findings"]), "bugs + architecture + recommendations"),
        ("mode", result["mode"], "retry/fallback enabled"),
    ]), "review pipeline", "PR → comment")
    _answer("AI code review", markdown, result["llm"])


def demo33(ticket_id: str = "ADVENT-101") -> None:
    _day_header(33, "Ассистент поддержки", [
        "MCP support server возвращает пользователя и тикет",
        "RAG соединяет FAQ со связанными transaction_id",
        "ассистент не меняет баланс и отделяет факты от предположений",
    ])
    result = support.answer_ticket(ticket_id)
    ticket = result["card"]["ticket"]
    answer = result["answer"]
    _control_panel(_kv_table([
        ("ticket", ticket["id"]),
        ("user", ticket["user_id"]),
        ("subject", ticket["subject"]),
        ("transactions", ", ".join(ticket["transaction_ids"])),
    ]), "ticket context", "MCP")
    _control_panel(_sources(result["hits"]), "support context", "FAQ + transactions")
    _answer("Диагноз", str(answer.get("diagnosis", "")), result["llm"])
    _answer("Ответ пользователю", str(answer.get("reply", "")))
    _answer("Следующее действие", str(answer.get("next_action", "")))


def demo34() -> None:
    _day_header(34, "Файловый ассистент", [
        "цель → AI-план из разрешённых файлов → безопасные MCP-вызовы",
        "читает 2–3 выбранных файла через tools/MCP",
        "создаёт audit report и отдельно показывает воспроизводимый diff preview",
    ])
    result = file_agent.run_file_goal()
    _answer("Agent file plan", result["plan"]["reason"], result["plan_llm"])
    _control_panel(_metric_table([
        ("plan mode", result["plan_mode"], "allowlist validated"),
        ("files read", len(result["inspected"]), ", ".join(result["inspected"])),
        ("schema issues", len(result["issues"]), "детерминированная валидация"),
        ("artifact", result["written"]["path"], f"{result['written']['bytes']} bytes"),
    ]), "file operations", "MCP safe write")
    _answer("AI audit summary", result["summary"], result["llm"])
    _answer("Proposed documentation diff", result["diff_preview"][:6000])


def demo35() -> None:
    _day_header(35, "Реальный недельный pipeline", [
        "validate → filter → calculate → retrieve → generate → save draft",
        "pending, failed, transfer и duplicate не искажают расходы",
        "human-in-the-loop: результат сохраняется как черновик, не отправляется автоматически",
    ])
    result = reporting.run_weekly_pipeline()
    metrics = result["metrics"]
    _control_panel(_metric_table([
        ("period", f"{metrics['start']} → {metrics['end']}", "последние 7 дней данных"),
        ("posted spend", data.money(metrics["spend"]), "только expense/posted/not duplicate"),
        ("review queue", metrics["review_count"], "пограничные операции"),
        ("mode", result["mode"], "ProxyAPI или детерминированный fallback"),
        ("draft", result["written"]["path"], "требует проверки человеком"),
    ]), "pipeline result", "production-ready")
    _control_panel(_sources(result["hits"]), "evidence", "RAG sources")
    if result["llm"]:
        _answer("Generation metrics", "Черновик успешно сформирован.", result["llm"])


def dispatch(text: str) -> bool:
    name, _, args = text.partition(" ")
    args = args.strip()
    if name == "/demo":
        demos = {"day31": demo31, "day32": demo32, "day33": demo33, "day34": demo34, "day35": demo35}
        if args not in demos:
            console.print(Text("Формат: /demo day31|day32|day33|day34|day35", style=WARN))
        else:
            demos[args]()
    elif name == "/help":
        demo31(args) if args else show_commands()
    elif name == "/review":
        demo32(use_demo_diff=False)
    elif name == "/support":
        demo33(args or "ADVENT-101")
    elif name == "/files":
        demo34()
    elif name == "/report":
        demo35()
    elif name == "/reset":
        console.print(Text("BM25 индекс строится из файлов при каждом сценарии; состояние уже чистое.", style=OK))
    elif name == "/exit":
        return False
    else:
        console.print(Text("Неизвестная команда, /help.", style=WARN))
    return True


def main() -> None:
    banner()
    show_commands()
    session = PromptSession(
        completer=CommandCompleter(),
        complete_while_typing=False,
        complete_style=CompleteStyle.READLINE_LIKE,
        style=MENU_STYLE,
    )
    while True:
        try:
            console.print()
            text = session.prompt(HTML("<prompt>Ты:</prompt> ")).strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not text:
            continue
        try:
            if not dispatch(text):
                break
        except Exception as error:
            _error("Ошибка команды", error)
    console.print(Text("budget-pipeline offline", style=MUTED))


if __name__ == "__main__":
    main()
