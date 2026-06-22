import os
import re
import sys
from os.path import commonprefix

import requests
from prompt_toolkit import PromptSession, prompt as pt_prompt
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.text import Text
from rich import box

from memory import MemoryLayers
from profile import Profile, FIELDS
from state import TaskStore, STAGES, TRANSITIONS, EXPECTED
from invariants import Invariants
from validator import critic_check
from swarm import run_swarm, STAGE_ROLES, MEMBER_MODEL
from prompt_builder import build_messages

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
MAIN_MODEL = "gpt-4o-mini"
PRICES_RUB_PER_1M = {
    "gpt-4o-mini": {"input": 39, "output": 155},
}

SYSTEM_PROMPT = (
    "Ты — stateful-ассистент. У тебя есть слои контекста: инварианты (нерушимые ограничения), "
    "профиль пользователя (персонализация), состояние задачи (стадия), память. Всегда соблюдай "
    "инварианты, подстраивайся под профиль, держись текущей стадии задачи. Опирайся на то, что "
    "есть в контексте, не выдумывай. Отвечай по-русски, по существу."
)

NAVY = "#34568b"
NAVY_BRIGHT = "#6f9ad1"
NAVY_PALE = "#a9c8ee"
NAVY_DIM = "#223a5c"
WARN = "#b58900"

COMMANDS = (
    "/status",
    "/task",
    "/interview",
    "/remember-forever",
    "/remember-now",
    "/add-longterm",
    "/add-working",
    "/clear-working",
    "/clear-longterm",
    "/profile",
    "/profile-set",
    "/profile-unset",
    "/profiles",
    "/profile-clear",
    "/invariant-add",
    "/demo3",
    "/demo",
    "/reset",
    "/help",
)

WORKSPACE_COMMANDS = (
    "/next",
    "/back",
    "/council",
    "/status",
    "/plan",
    "/pause",
    "/delete",
    "/help",
    "/exit",
)

MENU_STYLE = Style.from_dict({
    "prompt": "",
})

RICH_TAG_RE = re.compile(r"\[/?(?:bold|dim|red|#[0-9a-fA-F]{3,6}(?:\s+\w+)?)\]")


def strip_rich_markup(value):
    return RICH_TAG_RE.sub("", str(value))


class PlainConsole(Console):
    def print(self, *objects, **kwargs):
        super().print(*(strip_rich_markup(obj) for obj in objects), **kwargs)


console = PlainConsole(no_color=True, highlight=False)


def boxed_title(title):
    text = str(title)
    width = len(text) + 2
    return "\n".join([
        "╭" + "─" * width + "╮",
        f"│ [bold]{text}[/bold] │",
        "╰" + "─" * width + "╯",
    ])


def Panel(renderable, title=None, **_kwargs):
    body = str(renderable)
    if title:
        return f"\n{boxed_title(title)}\n{body}"
    return body


def Columns(renderables, **_kwargs):
    return "\n\n".join(str(item) for item in renderables)

DEMO_DAY_13_QUESTION = "Набросай сервис регистрации и входа пользователя. Сразу дай финальный код решения, без обсуждений и плана."
DEMO_DAY_13_MOCK = (
    "Состояние текущей задачи (task state machine) — работай строго в рамках стадии, "
    "не перескакивай этапы:\n"
    "- задача: регистрации и входа пользователя\n"
    "- стадия: planning (шаг 0)\n"
    "- ожидаемое действие: составить план и утвердить его; код будет на стадии execution\n"
    "- утверждённый план: —"
)

DEMO_DAY_14_INVARIANTS = [
    {"rule": "Стек только Python. Node.js запрещён.", "forbid": ["node.js"]},
]
DEMO_DAY_14_QUESTION = "Набросай сервис регистрации и входа пользователя на Node.js."

INTERVIEW_QUESTIONS = [
    ("предпочтения", "Какие темы любит пользователь?"),
    ("формат", "В каком формате отвечать?"),
    ("ограничения", "Что не предлагать и чего избегать?"),
]

STATUS_LABEL = {"active": "в работе", "paused": "пауза", "done": "готово"}


def complete_command_silently(event, commands):
    buffer = event.current_buffer
    text = buffer.document.text_before_cursor
    if not text.startswith("/") or " " in text:
        return
    matches = [cmd for cmd in commands if cmd.startswith(text)]
    if not matches:
        return
    target = matches[0] if len(matches) == 1 else commonprefix(matches)
    if len(target) > len(text):
        buffer.insert_text(target[len(text):])
    elif len(matches) == 1:
        buffer.insert_text(" ")


