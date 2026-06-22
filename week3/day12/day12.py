import requests

try:
    import readline
except ImportError:
    readline = None


def is_exit(value):
    text = value.lower().strip()
    return text in ("exit", "esc", "/exit") or "\x1b" in value


COMMANDS = (
    "/profile",
    "/profile-set",
    "/profile-unset",
    "/profiles",
    "/profile-clear",
    "/add-working",
    "/add-longterm",
    "/show",
    "/clear-working",
    "/clear-longterm",
    "/compare-profiles",
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


def normalize_command(user):
    text = user.strip()
    if text.startswith("/"):
        return text

    command = text.split(maxsplit=1)[0].lower()
    if command in [item[1:] for item in COMMANDS if item != "/exit"]:
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


def parse_kv(text, fallback_key):
    text = text.strip()
    if not text:
        return None, None
    if "=" in text:
        key, value = (part.strip() for part in text.split("=", 1))
        return key, value
    return fallback_key, text


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
    print()


def show_profiles(profile_store):
    print("\n___ПРОФИЛИ___\n")
    for name, profile in profile_store.list_profiles().items():
        marker = "*" if name == profile_store.active_name else " "
        print(f"{marker} {name}")
        if profile:
            for key, value in profile.items():
                print(f"  - {key}: {value}")
        else:
            print("  - пусто")
    print()


def show_profile_fields():
    from profile import FIELDS
    print("Поля профиля:")
    for key, hint in FIELDS.items():
        print(f"- {key}: {hint}")

from agent import AssistantAgent


def print_help(show_memory_commands=True):
    print("Команды:")
    print("/profile NAME - переключить или создать профиль")
    print("/profile-set ключ = значение - записать предпочтение активного профиля")
    print("/profile-unset ключ - удалить поле профиля")
    print("/profiles - показать профили")
    print("/profile-clear - очистить активный профиль")
    if show_memory_commands:
        print("/show - показать три слоя памяти")
        print("/add-working инструкция - сохранить в рабочую память (текущая задача)")
        print("/add-longterm инструкция - сохранить в долговременную память (профиль, решения, знания)")
        print("/clear-working - очистить рабочую память")
        print("/clear-longterm - очистить долговременную память")
    print("/compare-profiles [вопрос] - сравнить ответы для всех профилей из /profiles")
    print("/reset - стереть память и активный профиль")
    print("/help - список команд")
    print("/exit - выход")


def compare_profiles(agent, rest):
    question = rest.strip() or "Объясни, как добавить сохранение JSON-состояния в CLI-агента."
    print("\n[Сравнение: один вопрос для всех сохраненных профилей]\n")
    for name, profile, answer, usage in agent.compare_profiles(question):
        print(f"___ПРОФИЛЬ: {name}___")
        if profile:
            for key, value in profile.items():
                print(f"- {key}: {value}")
        else:
            print("- пусто")
        print("\nОтвет:\n")
        print(answer)
        print()
        print_usage(usage, 3)
        print()


def handle_command(agent, user):
    parts = user[1:].split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    if command == "help":
        print_help()
        show_profile_fields()
    elif command == "profile":
        if not rest.strip():
            print(f"Активный профиль: {agent.profile.active_name}")
            return
        agent.profile.switch(rest.strip())
        print(f"[Активный профиль: {agent.profile.active_name}]")
    elif command == "profile-set":
        key, value = parse_kv(rest, None)
        if not key:
            print("Формат: /profile-set ключ = значение")
            return
        agent.profile.set(key, value)
        print(f"[Профиль {agent.profile.active_name}] {key} = {value}")
    elif command == "profile-unset":
        key = rest.strip()
        print("[Удалено]" if agent.profile.unset(key) else "[Такого поля не было]")
    elif command == "profiles":
        show_profiles(agent.profile)
    elif command == "profile-clear":
        agent.profile.clear_active()
        print(f"[Профиль {agent.profile.active_name} очищен]")
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
    elif command == "show":
        show_memory(agent.memory)
    elif command == "clear-working":
        agent.memory.clear_working()
        print("[Рабочая память очищена]")
    elif command == "clear-longterm":
        agent.memory.clear_long_term()
        print("[Долговременная память очищена]")
    elif command == "compare-profiles":
        compare_profiles(agent, rest)
    elif command == "reset":
        agent.memory.reset()
        agent.profile.clear_active()
        print("[Память и активный профиль очищены]")
    else:
        print("Неизвестная команда. Набери /help")


def main():
    setup_readline()
    agent = AssistantAgent()
    stats = agent.memory.stats()
    print("\n___ДЕНЬ 12. ПЕРСОНАЛИЗИРОВАННЫЙ АГЕНТ___\n")
    print(f"Активный профиль: {agent.profile.active_name}")
    print(
        f"Память: краткосрочная {stats['short_term']} сообщений, "
        f"рабочая {stats['working']} записей, долговременная {stats['long_term']} записей."
    )
    print_help(show_memory_commands=False)
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
