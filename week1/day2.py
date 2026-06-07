import os
import requests

URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
PROXY_API_KEY = os.environ["PROXY_API_KEY"]


def ask(payload):
    response = requests.post(
        URL,
        headers={"Authorization": f"Bearer {PROXY_API_KEY}"},
        json=payload,
    )
    response.raise_for_status()

    data = response.json()

    content = data["choices"][0]["message"]["content"]
    usage = data["usage"]

    return content, usage


def print_usage_line(title, usage):
    print(
        f"ТОКЕНЫ {title}: "
        f"Вход: {usage['prompt_tokens']}. "
        f"Выход: {usage['completion_tokens']}"
    )


try:
    free, free_usage = ask({
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Дай 3 причины почему футбол главный вид спорта на планете"}
        ],
    })

    controlled, controlled_usage = ask({
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Отвечай списком из трёх пунктов А, Б, В."
                    "Каждый пункт — одна короткая строка не длиннее 10 слов."
                    "В конце каждого пункта восклицательный знак"
                    "После последнего пункта на новой строке напиши слово обрезка."
                ),
            },
            {"role": "user", "content": "Дай 3 причины почему футбол главный вид спорта на планете"}
        ],
        "max_tokens": 100,
        "stop": ["обрезка"],
    })

    print("\n\n___ОТВЕТ БЕЗ ОГРАНИЧЕНИЙ___\n\n")
    print(free)
    print("\n\n___ОТВЕТ С ОГРАНИЧЕНИЯМИ___\n\n")
    print(controlled)

    print_usage_line("БЕЗ ОГРАНИЧЕНИЙ", free_usage)
    print_usage_line("С ОГРАНИЧЕНИЯМИ", controlled_usage)

except requests.exceptions.HTTPError as error:
    print("Ошибка HTTP:", error)

    if error.response is not None:
        print("Ответ сервера:", error.response.text)