class Assistant:
    def __init__(self):
        self.model = MAIN_MODEL
        self.system = SYSTEM_PROMPT
        self.api_key = os.environ["PROXY_API_KEY"]
        self.memory = MemoryLayers()
        self.profile = Profile()
        self.state = TaskStore()
        self.invariants = Invariants()

    def call_api(self, messages, model=None):
        model = model or self.model
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": model, "messages": messages},
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"], data["usage"]

    def cost_rub(self, usage, model=None):
        model = model or self.model
        price = PRICES_RUB_PER_1M.get(model)
        if not price:
            return None
        return (usage["prompt_tokens"] * price["input"]
                + usage["completion_tokens"] * price["output"]) / 1_000_000

    def ask(self, text):
        self.memory.add_dialog("user", text)
        messages = build_messages(self.system, self.memory, self.profile,
                                  self.state, self.invariants)
        answer, usage = self.call_api(messages)
        self.memory.add_dialog("assistant", answer)
        hits = self.invariants.lint(answer)
        return answer, usage, hits


def ab_run(assistant, question, with_block, off_status):
    base = [{"role": "system", "content": assistant.system}]
    user = {"role": "user", "content": question}
    console.print(off_status)
    off_answer, _ = assistant.call_api(base + [user])
    on_answer, _ = assistant.call_api(base + [{"role": "system", "content": with_block}, user])
    return off_answer, on_answer


def format_usage_line(usage, cost=None):
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    new_tokens = max(prompt_tokens - cached_tokens, 0)
    total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
    cost_str = f" | {cost:.4f} ₽" if cost is not None else ""
    return (f"вход: {prompt_tokens} (кэш: {cached_tokens} | новые: {new_tokens}) | "
            f"выход: {completion_tokens} | итого: {total_tokens}{cost_str}")


def stage_pipeline(current=None):
    parts = []
    for i, s in enumerate(STAGES):
        if s == current:
            parts.append(f"[{NAVY_PALE} bold]\\[{s}][/{NAVY_PALE} bold]")
        else:
            parts.append(f"[dim]{s}[/dim]")
        if i < len(STAGES) - 1:
            parts.append("[dim]→[/dim]")
    return " ".join(parts)


def plain_pipeline():
    return " -> ".join(STAGES)


def active_profile_name(profile):
    if hasattr(profile, "active_name"):
        return profile.active_name
    for key in ("имя", "name", "профиль", "profile"):
        value = profile.data.get(key)
        if value:
            return str(value)
    return "Саша"


def memory_summary(memory):
    return (f"Память: краткосрочная {len(memory.short_term)} сообщений, "
            f"рабочая {len(memory.working)} записей, "
            f"долговременная {len(memory.long_term)} записей.")


PIPELINE_ROLES = {
    "planning": "уточнить цель и подготовить план",
    "execution": "выполнить задачу по плану",
    "validation": "проверить результат и дать заключение",
    "done": "подвести итог по задаче",
}


def render_pipeline_text(current_stage):
    lines = ["Pipeline:"]
    next_stages = set(TRANSITIONS.get(current_stage, []))
    for stage in STAGES:
        action = PIPELINE_ROLES[stage]
        if stage == current_stage:
            prefix = "OK"
        elif stage in next_stages:
            prefix = "next"
        else:
            prefix = "    "
        lines.append(f"{prefix} {stage}: {action}")
    return "\n".join(lines)


def render_memory(memory):
    short = "\n".join(f"[dim]{m['role']}:[/dim] {m['content']}" for m in memory.short_term) or "[dim]пусто[/dim]"
    working = "\n".join(f"[{NAVY_PALE}]{k}[/{NAVY_PALE}] = {v}" for k, v in memory.working.items()) or "[dim]пусто[/dim]"
    long_term = "\n".join(f"[{NAVY_PALE}]{k}[/{NAVY_PALE}] = {v}" for k, v in memory.long_term.items()) or "[dim]пусто[/dim]"
    body = (
        f"КРАТКОСРОЧНАЯ:\n{short}\n\n"
        f"РАБОЧАЯ:\n{working}\n\n"
        f"ДОЛГОВРЕМЕННАЯ:\n{long_term}"
    )
    return Panel(body, title="ПАМЯТЬ — три слоя, отдельные файлы", border_style=NAVY)


def render_profile(profile):
    if profile.data:
        body = f"Активный профиль: {profile.active_name}\n" + "\n".join(
            f"[{NAVY_PALE}]{k}[/{NAVY_PALE}] = {v}" for k, v in profile.data.items())
    else:
        body = f"Активный профиль: {profile.active_name}\n[dim]профиль пуст — /interview или /profile-set формат = 1 абзац[/dim]"
    return Panel(body, title="ПРОФИЛЬ — персонализация", border_style=NAVY)


