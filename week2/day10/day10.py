import copy
import json
import os
import sys
from pathlib import Path

import requests

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
MODEL = "gpt-4o-mini"
FACTS_MODEL = "gpt-4o-mini"
HISTORY_PATH = Path(__file__).parent / "history_day10.json"

CONTEXT_LIMIT = 128000
WARNING_PERCENT = 80
WINDOW_N = 6
MAX_COMPLETION_TOKENS = 1000
MAX_FACTS_TOKENS = 600

STRATEGIES = ("sliding", "facts", "branching")

PRICES_RUB_PER_1M = {
    MODEL: {"input": 39, "output": 155},
    FACTS_MODEL: {"input": 39, "output": 155},
}

SYSTEM_MESSAGE = (
    "Ты — полезный агент для сбора и уточнения требований. "
    "Отвечай только на русском языке. Отвечай по существу, без лишней воды. "
    "Не выдумывай факты: если детали нет в контексте, прямо скажи, что её не хватает."
)

FACTS_SYSTEM_MESSAGE = (
    "Ты обновляешь долговременную память агента в формате JSON ключ-значение. "
    "Тебе дают текущие facts, последние сообщения диалога и новое сообщение пользователя. "
    "Верни ОБНОВЛЁННЫЙ JSON-объект целиком. "
    "Сохраняй только важные данные: цель, ограничения, предпочтения, решения, договорённости, "
    "сроки, бюджет, роли, платформы, технологии, важные числа и открытые вопросы. "
    "Не выдумывай то, чего нет в диалоге. Удаляй устаревшие факты, если пользователь их изменил. "
    "Ключи и значения пиши короткими строками на русском языке. "
    "Ответ верни только JSON-объектом, без markdown и пояснений."
)

FACTS_PREFIX = (
    "Ниже facts — отдельная key-value память агента. "
    "Используй её как важные устойчивые детали диалога:\n"
)

STRATEGY_DESCRIPTIONS = {
    "sliding": (
        "Sliding Window — в запрос отправляются только последние N сообщений. "
        "Старые сообщения отбрасываются."
    ),
    "facts": (
        "Sticky Facts / Key-Value Memory — после каждого сообщения пользователя обновляется блок facts. "
        "В запрос отправляются facts + последние N сообщений."
    ),
    "branching": (
        "Branching — можно сохранить checkpoint, создать от него ветки и вести каждую ветку независимо. "
        "В запрос отправляется история текущей ветки."
    ),
}


