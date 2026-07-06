import json
import os

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box

import ingest
import slicing
import vectors
from vectorstore import VectorIndex
from grounding import answer_no_rag, answer_rag, generate_answer
from searchflow import DEFAULTS, retrieve
from memory import ChatMemory

SURFACE = "#30363d"
SURFACE_DIM = "#21262d"
ACCENT = "#7ee787"
ACCENT_2 = "#79c0ff"
TEXT = "#d0d7de"
MUTED = "#8b949e"
WARN = "#d29922"
ERROR = "#f85149"
OK = "#3fb950"

# Compatibility names for the original week5 renderers. They now point to the
# week4 control-room palette.
NAVY = SURFACE
NAVY_BRIGHT = ACCENT
NAVY_PALE = TEXT
NAVY_DIM = MUTED

COMMANDS = {
    "/demo day21": "корпус, статистика двух стратегий чанкинга, пример поиска",
    "/demo day22": "один вопрос с RAG и без RAG рядом",
    "/demo day23": "сравнение выдачи до и после фильтрации на примере",
    "/demo day24": "ответ с цитатами + вопрос мимо базы (режим «не знаю»)",
    "/demo day25": "подсказка сценария и вход в чат",
    "/reset": "очистить память чата и вернуть настройки демо по умолчанию",
    "/help": "справка по командам",
    "/exit": "выйти",
}