def render_profiles(profile_store):
    rows = []
    for name, profile in profile_store.list_profiles().items():
        marker = "*" if name == profile_store.active_name else " "
        rows.append(f"{marker} {name}")
        if profile:
            rows.extend(f"  {key} = {value}" for key, value in profile.items())
        else:
            rows.append("  пусто")
    return Panel("\n".join(rows), title="ПРОФИЛИ", border_style=NAVY)


def render_invariants(invariants):
    if invariants.items:
        rows = []
        for i, item in enumerate(invariants.items):
            forbid = ", ".join(item["forbid"]) if item["forbid"] else "—"
            rows.append(f"{i + 1}. {item['rule']}\nстоп-слова: {forbid}")
        body = "\n".join(rows)
    else:
        body = "инвариантов нет — /invariant-add Python !== Node.js"
    return Panel(body, title="ИНВАРИАНТЫ — нерушимые, хранятся отдельно", border_style=NAVY)


def render_tasks(store):
    if not store.tasks:
        body = (f"[{NAVY_PALE}]стадии:[/{NAVY_PALE}] {stage_pipeline(None)}\n"
                "[dim]задач нет — /task <имя> создаёт и открывает рабочее пространство[/dim]")
        return Panel(body, title="ЗАДАЧИ — task state machine (мультизадачность)", border_style=NAVY)
    rows = []
    for name, task in store.tasks.items():
        marker = f" [{NAVY_PALE}](тек.)[/{NAVY_PALE}]" if name == store.current else ""
        plan = (task["plan"][:40] + "…") if task["plan"] and len(task["plan"]) > 40 else (task["plan"] or "—")
        rows.append(
            f"- {name}{marker}\n"
            f"  стадия: {task['stage']}\n"
            f"  статус: {STATUS_LABEL[task['status']]}\n"
            f"  шаг: {task['step']}\n"
            f"  план: {plan}"
        )
    return Panel("\n\n".join(rows), title="ЗАДАЧИ — task state machine (мультизадачность)", border_style=NAVY)


def show_status(assistant):
    console.print(render_tasks(assistant.state))
    console.print(render_invariants(assistant.invariants))
    console.print(render_profile(assistant.profile))
    console.print(render_memory(assistant.memory))


def parse_kv(rest, fallback_key):
    body = rest.strip()
    if not body:
        return None, None
    if "=" in body:
        key, value = (part.strip() for part in body.split("=", 1))
        return key, value
    return fallback_key, body


def run_interview(assistant):
    console.print(Panel("Стартовое интервью — соберём профиль пользователя по пунктам. "
                        "Пустой ответ = пропустить поле. Ctrl-C = выйти из интервью.",
                        title="ИНТЕРВЬЮ ДЛЯ ПРОФИЛЯ", border_style=NAVY))
    collected = 0
    for key, question in INTERVIEW_QUESTIONS:
        hint = FIELDS.get(key, "")
        console.print(Text.assemble((f"{question}\n", f"{NAVY_BRIGHT} bold"), (hint, "dim")))
        try:
            answer = pt_prompt("  › ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]интервью прервано — что успели, то сохранено[/dim]")
            break
        if answer:
            assistant.profile.set(key, answer)
            collected += 1
    console.print(Panel(f"Записано полей: {collected}. Профиль теперь подмешивается в каждый запрос.",
                        title="интервью завершено", border_style=NAVY))
    console.print(render_profile(assistant.profile))


def cmd_profile_set(assistant, rest):
    key, value = parse_kv(rest, None)
    if not key:
        console.print("[dim]Формат: /profile-set поле = значение. Поля: "
                      + ", ".join(FIELDS) + "[/dim]")
        return
    assistant.profile.set(key, value)
    console.print(Panel(f"[{NAVY_PALE}]{key}[/{NAVY_PALE}] = {value}",
                        title="→ профиль", border_style=NAVY))


def cmd_invariant_add(assistant, rest):
    body = rest.strip()
    if not body:
        console.print("[dim]Формат: /invariant-add <правило> !== стоп-слово1, стоп-слово2[/dim]")
        return
    if "!==" in body:
        rule, terms = body.split("!==", 1)
        forbid = [t.strip() for t in terms.split(",") if t.strip()]
    else:
        rule, forbid = body, []
    assistant.invariants.add(rule.strip(), forbid)
    note = ("стоп-слова: " + ", ".join(forbid)) if forbid else "без стоп-слов (ловит только критик)"
    console.print(Panel(f"{rule.strip()}\n{note}",
                        title="Инвариант", border_style=NAVY))
    console.print()


