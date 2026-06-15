import json
import os
import sys
from pathlib import Path

import requests

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
MODEL = "gpt-4o-mini"
HISTORY_PATH = Path(__file__).parent / "history_day9.json"
SUMMARY_PATH = Path(__file__).parent / "summary_day9.txt"

CONTEXT_LIMIT = 128000
WARNING_PERCENT = 80
KEEP_LAST_MESSAGES = 6
COMPRESS_EVERY_MESSAGES = 10
MAX_COMPLETION_TOKENS = 1000

PRICES_RUB_PER_1M = {
    MODEL: {"input": 39, "output": 155},
}

SYSTEM_MESSAGE = "Отвечай только на русском языке. Отвечай по существу, без лишней воды."

SUMMARY_SYSTEM_MESSAGE = (
    "Ты сжимаешь историю диалога в summary для будущих запросов к LLM. "
    "Сохраняй факты, числа, имена, решения, договорённости, предпочтения пользователя, "
    "ошибки, важные выводы и открытые вопросы. Убирай повторы, воду и технический мусор. "
    "Пиши кратко, но не теряй смысл. Ответ верни только на русском языке."
)

SUMMARY_PREFIX = (
    "Ниже краткое содержание более ранней части диалога. "
    "Полной старой истории у тебя нет, поэтому используй это summary как память:\n"
)