class TokenCounter:
    def __init__(self, model=MODEL):
        self.encoder = None
        try:
            import tiktoken
            try:
                self.encoder = tiktoken.encoding_for_model(model)
            except KeyError:
                self.encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            self.encoder = None

    def text(self, value):
        if not value:
            return 0
        if self.encoder:
            return len(self.encoder.encode(str(value)))
        return max(1, len(str(value)) // 4)

    def one_message(self, message):
        return (
            4
            + self.text(message.get("role", ""))
            + self.text(message.get("content", ""))
        )

    def messages(self, messages):
        # Приближённая формула для chat messages:
        # текст + небольшой служебный overhead на role/content.
        total = 2
        for message in messages:
            total += self.one_message(message)
        return total


class Agent:
    def __init__(
        self,
        model=MODEL,
        facts_model=FACTS_MODEL,
        history_path=HISTORY_PATH,
        context_limit=CONTEXT_LIMIT,
        window_n=WINDOW_N,
        strategy="sliding",
        system_message=SYSTEM_MESSAGE,
    ):
        if strategy not in STRATEGIES:
            raise ValueError(f"Неизвестная стратегия: {strategy}")

        self.model = model
        self.facts_model = facts_model
        self.history_path = Path(history_path)
        self.context_limit = context_limit
        self.window_n = window_n
        self.strategy = strategy
        self.system_message = system_message
        self.api_key = os.environ.get("PROXY_API_KEY") or os.environ.get("PROXYAPI_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Не найден API-ключ. Добавь переменную окружения PROXY_API_KEY или PROXYAPI_KEY."
            )

        self.counter = TokenCounter(model)
        self.branches = {}
        self.current_branch = "main"
        self.checkpoint = None
        self.facts = {}
        self.turns = []
        self.last_facts_update = None
        self.load()

    @property
    def messages(self):
        return self.branches[self.current_branch]

    def fresh(self):
        self.branches = {"main": []}
        self.current_branch = "main"
        self.checkpoint = None
        self.facts = {}
        self.turns = []
        self.last_facts_update = None

    def load(self):
        if not self.history_path.exists():
            self.fresh()
            return

        try:
            state = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.fresh()
            return

        self.strategy = state.get("strategy", self.strategy)
        if self.strategy not in STRATEGIES:
            self.strategy = "sliding"

        self.window_n = int(state.get("window_n", self.window_n))
        self.branches = state.get("branches", {"main": []})
        if not self.branches:
            self.branches = {"main": []}
        self.current_branch = state.get("current_branch", "main")
        if self.current_branch not in self.branches:
            self.current_branch = "main"
        self.checkpoint = state.get("checkpoint")
        self.facts = state.get("facts", {})
        self.turns = state.get("turns", [])
        self.last_facts_update = None

    def save(self):
        state = {
            "strategy": self.strategy,
            "window_n": self.window_n,
            "branches": self.branches,
            "current_branch": self.current_branch,
            "checkpoint": self.checkpoint,
            "facts": self.facts,
            "turns": self.turns,
            "settings": {
                "context_limit": self.context_limit,
                "model": self.model,
                "facts_model": self.facts_model,
            },
        }
        self.history_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def reset(self):
        self.fresh()
        self.history_path.unlink(missing_ok=True)

    def set_strategy(self, strategy):
        if strategy not in STRATEGIES:
            raise ValueError(f"Неизвестная стратегия: {strategy}")
        self.strategy = strategy
        self.save()

    def set_window(self, window_n):
        if window_n < 1:
            raise ValueError("Размер окна должен быть больше 0")
        self.window_n = window_n
        self.save()

    def live_messages(self):
        return self.messages

    def system_messages(self):
        return [{"role": "system", "content": self.system_message}]

    def facts_message(self):
        if not self.facts:
            return None
        facts_text = json.dumps(self.facts, ensure_ascii=False, indent=2)
        return {"role": "system", "content": FACTS_PREFIX + facts_text}

    def request_messages(self):
        result = self.system_messages()

        if self.strategy == "branching":
            result.extend(self.live_messages())
            return result

        if self.strategy == "facts":
            facts = self.facts_message()
            if facts:
                result.append(facts)

        result.extend(self.live_messages()[-self.window_n:])
        return result

    def full_history_messages(self):
        return self.system_messages() + self.live_messages()

    def request_prompt_tokens_estimate(self):
        return self.counter.messages(self.request_messages())

    def full_prompt_tokens_estimate(self):
        return self.counter.messages(self.full_history_messages())

    def context_percent(self):
        return round(self.request_prompt_tokens_estimate() / self.context_limit * 100)

    def cost_rub(self, model, prompt_tokens, completion_tokens):
        price = PRICES_RUB_PER_1M.get(model, PRICES_RUB_PER_1M[MODEL])
        return (prompt_tokens * price["input"] + completion_tokens * price["output"]) / 1_000_000

    def total_spent_rub(self):
        return sum(turn.get("cost_rub", 0) for turn in self.turns)

    def total_answer_spent_rub(self):
        return sum(turn.get("cost_rub", 0) for turn in self.turns if turn.get("kind") == "answer")

    def total_facts_spent_rub(self):
        return sum(turn.get("cost_rub", 0) for turn in self.turns if turn.get("kind") == "facts")

    def call_api(self, model, messages, max_tokens=MAX_COMPLETION_TOKENS, temperature=None):
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )

        # Некоторые новые модели принимают max_completion_tokens вместо max_tokens.
        # Для gpt-4o-mini обычно работает max_tokens, но fallback делает файл устойчивее.
        if response.status_code == 400 and "max_completion_tokens" in response.text:
            payload.pop("max_tokens", None)
            payload["max_completion_tokens"] = max_tokens
            response = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )

        response.raise_for_status()
        return response.json()

    def parse_json_object(self, text):
        text = (text or "").strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start:end + 1])
            raise

    def normalize_facts(self, value):
        if not isinstance(value, dict):
            return self.facts

        normalized = {}
        for key, item in value.items():
            if item is None:
                continue
            key = str(key).strip()
            if not key:
                continue
            if isinstance(item, (dict, list)):
                item = json.dumps(item, ensure_ascii=False)
            item = str(item).strip()
            if item:
                normalized[key] = item
        return normalized

    def update_facts(self, new_user_text):
        recent_messages = self.live_messages()[-self.window_n:]
        recent_text = "\n".join(
            f"{'Пользователь' if message['role'] == 'user' else 'Ассистент'}: {message['content']}"
            for message in recent_messages
        )
        prompt = (
            "Текущие facts:\n"
            f"{json.dumps(self.facts, ensure_ascii=False, indent=2)}\n\n"
            "Последние сообщения диалога:\n"
            f"{recent_text}\n\n"
            "Новое сообщение пользователя:\n"
            f"{new_user_text}\n\n"
            "Верни обновлённый JSON целиком."
        )
        messages = [
            {"role": "system", "content": FACTS_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ]

        data = self.call_api(
            self.facts_model,
            messages,
            max_tokens=MAX_FACTS_TOKENS,
            temperature=0,
        )
        answer = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", self.counter.messages(messages))
        completion_tokens = usage.get("completion_tokens", self.counter.text(answer))
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
        cost = self.cost_rub(self.facts_model, prompt_tokens, completion_tokens)

        parse_ok = True
        try:
            parsed = self.parse_json_object(answer)
            self.facts = self.normalize_facts(parsed)
        except (json.JSONDecodeError, TypeError):
            parse_ok = False

        turn = {
            "kind": "facts",
            "strategy": self.strategy,
            "branch": self.current_branch,
            "model": self.facts_model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_rub": cost,
            "facts_count": len(self.facts),
            "parse_ok": parse_ok,
        }
        self.turns.append(turn)
        self.last_facts_update = turn
        self.save()
        return turn

    def ask(self, user_text):
        self.last_facts_update = None
        request_tokens_local = self.counter.text(user_text)
        tokens_before = self.request_prompt_tokens_estimate()

        user_message = {"role": "user", "content": user_text}
        self.messages.append(user_message)

        if self.strategy == "facts":
            self.update_facts(user_text)

        request_messages = self.request_messages()
        full_prompt_tokens_estimate = self.full_prompt_tokens_estimate()

        data = self.call_api(
            self.model,
            request_messages,
            max_tokens=MAX_COMPLETION_TOKENS,
        )
        answer = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        prompt_tokens = usage.get("prompt_tokens", self.counter.messages(request_messages))
        completion_tokens = usage.get("completion_tokens", self.counter.text(answer))
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
        cost = self.cost_rub(self.model, prompt_tokens, completion_tokens)

        assistant_message = {"role": "assistant", "content": answer}
        self.messages.append(assistant_message)

        turn = {
            "kind": "answer",
            "strategy": self.strategy,
            "branch": self.current_branch,
            "model": self.model,
            "request_tokens": request_tokens_local,
            "prompt_tokens": prompt_tokens,
            "full_prompt_tokens_estimate": full_prompt_tokens_estimate,
            "saved_prompt_tokens_estimate": max(0, full_prompt_tokens_estimate - prompt_tokens),
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "tokens_before": tokens_before,
            "tokens_after": self.request_prompt_tokens_estimate(),
            "cost_rub": cost,
        }
        self.turns.append(turn)
        self.save()
        return answer

    def make_checkpoint(self, name=None):
        if not name:
            name = f"checkpoint_{len(self.live_messages())}"
        self.checkpoint = {
            "name": name,
            "branch": self.current_branch,
            "messages": copy.deepcopy(self.live_messages()),
        }
        self.save()
        return self.checkpoint

    def branch(self, name):
        name = name.strip()
        if not name:
            raise ValueError("Название ветки не должно быть пустым")
        if name in self.branches:
            raise ValueError(f"Ветка уже существует: {name}")
        if not self.checkpoint:
            self.make_checkpoint("auto_checkpoint")
        self.branches[name] = copy.deepcopy(self.checkpoint["messages"])
        self.current_branch = name
        self.save()

    def switch(self, name):
        if name not in self.branches:
            raise ValueError(f"Нет такой ветки: {name}")
        self.current_branch = name
        self.save()


def message_word(number):
    if 11 <= number % 100 <= 14:
        return "сообщений"
    if number % 10 == 1:
        return "сообщение"
    if 2 <= number % 10 <= 4:
        return "сообщения"
    return "сообщений"


def strategy_name(value):
    return {
        "sliding": "Sliding Window",
        "facts": "Sticky Facts",
        "branching": "Branching",
    }.get(value, value)


def print_help():
    print("Команды:")
    print("/strategy — показать текущую стратегию")
    print("/strategy sliding — включить Sliding Window")
    print("/strategy facts — включить Sticky Facts / Key-Value Memory")
    print("/strategy branching — включить Branching")
    print("/window N — изменить размер окна последних сообщений")
    print("/facts — показать текущий блок facts")
    print("/checkpoint [name] — сохранить checkpoint текущей ветки")
    print("/branch NAME — создать ветку от checkpoint и переключиться на неё")
    print("/switch NAME — переключиться на ветку")
    print("/branches — показать ветки")
    print("/stats — таблица токенов и стоимости")
    print("/compare — прогнать одинаковый сценарий на 3 стратегиях и сравнить")
    print("/reset — очистить историю, facts, checkpoint и ветки")
    print("/help — список команд")
    print("/exit — выход")


def print_turn_stats(agent):
    answer_turns = [turn for turn in agent.turns if turn.get("kind") == "answer"]
    if not answer_turns:
        return

    turn = answer_turns[-1]
    fill = round(
        (
            turn["request_tokens"]
            + turn["prompt_tokens"]
            + turn["completion_tokens"]
        )
        / (agent.context_limit + 10000)
        * 100
    )

    print(
        f"[Стратегия: {strategy_name(turn['strategy'])}. "
        f"Ветка: {turn['branch']}. Окно: {agent.window_n} сообщений]"
    )
    print(
        f"[Токены вход: {turn['request_tokens']}. "
        f"Токены вход с контекстом: {turn['prompt_tokens']}. "
        f"Токены выход: {turn['completion_tokens']}. "
        f"Цена запроса: {turn['cost_rub']:.4f} ₽]"
    )

    if turn["strategy"] in ("sliding", "facts"):
        print(
            f"[Полная история была бы примерно: "
            f"{turn['full_prompt_tokens_estimate']} токенов. "
            f"Экономия окна: ~{turn['saved_prompt_tokens_estimate']} токенов]"
        )

    if agent.last_facts_update:
        facts = agent.last_facts_update
        status = "ок" if facts.get("parse_ok") else "JSON не распознан, facts оставлены как были"
        print(
            f"[FACTS: {status}. Ключей: {facts.get('facts_count', 0)}. "
            f"Токены вход: {facts.get('prompt_tokens', 0)}. "
            f"Токены выход: {facts.get('completion_tokens', 0)}. "
            f"Цена обновления: {facts.get('cost_rub', 0):.4f} ₽]"
        )

    if fill >= WARNING_PERCENT:
        print(f"[ВНИМАНИЕ: контекст заполнен больше {WARNING_PERCENT}%]")
    print()


def print_dialog_stats(agent):
    if not agent.turns:
        print("[Ходов ещё не было]\n")
        return

    print(
        f"{'№':>3} | {'тип':>7} | {'стратегия':>10} | {'ветка':>10} | "
        f"{'вход':>8} | {'полная история':>14} | {'экономия':>9} | "
        f"{'выход':>6} | {'цена ₽':>8}"
    )
    print("-" * 100)

    for number, turn in enumerate(agent.turns, 1):
        kind = "ответ" if turn.get("kind") == "answer" else "facts"
        prompt_tokens = turn.get("prompt_tokens", 0)
        full_prompt = turn.get("full_prompt_tokens_estimate", "—")
        saved = turn.get("saved_prompt_tokens_estimate", "—")
        completion = turn.get("completion_tokens", 0)
        print(
            f"{number:>3} | "
            f"{kind:>7} | "
            f"{turn.get('strategy', '—'):>10} | "
            f"{turn.get('branch', '—'):>10} | "
            f"{prompt_tokens:>8} | "
            f"{str(full_prompt):>14} | "
            f"{str(saved):>9} | "
            f"{completion:>6} | "
            f"{turn.get('cost_rub', 0):>8.4f}"
        )

    answer_input = sum(turn.get("prompt_tokens", 0) for turn in agent.turns if turn.get("kind") == "answer")
    answer_output = sum(turn.get("completion_tokens", 0) for turn in agent.turns if turn.get("kind") == "answer")
    facts_input = sum(turn.get("prompt_tokens", 0) for turn in agent.turns if turn.get("kind") == "facts")
    facts_output = sum(turn.get("completion_tokens", 0) for turn in agent.turns if turn.get("kind") == "facts")
    full_history_input = sum(
        turn.get("full_prompt_tokens_estimate", 0)
        for turn in agent.turns
        if turn.get("kind") == "answer"
    )
    saved = sum(
        turn.get("saved_prompt_tokens_estimate", 0)
        for turn in agent.turns
        if turn.get("kind") == "answer"
    )

    print()
    print(f"Токены ответов: вход {answer_input}, выход {answer_output}")
    print(f"Токены обновления facts: вход {facts_input}, выход {facts_output}")
    print(f"Полная история без стратегии окна/facts была бы примерно: {full_history_input}")
    print(f"Экономия входных токенов на ответах, примерно: {saved}")
    print(f"Цена ответов: {agent.total_answer_spent_rub():.4f} ₽")
    print(f"Цена обновления facts: {agent.total_facts_spent_rub():.4f} ₽")
    print(f"Итого за диалог: {agent.total_spent_rub():.4f} ₽\n")


def print_facts(agent):
    if not agent.facts:
        print("\n[FACTS пока пустые]\n")
        return
    print("\n[FACTS]")
    for key, value in agent.facts.items():
        print(f"- {key}: {value}")
    print()


def print_branches(agent):
    print("\n[ВЕТКИ]")
    for name, messages in agent.branches.items():
        marker = "*" if name == agent.current_branch else " "
        print(f"{marker} {name}: {len(messages)} {message_word(len(messages))}")
    if agent.checkpoint:
        print(
            f"Checkpoint: {agent.checkpoint.get('name')} "
            f"из ветки {agent.checkpoint.get('branch')} "
            f"({len(agent.checkpoint.get('messages', []))} сообщений)"
        )
    else:
        print("Checkpoint: нет")
    print()


SPEC_MESSAGES = [
    "Делаем сервис онлайн-записи к барберам. Цель — MVP для одной сети из 5 салонов.",
    "Бюджет проекта — 450 тысяч рублей.",
    "Срок запуска — 6 недель, демо нужно через 3 недели.",
    "Платформа — веб-приложение, мобильные приложения не делаем.",
    "Авторизация — по номеру телефона через СМС-код.",
    "Главные роли: клиент, барбер, администратор.",
    "Клиент выбирает салон, услугу, барбера, дату и время.",
    "Администратор управляет расписанием, услугами и ценами.",
    "Нужно отправлять напоминание клиенту за 2 часа до визита.",
    "Оплата на первом этапе только в салоне, онлайн-оплату не подключаем.",
    "Фирменный стиль: чёрный фон, золотой акцент #D4AF37.",
    "Важное ограничение: нельзя хранить паспортные данные и лишние персональные данные.",
    "Нужен экспорт записей в CSV для администратора.",
]

CONTROL_QUESTIONS = [
    "Собери краткое ТЗ: цель, бюджет, срок, платформа, роли, оплата, напоминания, ограничения по данным.",
    "Какие детали интерфейса и фирменного стиля нужно учесть?",
]

DETAIL_CHECKS = {
    0: [
        ("цель/MVP", ["mvp", "онлайн-запис"]),
        ("5 салонов", ["5 сал"]),
        ("бюджет 450 тыс.", ["450"]),
        ("срок 6 недель", ["6 недель"]),
        ("демо через 3 недели", ["3 недель"]),
        ("платформа web", ["веб", "web"]),
        ("роли", ["клиент", "барбер", "администратор"]),
        ("напоминание за 2 часа", ["2 часа"]),
        ("оплата в салоне", ["в салоне", "онлайн-оплат"]),
        ("ограничение по персональным данным", ["паспорт", "персональ"]),
    ],
    1: [
        ("чёрный фон", ["чёрн", "черн"]),
        ("золотой #D4AF37", ["d4af37", "золот"]),
        ("выбор салона", ["салон"]),
        ("выбор услуги", ["услуг"]),
        ("выбор барбера", ["барбер"]),
        ("выбор даты/времени", ["дат", "врем"]),
        ("экспорт CSV", ["csv"]),
    ],
}


def detail_report(answer, question_index):
    low = answer.lower()
    kept = []
    lost = []
    for label, variants in DETAIL_CHECKS[question_index]:
        if all(any(variant in low for variant in group.split("|")) for group in variants):
            kept.append(label)
        elif any(variant in low for variant in variants):
            kept.append(label)
        else:
            lost.append(label)
    return kept, lost


def kept_total(answers):
    total = 0
    for index in DETAIL_CHECKS:
        kept, _ = detail_report(answers[index], index)
        total += len(kept)
    return total


def total_details():
    return sum(len(items) for items in DETAIL_CHECKS.values())


def answer_prompt_tokens(agent):
    return sum(turn.get("prompt_tokens", 0) for turn in agent.turns if turn.get("kind") == "answer")


def answer_completion_tokens(agent):
    return sum(turn.get("completion_tokens", 0) for turn in agent.turns if turn.get("kind") == "answer")


def facts_prompt_tokens(agent):
    return sum(turn.get("prompt_tokens", 0) for turn in agent.turns if turn.get("kind") == "facts")


def facts_completion_tokens(agent):
    return sum(turn.get("completion_tokens", 0) for turn in agent.turns if turn.get("kind") == "facts")


def run_strategy_comparison(strategy, history_path):
    history_path.unlink(missing_ok=True)
    agent = Agent(history_path=history_path, strategy=strategy, window_n=WINDOW_N)

    for text in SPEC_MESSAGES:
        agent.ask(text)

    answers = []
    for question in CONTROL_QUESTIONS:
        answers.append(agent.ask(question))

    history_path.unlink(missing_ok=True)
    return agent, answers


def run_branching_demo(history_path):
    history_path.unlink(missing_ok=True)
    agent = Agent(history_path=history_path, strategy="branching", window_n=WINDOW_N)

    agent.ask("Делаем сервис онлайн-записи к барберам. Нужно рассмотреть две версии продукта.")
    checkpoint = agent.make_checkpoint("base_after_product_choice")

    agent.branch("mvp")
    agent.ask("Ветка MVP: бюджет 450 тысяч рублей, только веб-приложение, оплата только в салоне.")

    agent.branch("premium")
    agent.ask("Ветка Premium: бюджет 900 тысяч рублей, добавляем iOS и Android, онлайн-оплату подключаем сразу.")

    question = "Какой бюджет, платформа и способ оплаты зафиксированы в этой ветке? Ответь одной строкой."

    agent.switch("mvp")
    mvp_answer = agent.ask(question)

    agent.switch("premium")
    premium_answer = agent.ask(question)

    history_path.unlink(missing_ok=True)
    return checkpoint, mvp_answer, premium_answer


def print_control_answers(strategy, answers):
    print("=" * 80)
    print(f"Стратегия: {strategy_name(strategy)}")
    for index, answer in enumerate(answers):
        kept, lost = detail_report(answer, index)
        print("-" * 80)
        print(f"Контрольный вопрос: {CONTROL_QUESTIONS[index]}")
        print(answer)
        print(f"Сохранено деталей: {len(kept)} / {len(DETAIL_CHECKS[index])}")
        if lost:
            print("Потеряно/не найдено в ответе: " + ", ".join(lost))
    print()


def print_compare_table(results):
    print("=" * 80)
    print("Итоговое сравнение стратегий:")
    print(
        f"{'стратегия':>10} | "
        f"{'детали':>9} | "
        f"{'вход ответов':>13} | "
        f"{'выход':>7} | "
        f"{'facts вход':>10} | "
        f"{'facts выход':>11} | "
        f"{'цена ₽':>8} | "
        f"{'удобство':>22}"
    )
    print("-" * 110)
    for strategy, agent, answers in results:
        if strategy == "sliding":
            convenience = "просто, но забывает старое"
        elif strategy == "facts":
            convenience = "удобно для ТЗ"
        else:
            convenience = "удобно для альтернатив"
        print(
            f"{strategy:>10} | "
            f"{kept_total(answers):>2}/{total_details():<6} | "
            f"{answer_prompt_tokens(agent):>13} | "
            f"{answer_completion_tokens(agent):>7} | "
            f"{facts_prompt_tokens(agent):>10} | "
            f"{facts_completion_tokens(agent):>11} | "
            f"{agent.total_spent_rub():>8.4f} | "
            f"{convenience:>22}"
        )
    print()


def print_compare_conclusions(results):
    print("Вывод:")
    for strategy, agent, answers in results:
        details = kept_total(answers)
        if strategy == "sliding":
            print(
                f"- Sliding Window: сохранено {details}/{total_details()} проверяемых деталей. "
                "Самая простая и дешёвая стратегия, но ранние требования могут исчезнуть из окна."
            )
        elif strategy == "facts":
            print(
                f"- Sticky Facts: сохранено {details}/{total_details()} проверяемых деталей. "
                "Лучше держит устойчивые требования, но тратит дополнительные токены на обновление facts."
            )
        else:
            print(
                f"- Branching: сохранено {details}/{total_details()} проверяемых деталей в основной ветке. "
                "Сильна там, где нужно развести разные варианты решения без смешивания контекста."
            )
    print()


def run_comparison():
    print("\n[День 10: сравнение стратегий без summary]")
    print(f"Сценарий: сбор ТЗ из {len(SPEC_MESSAGES)} сообщений + контрольные вопросы.")
    print(f"Размер окна Sliding/Facts: последние {WINDOW_N} сообщений.\n")

    results = []
    base_dir = Path(__file__).parent
    for strategy in STRATEGIES:
        history_path = base_dir / f"compare_day10_{strategy}.json"
        agent, answers = run_strategy_comparison(strategy, history_path)
        results.append((strategy, agent, answers))
        print_control_answers(strategy, answers)

    print_compare_table(results)
    print_compare_conclusions(results)

    checkpoint, mvp_answer, premium_answer = run_branching_demo(base_dir / "compare_day10_branching_demo.json")
    print("=" * 80)
    print("Проверка независимости веток Branching:")
    print(f"Checkpoint: {checkpoint.get('name')} из ветки {checkpoint.get('branch')}")
    print(f"Ветка MVP: {mvp_answer}")
    print(f"Ветка Premium: {premium_answer}")
    print(
        "Если ответы не смешивают бюджет/платформы/оплату между MVP и Premium, "
        "значит ветки работают независимо.\n"
    )


def print_http_error(error):
    print()
    status = error.response.status_code if error.response is not None else "?"
    print(f"HTTP {status}")
    if error.response is not None:
        try:
            body = error.response.json()
            if "error" in body:
                print(f"Ошибка API: {body['error'].get('message', body['error'])}")
            else:
                print(f"Ответ сервера: {body}")
        except ValueError:
            print(f"Ответ сервера: {error.response.text}")
    else:
        print(f"Ошибка HTTP: {error}")
    print()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    agent = Agent()
    dialog_messages = len(agent.live_messages())

    print("_ДЕНЬ 10. УПРАВЛЕНИЕ КОНТЕКСТОМ: РАЗНЫЕ СТРАТЕГИИ БЕЗ SUMMARY_\n")
    print(
        f"Загружена история ветки {agent.current_branch}: "
        f"{dialog_messages} {message_word(dialog_messages)}"
    )
    print(f"Модель: {agent.model}")
    print(f"Модель обновления facts: {agent.facts_model}")
    print(f"Лимит контекста: {agent.context_limit} токенов")
    print(f"Текущая стратегия: {strategy_name(agent.strategy)}")
    print(f"Размер окна: последние {agent.window_n} сообщений")
    print_help()
    print()

    while True:
        user = input("Ты: ").strip()

        if user == "":
            continue

        command = user.lower()

        if command == "/exit" or "\x1b" in user:
            break

        if command == "/reset":
            agent.reset()
            print("\n[История, facts, checkpoint и ветки очищены]\n")
            continue

        if command == "/help":
            print()
            print_help()
            print()
            continue

        if command == "/stats":
            print()
            print_dialog_stats(agent)
            continue

        if command == "/facts":
            print_facts(agent)
            continue

        if command == "/branches":
            print_branches(agent)
            continue

        if command == "/strategy":
            print(f"\n[Текущая стратегия: {strategy_name(agent.strategy)}]")
            print(f"{STRATEGY_DESCRIPTIONS[agent.strategy]}\n")
            continue

        if command.startswith("/strategy "):
            parts = user.split(maxsplit=1)
            strategy = parts[1].strip().lower()
            try:
                agent.set_strategy(strategy)
                print(f"\n[Стратегия изменена: {strategy_name(agent.strategy)}]")
                print(f"{STRATEGY_DESCRIPTIONS[agent.strategy]}\n")
            except ValueError as error:
                print(f"\n[{error}. Доступно: {', '.join(STRATEGIES)}]\n")
            continue

        if command == "/window" or command.startswith("/window "):
            parts = user.split()
            if len(parts) != 2 or not parts[1].isdigit():
                print("\n[Формат: /window N, например /window 6]\n")
                continue
            try:
                agent.set_window(int(parts[1]))
                print(f"\n[Размер окна изменён: последние {agent.window_n} сообщений]\n")
            except ValueError as error:
                print(f"\n[{error}]\n")
            continue

        if command == "/checkpoint" or command.startswith("/checkpoint "):
            name = user.split(maxsplit=1)[1].strip() if " " in user else None
            checkpoint = agent.make_checkpoint(name)
            print(
                f"\n[Checkpoint сохранён: {checkpoint['name']}. "
                f"Ветка: {checkpoint['branch']}. "
                f"Сообщений: {len(checkpoint['messages'])}]\n"
            )
            continue

        if command == "/branch" or command.startswith("/branch "):
            parts = user.split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                print("\n[Формат: /branch NAME, например /branch variant_a]\n")
                continue
            try:
                agent.branch(parts[1].strip())
                print(f"\n[Создана ветка {agent.current_branch} от checkpoint. Переключился на неё]\n")
            except ValueError as error:
                print(f"\n[{error}]\n")
            continue

        if command == "/switch" or command.startswith("/switch "):
            parts = user.split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                print("\n[Формат: /switch NAME, например /switch main]\n")
                continue
            try:
                agent.switch(parts[1].strip())
                print(f"\n[Переключился на ветку {agent.current_branch}]\n")
            except ValueError as error:
                print(f"\n[{error}]\n")
            continue

        if command == "/compare":
            try:
                run_comparison()
            except requests.exceptions.HTTPError as error:
                print_http_error(error)
            continue

        try:
            print(f"\nАгент: {agent.ask(user)}\n")
            print_turn_stats(agent)
        except requests.exceptions.HTTPError as error:
            print_http_error(error)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"Ошибка запуска: {error}")