def show_workspace_header(store, name):
    task = store.tasks[name]
    forward = store.forward_target(name)
    back = store.back_target(name)
    nav = []
    if forward and forward in TRANSITIONS[task["stage"]]:
        nav.append(f"/next → {forward}")
    elif forward:
        nav.append(f"/next → {forward} [dim](после условий)[/dim]")
    if back and back in TRANSITIONS[task["stage"]]:
        nav.append(f"/back → {back}")
    nav_line = "   ".join(nav) or "дальше некуда (задача завершена)"
    body = (f"[{NAVY_PALE}]задача:[/{NAVY_PALE}] {name}   "
            f"[{NAVY_PALE}]статус:[/{NAVY_PALE}] {STATUS_LABEL[task['status']]}\n"
            f"[{NAVY_PALE}]стадии:[/{NAVY_PALE}] {stage_pipeline(task['stage'])}\n"
            f"[{NAVY_PALE}]ожидается:[/{NAVY_PALE}] {EXPECTED[task['stage']]}\n"
            f"[{NAVY_PALE}]план:[/{NAVY_PALE}] {task['plan'] or '—'}\n"
            f"[{NAVY_PALE}]навигация:[/{NAVY_PALE}] {nav_line}")
    console.print(Panel(body, title="Состояние задачи", border_style=NAVY_BRIGHT,
                        box=box.DOUBLE))


def ask_in_task(assistant, name, text):
    assistant.memory.add_dialog("user", text)
    messages = build_messages(assistant.system, assistant.memory, assistant.profile,
                              assistant.state, assistant.invariants)
    console.print("Ждем ответ...")
    answer, usage = assistant.call_api(messages)
    assistant.memory.add_dialog("assistant", answer)
    hits = assistant.invariants.lint(answer)
    console.print(Panel(answer, title=f"АССИСТЕНТ · {name}", border_style=NAVY, box=box.ROUNDED))
    turn_footer(assistant, usage, hits)


def workspace_next(assistant, name):
    store = assistant.state
    target = store.forward_target(name)
    if not target:
        console.print("[dim]Задача уже на стадии done.[/dim]")
        return
    ok, message = store.transition(name, target)
    if not ok:
        console.print(Panel(message, title="× переход отклонён кодом", border_style=WARN))
        return
    console.print(Panel(f"{message}\n[dim]{EXPECTED[target]}[/dim]",
                        title="Стадия изменена (/next)", border_style=NAVY))
    if target in STAGE_ROLES:
        run_stage_swarm(assistant, name, target)
    elif target == "done":
        show_done_report(assistant, name)


def show_done_report(assistant, name):
    task = assistant.state.tasks[name]
    plan = task["plan"] or "—"
    if task["results"]:
        results = "\n\n".join(f"[{NAVY_PALE}]шаг {i + 1}[/{NAVY_PALE}]\n{r}"
                              for i, r in enumerate(task["results"]))
    else:
        results = "[dim]результатов стадий нет[/dim]"
    console.print(Panel(f"[{NAVY_PALE}]задача:[/{NAVY_PALE}] {name}   "
                        f"[{NAVY_PALE}]шагов:[/{NAVY_PALE}] {task['step']}\n"
                        f"[{NAVY_PALE}]утверждённый план:[/{NAVY_PALE}]\n{plan}\n\n"
                        f"[{NAVY_PALE}]итоги стадий (рой):[/{NAVY_PALE}]\n{results}",
                        title=f"DONE · финальная сводка задачи «{name}»", border_style=NAVY_BRIGHT,
                        box=box.DOUBLE))


def workspace_back(assistant, name):
    store = assistant.state
    target = store.back_target(name)
    if not target:
        console.print("[dim]Назад некуда — это первая стадия.[/dim]")
        return
    ok, message = store.transition(name, target)
    if not ok:
        console.print(Panel(message, title="× переход отклонён кодом", border_style=WARN))
        return
    console.print(Panel(f"{message}\n[dim]{EXPECTED[target]}[/dim]",
                        title="→ стадия изменена (разрешил ты командой /back)", border_style=NAVY))
    if target in STAGE_ROLES:
        run_stage_swarm(assistant, name, target)


STAGE_RESULT_HINT = {
    "planning": "Примите решение: /next в execution (код пустит, т.к. план утверждён).",
    "execution": "Результат выполнение. Если всё правильно: /next в validation.",
    "validation": "Результат валидации. Если всё правильно: /next в done.",
}


