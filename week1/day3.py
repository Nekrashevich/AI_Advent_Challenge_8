import os
import requests

URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
PROXY_API_KEY = os.environ["PROXY_API_KEY"]
MODEL = "gpt-5.2"

TASK = (
    "Мне нужно помыть свою машину которая стоит у дома. Автомойка в 50 метрах от дома. "
    "Машину можно помыть только на самой автомойке — дома мыть негде. "
    "Как мне лучше добраться до автомойки чтобы помыть машину — доехать на машине, которую надо "
    "помыть и которая стоит у моего дома, или дойти пешком?"
)

SYSTEM_STEP = (
    "Решай задачу пошагово. "
    "Сначала покажи ход решения по шагам, затем дай финальный ответ. "
    "В финальном ответе укажи найденную подпоследовательность, её сумму, "
    "длину и индексы начала и конца."
)

META_PROMPT = (
    "Составь оптимальный промпт для решения задачи ниже. "
    "Промпт должен быть самодостаточным: включи в него саму задачу, "
    "критерии выбора ответа и формат финального вывода. "
    "Верни только текст промпта, без решения.\n\n"
    "Задача:\n"
    f"{TASK}"
)

SYSTEM_EXPERTS = (
    "Реши задачу как группа из трёх экспертов:\n"
    "1. Аналитик — формализует условие и критерии выбора.\n"
    "2. Инженер — решает задачу алгоритмически и находит ответ.\n"
    "3. Критик — проверяет решение, сумму, длину и правило выбора при равенстве.\n"
    "Каждый эксперт даёт свой короткий вывод. "
    "В конце напиши строку 'ИТОГ:' и общий финальный ответ."
)


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


def make_payload(messages, max_tokens=3000):
    return {
        "model": MODEL,
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }


try:
    direct, direct_usage = ask(
        make_payload([
            {"role": "user", "content": TASK},
        ])
    )

    step, step_usage = ask(
        make_payload([
            {"role": "system", "content": SYSTEM_STEP},
            {"role": "user", "content": TASK},
        ])
    )

    generated_prompt, generated_prompt_usage = ask(
        make_payload([
            {"role": "user", "content": META_PROMPT},
        ])
    )

    self_prompt, self_prompt_usage = ask(
        make_payload([
            {"role": "user", "content": generated_prompt},
        ])
    )

    experts, experts_usage = ask(
        make_payload([
            {"role": "system", "content": SYSTEM_EXPERTS},
            {"role": "user", "content": TASK},
        ])
    )

    print("\n\n___ЗАДАЧА___\n\n")
    print(TASK)

    print("\n\n___1. ПРЯМОЙ ОТВЕТ___\n\n")
    print(direct)

    print("\n\n___2. РЕШАЙ ПОШАГОВО___\n\n")
    print(step)

    print("\n\n___3. МОДЕЛЬ СНАЧАЛА СОСТАВИЛА ПРОМПТ___\n\n")
    print("[СГЕНЕРИРОВАННЫЙ ПРОМПТ]\n")
    print(generated_prompt)
    print("\n[ОТВЕТ ПО СГЕНЕРИРОВАННОМУ ПРОМПТУ]\n")
    print(self_prompt)

    print("\n\n___4. ГРУППА ЭКСПЕРТОВ___\n\n")
    print(experts)

    print_usage_line("1. ПРЯМОЙ ОТВЕТ", direct_usage)
    print_usage_line("2. РЕШАЙ ПОШАГОВО", step_usage)
    print_usage_line("3. СОСТАВЛЕНИЕ ПРОМПТА", generated_prompt_usage)
    print_usage_line("3. ОТВЕТ ПО ПРОМПТУ", self_prompt_usage)
    print_usage_line("4. ГРУППА ЭКСПЕРТОВ", experts_usage)

except requests.exceptions.HTTPError as error:
    print("Ошибка HTTP:", error)

    if error.response is not None:
        print("Ответ сервера:", error.response.text)
