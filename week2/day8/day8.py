import json
import os
import sys
from pathlib import Path

import requests

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
MODEL = "gpt-3.5-turbo"
HISTORY_PATH = Path(__file__).parent / "history.json"

CONTEXT_LIMIT = 16385
WARNING_PERCENT = 80

PRICES_RUB_PER_1M = {
    MODEL: {"input": 129, "output": 387},
}

SYSTEM_MESSAGE = (
    "Отвечай только на русском языке."
)

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
            return len(self.encoder.encode(value))
        return max(1, len(value) // 4)

    def messages(self, messages):
        # Приближённая формула для chat messages:
        # текст + небольшой служебный overhead на role/content.
        total = 2
        for message in messages:
            total += 4
            total += self.text(message.get("role", ""))
            total += self.text(message.get("content", ""))
        return total


class Agent:
    def __init__(self, model=MODEL, history_path=HISTORY_PATH, context_limit=CONTEXT_LIMIT):
        self.model = model
        self.history_path = Path(history_path)
        self.context_limit = context_limit
        self.api_key = os.environ.get("PROXY_API_KEY") or os.environ.get("PROXYAPI_KEY")
        if not self.api_key:
            raise RuntimeError("Не найден API-ключ. Добавь переменную окружения PROXY_API_KEY или PROXYAPI_KEY.")

        self.counter = TokenCounter(model)
        self.messages = []
        self.turns = []
        self.load()

    def fresh(self):
        self.messages = [{"role": "system", "content": SYSTEM_MESSAGE}]
        self.turns = []

    def load(self):
        if not self.history_path.exists():
            self.fresh()
            return

        try:
            state = json.loads(self.history_path.read_text(encoding="utf-8"))
            self.messages = state.get("messages", [])
            self.turns = state.get("turns", [])
        except (json.JSONDecodeError, OSError):
            self.fresh()
            return

        if not self.messages:
            self.fresh()
        elif self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": SYSTEM_MESSAGE})

    def save(self):
        state = {
            "messages": self.messages,
            "turns": self.turns,
        }
        self.history_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def reset(self):
        self.fresh()
        self.history_path.unlink(missing_ok=True)

    def history_tokens(self):
        return self.counter.messages(self.messages)

    def context_percent(self):
        return round(self.history_tokens() / self.context_limit * 100)

    def cost_rub(self, prompt_tokens, completion_tokens):
        price = PRICES_RUB_PER_1M.get(self.model, PRICES_RUB_PER_1M[MODEL])
        return (prompt_tokens * price["input"] + completion_tokens * price["output"]) / 1_000_000

    def total_spent_rub(self):
        return sum(turn.get("cost_rub", 0) for turn in self.turns)

    def add(self, target_tokens):
        # Локальный буст: нужен, чтобы показать рост истории без оплаты десятков запросов.
        # Точное число токенов зависит от токенизатора, поэтому это примерная величина.
        text = "Буст токенов. " + "stub " * max(1, target_tokens)
        self.messages.append({"role": "user", "content": text})
        self.messages.append({"role": "assistant", "content": "Принято"})
        self.save()

    def ask(self, user_text):
        request_tokens_local = self.counter.text(user_text)
        tokens_before = self.history_tokens()

        self.messages.append({"role": "user", "content": user_text})

        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": self.messages,
                "max_tokens": 500,
            },
        )
        response.raise_for_status()

        data = response.json()
        answer = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        prompt_tokens = usage.get("prompt_tokens", self.history_tokens())
        completion_tokens = usage.get("completion_tokens", self.counter.text(answer))
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
        cost = self.cost_rub(prompt_tokens, completion_tokens)

        self.messages.append({"role": "assistant", "content": answer})

        turn = {
            "request_tokens": request_tokens_local,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "history_tokens": self.history_tokens(),
            "tokens_before": tokens_before,
            "cost_rub": cost,
        }
        self.turns.append(turn)
        self.save()
        return answer



def print_turn_stats(agent):
    turn = agent.turns[-1]
    fill = round(
        (
            turn["request_tokens"]
            + turn["prompt_tokens"]
            + turn["completion_tokens"]
        )
        / (agent.context_limit)
        * 100
    )
    print(
        f"[Токены вход: {turn['request_tokens']}. "
        f"Токены вход с историей: {turn['prompt_tokens']}. "
        f"Токены выход: {turn['completion_tokens']}. "
        f"Цена запроса: {turn['cost_rub']:.4f} ₽]"
    )
    if fill >= WARNING_PERCENT:
        print(f"[ВНИМАНИЕ: контекст заполнен больше {WARNING_PERCENT}%]")
    print()


def print_dialog_stats(agent):
    if not agent.turns:
        print("[Ходов ещё не было]\n")
        return

    print(f"{'№':>3} | {'вход':>6} | {'вход с историей':>16} | {'выход':>6} | {'цена ₽':>8}")
    for number, turn in enumerate(agent.turns, 1):
        print(
            f"{number:>3} | "
            f"{turn['request_tokens']:>6} | "
            f"{turn['prompt_tokens']:>16} | "
            f"{turn['completion_tokens']:>6} | "
            f"{turn['cost_rub']:>8.4f}"
        )
    print(f"Итого за диалог: {agent.total_spent_rub():.4f} ₽\n")


def message_word(number):
    if 11 <= number % 100 <= 14:
        return "сообщений"
    if number % 10 == 1:
        return "сообщение"
    if 2 <= number % 10 <= 4:
        return "сообщения"
    return "сообщений"


def print_help():
    print("Команды:")
    print("/reset — очистить историю")
    print("/add N — дописать в историю ~N токенов")
    print("/stats — таблица токенов")
    print("/help — список команд")
    print("/exit — выход")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    agent = Agent()
    dialog_replicas = len([m for m in agent.messages if m.get("role") != "system"])

    print("_ДЕНЬ 8. АГЕНТ С ПОДСЧЁТОМ ТОКЕНОВ_\n")
    print(
        f"Загружена история: {dialog_replicas} "
        f"{message_word(dialog_replicas)}, {agent.history_tokens()} токенов"
    )
    print(f"Модель: {agent.model}")
    print(f"Лимит контекста: {agent.context_limit} токенов")
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
            print("\n[История очищена]\n")
            continue

        if command == "/stats":
            print()
            print_dialog_stats(agent)
            continue

        if command == "/help":
            print()
            print_help()
            print()
            continue

        if command == "/add" or command.startswith("/add "):
            parts = user.split()
            if len(parts) != 2 or not parts[1].isdigit():
                print("\n[Формат: /add N, например /add 7000]\n")
                continue
            added_tokens = int(parts[1])
            agent.add(added_tokens)
            print(f"\n[В историю добавлено ~{added_tokens} токенов]\n")
            continue

        try:
            print(f"\nАгент: {agent.ask(user)}\n")
            print_turn_stats(agent)
        except requests.exceptions.HTTPError as error:
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


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"Ошибка запуска: {error}")