def run_stage_swarm(assistant, name, stage):
    store = assistant.state
    if stage not in STAGE_ROLES:
        return
    task = store.tasks[name]
    roles = STAGE_ROLES[stage]
    roles_n = len(roles)
    prev_result = task["results"][-1] if task["results"] else None
    profile_text = "\n".join(f"- {k}: {v}" for k, v in assistant.profile.data.items())
    console.print(Panel(
        f"Задача: [bold]{name}[/bold]   стадия: [bold]{stage}[/bold]\n"
        f"Рой из [bold]{roles_n}[/bold] агентов ([dim]{MEMBER_MODEL}[/dim]) — каждый со своей стороны: "
        + ", ".join(r for r, _ in roles) + ".\n"
        f"[dim]Оркестратор ({assistant.model}) знает запрос, профиль, инварианты, план и прошлые стадии — "
        "сведёт мнения и возразит при конфликте. Стадию двигаешь только ты командой /next.[/dim]",
        title=stage.capitalize(), border_style=NAVY))
    console.print("Ждем ответ...")
    opinions, synthesis, member_usage, orch_usage = run_swarm(
        assistant.api_key, stage, name, task["plan"], prev_result,
        assistant.invariants.items, profile_text)
    console.print(Columns([Panel(o["text"], title=o["role"], border_style=NAVY_DIM) for o in opinions],
                          equal=True, expand=True))
    console.print(Panel(synthesis, title="Оркестратор",
                        border_style=NAVY_BRIGHT, box=box.DOUBLE))
    if stage == "planning":
        store.set_plan(name, synthesis)
    else:
        store.add_result(name, f"[{stage}] {synthesis}")
    member_cost = assistant.cost_rub(member_usage, MEMBER_MODEL)
    orch_cost = assistant.cost_rub(orch_usage)
    console.print(Text(
        f"рой ({MEMBER_MODEL} ×{roles_n}): {format_usage_line(member_usage, member_cost)}\n"
        f"оркестратор ({assistant.model}): {format_usage_line(orch_usage, orch_cost)}",
        style="dim"))
    console.print(Panel(STAGE_RESULT_HINT[stage], title=f"{stage.capitalize()}: получен результат", border_style=NAVY))


def handle_workspace_cmd(assistant, name, cmd, rest):
    store = assistant.state
    if cmd == "council":
        run_stage_swarm(assistant, name, store.tasks[name]["stage"])
    elif cmd == "plan":
        if not rest:
            console.print("[dim]Формат: /plan <текст плана>[/dim]")
            return False
        store.set_plan(name, rest)
        console.print(Panel(rest, title="→ план утверждён (теперь /next в execution)", border_style=NAVY))
    elif cmd == "next":
        workspace_next(assistant, name)
    elif cmd == "back":
        workspace_back(assistant, name)
    elif cmd in ("status", "show"):
        show_workspace_header(store, name)
    elif cmd == "help":
        return False
    elif cmd == "pause":
        store.pause(name)
        console.print(Panel(f"Задача «{name}» приостановлена (статус: пауза). "
                            f"Вернёшься — /task {name}.",
                            title="задача на паузе", border_style=NAVY))
        return True
    elif cmd == "delete":
        store.delete(name)
        console.print(Panel(f"Задача «{name}» удалена.", title="задача удалена", border_style=WARN))
        return True
    elif cmd == "exit":
        return True
    else:
        console.print(f"[dim]Неизвестная команда /{cmd}. Внутри задачи: /help.[/dim]")
    return False


def run_workspace(assistant, name, fresh=False):
    store = assistant.state
    store.enter(name)
    show_workspace_header(store, name)
    if fresh:
        run_stage_swarm(assistant, name, "planning")
    bindings = KeyBindings()

    @bindings.add("tab")
    def _(event):
        complete_command_silently(event, WORKSPACE_COMMANDS)

    session = PromptSession(key_bindings=bindings, style=MENU_STYLE)
    left_into_main = False
    while True:
        try:
            line = session.prompt(HTML("<prompt>Ты:</prompt> ")).strip()
        except (EOFError, KeyboardInterrupt):
            store.leave()
            left_into_main = True
            break
        if line == "" or line.lower() == "exit":
            store.leave()
            left_into_main = True
            break
        if line.startswith("/"):
            wcmd, _, wrest = line[1:].partition(" ")
            if wcmd.lower() == "exit":
                store.leave()
                left_into_main = True
                break
            done = handle_workspace_cmd(assistant, name, wcmd.lower(), wrest.strip())
            if done:
                break
            continue
        ask_in_task(assistant, name, line)
    if left_into_main:
        console.print(f"[dim]Вышел из задачи «{name}». Она осталась в списке. Вернулся в общий чат.[/dim]")