class TokenCounter:
    def __init__(self, model=MODEL):
        self.encoder = None
        try:
            import tiktoken
            try:
                self.encoder = tiktoken.encoding_for_model(model)
            except KeyError:
                self.encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            self.encoder = None

    def text(self, value):
        if not value:
            return 0
        if self.encoder:
            return len(self.encoder.encode(value))
        return max(1, len(value) // 4)

    def one_message(self, message):
        return (
            4
            + self.text(message.get("role", ""))
            + self.text(message.get("content", ""))
        )

    def messages(self, messages):
        # Приближённая формула для chat messages:
        # текст + небольшой служебный overhead на role/content.
        total = 2
        for message in messages:
            total += self.one_message(message)
        return total


class Agent:
    def __init__(
        self,
        model=MODEL,
        history_path=HISTORY_PATH,
        summary_path=SUMMARY_PATH,
        context_limit=CONTEXT_LIMIT,
        keep_last=KEEP_LAST_MESSAGES,
        compress_every=COMPRESS_EVERY_MESSAGES,
        use_compression=True,
    ):
        self.model = model
        self.history_path = Path(history_path)
        self.summary_path = Path(summary_path)
        self.context_limit = context_limit
        self.keep_last = keep_last
        self.compress_every = compress_every
        self.use_compression = use_compression
        self.api_key = os.environ.get("PROXY_API_KEY") or os.environ.get("PROXYAPI_KEY")
        if not self.api_key:
            raise RuntimeError("Не найден API-ключ. Добавь переменную окружения PROXY_API_KEY или PROXYAPI_KEY.")

        self.counter = TokenCounter(model)
        self.messages = []
        self.turns = []
        self.summary = ""
        self.last_compression = None
        self.raw_history_tokens_estimate = 0
        self.load()

    def fresh(self):
        self.messages = [{"role": "system", "content": SYSTEM_MESSAGE}]
        self.turns = []
        self.summary = ""
        self.last_compression = None
        self.raw_history_tokens_estimate = self.counter.messages(self.messages)

    def load(self):
        if not self.history_path.exists():
            self.fresh()
            return

        try:
            state = json.loads(self.history_path.read_text(encoding="utf-8"))
            self.messages = state.get("messages", [])
            self.turns = state.get("turns", [])
            self.raw_history_tokens_estimate = state.get("raw_history_tokens_estimate", 0)
        except (json.JSONDecodeError, OSError):
            self.fresh()
            return

        if not self.messages:
            self.fresh()
        elif self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": SYSTEM_MESSAGE})

        if self.summary_path.exists():
            self.summary = self.summary_path.read_text(encoding="utf-8").strip()
        else:
            self.summary = ""

        if not self.raw_history_tokens_estimate:
            self.raw_history_tokens_estimate = self.counter.messages(self.messages)

    def save(self):
        state = {
            "messages": self.messages,
            "turns": self.turns,
            "raw_history_tokens_estimate": self.raw_history_tokens_estimate,
            "settings": {
                "keep_last": self.keep_last,
                "compress_every": self.compress_every,
                "use_compression": self.use_compression,
            },
        }
        self.history_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if self.summary:
            self.summary_path.write_text(self.summary, encoding="utf-8")
        else:
            self.summary_path.unlink(missing_ok=True)

    def reset(self):
        self.fresh()
        self.history_path.unlink(missing_ok=True)
        self.summary_path.unlink(missing_ok=True)

    def live_messages(self):
        return self.messages[1:]

    def request_messages(self):
        result = [self.messages[0]]
        if self.use_compression and self.summary:
            result.append({"role": "system", "content": SUMMARY_PREFIX + self.summary})
        result.extend(self.live_messages())
        return result

    def compressed_prompt_tokens_estimate(self):
        return self.counter.messages(self.request_messages())

    def context_percent(self):
        return round(self.compressed_prompt_tokens_estimate() / self.context_limit * 100)

    def cost_rub(self, prompt_tokens, completion_tokens):
        price = PRICES_RUB_PER_1M.get(self.model, PRICES_RUB_PER_1M[MODEL])
        return (prompt_tokens * price["input"] + completion_tokens * price["output"]) / 1_000_000

    def total_spent_rub(self):
        return sum(turn.get("cost_rub", 0) for turn in self.turns)

    def total_spent_without_compression_estimate(self):
        total = 0
        for turn in self.turns:
            if turn.get("type") == "answer":
                prompt_tokens = turn.get("prompt_tokens_no_compression_estimate", turn.get("prompt_tokens", 0))
                completion_tokens = turn.get("completion_tokens", 0)
                total += self.cost_rub(prompt_tokens, completion_tokens)
        return total

    def call_api(self, messages, max_tokens=MAX_COMPLETION_TOKENS, temperature=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def add(self, target_tokens):
        # Локальный буст: нужен, чтобы быстро показать рост истории без оплаты десятков запросов.
        # Точное число токенов зависит от токенизатора, поэтому это примерная величина.
        user_message = {
            "role": "user",
            "content": "Буст токенов для теста компрессии. " + "stub " * max(1, target_tokens),
        }
        assistant_message = {"role": "assistant", "content": "Принято"}
        self.messages.append(user_message)
        self.messages.append(assistant_message)
        self.raw_history_tokens_estimate += self.counter.one_message(user_message)
        self.raw_history_tokens_estimate += self.counter.one_message(assistant_message)
        self.save()

    def compress(self):
        if not self.use_compression:
            return None

        archive = self.live_messages()[:-self.keep_last]
        if not archive:
            return None

        tokens_before = self.compressed_prompt_tokens_estimate()
        archive_text = "\n".join(
            f"{'Пользователь' if message['role'] == 'user' else 'Ассистент'}: {message['content']}"
            for message in archive
        )

        prompt_parts = []
        if self.summary:
            prompt_parts.append("Старое summary:\n" + self.summary)
        prompt_parts.append("Новые сообщения, которые нужно добавить в summary:\n" + archive_text)
        prompt_parts.append("Верни новое summary целиком. Не добавляй пояснений.")
        prompt = "\n\n".join(prompt_parts)

        data = self.call_api(
            [
                {"role": "system", "content": SUMMARY_SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ],
            max_tokens=700,
            temperature=0,
        )
        new_summary = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", self.counter.messages([
            {"role": "system", "content": SUMMARY_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ]))
        completion_tokens = usage.get("completion_tokens", self.counter.text(new_summary))
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
        cost = self.cost_rub(prompt_tokens, completion_tokens)

        self.summary = new_summary
        self.messages = [self.messages[0]] + self.live_messages()[-self.keep_last:]
        tokens_after = self.compressed_prompt_tokens_estimate()

        compression = {
            "type": "compression",
            "removed_messages": len(archive),
            "summary_chars": len(self.summary),
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "saved_tokens_estimate": max(0, tokens_before - tokens_after),
            "request_tokens": prompt_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_rub": cost,
        }
        self.turns.append(compression)
        self.last_compression = compression
        self.save()
        return compression

    def maybe_compress(self):
        if not self.use_compression:
            return None
        old_messages_count = len(self.live_messages()) - self.keep_last
        if old_messages_count >= self.compress_every:
            return self.compress()
        return None

    def ask(self, user_text):
        self.last_compression = None
        request_tokens_local = self.counter.text(user_text)
        tokens_before = self.compressed_prompt_tokens_estimate()

        user_message = {"role": "user", "content": user_text}
        self.messages.append(user_message)
        prompt_tokens_no_compression_estimate = self.raw_history_tokens_estimate + self.counter.one_message(user_message)

        data = self.call_api(self.request_messages())
        answer = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        prompt_tokens = usage.get("prompt_tokens", self.compressed_prompt_tokens_estimate())
        completion_tokens = usage.get("completion_tokens", self.counter.text(answer))
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
        cost = self.cost_rub(prompt_tokens, completion_tokens)

        assistant_message = {"role": "assistant", "content": answer}
        self.messages.append(assistant_message)
        self.raw_history_tokens_estimate = (
            prompt_tokens_no_compression_estimate
            + self.counter.one_message(assistant_message)
        )

        turn = {
            "type": "answer",
            "request_tokens": request_tokens_local,
            "prompt_tokens": prompt_tokens,
            "prompt_tokens_no_compression_estimate": prompt_tokens_no_compression_estimate,
            "saved_prompt_tokens_estimate": max(0, prompt_tokens_no_compression_estimate - prompt_tokens),
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "tokens_before": tokens_before,
            "tokens_after": self.compressed_prompt_tokens_estimate(),
            "cost_rub": cost,
        }
        self.turns.append(turn)
        self.maybe_compress()
        self.save()
        return answer


def message_word(number):
    if 11 <= number % 100 <= 14:
        return "сообщений"
    if number % 10 == 1:
        return "сообщение"
    if 2 <= number % 10 <= 4:
        return "сообщения"
    return "сообщений"


def print_help():
    print("Команды:")
    print("/reset — очистить историю и summary")
    print("/add N — дописать в историю ~N токенов")
    print("/compress — принудительно сжать старую историю")
    print("/summary — показать текущее summary")
    print("/stats — таблица токенов и экономии")
    print("/compare — два прогона сравнения сжатия: /add 30000 и /add 5000")
    print("/help — список команд")
    print("/exit — выход")


def print_turn_stats(agent):
    answer_turns = [turn for turn in agent.turns if turn.get("type") == "answer"]
    if not answer_turns:
        return

    turn = answer_turns[-1]
    fill = round(
        (
            turn["request_tokens"]
            + turn["prompt_tokens"]
            + turn["completion_tokens"]
        )
        / (agent.context_limit + 10000)
        * 100
    )
    print(
        f"[Токены вход: {turn['request_tokens']}. "
        f"Токены вход с историей: {turn['prompt_tokens']}. "
        f"Токены выход: {turn['completion_tokens']}. "
        f"Цена запроса: {turn['cost_rub']:.4f} ₽]"
    )
    print(
        f"[Без сжатия вход был бы примерно: "
        f"{turn['prompt_tokens_no_compression_estimate']} токенов. "
        f"Экономия: ~{turn['saved_prompt_tokens_estimate']} токенов]"
    )

    if agent.last_compression:
        compression = agent.last_compression
        print(
            f"[СЖАТИЕ: {compression['removed_messages']} сообщений заменены summary. "
            f"Контекст: ~{compression['tokens_before']} → ~{compression['tokens_after']} токенов. "
            f"Экономия: ~{compression['saved_tokens_estimate']} токенов. "
            f"Цена сжатия: {compression['cost_rub']:.4f} ₽]"
        )

    if fill >= WARNING_PERCENT:
        print(f"[ВНИМАНИЕ: контекст заполнен больше {WARNING_PERCENT}%]")
    print()


def print_dialog_stats(agent):
    if not agent.turns:
        print("[Ходов ещё не было]\n")
        return

    print(
        f"{'№':>3} | {'тип':>8} | {'вход':>8} | {'без сжатия':>12} | "
        f"{'экономия':>9} | {'выход':>6} | {'цена ₽':>8}"
    )
    for number, turn in enumerate(agent.turns, 1):
        if turn.get("type") == "compression":
            kind = "сжатие"
            prompt_tokens = turn.get("prompt_tokens", 0)
            raw_prompt = "—"
            saved = turn.get("saved_tokens_estimate", 0)
            completion = turn.get("completion_tokens", 0)
        else:
            kind = "ответ"
            prompt_tokens = turn.get("prompt_tokens", 0)
            raw_prompt = turn.get("prompt_tokens_no_compression_estimate", prompt_tokens)
            saved = turn.get("saved_prompt_tokens_estimate", 0)
            completion = turn.get("completion_tokens", 0)

        print(
            f"{number:>3} | "
            f"{kind:>8} | "
            f"{prompt_tokens:>8} | "
            f"{str(raw_prompt):>12} | "
            f"{saved:>9} | "
            f"{completion:>6} | "
            f"{turn.get('cost_rub', 0):>8.4f}"
        )

    real_input = sum(turn.get("prompt_tokens", 0) for turn in agent.turns)
    raw_input = sum(
        turn.get("prompt_tokens_no_compression_estimate", 0)
        for turn in agent.turns
        if turn.get("type") == "answer"
    )
    compression_input = sum(
        turn.get("prompt_tokens", 0)
        for turn in agent.turns
        if turn.get("type") == "compression"
    )
    print()
    print(f"Вход токенов реально: {real_input}")
    print(f"Вход токенов без сжатия, примерно: {raw_input}")
    print(f"Из них вход на вызовы сжатия: {compression_input}")
    print(f"Экономия на ответах, примерно: {max(0, raw_input - (real_input - compression_input))}")
    print(f"Итого за диалог: {agent.total_spent_rub():.4f} ₽")
    print(f"Итого без сжатия, примерно: {agent.total_spent_without_compression_estimate():.4f} ₽\n")


def print_summary(agent):
    if agent.summary:
        print(f"\n[SUMMARY]\n{agent.summary}\n")
    else:
        print("\n[Summary пока нет — история ещё не сжималась]\n")


DIMA_TALE = """Жил-был в одном уютном городке мальчик по имени Дима. Он был очень любознательным и мечтал о великих приключениях. Каждый день после школы он спешил в свой любимый парк, где собирал красивые камешки, строил домики для муравьев и запускал бумажные самолетики. Но больше всего на свете он любил слушать истории, которые рассказывала ему его бабушка.

Однажды, пока Дима сидел на скамейке и смотрел на облака, к нему подошел странный старик с длинной бородой и сумкой, полной необычных предметов. Старику выглядел весьма загадочно, и у Димы возникло непреодолимое желание узнать о нем больше.

— Привет, молодой друг! — произнес старик. — Я — Странник. Я путешествую по миру в поисках тех, кто способен вести за собой других. У меня есть для тебя особое задание.

Дима, полный удивления, внимательно слушал. Странник рассказал ему о магическом лесу, который находился на краю городка. В этом лесу спрятаны три волшебных семени, каждое из которых дарует своему обладателю уникальную силу. Но чтобы получить семена, нужно преодолеть три испытания.

Заинтригованный, Дима решил принять вызов. Он попрощался с бабушкой и отправился в путь. Пройдя через заросли и извивающиеся тропинки, он вскоре оказался у подножия великого дерева, где началось первое испытание.

Первое испытание требовало от Димы проявить свою умственную смекалку. Вокруг дерева стояли три статуи, каждая из которых охраняла семя. Статии по очереди задавали мальчику загадки. Дима, помнив рассказы бабушки о важности логики и внимательности, с легкостью разгадал все загадки. Статус, которую он разгадывал последней, восторженно улыбнулась и вручила ему первое семя — семя мудрости.

Далее Дима отправился дальше в лес, где его ждал второй вызов. Он подошел к спокойному озеру, на берегу которого находилась сова по имени Лира. Она пригласила мальчика поиграть в игру на дружбу. Диме нужно было придумать и рассказать историю о своем самом лучшем друге, которая бы подняла настроение не только ему, но и всем вокруг.

Дима вспомнил о своих друзьях, о том, как они вместе строили шалаши и катались на велосипедах, о том, как помогали друг другу делать уроки. Он рассказал такую захватывающую историю, что Лира, улыбаясь, вручила ему второе семя — семя дружбы.

Обрадованный, но слегка уставший, Дима продолжил свой путь. Вскоре он увидел чудесный свет, исходящий от лесной поляны. Как только он подошел ближе, то увидел там фей, которые весело танцевали и пели. Феи заметили Диму и пригласили его присоединиться к их празднику.

Для третьего испытания Дима должен был проявить смелость и решительность. Ему предложили пройти через мистический мост, который вел к центру поляны, но охранялся великим драконом. Дима, хотя и немного испугался, вспомнил о том, как его бабушка всегда говорила, что смелость — это не отсутствие страха, а умение действовать, несмотря на него.

Собрав все свое мужество, он подошел к дракону и вежливо попросил его пропустить на праздник. Дракон, увидев искренность и смелость Димы, улыбнулся и пропустил его. На празднике феи подарили Диме третье волшебное семя — семя смелости.

С семенами в руках Дима вернулся к Страннику. Тот, увидев, как много Дима учился и преодолевал трудности, сказал:

— Ты стал мудрым, дружелюбным и смелым. Эти семена не только даруют тебе силы, но и наполнят твою душу. Теперь ты можешь делиться ими с окружающими.

С тех пор Дима стал настоящим героем своего городка. Он использовал свои силы, чтобы помочь друзьям и тем, кто нуждался в поддержке. Дима стал известным благодаря своим добрым делам и вдохновляющим"""


def run_single_comparison(add_tokens):
    compare_dir = Path(__file__).parent
    suffix = f"add_{add_tokens}"
    raw_path = compare_dir / f"compare_day9_{suffix}_raw.json"
    compressed_path = compare_dir / f"compare_day9_{suffix}_compressed.json"
    raw_summary = compare_dir / f"compare_day9_{suffix}_raw_summary.txt"
    compressed_summary = compare_dir / f"compare_day9_{suffix}_compressed_summary.txt"

    for path in (raw_path, compressed_path, raw_summary, compressed_summary):
        path.unlink(missing_ok=True)

    raw = Agent(history_path=raw_path, summary_path=raw_summary, use_compression=False)
    compressed = Agent(
        history_path=compressed_path,
        summary_path=compressed_summary,
        use_compression=True,
        keep_last=4,
        compress_every=4,
    )

    facts = [
        "Меня зовут Игорь. Мне 20 лет. ",
        "У меня есть собака Шарик. ",
        "В понедельник в 14:00 дедлайн. ",
    ]
    chatter = [
        "Какая столица Китая? Ответь одним словом.",
        DIMA_TALE,
        "Какая столица Франции? Ответь одним словом.",
        "Сколько дней в неделе? Ответь одним числом.",
    ]
    control_questions = [
        # "Назови моё имя, возраст, имя собаки и время дедлайна. Одной строкой.",
        "Назови моё имя и возраст",
        "Назови имя моей собаки",
        "Назови время дедлайна",
        "Дай все реплики старика Диме.",
    ]

    print("=" * 80)
    print(f"[Прогон compare с /add {add_tokens}]")
    print("Первый агент хранит всю историю. Второй хранит summary + последние сообщения.")
    print("В chatter добавлена длинная сказка про Диму.\n")

    for text in facts + chatter:
        raw.ask(text)
        compressed.ask(text)

    # Аналог вызова команды /add N перед сжатием.
    # Важно: после /add добавляем две короткие пары сообщений.
    # Тогда огромный локальный буст уходит из последних keep_last=4 сообщений
    # и действительно попадает в архивируемую часть при ручном compress().
    raw.add(add_tokens)
    compressed.add(add_tokens)
    print(f"[Перед сжатием выполнено: /add {add_tokens}]")

    buffer_messages = [
        "Буфер 1. Ответь: принято.",
        "Буфер 2. Ответь: принято.",
    ]
    for text in buffer_messages:
        raw.ask(text)
        compressed.ask(text)
    print(f"[Добавлены 2 буферные реплики, чтобы /add {add_tokens} попал в сжатие]\n")

    compression = compressed.compress()
    if compression:
        print(
            f"[СЖАТИЕ compare: {compression['removed_messages']} сообщений заменены summary. "
            f"Контекст: ~{compression['tokens_before']} → ~{compression['tokens_after']} токенов. "
            f"Экономия: ~{compression['saved_tokens_estimate']} токенов. "
            f"Цена сжатия: {compression['cost_rub']:.4f} ₽]\n"
        )
    else:
        print("[СЖАТИЕ compare: сжимать нечего]\n")

    print(f"Summary сжатого агента:\n{compressed.summary}\n")

    for question in control_questions:
        print("=" * 80)
        print(f"Контрольный вопрос: {question}\n")
        for label, agent in (("БЕЗ сжатия", raw), ("С сжатием", compressed)):
            answer = agent.ask(question)
            last_answer_turn = [turn for turn in agent.turns if turn.get("type") == "answer"][-1]
            print(
                f"--- {label}: вход {last_answer_turn['prompt_tokens']} токенов, "
                f"выход {last_answer_turn['completion_tokens']} токенов, "
                f"цена {last_answer_turn['cost_rub']:.4f} ₽"
            )
            print(answer)
            print()

    raw_input = sum(turn.get("prompt_tokens", 0) for turn in raw.turns)
    raw_output = sum(turn.get("completion_tokens", 0) for turn in raw.turns)
    compressed_input = sum(turn.get("prompt_tokens", 0) for turn in compressed.turns)
    compressed_output = sum(turn.get("completion_tokens", 0) for turn in compressed.turns)

    result = {
        "add_tokens": add_tokens,
        "raw_input": raw_input,
        "raw_output": raw_output,
        "compressed_input": compressed_input,
        "compressed_output": compressed_output,
        "raw_price": raw.total_spent_rub(),
        "compressed_price": compressed.total_spent_rub(),
    }

    print("=" * 80)
    print("Итог:")
    print(
        f"Токены БЕЗ сжатия: суммарный вход {result['raw_input']}, "
        f"суммарный выход {result['raw_output']}"
    )
    print(
        f"Токены С сжатием: суммарный вход {result['compressed_input']}, "
        f"суммарный выход {result['compressed_output']}"
    )
    print(f"Цена БЕЗ сжатия: {result['raw_price']:.4f} ₽")
    print(f"Цена С сжатием: {result['compressed_price']:.4f} ₽\n")

    for path in (raw_path, compressed_path, raw_summary, compressed_summary):
        path.unlink(missing_ok=True)

    return result


def print_compare_runs_table(results):
    print("=" * 80)
    print("Сравнение двух прогонов:")
    print(
        f"{'/add':>8} | "
        f"{'вход без':>10} | "
        f"{'выход без':>10} | "
        f"{'вход с':>10} | "
        f"{'выход с':>10} | "
        f"{'цена без ₽':>12} | "
        f"{'цена с ₽':>10} | "
        f"{'разница ₽':>10}"
    )
    print("-" * 100)
    for result in results:
        diff = result["raw_price"] - result["compressed_price"]
        print(
            f"{result['add_tokens']:>8} | "
            f"{result['raw_input']:>10} | "
            f"{result['raw_output']:>10} | "
            f"{result['compressed_input']:>10} | "
            f"{result['compressed_output']:>10} | "
            f"{result['raw_price']:>12.4f} | "
            f"{result['compressed_price']:>10.4f} | "
            f"{diff:>10.4f}"
        )
    print()


def run_comparison():
    print("\n[Сравнение compare: два последовательных прогона]")
    print("Будут выполнены одинаковые сценарии с /add 30000 и /add 5000.\n")

    results = []
    for add_tokens in (30000, 5000):
        results.append(run_single_comparison(add_tokens))

    print_compare_runs_table(results)

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    agent = Agent()
    dialog_messages = len([message for message in agent.live_messages()])

    print("_ДЕНЬ 9. УПРАВЛЕНИЕ КОНТЕКСТОМ: СЖАТИЕ ИСТОРИИ_\n")
    print(
        f"Загружена история: {dialog_messages} "
        f"{message_word(dialog_messages)}, "
        f"summary: {'есть' if agent.summary else 'нет'}"
    )
    print(f"Модель: {agent.model}")
    print(f"Лимит контекста: {agent.context_limit} токенов")
    print(f"Сжатие: последние {agent.keep_last} сообщений хранятся как есть")
    print(f"Автосжатие: каждые {agent.compress_every} старых сообщений сверх хвоста")
    print_help()
    print()

    while True:
        user = input("Ты: ").strip()

        if user == "":
            continue

        command = user.lower()

        if command == "/exit" or "\x1b" in user:
            break

        if command == "/reset":
            agent.reset()
            print("\n[История и summary очищены]\n")
            continue

        if command == "/stats":
            print()
            print_dialog_stats(agent)
            continue

        if command == "/help":
            print()
            print_help()
            print()
            continue

        if command == "/summary":
            print_summary(agent)
            continue

        if command == "/compress":
            try:
                compression = agent.compress()
                if compression:
                    print(
                        f"\n[СЖАТИЕ: {compression['removed_messages']} сообщений заменены summary. "
                        f"Контекст: ~{compression['tokens_before']} → ~{compression['tokens_after']} токенов. "
                        f"Экономия: ~{compression['saved_tokens_estimate']} токенов. "
                        f"Цена сжатия: {compression['cost_rub']:.4f} ₽]\n"
                    )
                else:
                    print(
                        f"\n[Сжимать нечего: храню последние {agent.keep_last} сообщений как есть]\n"
                    )
            except requests.exceptions.HTTPError as error:
                print_http_error(error)
            continue

        if command == "/compare":
            try:
                run_comparison()
            except requests.exceptions.HTTPError as error:
                print_http_error(error)
            continue

        if command == "/add" or command.startswith("/add "):
            parts = user.split()
            if len(parts) != 2 or not parts[1].isdigit():
                print("\n[Формат: /add N, например /add 7000]\n")
                continue
            added_tokens = int(parts[1])
            agent.add(added_tokens)
            print(f"\n[В историю добавлено ~{added_tokens} токенов]\n")
            continue

        try:
            print(f"\nАгент: {agent.ask(user)}\n")
            print_turn_stats(agent)
        except requests.exceptions.HTTPError as error:
            print_http_error(error)


def print_http_error(error):
    print()
    status = error.response.status_code if error.response is not None else "?"
    print(f"HTTP {status}")
    if error.response is not None:
        try:
            body = error.response.json()
            if "error" in body:
                print(f"Ошибка API: {body['error'].get('message', body['error'])}")
            else:
                print(f"Ответ сервера: {body}")
        except ValueError:
            print(f"Ответ сервера: {error.response.text}")
    else:
        print(f"Ошибка HTTP: {error}")
    print()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"Ошибка запуска: {error}")
