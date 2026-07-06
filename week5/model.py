import os

import requests

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
MAIN_MODEL = "gpt-4o-mini"
CHEAP_MODEL = "gpt-4o-mini"


def chat(messages, model=MAIN_MODEL, temperature=0.3, json_mode=False):
    api_key = os.environ["PROXY_API_KEY"]
    payload = {"model": model, "messages": messages, "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()
