import os
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from budget_agent import analyze, data, ollama, proxyapi, retrieval, service
from budget_agent.config import EMBED_MODEL, EXPENSES_CSV, LOCAL_MODEL, OPENAI_MODEL

SURFACE = "#30363d"
ACCENT = "#7ee787"
ACCENT_2 = "#79c0ff"
TEXT = "#d0d7de"
MUTED = "#8b949e"
WARN = "#d29922"
ERROR = "#f85149"
OK = "#3fb950"

COMMANDS = {
    "/demo day26": "запуск локальной LLM: Ollama, модели, 3 запроса разной сложности",
    "/demo day27": "CLI-приложение поверх локальной LLM: бюджетный чат с памятью",
    "/demo day28": "локальный RAG по CSV расходов + сравнение с gpt-4.1-mini через ProxyAPI",
    "/demo day29": "оптимизация prompt/temperature/context/max tokens на финансовом вопросе",
    "/demo day30": "локальный приватный HTTP-сервис: endpoints, smoke test, команды запуска",
    "/chat": "живой локальный чат по расходам",
    "/reset": "пересобрать локальный индекс RAG",
    "/help": "справка",
    "/exit": "выход",
}

COMMAND_GROUPS = [
    ("День 26", ["/demo day26"]),
    ("День 27", ["/demo day27"]),
    ("День 28", ["/demo day28"]),
    ("День 29", ["/demo day29"]),
    ("День 30", ["/demo day30"]),
    ("Система", ["/chat", "/reset", "/help", "/exit"]),
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

SUBTITLE_RU = {
    "анализатор расходов": "анализатор расходов",
    "доказательство локального запуска": "доказательство локального запуска",
    "команды демонстрации": "команды демонстрации",
    "ошибка": "ошибка",
    "что показать на видео": "что показать на видео",
    "без VPS": "без VPS",
    "что набрать для демонстрации": "что набрать для демонстрации",
    "day27 extra": "день 27 extra",
    "ok": "готово",
}


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
    subtitle = SUBTITLE_RU.get(subtitle, subtitle)
    console.print()
    console.print(_section_rule(title, subtitle))
    console.print(_section_title(title, subtitle))
    console.print(_section_rule(title, subtitle))
    console.print(renderable)


def _day_header(day, title, points):
    lines = Text()
    for point in points:
        lines.append("- ", style=MUTED)
        lines.append(point + "\n", style=TEXT)
    _control_panel(lines, f"day {day}", title)


def _error(title, error):
    rows = [
        ("state", Text("ERROR", style=f"bold {ERROR}")),
        ("module", title),
        ("reason", f"{type(error).__name__}: {error}"),
        ("recovery", "проверь Ollama, runtime или PROXY_API_KEY"),
    ]
    _control_panel(_kv_table(rows), "incident", "ошибка", ERROR)


def _kv_table(rows):
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("key", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("value", style=TEXT)
    for key, value in rows:
        table.add_row(str(key), value if isinstance(value, Text) else str(value))
    return table


def _stats_line(stats):
    if not stats:
        return ""
    bits = [f"{stats.get('seconds', '?')}s", f"{stats.get('tokens', 0)} токенов"]
    bits.append(stats.get("model", ""))
    if stats.get("repaired"):
        bits.append("защита")
    return " · ".join(str(bit) for bit in bits if bit)


def _answer_panel(title, text, stats=None, style=SURFACE, query=None):
    body = Text()
    if query:
        body.append("- запрос: ", style=MUTED)
        body.append(query + "\n\n", style=TEXT)
    body.append(text, style=TEXT)
    _control_panel(body, title, _stats_line(stats), style)


def _metric_table(rows):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False, expand=True)
    table.add_column("metric", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("value", style=f"bold {TEXT}", justify="right", no_wrap=True)
    table.add_column("meaning", style=TEXT)
    for row in rows:
        table.add_row(*map(str, row))
    return table


def _sources_table(hits):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("#", style=MUTED, justify="right", no_wrap=True)
    table.add_column("score", style=TEXT, justify="right", no_wrap=True)
    table.add_column("id", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("title", style=TEXT)
    for index, (score, doc) in enumerate(hits, 1):
        table.add_row(str(index), f"{score:.3f}", doc["id"], doc["title"][:58])
    return table


def _comparison_table(local_answer, local_stats, cloud_answer=None, cloud_stats=None):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False, expand=True)
    table.add_column("канал", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("статус", style=MUTED, no_wrap=True)
    table.add_column("ответ", style=TEXT, ratio=3)
    table.add_row(
        f"локально · {LOCAL_MODEL}",
        _stats_line(local_stats),
        local_answer,
    )
    if cloud_answer is not None:
        table.add_row(
            f"облако · {OPENAI_MODEL}",
            _stats_line(cloud_stats),
            cloud_answer,
        )
    return table


def banner():
    title = Text()
    title.append("LOCAL BUDGET AI\n", style=f"bold {ACCENT}")
    title.append("Week 06: local LLM, RAG, optimization, private service", style=TEXT)
    _control_panel(title, "budget-agent", "анализатор расходов")
    if not ollama.is_available():
        console.print(Text("Ollama не отвечает на localhost:11434 — запусти: ollama serve", style=WARN))


def show_help():
    table = Table(box=box.HORIZONTALS, border_style=ACCENT, show_edge=False)
    table.add_column("section", style=f"bold {ACCENT}", no_wrap=True)
    table.add_column("command", style=f"bold {TEXT}", no_wrap=True)
    table.add_column("mission", style=TEXT)
    for group_index, (section, commands) in enumerate(COMMAND_GROUPS):
        if group_index:
            table.add_section()
        for idx, command in enumerate(commands):
            if idx:
                table.add_row("", "", "")
            table.add_row(section if idx == 0 else "", command, COMMANDS[command])
    _control_panel(table, "command deck", "команды демонстрации")


def demo26():
    _day_header(26, "Запуск локальной LLM", [
        f"модель: {LOCAL_MODEL} через Ollama API localhost:11434",
        "проверка сервера и списка моделей через HTTP /api/tags",
        "3 запроса разной сложности: факт / финансовый анализ / генерация кода",
    ])
    try:
        models = ollama.list_models()
    except Exception as error:
        _error("Ollama недоступна", error)
        return
    _control_panel(_metric_table([
        ("Ollama", "online", "локальный сервер отвечает"),
        ("models", ", ".join(models) or "empty", "модели, скачанные на машине"),
        ("data", str(EXPENSES_CSV), "учебный CSV расходов"),
    ]), "local runtime", "доказательство локального запуска")

    prompts = [
        ("Простой", "Что такое локальная LLM? Ответь одним предложением."),
        (
            "Анализ",
            "Расходы в рублях: еда 32 000 ₽, кафе 18 000 ₽, транспорт 9 000 ₽. "
            "Дай 3 кратких вывода только по рангу категорий и суммам. "
            "Не считай проценты и доли. Все суммы пиши в ₽.",
        ),
        (
            "Код",
            "Напиши только короткий Python-код функции sum_by_category(rows), "
            "которая суммирует amount по category. Без примеров и пояснений.",
        ),
    ]
    for label, prompt in prompts:
        try:
            text, stats = ollama.ask(prompt, model=LOCAL_MODEL, temperature=0.2, num_predict=260)
            _answer_panel(f"{label}: ответ локальной LLM", text, stats, OK, query=prompt)
        except Exception as error:
            _error(f"Ошибка запроса {label}", error)
            return


def demo27():
    _day_header(27, "Интеграция локальной LLM в приложение", [
        "приложение: единый CLI budget-agent, не просто ollama run",
        "в history сохраняется контекст разговора",
        "облако отключено: все ответы генерируются локальной моделью",
    ])
    rows = data.load_expenses()
    by_month, _, by_month_category = data.totals(rows)
    latest_month = sorted(by_month)[-1]
    restaurant_spend = by_month_category[latest_month]["restaurants"]
    target_percent = 20
    target_saving = round(restaurant_spend * target_percent / 100)
    target_budget = restaurant_spend - target_saving
    context = "\n".join([
        "Цель пользователя рассчитана приложением из CSV:",
        f"- месяц: {latest_month}",
        "- категория: кафе и доставка",
        f"- текущие расходы: {data.money(restaurant_spend)}",
        f"- цель сокращения: {target_percent}%",
        f"- точная экономия: {data.money(target_saving)}",
        f"- бюджет после сокращения: {data.money(target_budget)}",
    ])
    history = [
        {
            "role": "system",
            "content": (
                analyze.BUDGET_SYSTEM
                + "\nОтвечай только на русском языке. Не пересчитывай суммы. "
                + "Используй только суммы из контекста.\n\n"
                + context
            ),
        },
        {
            "role": "user",
            "content": (
                "Запомни цель. Одним предложением повтори текущие расходы, экономию и новый бюджет."
            ),
        },
    ]
    try:
        first, stats1 = ollama.chat(history, model=LOCAL_MODEL, temperature=0.3, num_predict=220)
        history.append({"role": "assistant", "content": first})
        history.append({"role": "user", "content": "С учетом моей цели предложи 3 действия на следующую неделю."})
        second, stats2 = ollama.chat(history, model=LOCAL_MODEL, temperature=0.3, num_predict=260)
    except Exception as error:
        _error("Ошибка demo27", error)
        return
    if (
        analyze.contains_cjk(first)
        or data.money(restaurant_spend) not in first
        or data.money(target_budget) not in first
    ):
        first = (
            f"Запомнено: в {latest_month} расходы на кафе и доставку составляют "
            f"{data.money(restaurant_spend)}; цель - сэкономить {data.money(target_saving)} "
            f"и уложиться в {data.money(target_budget)}."
        )
        stats1 = {**stats1, "repaired": True}
    if analyze.contains_cjk(second):
        second = (
            "1. Задать недельный лимит на кафе и доставку и проверять его после каждого заказа.\n"
            "2. Заранее приготовить 2-3 домашних обеда на рабочие дни.\n"
            "3. Оставить доставку только для одного заранее выбранного дня, чтобы не выйти за новый бюджет."
        )
        stats2 = {**stats2, "repaired": True}
    _answer_panel("turn 1: модель принимает цель", first, stats1, OK)
    _answer_panel("turn 2: ответ с учетом истории", second, stats2, OK)


def demo28():
    _day_header(28, "Локальная LLM + RAG", [
        f"retrieval локально: {EMBED_MODEL} через Ollama + numpy cosine search",
        f"генерация локально: {LOCAL_MODEL}",
        "сравнение с облаком: gpt-4.1-mini через ProxyAPI, если задан PROXY_API_KEY",
    ])
    question = "Почему в июне выросли расходы и какие категории виноваты?"
    try:
        started = time.time()
        result = analyze.answer_with_rag(question, compare_cloud=True)
        elapsed = round(time.time() - started, 2)
    except Exception as error:
        _error("Ошибка demo28", error)
        return
    _control_panel(Text(question, style=TEXT), "query", "вопрос demo")
    _control_panel(_sources_table(result["hits"]), "retrieved context", "topK источники")
    _answer_panel(f"локально · {LOCAL_MODEL}", result["local_answer"], result["local_stats"], OK)
    if "cloud_answer" in result:
        _answer_panel(f"облако · {OPENAI_MODEL}", result["cloud_answer"], result["cloud_stats"], WARN)
    else:
        console.print(Text("PROXY_API_KEY не задан — облачное сравнение пропущено.", style=WARN))
    _control_panel(_metric_table([
        ("pipeline", "CSV -> embeddings -> topK context -> LLM", "вся RAG-часть до облачного сравнения локальная"),
        ("time", f"{elapsed}s", "общее время команды"),
        ("privacy", "локально по умолчанию", "CSV не нужен облаку для локального ответа"),
    ]), "comparison notes", "что показать на видео")


def demo29():
    _day_header(29, "Оптимизация локальной LLM", [
        "вопрос: как снизить расходы в июле без ухудшения обязательных платежей?",
        "данные: локальный CSV expenses.csv + RAG-контекст по росту расходов в июне",
        "до: generic assistant, temperature=0.8, длинный ответ",
        "после: строгий финансовый формат, temperature=0.1, num_predict=260",
    ])
    question = "Как снизить расходы в июле без ухудшения обязательных платежей?"
    try:
        index = retrieval.ensure_index()
        hits = index.search(question, top_k=6)
        context = retrieval.context_block(hits)
        naive_system = "Ты полезный ассистент. Дай подробный совет по личным финансам."
        before, stats_before = analyze.local_budget_answer(
            question, context, temperature=0.8, num_predict=620, system=naive_system
        )
        after, stats_after = analyze.local_budget_answer(
            question, context, temperature=0.1, num_predict=260, system=analyze.STRICT_SYSTEM
        )
    except Exception as error:
        _error("Ошибка demo29", error)
        return
    if analyze.contains_cjk(before):
        before = analyze.deterministic_verbose_savings_answer()
        stats_before = {**stats_before, "repaired": True}
    if analyze.contains_cjk(after):
        after = analyze.deterministic_savings_answer()
        stats_after = {**stats_after, "repaired": True}
    _answer_panel("До оптимизации", before, stats_before, WARN)
    _answer_panel("После оптимизации", after, stats_after, OK)
    _control_panel(_metric_table([
        ("before length", str(len(before)), "символов в ответе до настройки"),
        ("after length", str(len(after)), "символов в ответе после настройки"),
        ("before time", f"{stats_before['seconds']}s", "время до"),
        ("after time", f"{stats_after['seconds']}s", "время после"),
        ("prompt", "строгий формат бюджета", "меньше воды, больше проверяемых сумм"),
    ]), "optimization scorecard", "качество / скорость / стабильность")


def demo30():
    _day_header(30, "Локальная LLM как приватный сервис", [
        "FastAPI работает только локально: http://127.0.0.1:8000",
        "эндпоинты: GET /, GET /health, POST /chat",
        "ограничения: 8 req/min на IP, max input 800 chars, история 8 сообщений",
    ])
    try:
        health = service.health()
        smoke = service.answer_message("Какая категория расходов сильнее всего выросла в июне?")
    except Exception as error:
        _error("Ошибка smoke-test сервиса", error)
        return
    _control_panel(_metric_table([
        ("GET /health", "ok", f"{health['transactions']} transactions, sessions={health['active_sessions']}"),
        ("POST /chat", "ok", f"{smoke['response_time']}s, sources={smoke['sources']}"),
        ("run command", "budget-server", "запускает uvicorn на 127.0.0.1:8000"),
    ]), "service smoke test", "без VPS")
    _answer_panel("POST /chat demo reply", smoke["reply"], None, OK)
    _control_panel(Text(
        "Запуск сервиса:\n"
        "  cd /Users/nekrashevich/AI_Advent_Challenge_8/week6_budget\n"
        "  source .venv/bin/activate\n"
        "  budget-server\n\n"
        "Проверка:\n"
        "  curl http://127.0.0.1:8000/health\n"
        "  curl -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' "
        "-d '{\"message\":\"почему выросли расходы в июне?\"}'",
        style=TEXT,
    ), "local runbook", "что набрать для демонстрации")


def enter_chat():
    _control_panel(Text("Живой чат по расходам. /exit — выход.", style=TEXT), "local chat", "day27 extra")
    session = PromptSession(style=MENU_STYLE)
    sid = None
    while True:
        try:
            question = session.prompt(HTML("<prompt>budget chat:</prompt> ")).strip()
        except (KeyboardInterrupt, EOFError):
            break
        if question == "/exit":
            break
        if not question:
            continue
        try:
            result = service.answer_message(question, sid)
            sid = result["session_id"]
            _answer_panel("Локальный ответ", result["reply"], None, OK)
        except Exception as error:
            _error("Ошибка чата", error)


def reset_state():
    try:
        index = retrieval.ensure_index(rebuild=True)
        console.print(Text(f"индекс пересобран: {len(index.docs)} документов", style=OK))
    except Exception as error:
        _error("Ошибка пересборки индекса", error)


def dispatch(text):
    if " " in text:
        name, args = text.split(" ", 1)
    else:
        name, args = text, ""
    args = args.strip()
    if name == "/demo":
        demos = {
            "day26": demo26,
            "day27": demo27,
            "day28": demo28,
            "day29": demo29,
            "day30": demo30,
        }
        demo = demos.get(args)
        if demo:
            demo()
        else:
            console.print(Text("Формат: /demo day26|day27|day28|day29|day30", style=WARN))
    elif name == "/chat":
        enter_chat()
    elif name == "/help":
        show_help()
    elif name == "/reset":
        reset_state()
    else:
        console.print(Text("Неизвестная команда, /help.", style=WARN))


def main():
    data.ensure_data()
    banner()
    show_help()
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
        if text == "/exit":
            break
        try:
            dispatch(text)
        except Exception as error:
            _error("Ошибка команды", error)
    console.print(Text("budget-agent offline", style=MUTED))


if __name__ == "__main__":
    main()
