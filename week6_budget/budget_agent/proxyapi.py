import os
import time

import requests

from budget_agent.config import OPENAI_MODEL, PROXY_API_URL


def is_configured():
    return bool(os.getenv("PROXY_API_KEY"))


def chat(messages, model=OPENAI_MODEL, temperature=0.2, max_tokens=500):
    api_key = os.environ["PROXY_API_KEY"]
    started = time.time()
    response = requests.post(
        PROXY_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    text = payload["choices"][0]["message"]["content"].strip()
    usage = payload.get("usage", {})
    return text, {
        "seconds": round(time.time() - started, 2),
        "model": model,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "tokens": usage.get("completion_tokens", 0),
    }