COMMAND_GROUPS = [
    ("День 21", ["/demo day21"]),
    ("День 22", ["/demo day22"]),
    ("День 23", ["/demo day23"]),
    ("День 24", ["/demo day24"]),
    ("День 25", ["/demo day25"]),
    ("Система", ["/reset", "/help", "/exit"]),
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
indexes = {}
settings = dict(DEFAULTS)
active_strategy = "structural"

SUBTITLE_RU = {
    "action required": "требуется действие",
    "all chunks sent to generation": "все чанки, переданные в генерацию",
    "answer first, proof below": "сначала ответ, затем доказательства",
    "chunks used by grounded answer": "чанки, использованные в ответе",
    "code checks exact substrings": "код проверяет точное совпадение",
    "day 22 narrative": "сценарий дня 22",
    "day 25": "день 25",
    "different context": "разный контекст",
    "first 500 characters": "первые 500 символов",
    "fixed: 1600 chars + overlap 200 | structural: headings": "fixed: 1600 символов + overlap 200 | structural: по заголовкам",
    "general model knowledge": "общие знания модели",
    "grounded answer": "ответ с источниками",
    "grouped by RAG day": "сгруппировано по дням RAG",
    "metadata stored in index": "метаданные в индексе",
    "memory-bank -> normalized docs": "банк памяти -> нормализованные документы",
    "query -> prompt context": "запрос -> контекст промпта",
    "saved to task state": "сохранено в памяти задачи",
    "same corpus, different chunk boundaries": "один корпус, разные границы чанков",
    "same corpus, two chunkers": "один корпус, две стратегии чанкинга",
    "same question, different context": "один вопрос, разный контекст",
    "state before entering live chat": "состояние перед входом в чат",
    "traceable chunks": "прослеживаемые чанки",
    "verified by substring match": "проверено поиском подстроки",
    "weak context stops before generation": "слабый контекст останавливает генерацию",
    "week 05 RAG": "неделя 05 RAG",
    "what reached generation": "что дошло до генерации",
    "what to show in the chat": "что показать в чате",
    "why chunks survived or disappeared": "почему чанки остались или исчезли",
    "ok": "готово",
    "no_context": "нет контекста",
}


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


def _kv_table(rows):
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("key", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("value", style=TEXT)
    for key, value in rows:
        table.add_row(str(key), value if isinstance(value, Text) else str(value))
    return table


def _demo_steps(rows):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("step", style=MUTED, justify="right", no_wrap=True)
    table.add_column("signal", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("what changes on screen", style=TEXT)
    for index, (signal, description) in enumerate(rows, 1):
        table.add_row(f"{index:02}", signal, description)
    return table


def _metric_board(rows):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False, expand=True)
    table.add_column("metric", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("value", style=f"bold {TEXT}", justify="right", no_wrap=True)
    table.add_column("meaning", style=TEXT)
    for metric, value, meaning in rows:
        table.add_row(metric, value, meaning)
    return table


def _compact_source_ledger(sources):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("#", style=MUTED, justify="right", no_wrap=True)
    table.add_column("source", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("section", style=TEXT)
    table.add_column("chunk", style=MUTED, no_wrap=True)
    for index, source in enumerate(sources, 1):
        table.add_row(
            str(index),
            source["source"],
            source["section"][:52],
            source["chunk_id"],
        )
    return table


def _prompt_context_ledger(final_hits):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("#", style=MUTED, justify="right", no_wrap=True)
    table.add_column("chunk_id", style=MUTED, no_wrap=True)
    table.add_column("document · section", style=TEXT)
    for index, (score, chunk) in enumerate(final_hits, 1):
        table.add_row(
            str(index),
            chunk["chunk_id"],
            f"{chunk['title'][:34]} · {_compact_section(chunk['section'], 44)}",
        )
    return table


def _quote_audit_table(quotes):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False, expand=True)
    table.add_column("#", style=MUTED, justify="right", no_wrap=True)
    table.add_column("check", no_wrap=True)
    table.add_column("chunk", style=MUTED, no_wrap=True, max_width=28)
    table.add_column("quote", style=TEXT, ratio=3)
    for index, quote in enumerate(quotes, 1):
        if quote.get("repaired"):
            state = Text("VERIFIED BY CODE", style=f"bold {OK}")
        elif quote.get("verified"):
            state = Text("VERIFIED", style=f"bold {OK}")
        else:
            state = Text("MISSING", style=f"bold {WARN}")
        chunk_id = quote.get("chunk_id", "?")
        chunk_label = chunk_id.split("__", 1)[-1]
        table.add_row(str(index), state, chunk_label, quote.get("text", "")[:180])
    return table


def _demo_answer_split(question, plain, result):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False, expand=True)
    table.add_column("question", style=f"bold {ACCENT_2}", ratio=1)
    table.add_column("model only", style=TEXT, ratio=2)
    table.add_column("RAG grounded", style=TEXT if result["status"] == "ok" else WARN, ratio=2)
    table.add_row(question, plain[:900], result["answer"][:900])
    return table


def _retrieval_funnel(result):
    settings_used = result["settings"]
    raw_count = len(result["raw"])
    threshold_count = raw_count - len(result["dropped_threshold"])
    rerank_count = threshold_count - len(result["dropped_rerank"])
    final_count = len(result["final"])
    rows = [
        ("input", "1", result["question"]),
        ("rewrite", "1", result["query"] if result["query"] != result["question"] else "not changed"),
        ("vector topN", str(raw_count), f"topN={settings_used['top_n']}"),
        ("threshold", str(threshold_count), f"kept score >= {settings_used['threshold']}"),
        ("rerank", str(rerank_count), f"kept LLM score >= {settings_used['rerank_min']}"),
        ("prompt", str(final_count), f"topK={settings_used['top_k']}"),
    ]
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("stage", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("count", style=f"bold {TEXT}", justify="right", no_wrap=True)
    table.add_column("detail", style=TEXT)
    for row in rows:
        table.add_row(*row)
    return table


def _candidate_audit(result, limit=8):
    kept_ids = {chunk["chunk_id"] for _, chunk in result["final"]}
    dropped_threshold = {chunk["chunk_id"] for _, chunk in result["dropped_threshold"]}
    dropped_rerank = {chunk["chunk_id"] for _, chunk in result["dropped_rerank"]}
    passed = [(score, chunk) for score, chunk in result["raw"]
              if score >= result["settings"]["threshold"]]
    position_by_id = {chunk["chunk_id"]: index for index, (_, chunk) in enumerate(passed, 1)}
    raw_position_by_id = {chunk["chunk_id"]: index for index, (_, chunk) in enumerate(result["raw"], 1)}
    shown = list(result["raw"][:limit])
    shown_ids = {chunk["chunk_id"] for _, chunk in shown}
    for item in result["final"]:
        chunk_id = item[1]["chunk_id"]
        if chunk_id not in shown_ids:
            shown.append(item)
            shown_ids.add(chunk_id)

    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("#", style=MUTED, justify="right", no_wrap=True)
    table.add_column("score", style=TEXT, justify="right", no_wrap=True)
    table.add_column("LLM", style=TEXT, justify="right", no_wrap=True)
    table.add_column("candidate", style=TEXT)
    table.add_column("fate", no_wrap=True)
    for score, chunk in shown:
        chunk_id = chunk["chunk_id"]
        llm = result["llm_scores"].get(position_by_id.get(chunk_id, -1), "")
        if chunk_id in kept_ids:
            fate = Text("PROMPT", style=f"bold {OK}")
        elif chunk_id in dropped_threshold:
            fate = Text("THRESHOLD", style=f"bold {WARN}")
        elif chunk_id in dropped_rerank:
            fate = Text("RERANK", style=f"bold {WARN}")
        else:
            fate = Text("TOPK", style=MUTED)
        table.add_row(
            f"{raw_position_by_id.get(chunk_id, 0):02}",
            f"{score:.3f}",
            str(llm),
            f"{chunk['title'][:38]} · {chunk['section'][:38]}",
            fate,
        )
    return table


def _memory_workspace(memory):
    glossary = ", ".join(sorted(memory.state.get("glossary", {}).keys())) or "пусто"
    goal = memory.state.get("goal") or "не определена"
    facts = len(memory.state.get("clarified", [])) + len(memory.state.get("constraints", []))
    rows = [
        ("goal", goal, "что чат уже понял как задачу"),
        ("facts", str(facts), "уточнения и ограничения"),
        ("glossary", glossary, "термины, которые чат запомнил"),
        ("messages", str(len(memory.history)), "история переживает перезапуск"),
    ]
    return _metric_board(rows)


def banner():
    title = Text()
    title.append("RAG CONTROL ROOM\n", style=f"bold {ACCENT}")
    title.append("MDN JavaScript knowledge base", style=TEXT)
    _control_panel(title, "AGENT-RAG", "week 05 RAG")
    if not vectors.is_available():
        console.print(Text("Ollama не отвечает на localhost:11434 — запусти сервис.", style=WARN))


def show_help():
    table = Table(box=box.HORIZONTALS, border_style=ACCENT, show_edge=False)
    table.add_column("section", style=f"bold {ACCENT}", no_wrap=True)
    table.add_column("command", style=f"bold {TEXT}", no_wrap=True)
    table.add_column("mission", style=TEXT)
    for group_index, (section, commands) in enumerate(COMMAND_GROUPS):
        if group_index:
            table.add_section()
        for index, command in enumerate(commands):
            if index:
                table.add_row("", "", "")
            table.add_row(section if index == 0 else "", command, COMMANDS[command])
    _control_panel(table, "command deck", "grouped by RAG day")


def _error(title, error):
    rows = [
        ("state", Text("ERROR", style=f"bold {ERROR}")),
        ("module", title),
        ("reason", f"{type(error).__name__}: {error}"),
        ("recovery", "проверь runtime_store, Ollama или PROXY_API_KEY"),
    ]
    _control_panel(_kv_table(rows), "incident", "action required", ERROR)


def _load_indexes():
    for strategy in slicing.STRATEGIES:
        if strategy not in indexes and VectorIndex.exists(strategy):
            indexes[strategy] = VectorIndex.load(strategy)


def _need_index():
    _load_indexes()
    if active_strategy not in indexes:
        console.print(Text("Индекс не найден в runtime_store — подготовь индекс перед демо.", style=WARN))
        return False
    return True


def _stats_table(stats_by_strategy):
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("стратегия", style=f"bold {NAVY_BRIGHT}", no_wrap=True)
    table.add_column("чанков", justify="right", style=NAVY_PALE)
    table.add_column("средний размер", justify="right", style=NAVY_PALE)
    table.add_column("мин", justify="right", style=NAVY_PALE)
    table.add_column("макс", justify="right", style=NAVY_PALE)
    table.add_column("коротких", justify="right", style=NAVY_PALE)
    for strategy, stats in stats_by_strategy.items():
        table.add_row(strategy, str(stats["count"]), str(stats["avg"]),
                      str(stats["min"]), str(stats["max"]), str(stats["broken_end"]))
    return table


def _compact_section(section, limit=44):
    text = str(section or "")
    if ">" in text and len(text) > limit:
        text = text.split(">")[-1].strip()
    if len(text) > limit:
        return text[:limit - 1].rstrip() + "…"
    return text


def _render_answer(result, title="grounded answer"):
    style = OK if result["status"] == "ok" else WARN
    _control_panel(Text(result["answer"], style=NAVY_PALE), title, result["status"], style)
    if result["sources"]:
        table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
        table.add_column("#", style=NAVY_DIM, justify="right", no_wrap=True)
        table.add_column("source", style=f"bold {NAVY_BRIGHT}", no_wrap=True)
        table.add_column("section", style=NAVY_PALE)
        table.add_column("chunk", style=NAVY_DIM, no_wrap=True)
        for index, source in enumerate(result["sources"], 1):
            table.add_row(
                str(index),
                source["source"],
                _compact_section(source["section"], 48),
                source["chunk_id"],
            )
        _control_panel(table, "sources", f"чанков: {len(result['sources'])}")
    if result["quotes"]:
        lines = Text()
        for quote in result["quotes"]:
            mark = "дословно"
            if quote.get("repaired"):
                mark = "дословно (подобрано кодом)"
            elif not quote["verified"]:
                mark = "НЕ НАЙДЕНА В ЧАНКЕ"
            quote_text = quote.get("text", "")
            lines.append(f"[{quote.get('chunk_id', '?')}] ", style=NAVY_DIM)
            lines.append(f"«{quote_text[:500]}»\n", style=NAVY_PALE)
            if len(quote_text) > 500:
                lines.append("[quote preview truncated]\n", style=MUTED)
            lines.append(f"  проверка кодом: {mark}\n", style=OK if quote["verified"] else WARN)
        _control_panel(lines, "quotes", "verified by substring match")


def reset_state():
    global active_strategy
    settings.clear()
    settings.update(DEFAULTS)
    active_strategy = "structural"
    ChatMemory().reset()
    console.print(Text("state очищен: память чата сброшена, настройки демо по умолчанию", style=OK))


def _is_memory_note(text):
    lowered = text.lower()
    markers = (
        "запомни",
        "зафиксируй",
        "учти",
        "сохрани в памяти",
        "мне нужно для проекта",
        "для проекта по rag",
    )
    return any(marker in lowered for marker in markers)


def enter_chat():
    if not _need_index():
        return
    memory = ChatMemory()
    _control_panel(
        Text("Чат с RAG и памятью задачи. Внутри: /state — память, /reset — сброс, /exit — выход. "
             "История и память переживают перезапуск.", style=NAVY_PALE),
        "mini chat",
        "day 25",
    )

    session = PromptSession(style=MENU_STYLE)
    while True:
        try:
            text = session.prompt(HTML("<prompt>day25 chat:</prompt> ")).strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not text:
            continue
        if text == "/exit":
            break
        if text == "/state":
            _control_panel(Text(json.dumps(memory.state, ensure_ascii=False, indent=1),
                                style=NAVY_PALE),
                           "task memory", f"сообщений: {len(memory.history)}")
            continue
        if text == "/reset":
            memory.reset()
            console.print(Text("память очищена", style=OK))
            continue
        if text.startswith("/"):
            console.print(Text("Неизвестная команда чата. Доступны: /state, /reset, /exit.", style=WARN))
            continue
        try:
            if _is_memory_note(text):
                answer = "Зафиксировал это в памяти задачи."
                _control_panel(Text(answer, style=TEXT), "memory note", "saved to task state", OK)
                memory.add_exchange(text, answer)
                memory.update_state(text, answer)
                continue
            chat_settings = {**settings, "rewrite": True}
            result = answer_rag(text, indexes[active_strategy], chat_settings,
                                history_text=memory.history_text(),
                                history_messages=memory.recent_messages())
            _render_answer(result)
            memory.add_exchange(text, result["answer"])
            memory.update_state(text, result["answer"])
        except Exception as error:
            _error("Ошибка чата", error)


def _day_header(day, title, points):
    lines = Text()
    for point in points:
        lines.append("- ", style=NAVY_DIM)
        lines.append(point + "\n", style=NAVY_PALE)
    _control_panel(lines, f"day {day}", title)


def _show_sample_chunk(sample=None):
    if sample is None and active_strategy not in indexes:
        return
    if sample is None:
        sample = next((c for c in indexes[active_strategy].chunks
                       if "event" in c["section"].lower() or "event" in c["source"].lower()),
                      indexes[active_strategy].chunks[0])
    meta = {k: sample[k] for k in ("chunk_id", "strategy", "source", "title", "section", "n_chars")}
    table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    table.add_column("field", style=f"bold {ACCENT_2}", no_wrap=True)
    table.add_column("value", style=TEXT)
    for field, value in meta.items():
        table.add_row(field, str(value))
    _control_panel(table, "sample chunk", "metadata stored in index")

    preview_text = sample["text"][:500]
    if len(sample["text"]) > 500 and " " in preview_text:
        preview_text = preview_text.rsplit(" ", 1)[0]
    preview = Text(preview_text, style=NAVY_DIM)
    if len(sample["text"]) > 500:
        preview.append("\n[chunk preview truncated]", style=MUTED)
    _control_panel(preview, "chunk preview", "first 500 characters")


def demo21():
    _day_header(21, "Индексация документов", [
        f"корпус: {ingest.KNOWLEDGE} — MDN markdown + опционально txt/PDF",
        "эмбеддинги локальные: Ollama bge-m3, данные заказчика не покидают машину",
        "две стратегии чанкинга: fixed (1600+overlap 200) vs structural (по заголовкам)",
        "индекс: JSON + numpy, метаданные у каждого чанка",
    ])
    collected = ingest.collect()
    documents = ingest.load_documents()
    total_chars = sum(doc["n_chars"] for doc in collected)
    stats_by_strategy = {s: slicing.stats(slicing.chunk_corpus(documents, s))
                         for s in slicing.STRATEGIES}
    _control_panel(
        _metric_board([
            ("documents", str(len(collected)), "сколько файлов попало в базу знаний"),
            ("characters", f"{total_chars:,}", "объем корпуса до чанкинга"),
            ("pages", f"~{total_chars // 1800}", "грубая оценка учебного объема"),
            ("strategies", str(len(slicing.STRATEGIES)), "fixed и structural на одном корпусе"),
        ]),
        "corpus dashboard",
        "memory-bank -> normalized docs",
    )
    _control_panel(_stats_table(stats_by_strategy), "chunking matrix", "same corpus, different chunk boundaries")
    _load_indexes()
    sample_chunk = None
    if indexes:
        query = "как работает event bubbling"
        vector = vectors.embed_one(query)
        proof = {strategy: index.search(vector, 3)
                 for strategy, index in sorted(indexes.items())}
        if proof.get(active_strategy):
            sample_chunk = proof[active_strategy][0][1]
        elif proof:
            first_hits = next(iter(proof.values()))
            sample_chunk = first_hits[0][1] if first_hits else None
        table = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
        table.add_column("strategy", style=f"bold {ACCENT_2}", no_wrap=True)
        table.add_column("#", style=MUTED, justify="right", no_wrap=True)
        table.add_column("score", style=TEXT, justify="right", no_wrap=True)
        table.add_column("document · section", style=TEXT)
        for strategy, hits in proof.items():
            for position, (score, chunk) in enumerate(hits, 1):
                table.add_row(strategy if position == 1 else "", str(position),
                              f"{score:.3f}", f"{chunk['title'][:40]} · {_compact_section(chunk['section'])}")
        _control_panel(table, "search proof", f"запрос: {query}")
    _show_sample_chunk(sample_chunk)


def demo22():
    _day_header(22, "Первый RAG-запрос", [
        "вопрос -> векторный поиск -> чанки в промпт -> gpt-4o-mini",
        "сравнение: тот же вопрос без RAG (общие знания) и с RAG (факты проекта)",
        "контроль источников встроен в демонстрационный сценарий",
    ])
    question = "Как JavaScript может изменить DOM на странице?"
    if not _need_index():
        return
    try:
        plain = answer_no_rag(question)
        result = answer_rag(question, indexes[active_strategy], settings)
    except Exception as error:
        _error("Ошибка demo22", error)
        return
    _control_panel(_demo_answer_split(question, plain, result), "before / after", "same question, different context")
    if result["sources"]:
        _control_panel(_compact_source_ledger(result["sources"]), "source trail", "chunks used by grounded answer")
    _control_panel(_demo_steps([
        ("model only", "ответ строится из общих знаний модели"),
        ("retrieval", "поиск выбирает MDN-фрагменты перед генерацией"),
        ("grounding", "ответ показывает, какие источники реально использованы"),
    ]), "takeaway", "day 22 narrative")


def demo23():
    _day_header(23, "Реранкинг и фильтрация", [
        "конвейер: rewrite -> поиск topN=20 -> порог косинуса -> LLM-реранк 0-10 -> topK=5",
        "векторная близость не равна релевантности — реранк отсеивает похожее-но-не-то",
        "параметры пайплайна зафиксированы внутри демо; ниже — судьба каждого чанка",
    ])
    if not _need_index():
        return
    question = "как fetch получает JSON без перезагрузки страницы"
    tuned = {**settings, "rewrite": True, "rerank": True}
    try:
        result = retrieve(indexes[active_strategy], question, tuned)
        answer = generate_answer(question, result)
    except Exception as error:
        _error("Ошибка demo23", error)
        return
    _control_panel(_retrieval_funnel(result), "retrieval funnel", "query -> prompt context")
    _control_panel(_candidate_audit(result), "candidate audit", "why chunks survived or disappeared")
    _control_panel(Text(answer["answer"], style=TEXT if answer["status"] == "ok" else WARN),
                   "grounded answer", f"чанков в промпте: {len(result['final'])}")
    _control_panel(_prompt_context_ledger(result["final"]), "prompt context", "all chunks sent to generation")


def demo24():
    _day_header(24, "Цитаты, источники, анти-галлюцинации", [
        "каждый ответ: Ответ + Источники (source/section/chunk_id) + Цитаты",
        "цитаты проверяет КОД — подстрока чанка, пометка «дословно»",
        "слабый контекст -> «не знаю» ДО вызова LLM (детерминированный гейт)",
        "проверка цитат показана ниже без отдельной команды",
    ])
    if not _need_index():
        return
    question = "Как работает event bubbling?"
    off_topic = "Из какой страны Криштиану Роналду?"
    try:
        result = answer_rag(question, indexes[active_strategy], settings)
        refusal = answer_rag(off_topic, indexes[active_strategy], settings)
    except Exception as error:
        _error("Ошибка demo24", error)
        return
    verified = bool(result["quotes"]) and all(quote["verified"] for quote in result["quotes"])
    _control_panel(
        _metric_board([
            ("status", result["status"], "RAG-ответ найден"),
            ("sources", str(len(result["sources"])), "фрагменты, использованные в ответе"),
            ("quotes", str(len(result["quotes"])), "цитаты, приложенные к ответу"),
            ("verified", "yes" if verified else "no", "каждая цитата найдена как подстрока чанка"),
        ]),
        "evidence report",
        question,
    )
    _control_panel(Text(result["answer"], style=TEXT), "grounded answer", "answer first, proof below")
    if result["sources"]:
        _control_panel(_compact_source_ledger(result["sources"]), "source ledger", "traceable chunks")
    if result["quotes"]:
        _control_panel(_quote_audit_table(result["quotes"]), "quote verification", "code checks exact substrings")
    gate = Table(box=box.SIMPLE, border_style=SURFACE, show_edge=False)
    gate.add_column("question", style=f"bold {ACCENT_2}")
    gate.add_column("best score", style=TEXT, justify="right", no_wrap=True)
    gate.add_column("status", no_wrap=True)
    gate.add_row(
        off_topic,
        f"{refusal['retrieval']['best_score']:.3f}",
        Text(refusal["status"], style=f"bold {WARN}"),
    )
    _control_panel(gate, "out-of-scope gate", "weak context stops before generation")
    _control_panel(Text(refusal["answer"], style=TEXT), "refusal answer", "ответ до генерации")


def demo25():
    _day_header(25, "Мини-чат с RAG + память задачи", [
        "история диалога (окно 8) + rewrite коротких вопросов по контексту («а лечение?»)",
        "память задачи {goal, clarified, constraints, glossary} — экстрактор gpt-4o-mini",
        "источники в каждом ответе; /state показывает память; память переживает перезапуск",
        "сценарий: спроси про правила, уточняй, зафиксируй ограничение, проверь /state, затем /reset",
    ])
    memory = ChatMemory()
    _control_panel(_memory_workspace(memory), "chat workspace", "state before entering live chat")
    _control_panel(_demo_steps([
        ("ask", "задать первый вопрос про event bubbling"),
        ("follow-up", "уточнить коротко: «а как остановить?»"),
        ("state", "проверить память командой /state"),
    ]), "live scenario", "what to show in the chat")
    enter_chat()


def dispatch(text):
    if " " in text:
        name, args = text.split(" ", 1)
    else:
        name, args = text, ""
    args = args.strip()
    if name == "/demo":
        demos = {
            "day21": demo21,
            "day22": demo22,
            "day23": demo23,
            "day24": demo24,
            "day25": demo25,
        }
        demo = demos.get(args)
        if demo:
            demo()
        else:
            console.print(Text("Формат: /demo day21|day22|day23|day24|day25", style=WARN))
    elif name == "/help":
        show_help()
    elif name == "/reset":
        reset_state()
    else:
        console.print(Text("Неизвестная команда, /help.", style=WARN))


def main():
    banner()
    _load_indexes()
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
    console.print(Text("control room offline", style=NAVY_DIM))


if __name__ == "__main__":
    main()