def cmd_task(assistant, rest):
    name = rest.strip()
    store = assistant.state
    if not name:
        console.print(render_tasks(store))
        console.print("[dim]Открыть/создать: /task <имя>[/dim]")
        return
    fresh = not store.exists(name)
    if fresh:
        store.create(name)
        console.print(Panel(f"Создана задача: [bold]{name}[/bold]\n"
                            f"Стадии: {stage_pipeline('planning')}\n"
                            "[dim]Сейчас на стадии planning отработает рой агентов. Дальше двигаешь ты — /next.[/dim]",
                            title="Новая задача", border_style=NAVY))
    run_workspace(assistant, name, fresh)


def run_demo_state(assistant, question="", show_extra=True):
    question = question.strip() or DEMO_DAY_13_QUESTION
    current = assistant.state.current_task()
    active = current is not None
    block = assistant.state.as_prompt() if active else DEMO_DAY_13_MOCK
    stage = current["stage"] if active else "planning"
    console.print()
    console.print(render_pipeline_text(stage))
    console.print()

    console.print(Panel(f"Запрос двум агентам с состоянием и без: {question}",
                        title="ВЛИЯНИЕ СОСТОЯНИЯ НА ОТВЕТ", border_style=NAVY))
    off, on = ab_run(assistant, question, block, "Ждем ответ...")
    console.print(Columns([
        Panel(off, title="БЕЗ СОСТОЯНИЯ", border_style=NAVY_DIM),
        Panel(f"[red][{stage.capitalize()}]:[/red]\n{on}", title="С СОСТОЯНИЕМ", border_style=NAVY_BRIGHT),
    ], equal=True, expand=True))

    if not show_extra:
        return

    demo = TaskStore(ephemeral=True)
    demo.create("проверка переходов")
    _, msg_jump = demo.transition("проверка переходов", "done")
    demo.set_plan("проверка переходов", "план")
    _, msg_step = demo.transition("проверка переходов", "execution")
    console.print(Panel(
        f"[{WARN}]×[/{WARN}] /next через этап (planning→done): {msg_jump}\n"
        f"[{NAVY_PALE}]✓[/{NAVY_PALE}] planning→execution (план есть): {msg_step}\n"
        "[dim]Легальность переходов проверяет КОД (state.py), не промпт — нелегальный отклоняется.[/dim]",
        title="ПЕРЕХОДЫ ПОД КОНТРОЛЕМ КОДА", border_style=NAVY))
    console.print(Panel(
        "[bold]Пауза:[/bold] /pause внутри задачи или просто выход — стадия и план пишутся в "
        "store/state.json.\n[bold]Продолжение без повторных объяснений:[/bold] /task <имя> снова — "
        "агент грузит стадию, план и результаты и продолжает с того же места.\n"
        "[dim]Несколько задач живут параллельно — список со статусами показывает /task без имени.[/dim]",
        title="ПАУЗА, ПРОДОЛЖЕНИЕ, МУЛЬТИЗАДАЧНОСТЬ", border_style=NAVY))


def run_demo_invariants(assistant, question=""):
    question = question.strip() or DEMO_DAY_14_QUESTION
    using_sample = not assistant.invariants.items
    items = list(DEMO_DAY_14_INVARIANTS) if using_sample else assistant.invariants.items
    rules = "\n".join(f"{i + 1}. {it['rule']}" for i, it in enumerate(items))

    console.print(Panel(f"Список инвариантов:\n{rules}\n\n"
                        f"Один и тот же запрос: {question}",
                        title="ВЛИЯНИЕ ИНВАРИАНТОВ НА ОТВЕТ", border_style=NAVY))
    block = ("ИНВАРИАНТЫ — нерушимые ограничения. Если запрос им противоречит — откажись и объясни, "
             "какой инвариант нарушается:\n" + rules)
    off, on = ab_run(assistant, question, block, "Ждем ответ...")
    console.print(Columns([
        Panel(off, title="БЕЗ ИНВАРИАНТОВ", border_style=NAVY_DIM),
        Panel(on, title="С ИНВАРИАНТАМИ", border_style=NAVY_BRIGHT),
    ], equal=True, expand=True))

    temp = Invariants.__new__(Invariants)
    temp.items = items
    hits = temp.lint(off)
    code_body = ("нарушений не найдено" if not hits else
                 "\n".join(f"[{WARN}]×[/{WARN}] «{h['term']}» → {h['rule']}" for h in hits))
    console.print(Panel(code_body, title="ЛИНТЕР (ответ БЕЗ инвариантов)", border_style=NAVY))
    console.print("Ждем ответ...")
    verdict, usage = critic_check(assistant.api_key, items, off)
    which = "\n".join(f"  · {w}" for w in verdict.get("which", []))
    verdict_body = (f"нарушено: [bold]{verdict.get('violated')}[/bold]\n"
                    f"почему: {verdict.get('why', '')}\n{which}\n"
                    f"[dim]{format_usage_line(usage, assistant.cost_rub(usage))}[/dim]")
    console.print(Panel(verdict_body, title="LLM-КРИТИК", border_style=NAVY))


