import json

import requests

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
CRITIC_MODEL = "gpt-4o-mini"

CRITIC_SYSTEM = (
    "Ты — критик-валидатор. Тебе дают список нерушимых инвариантов проекта и ответ ассистента. "
    "Твоя задача — проверить, нарушает ли ответ хоть один инвариант. Не оценивай качество, "
    "только соответствие инвариантам. Верни строго JSON без markdown: "
    '{"violated": true|false, "which": ["точная формулировка нарушенного инварианта", ...], '
    '"why": "коротко, чем именно нарушен"}. Если нарушений нет — which пустой, why пустой.'
)


def critic_check(api_key, invariant_items, answer):
    rules = "\n".join(f"{i + 1}. {item['rule']}" for i, item in enumerate(invariant_items))
    user = f"ИНВАРИАНТЫ:\n{rules}\n\nОТВЕТ АССИСТЕНТА:\n{answer}"
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": CRITIC_MODEL,
            "messages": [
                {"role": "system", "content": CRITIC_SYSTEM},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        },
    )
    response.raise_for_status()
    data = response.json()
    verdict = json.loads(data["choices"][0]["message"]["content"])
    return verdict, data["usage"]
