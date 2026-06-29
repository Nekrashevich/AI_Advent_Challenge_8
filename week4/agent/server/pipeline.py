import os
import re
from pathlib import Path

import requests

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
SUMMARY_MODEL = os.environ.get("PROXY_API_MODEL") or os.environ.get("PROXYAPI_MODEL") or "gpt-4o-mini"
STORE = Path(__file__).resolve().parent.parent / "store"

SUMMARY_SYSTEM = (
    "Ты — суммаризатор. Сожми присланный текст до сути на русском: 4-6 коротких пунктов, "
    "только факты из текста, без воды и домыслов."
)


def _proxy_api_key():
    api_key = os.environ.get("PROXY_API_KEY") or os.environ.get("PROXYAPI_KEY")
    if not api_key:
        raise RuntimeError("Укажи PROXY_API_KEY или PROXYAPI_KEY для LLM-команд")
    return api_key


def _raise_for_status(response):
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        body = response.text.strip()
        detail = f": {body[:1000]}" if body else ""
        raise RuntimeError(f"{error}{detail}") from error


def summarize(text, max_chars=6000):
    api_key = _proxy_api_key()
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": SUMMARY_MODEL,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": text[:max_chars]},
            ],
        },
        timeout=60,
    )
    _raise_for_status(response)
    return response.json()["choices"][0]["message"]["content"].strip()


def save_to_file(name, content):
    STORE.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", name).strip("_") or "output"
    if not safe.lower().endswith((".txt", ".md")):
        safe += ".md"
    path = STORE / safe
    path.write_text(content, encoding="utf-8")
    return str(path)