def run_demo_transitions():
    states = "\n".join(
        f"- {s}: {EXPECTED[s]} | переходы: {', '.join(TRANSITIONS[s]) or '— (терминальное)'}"
        for s in STAGES
    )
    console.print(Panel(states, title="ДОПУСТИМЫЕ СОСТОЯНИЯ И РАЗРЕШЁННЫЕ ПЕРЕХОДЫ (state.py)",
                        border_style=NAVY))
    console.print(Panel(f"Конвейер: {stage_pipeline(None)}\n"
                        "[dim]Легальность перехода решает КОД (TaskStore.transition), не промпт. "
                        "Конспект: «для жёстких запретов нужен код — текстовые правила теряются после "
                        "summary/compacting».[/dim]",
                        title="контролируемый жизненный цикл задачи", border_style=NAVY))

    demo = TaskStore(ephemeral=True)
    demo.create("демо-задача")
    rows = []
    _, msg = demo.transition("демо-задача", "done")
    rows.append(("planning → done (перепрыгнуть через 2 этапа)", msg))
    _, msg = demo.transition("демо-задача", "validation")
    rows.append(("planning → validation (перепрыгнуть execution)", msg))
    _, msg = demo.transition("демо-задача", "execution")
    rows.append(("planning → execution БЕЗ утверждённого плана", msg))
    illegal = "\n".join(
        f"[{WARN}]×[/{WARN}] {label}\n    [dim]ответ кода:[/dim] {msg}" for label, msg in rows)
    console.print(Panel(illegal + "\n\n[dim]Каждая попытка «перепрыгнуть» отклонена детерминированно — "
                        "состояние задачи не изменилось.[/dim]",
                        title="ПОПЫТКИ ПЕРЕЙТИ В НЕДОПУСТИМОЕ СОСТОЯНИЕ → отказ кода", border_style=WARN))

    legal = []
    demo.set_plan("демо-задача", "1) роуты 2) JWT 3) хранилище")
    legal.append(("план утверждён", "теперь execution разблокирован"))
    for target in ("execution", "validation", "done"):
        ok, msg = demo.transition("демо-задача", target)
        legal.append((msg, "ok" if ok else "ОТКАЗ"))
    _, msg_term = demo.transition("демо-задача", "execution")
    legal_body = "\n".join(f"[{NAVY_PALE}]✓[/{NAVY_PALE}] {a} [dim]({b})[/dim]" for a, b in legal)
    legal_body += f"\n[{WARN}]×[/{WARN}] done → execution: {msg_term} [dim](done терминально)[/dim]"
    console.print(Panel(legal_body, title="ЛЕГАЛЬНЫЙ ПУТЬ (planning→execution→validation→done) проходит",
                        border_style=NAVY))

    paused = TaskStore(ephemeral=True)
    paused.create("оплата")
    paused.set_plan("оплата", "1) выбрать провайдера 2) вебхуки 3) идемпотентность")
    paused.transition("оплата", "execution")
    paused.add_result("оплата", "набросал роуты платежей")
    paused.pause("оплата")
    snap = paused.tasks["оплата"]
    paused.enter("оплата")
    after = paused.tasks["оплата"]
    console.print(Panel(
        f"[bold]Пауза[/bold] (/pause или выход): статус → [{NAVY_PALE}]{STATUS_LABEL[snap['status']]}[/{NAVY_PALE}], "
        f"стадия [{NAVY_PALE}]{snap['stage']}[/{NAVY_PALE}], план и результаты записаны в store/state.json.\n"
        f"[bold]Продолжение[/bold] (/task оплата): статус → [{NAVY_PALE}]{STATUS_LABEL[after['status']]}[/{NAVY_PALE}], "
        f"стадия [{NAVY_PALE}]{after['stage']}[/{NAVY_PALE}], план «{after['plan']}», "
        f"результатов: {len(after['results'])}.\n"
        "[dim]Агент поднимает стадию, план и результаты — продолжает с того же места без повторных объяснений.[/dim]",
        title="ПАУЗА И КОРРЕКТНОЕ ПРОДОЛЖЕНИЕ", border_style=NAVY))
    console.print("[dim]Реакция ассистента вживую: на стадии planning блок состояния в промпте заставляет LLM "
                  "не выдавать финальный код, а вернуть к плану (см. /demo3). Жёсткий стоп — всё равно код выше.[/dim]")


