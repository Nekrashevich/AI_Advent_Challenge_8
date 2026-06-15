import os
import time
import requests

URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
PROXY_API_KEY = os.environ["PROXY_API_KEY"]

MODEL = "gpt-4o-mini"


class Agent:
    def __init__(self, model=MODEL):
        self.model = model
        self.messages = [
            {
                "role": "system",
                "content": "Отвечай только на русском языке."
            }
        ]

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

        return answer, usage, elapsed


def get_token_count(usage, key):
    return usage.get(key, 0)


try:
    agent = Agent()

    print("\n___ПРОСТОЙ LLM АГЕНТ___\n")

    while True:
        user_text = input("Запрос (exit/esc для выхода): ").strip()

        if user_text.lower() in ("exit", "esc"):
            break

        answer, usage, elapsed = agent.ask(user_text)

        print("\n___ОТВЕТ___\n")
        print(answer)

        print(
            f"\nМЕТРИКИ: "
            f"Время: {elapsed:.2f} сек. "
            f"Вход: {get_token_count(usage, 'prompt_tokens')}. "
            f"Выход: {get_token_count(usage, 'completion_tokens')}. "
            f"Всего: {get_token_count(usage, 'total_tokens')}."
        )

except requests.exceptions.HTTPError as error:
    print("Ошибка HTTP:", error)

    if error.response is not None:
        print("Ответ сервера:", error.response.text)
