import requests

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
MEMBER_MODEL = "gpt-4o-mini"
ORCHESTRATOR_MODEL = "gpt-4.1"

STAGE_ROLES = {
    "planning": [
        ("Архитектор", "структура решения, слои, границы модулей, как это масштабируется"),
        ("Безопасность", "данные, доступ, секреты, валидация ввода, поверхность атаки"),
        ("Производительность", "сложность, узкие места, нагрузка, расход ресурсов"),
        ("Прагматик", "сроки и простота: минимальное решение без оверинжиниринга, что выкинуть"),
        ("Критик", "слабые места задачи и чужих подходов: что сломается, чего не хватает"),
    ],
    "execution": [
        ("Бэкенд", "серверная логика, API, обработка запросов и ошибок"),
        ("Данные", "схема хранения, миграции, целостность, индексы"),
        ("Тесты", "что и как покрыть тестами, граничные случаи"),
        ("Интеграции", "внешние сервисы, контракты, ретраи, ошибки сети"),
        ("Критик кода", "слабые места реализации: дубли, связность, поддерживаемость"),
    ],
    "validation": [
        ("Инварианты", "соответствие результата нерушимым правилам проекта"),
        ("Безопасность", "уязвимости, утечки, доступ, обработка чужого ввода"),
        ("Граничные случаи", "пустые/большие входы, гонки, отказы зависимостей"),
        ("Производительность", "узкие места под нагрузкой, деградация"),
        ("Критик", "что осталось недоделано, риски релиза"),
    ],
}

STAGE_JOB = {
    "planning": "Сведи мнения в утверждаемый план из 3-6 пунктов — он станет планом задачи.",
    "execution": "Сведи мнения в перечень реализации: что делаем и в каком порядке, по утверждённому плану.",
    "validation": "Сведи мнения в вердикт: что готово, что нарушает инварианты или несёт риск, можно ли в done.",
}

MEMBER_SYSTEM = (
    "Ты — участник совета агентов на стадии «{stage}», твоя роль «{role}». Зона ответственности: {brief}. "
    "Дают задачу, утверждённый план, результаты прошлых стадий и инварианты проекта. "
    "Дай короткое мнение (2-4 предложения) строго со своей позиции: что предлагаешь и на что обратить "
    "внимание именно на стадии {stage}. Не пиши за другие роли, не пересказывай задачу. "
    "Учитывай инварианты — не предлагай того, что их нарушает."
)

ORCHESTRATOR_SYSTEM = (
    "Ты — оркестратор совета агентов на стадии «{stage}». Знаешь запрос пользователя, его профиль, "
    "инварианты проекта, утверждённый план и результаты прошлых стадий. Тебе дают мнения агентов-"
    "специалистов, каждый со своей роли. {job} Если мнения конфликтуют — выбери весомейшее и объясни "
    "выбор одной строкой. Если предложение нарушает инвариант — ОТКЛОНИ его и прямо напиши возражение "
    "и причину. Стадию ты НЕ меняешь — переход разрешает только человек командой. "
    "Формат ответа строго:\nВОЗРАЖЕНИЯ: <список или «нет»>\nИТОГ:\n1. ...\n2. ..."
)


def _call(api_key, model, messages):
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": messages},
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"], data["usage"]


def _accumulate(total, usage):
    total["prompt_tokens"] += usage["prompt_tokens"]
    total["completion_tokens"] += usage["completion_tokens"]


def _context_block(task, plan, prev_result, rules):
    lines = [f"ЗАДАЧА:\n{task}"]
    if plan:
        lines.append(f"УТВЕРЖДЁННЫЙ ПЛАН:\n{plan}")
    if prev_result:
        lines.append(f"РЕЗУЛЬТАТ ПРОШЛОЙ СТАДИИ:\n{prev_result}")
    lines.append(f"ИНВАРИАНТЫ:\n{rules}")
    return "\n\n".join(lines)


def run_swarm(api_key, stage, task, plan, prev_result, invariant_items, profile_text=""):
    roles = STAGE_ROLES[stage]
    job = STAGE_JOB[stage]
    rules = "\n".join(f"{i + 1}. {it['rule']}" for i, it in enumerate(invariant_items)) or "—"
    context = _context_block(task, plan, prev_result, rules)

    opinions = []
    member_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    for role, brief in roles:
        text, usage = _call(api_key, MEMBER_MODEL, [
            {"role": "system", "content": MEMBER_SYSTEM.format(stage=stage, role=role, brief=brief)},
            {"role": "user", "content": context},
        ])
        opinions.append({"role": role, "text": text.strip()})
        _accumulate(member_usage, usage)

    joined = "\n\n".join(f"[{o['role']}]\n{o['text']}" for o in opinions)
    profile_block = f"\n\nПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n{profile_text}" if profile_text else ""
    orch_user = f"{context}{profile_block}\n\nМНЕНИЯ АГЕНТОВ:\n{joined}"
    synthesis, orch_usage = _call(api_key, ORCHESTRATOR_MODEL, [
        {"role": "system", "content": ORCHESTRATOR_SYSTEM.format(stage=stage, job=job)},
        {"role": "user", "content": orch_user},
    ])
    return opinions, synthesis.strip(), member_usage, orch_usage
