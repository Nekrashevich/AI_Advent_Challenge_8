import os
import requests

URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
PROXY_API_KEY = os.environ["PROXY_API_KEY"]

MODEL = "gpt-4o-mini"

TASK = (
    "Объясни, что такое эффект Фата-моргана. "
    "Сначала дай научно объяснение, "
    "а затем придумай четверостишье об этом методе."
)

TEMPERATURES = [0, 0.7, 1.2]

CRITIC_SYSTEM = (
    "Ты критик, который анализирует ответы модели на один и тот же запрос "
    "при разных значениях temperature. "
    "Сравни ответы по трём критериям: точность, креативность, разнообразие. "
    "Для каждого значения temperature объясни, для каких задач оно подходит лучше всего. "
    "Пиши конкретно, практично и без лишней воды. "
    "В конце дай общий вывод."
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


def make_temperature_payload(temperature):
    return {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": TASK}
        ],
        "temperature": temperature,
        "max_completion_tokens": 400,
    }


def make_critic_payload(answers):
    answers_text = "\n\n".join(
        f"temperature = {temperature}:\n{answer}"
        for temperature, answer in answers.items()
    )

    critic_prompt = (
        f"Запрос:\n{TASK}\n\n"
        f"Ответы модели:\n\n{answers_text}\n\n"
        "Сделай сравнительную критику этих ответов."
    )

    return {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": CRITIC_SYSTEM},
            {"role": "user", "content": critic_prompt},
        ],
        "temperature": 0,
        "max_completion_tokens": 900,
    }


try:
    answers = {}
    usages = {}

    print("\n\n___ЗАПРОС___\n\n")
    print(TASK)

    for temperature in TEMPERATURES:
        answer, usage = ask(make_temperature_payload(temperature))

        answers[temperature] = answer
        usages[temperature] = usage

        print(f"\n\n___ОТВЕТ TEMPERATURE = {temperature}___\n\n")
        print(answer)

    critic, critic_usage = ask(make_critic_payload(answers))

    print("\n\n___КРИТИКА___\n\n")
    print(critic)

    print_usage_line("TEMPERATURE = 0", usages[0])
    print_usage_line("TEMPERATURE = 0.7", usages[0.7])
    print_usage_line("TEMPERATURE = 1.2", usages[1.2])
    print_usage_line("КРИТИКА", critic_usage)

except requests.exceptions.HTTPError as error:
    print("Ошибка HTTP:", error)

    if error.response is not None:
        print("Ответ сервера:", error.response.text)
