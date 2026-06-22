import os

import requests

from config import API_URL, MAX_COMPLETION_TOKENS, MODEL


class ApiClient:
    def __init__(self, model=MODEL):
        self.model = model
        self.api_key = os.environ.get("PROXY_API_KEY") or os.environ.get("PROXYAPI_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Не найден API-ключ. Добавь переменную окружения PROXY_API_KEY или PROXYAPI_KEY."
            )

    def chat(self, messages, max_tokens=MAX_COMPLETION_TOKENS, temperature=None, model=None):
        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=120,
        )

        if response.status_code == 400 and "max_completion_tokens" in response.text:
            payload.pop("max_tokens", None)
            payload["max_completion_tokens"] = max_tokens
            response = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=120,
            )

        response.raise_for_status()
        data = response.json()
        answer = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return answer, usage
