import os
import requests

URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
PROXY_API_KEY = os.environ["PROXY_API_KEY"]

try:
    response = requests.post(
        URL,
        headers={"Authorization": f"Bearer {PROXY_API_KEY}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": "Назови три достопримечательности столицы России"}
            ],
        },
    )

    response.raise_for_status()

    print(response.json()["choices"][0]["message"]["content"])

except requests.exceptions.HTTPError as error:
    print("Ошибка HTTP:", error)
    print("Ответ сервера:", response.text)
