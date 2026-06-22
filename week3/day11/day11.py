import requests

try:
    import readline
except ImportError:
    readline = None


def is_exit(value):
    text = value.lower().strip()
    return text in ("exit", "esc", "/exit") or "\x1b" in value


COMMANDS = (
    "/add-working",
    "/add-longterm",
    "/show",
    "/clear-working",
    "/clear-longterm",
    "/compare",
    "/reset",
    "/help",
    "/exit",
)


def complete_command(text, state):
    if not text.startswith("/"):
        return None
    matches = [command for command in COMMANDS if command.startswith(text)]
    if state < len(matches):
        return matches[state]
    return None


def setup_readline():
    if readline is None:
        return

    readline.set_completer(complete_command)
    readline.set_completer_delims(" \t\n")
    if readline.__doc__ and "libedit" in readline.__doc__:
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


MEMORY_KEY_HINTS = {
    "стиль",
    "язык",
    "тон",
    "формат",
    "роль",
    "слово",
}


def parse_memory_note(text, fallback_key):
    text = text.strip()
    if not text:
        return None, None
    if "=" in text:
        key, value = (part.strip() for part in text.split("=", 1))
        return key, value
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and parts[0].lower() in MEMORY_KEY_HINTS:
        return parts[0], parts[1]
    return fallback_key, text


def normalize_command(user):
    text = user.strip()
    if text.startswith("/"):
        return text

    aliases = (
        "add-working",
        "add-longterm",
        "clear-working",
        "clear-longterm",
        "show",
        "compare",
        "reset",
        "help",
    )
    command = text.split(maxsplit=1)[0].lower()
    if command in aliases:
        return "/" + text
    return None


def looks_like_memory_note(user):
    text = user.strip()
    if not text or "=" not in text or "\n" in text:
        return False
    if text.startswith("/"):
        return False
    command = text.split(maxsplit=1)[0].lower()
    return command not in ("add-working", "add-longterm")


def print_usage(usage, messages_count):
    if not usage:
        print("[Ответ без вызова API]")
        return
    print(
        f"[Токены вход: {usage.get('prompt_tokens', 0)}. "
        f"Токены выход: {usage.get('completion_tokens', 0)}. "
        f"Всего: {usage.get('total_tokens', 0)}. "
        f"Сообщений в запросе: {messages_count}.]"
    )


def print_http_error(error):
    print("Ошибка HTTP:", error)
    if error.response is not None:
        print("Ответ сервера:", error.response.text)


def show_memory(memory):
    print("\n___ПАМЯТЬ___\n")
    print("Краткосрочная память (текущий диалог):")
    if memory.short_term:
        for message in memory.short_term[-20:]:
            role = "Ты" if message.get("role") == "user" else "Агент"
            print(f"- {role}: {message.get('content')}")
    else:
        print("- пусто")

    print("\nРабочая память (текущая задача):")
    if memory.working:
        for key, value in memory.working.items():
            print(f"- {key}: {value}")
    else:
        print("- пусто")

    print("\nДолговременная память (профиль, решения, знания):")
    if memory.long_term:
        for key, value in memory.long_term.items():
            print(f"- {key}: {value}")
    else:
        print("- пусто")

    loose_notes = [
        message["content"]
        for message in memory.short_term
        if message.get("role") == "user" and looks_like_memory_note(message.get("content", ""))
    ]
    if loose_notes:
        print("\nПохожие на заметки реплики, но НЕ сохраненные в отдельный слой:")
        for note in loose_notes[-10:]:
            print(f"- {note}")
        print(
            "  Чтобы записать их явно, используй: "
            "/add-working инструкция или /add-longterm инструкция"
        )
    print()

from agent import AssistantAgent


def print_help():
    print("Команды:")
    print("/show - показать три слоя памяти")
    print("/add-working инструкция - сохранить в рабочую память (текущая задача)")
    print("/add-longterm инструкция - сохранить в долговременную память (профиль, решения, знания)")
    print("/clear-working - очистить рабочую память")
    print("/clear-longterm - очистить долговременную память")
    print("/compare [вопрос] - сравнить ответ с памятью и без памяти")
    print("/reset - стереть все слои памяти")
    print("/help - список команд")
    print("/exit - выход")


def run_compare(agent, text):
    question = text.strip() or "Предложи план разработки небольшого CLI-агента."
    print("\n[Сравнение: один вопрос без памяти и с памятью]\n")
    off, usage_off, on, usage_on = agent.compare_with_memory(question)
    print("___БЕЗ ПАМЯТИ___\n")
    print(off)
    print_usage(usage_off, 2)
    print("\n___С ПАМЯТЬЮ___\n")
    print(on)
    print_usage(usage_on, 3)
    print()


def handle_command(agent, user):
    parts = user[1:].split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    if command == "help":
        print_help()
    elif command == "show":
        show_memory(agent.memory)
    elif command == "add-working":
        key, value = parse_memory_note(rest, agent.memory.next_working_key())
        if not key:
            print("Формат: /add-working инструкция")
            return
        agent.memory.set_working(key, value)
        agent.memory.add_dialog("user", f"/add-working {rest.strip()}")
        agent.memory.add_dialog("assistant", f"Записал в рабочую память: {key} = {value}")
        print(f"[Рабочая память] {key} = {value}")
    elif command == "add-longterm":
        key, value = parse_memory_note(rest, agent.memory.next_long_key())
        if not key:
            print("Формат: /add-longterm инструкция")
            return
        agent.memory.remember_forever(key, value)
        agent.memory.add_dialog("user", f"/add-longterm {rest.strip()}")
        agent.memory.add_dialog("assistant", f"Записал в долговременную память: {key} = {value}")
        print(f"[Долговременная память] {key} = {value}")
    elif command == "clear-working":
        agent.memory.clear_working()
        print("[Рабочая память очищена]")
    elif command == "clear-longterm":
        agent.memory.clear_long_term()
        print("[Долговременная память очищена]")
    elif command == "compare":
        run_compare(agent, rest)
    elif command == "reset":
        agent.memory.reset()
        print("[Все слои памяти очищены]")
    else:
        print("Неизвестная команда. Набери /help")


def main():
    setup_readline()
    agent = AssistantAgent()
    stats = agent.memory.stats()
    print("\n___ДЕНЬ 11. АГЕНТ С ЯВНОЙ МОДЕЛЬЮ ПАМЯТИ___\n")
    print(
        f"Загружено: краткосрочная {stats['short_term']} сообщений, "
        f"рабочая {stats['working']} записей, долговременная {stats['long_term']} записей."
    )
    print_help()
    print()

    while True:
        user = input("Ты: ").strip()
        if not user:
            continue
        if is_exit(user):
            break

        command = normalize_command(user)
        if command:
            handle_command(agent, command)
            continue

        if looks_like_memory_note(user):
            print(
                "\n[Похоже на заметку для памяти. Выбери слой явно: "
                "/add-working инструкция или /add-longterm инструкция]\n"
            )
            continue

        try:
            answer, usage, messages = agent.ask(user)
            print("\nАгент:\n")
            print(answer)
            print()
            print_usage(usage, len(messages))
            print()
        except requests.exceptions.HTTPError as error:
            print_http_error(error)
        except RuntimeError as error:
            print("Ошибка запуска:", error)
            break


if __name__ == "__main__":
    main()
