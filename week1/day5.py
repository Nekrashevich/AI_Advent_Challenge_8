import os
import time
import requests

URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
PROXY_API_KEY = os.environ["PROXY_API_KEY"]

CRITIC_MODEL = "gpt-4o-mini"

TASK = (
    "Мне нужно помыть машину, которая стоит у дома. "
    "Автомойка находится в 50 метрах от дома. "
    "Машину можно помыть только на самой автомойке — дома мыть негде. "
    "Как мне лучше добраться до автомойки, чтобы помыть машину: "
    "доехать на машине, которую надо помыть, или дойти пешком? "
    "Дай короткий ответ и объясни рассуждение."
)

MODELS = [
    {
        "title": "СЛАБАЯ МОДЕЛЬ",
        "id": "gpt-3.5-turbo",
        "price_input": 129,
        "price_output": 387,
    },
    {
        "title": "СРЕДНЯЯ МОДЕЛЬ",
        "id": "gpt-4o",
        "price_input": 645,
        "price_output": 2577,
    },
    {
        "title": "СИЛЬНАЯ МОДЕЛЬ",
        "id": "gpt-5.5",
        "price_input": 1520,
        "price_output": 9100,
    },
]

CRITIC_PRICE = {
    "price_input": 39,
    "price_output": 155,
}

CRITIC_SYSTEM = (
    "Ты критик, который анализирует ответы слабой, средней и сильной модели "
    "на один и тот же запрос. "
    "Сравни ответы по четырём критериям: качество ответа, точность рассуждения, "
    "скорость и ресурсоёмкость. "
    "Объясни, какая модель справилась лучше, какая быстрее, какая дешевле, "
    "и для каких задач подходит каждая модель. "
    "Пиши конкретно, практично и без лишней воды. "
    "В конце дай короткий общий вывод о различиях между моделями."
)


def ask(payload):
    start = time.perf_counter()

    response = requests.post(
        URL,
        headers={"Authorization": f"Bearer {PROXY_API_KEY}"},
        json=payload,
    )
    response.raise_for_status()

    elapsed = time.perf_counter() - start
    data = response.json()

    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})

    return content, usage, elapsed


def get_token_count(usage, key):
    return usage.get(key, 0)


def calc_cost(usage, price):
    input_tokens = get_token_count(usage, "prompt_tokens")
    output_tokens = get_token_count(usage, "completion_tokens")

    return (
        input_tokens / 1_000_000 * price["price_input"]
        + output_tokens / 1_000_000 * price["price_output"]
    )


def print_result_line(title, result):
    usage = result["usage"]

    print(
        f"МЕТРИКИ {title}: "
        f"Время: {result['elapsed']:.2f} сек. "
        f"Вход: {get_token_count(usage, 'prompt_tokens')}. "
        f"Выход: {get_token_count(usage, 'completion_tokens')}. "
        f"Всего: {get_token_count(usage, 'total_tokens')}. "
        f"Стоимость: ${result['cost']:.6f}"
    )


def make_model_payload(model):
    return {
        "model": model["id"],
        "messages": [
            {"role": "user", "content": TASK},
        ],
        "max_completion_tokens": 500,
    }


def make_critic_payload(results):
    results_text = "\n\n".join(
        (
            f"{model['title']} — {model['id']}:\n"
            f"Время: {result['elapsed']:.2f} сек\n"
            f"Токены: вход {get_token_count(result['usage'], 'prompt_tokens')}, "
            f"выход {get_token_count(result['usage'], 'completion_tokens')}, "
            f"всего {get_token_count(result['usage'], 'total_tokens')}\n"
            f"Стоимость: ${result['cost']:.6f}\n"
            f"Ответ:\n{result['answer']}"
        )
        for model, result in results
    )

    critic_prompt = (
        f"Запрос:\n{TASK}\n\n"
        f"Ответы и метрики моделей:\n\n{results_text}\n\n"
        "Сделай сравнительную критику этих результатов."
    )

    return {
        "model": CRITIC_MODEL,
        "messages": [
            {"role": "system", "content": CRITIC_SYSTEM},
            {"role": "user", "content": critic_prompt},
        ],
        "temperature": 0,
        "max_completion_tokens": 900,
    }


try:
    results = []

    print("\n\n___ЗАПРОС___\n\n")
    print(TASK)

    for model in MODELS:
        answer, usage, elapsed = ask(make_model_payload(model))
        cost = calc_cost(usage, model)

        result = {
            "answer": answer,
            "usage": usage,
            "elapsed": elapsed,
            "cost": cost,
        }
        results.append((model, result))

        print(f"\n\n___ОТВЕТ {model['title']} — {model['id']}___\n\n")
        print(answer)

    critic, critic_usage, critic_elapsed = ask(make_critic_payload(results))
    critic_cost = calc_cost(critic_usage, CRITIC_PRICE)

    print("\n\n___КРИТИКА___\n\n")
    print(critic)

    print("\n\n___СВОДКА ПО МЕТРИКАМ___\n")
    for model, result in results:
        print_result_line(f"{model['title']} — {model['id']}", result)

    print(
        f"МЕТРИКИ КРИТИКА — {CRITIC_MODEL}: "
        f"Время: {critic_elapsed:.2f} сек. "
        f"Вход: {get_token_count(critic_usage, 'prompt_tokens')}. "
        f"Выход: {get_token_count(critic_usage, 'completion_tokens')}. "
        f"Всего: {get_token_count(critic_usage, 'total_tokens')}. "
        f"Стоимость: ${critic_cost:.6f}"
    )

except requests.exceptions.HTTPError as error:
    print("Ошибка HTTP:", error)

    if error.response is not None:
        print("Ответ сервера:", error.response.text)
