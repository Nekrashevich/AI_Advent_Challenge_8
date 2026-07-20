from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import requests

from budget_pipeline.config import (
    PROXY_API_URL,
    PROXY_FALLBACK_MODEL,
    PROXY_MAX_TOKENS,
    PROXY_MODEL,
    PROXY_TIMEOUT,
)


PRICE_RUB_PER_MILLION = {
    "gpt-4.1-mini": {"input": 104.0, "output": 413.0},
    "gpt-4o-mini": {"input": 39.0, "output": 155.0},
}


class ProxyAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    attempts: int

    @property
    def cost_rub(self) -> float | None:
        prices = PRICE_RUB_PER_MILLION.get(self.model)
        if not prices:
            return None
        return round(
            (self.prompt_tokens * prices["input"] + self.completion_tokens * prices["output"])
            / 1_000_000,
            4,
        )


class ProxyAPIClient:
    def __init__(self, api_key: str | None = None, model: str = PROXY_MODEL):
        self.api_key = (api_key or os.getenv("PROXY_API_KEY", "")).strip()
        self.model = model

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = PROXY_MAX_TOKENS,
        json_mode: bool = False,
        retries: int = 3,
    ) -> LLMResult:
        if not self.api_key:
            raise ProxyAPIError("PROXY_API_KEY не задан")
        chosen_model = model or self.model
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            started = time.monotonic()
            payload = {
                "model": chosen_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            try:
                response = requests.post(
                    PROXY_API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=PROXY_TIMEOUT,
                )
                response.raise_for_status()
                body = response.json()
                usage = body.get("usage") or {}
                return LLMResult(
                    text=(body["choices"][0]["message"]["content"] or "").strip(),
                    model=chosen_model,
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    seconds=round(time.monotonic() - started, 2),
                    attempts=attempt,
                )
            except (requests.RequestException, KeyError, ValueError) as error:
                last_error = error
                if attempt < retries:
                    time.sleep(0.6 * attempt)
        if chosen_model != PROXY_FALLBACK_MODEL:
            try:
                return self.chat(
                    messages,
                    model=PROXY_FALLBACK_MODEL,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    retries=1,
                )
            except ProxyAPIError as error:
                last_error = error
        raise ProxyAPIError(f"ProxyAPI не ответил после retries/fallback: {last_error}")

    def chat_json(self, messages: list[dict], **kwargs) -> tuple[dict, LLMResult]:
        result = self.chat(messages, json_mode=True, **kwargs)
        text = result.text.strip()
        if text.startswith("```"):
            text = re_fence(text)
        try:
            return json.loads(text), result
        except json.JSONDecodeError as error:
            raise ProxyAPIError(f"Модель вернула не JSON: {error}") from error


def re_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)