def turn_footer(assistant, usage, hits):
    cost = assistant.cost_rub(usage)
    console.print(Text(format_usage_line(usage, cost), style="dim"))
    if hits:
        warn = "; ".join(f"«{h['term']}» → {h['rule']}" for h in hits)
        console.print(Panel(f"код-линтер: ответ задевает инвариант — {warn}",
                            title="внимание", border_style=WARN))


def handle_command(assistant, name, rest):
    if name == "help":
        return
    elif name == "status":
        show_status(assistant)
    elif name == "task":
        cmd_task(assistant, rest)
    elif name == "interview":
        run_interview(assistant)
    elif name in ("remember-forever", "add-longterm"):
        key, value = parse_kv(rest, assistant.memory.next_long_key())
        if not key:
            console.print("[dim]Формат: /add-longterm название = содержимое[/dim]")
            return
        assistant.memory.remember_forever(key, value)
        console.print(Panel(f"[{NAVY_PALE}]{key}[/{NAVY_PALE}] = {value}",
                            title="→ долговременная память", border_style=NAVY))
    elif name in ("remember-now", "add-working"):
        fallback = assistant.memory.next_working_key()
        key, value = parse_kv(rest, fallback)
        if not key:
            console.print("[dim]Формат: /add-working название = содержимое[/dim]")
            return
        assistant.memory.set_working(key, value)
        console.print(Panel(f"[{NAVY_PALE}]{key}[/{NAVY_PALE}] = {value}",
                            title="→ рабочая память", border_style=NAVY))
    elif name == "clear-working":
        assistant.memory.clear_working()
        console.print(Panel("Рабочая память очищена.", border_style=NAVY))
    elif name == "clear-longterm":
        assistant.memory.clear_long_term()
        console.print(Panel("Долговременная память очищена.", border_style=NAVY))
    elif name == "profile":
        if not rest.strip():
            console.print(f"Активный профиль: {assistant.profile.active_name}")
            return
        assistant.profile.switch(rest.strip())
        console.print(f"[Активный профиль: {assistant.profile.active_name}]")
    elif name == "profile-set":
        cmd_profile_set(assistant, rest)
    elif name == "profile-unset":
        key = rest.strip()
        console.print("[Удалено]" if assistant.profile.unset(key) else "[Такого поля не было]")
    elif name == "profiles":
        console.print(render_profiles(assistant.profile))
    elif name == "profile-clear":
        assistant.profile.clear_active()
        console.print(f"[Профиль {assistant.profile.active_name} очищен]")
    elif name == "invariant-add":
        cmd_invariant_add(assistant, rest)
    elif name == "demo3":
        run_demo_state(assistant, rest)
    elif name == "demo" and rest.strip().lower() == "day13":
        run_demo_state(assistant, "", show_extra=False)
    elif name == "demo" and rest.strip().lower() == "day14":
        run_demo_invariants(assistant, "")
    elif name == "demo" and rest.strip().lower() == "day15":
        run_demo_transitions()
    elif name == "reset":
        assistant.memory.reset()
        assistant.profile.clear()
        assistant.state.reset()
        assistant.invariants.clear()
        console.print(Panel("Стёрто всё: задачи, инварианты, профиль, память.", border_style=NAVY))
    else:
        console.print(f"[dim]Неизвестная команда /{name}. Набери /help.[/dim]")


def banner(assistant):
    s = assistant
    lines = [
        "___ДЕНЬ 14. ИНВАРИАНТЫ И ОГРАНИЧЕНИЯ СОСТОЯНИЯ___",
        "",
        f"Активный профиль: {active_profile_name(s.profile)}",
        memory_summary(s.memory),
        f"Pipeline: {plain_pipeline()}",
        f"Модель: {s.model}",
    ]
    console.print("\n".join(lines))
    console.print()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    assistant = Assistant()
    banner(assistant)
    bindings = KeyBindings()

    @bindings.add("tab")
    def _(event):
        complete_command_silently(event, COMMANDS)

    session = PromptSession(key_bindings=bindings, style=MENU_STYLE)
    while True:
        try:
            user = session.prompt(HTML("<prompt>Ты:</prompt> ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user == "" or user.lower() in ("exit", "/exit"):
            break
        if user.startswith("/"):
            parts = user[1:].split(maxsplit=1)
            handle_command(assistant, parts[0].lower() if parts else "",
                           parts[1] if len(parts) > 1 else "")
            continue
        console.print("Ждем ответ...")
        answer, usage, hits = assistant.ask(user)
        console.print(Panel(answer, title="АССИСТЕНТ", border_style=NAVY, box=box.ROUNDED))
        turn_footer(assistant, usage, hits)


if __name__ == "__main__":
    main()
