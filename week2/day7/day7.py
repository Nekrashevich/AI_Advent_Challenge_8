import json
import os
import time
import requests
from pathlib import Path

URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
PROXY_API_KEY = os.environ["PROXY_API_KEY"]

MODEL = "gpt-4o-mini"
HISTORY_FILE = Path("messages.json")

SYSTEM_MESSAGE = {
    "role": "system",
    "content": "Отвечай только на русском языке."
}


class Agent:
    def __init__(self, model=MODEL, history_file=HISTORY_FILE):
        self.model = model
        self.history_file = Path(history_file)
        self.messages = self.load_messages()

    def load_messages(self):
        if not self.history_file.exists():
            return [SYSTEM_MESSAGE]

        try:
            with open(self.history_file, "r", encoding="utf-8") as file:
                messages = json.load(file)
        except (json.JSONDecodeError, OSError):
            return [SYSTEM_MESSAGE]

        if not messages:
            return [SYSTEM_MESSAGE]

        if messages[0].get("role") != "system":
            messages.insert(0, SYSTEM_MESSAGE)

        return messages

    def save_messages(self):
        with open(self.history_file, "w", encoding="utf-8") as file:
            json.dump(self.messages, file, ensure_ascii=False, indent=2)

    def clear_history(self):
        self.messages = [SYSTEM_MESSAGE]

        if self.history_file.exists():
            self.history_file.unlink()

    def ask(self, user_text):
        self.messages.append(
            {
                "role": "user",
                "content": user_text
            }
        )

        start = time.perf_counter()

        response = requests.post(
            URL,
            headers={"Authorization": f"Bearer {PROXY_API_KEY}"},
            json={
                "model": self.model,
                "messages": self.messages,
                "max_completion_tokens": 500,
            },
        )
        response.raise_for_status()

        elapsed = time.perf_counter() - start

        data = response.json()
        usage = data.get("usage", {})

        answer = data["choices"][0]["message"]["content"]

        self.messages.append(
            {
                "role": "assistant",
                "content": answer
            }
        )

        self.save_messages()

        return answer, usage, elapsed


def get_token_count(usage, key):
    return usage.get(key, 0)


def get_dialog_message_count(messages):
    return len([message for message in messages if message.get("role") != "system"])


def is_exit_command(user_text):
    text = user_text.lower().strip()
    return text in ("exit", "esc", "") or "\x1b" in user_text


try:
    agent = Agent()

    print("\n___LLM АГЕНТ С СОХРАНЕНИЕМ КОНТЕКСТА___\n")

    saved_messages_count = get_dialog_message_count(agent.messages)

    if saved_messages_count > 0:
        print(f"История загружена из файла {HISTORY_FILE}: {saved_messages_count} сообщений.\n")
    else:
        print(f"История пока пустая. После первого ответа будет создан файл {HISTORY_FILE}.\n")

    print("Команды:")
    print("exit или esc — выход")
    print("reset — очистить историю")
    print("history — показать историю\n")

    while True:
        user_text = input("Запрос (exit/esc для выхода): ").strip()

        if is_exit_command(user_text):
            print("\nДиалог завершён. История сохранена.\n")
            break

        if user_text.lower() == "reset":
            agent.clear_history()
            print("\nИстория очищена. Файл messages.json удалён.\n")
            continue

        if user_text.lower() == "history":
            print("\n___ИСТОРИЯ ДИАЛОГА___\n")

            for message in agent.messages:
                if message["role"] == "system":
                    continue

                role = "Ты" if message["role"] == "user" else "Агент"
                print(f"{role}: {message['content']}\n")

            continue

        answer, usage, elapsed = agent.ask(user_text)

        print("\n___ОТВЕТ___\n")
        print(answer)

        print(
            f"\nМЕТРИКИ: "
            f"Время: {elapsed:.2f} сек. "
            f"Вход: {get_token_count(usage, 'prompt_tokens')}. "
            f"Выход: {get_token_count(usage, 'completion_tokens')}. "
            f"Всего: {get_token_count(usage, 'total_tokens')}. "
            f"Сообщений в истории: {get_dialog_message_count(agent.messages)}."
        )

except requests.exceptions.HTTPError as error:
    print("Ошибка HTTP:", error)

    if error.response is not None:
        print("Ответ сервера:", error.response.text)
