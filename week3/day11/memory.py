import json

from config import STORE_DIR, WINDOW_N
from storage import read_json, write_json


SHORT_TERM_PATH = STORE_DIR / "short_term.json"
WORKING_PATH = STORE_DIR / "working_memory.json"
LONG_TERM_PATH = STORE_DIR / "long_term_memory.json"


class MemoryLayers:
    def __init__(self):
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        self.short_term = read_json(SHORT_TERM_PATH, [])
        self.working = read_json(WORKING_PATH, {})
        self.long_term = read_json(LONG_TERM_PATH, {})

    def save_all(self):
        write_json(SHORT_TERM_PATH, self.short_term)
        write_json(WORKING_PATH, self.working)
        write_json(LONG_TERM_PATH, self.long_term)

    def add_dialog(self, role, content):
        self.short_term.append({"role": role, "content": content})
        write_json(SHORT_TERM_PATH, self.short_term)

    def set_working(self, key, value):
        self.working[key] = value
        write_json(WORKING_PATH, self.working)

    def remember_forever(self, key, value):
        self.long_term[key] = value
        write_json(LONG_TERM_PATH, self.long_term)

    def forget_forever(self, key):
        existed = key in self.long_term
        self.long_term.pop(key, None)
        write_json(LONG_TERM_PATH, self.long_term)
        return existed

    def forget_working(self, key):
        existed = key in self.working
        self.working.pop(key, None)
        write_json(WORKING_PATH, self.working)
        return existed

    def clear_short_term(self):
        self.short_term = []
        write_json(SHORT_TERM_PATH, self.short_term)

    def clear_working(self):
        self.working = {}
        write_json(WORKING_PATH, self.working)

    def clear_long_term(self):
        self.long_term = {}
        write_json(LONG_TERM_PATH, self.long_term)

    def reset(self):
        self.short_term = []
        self.working = {}
        self.long_term = {}
        self.save_all()

    def next_long_key(self):
        return f"факт_{len(self.long_term) + 1}"

    def next_working_key(self):
        return f"пункт_{len(self.working) + 1}"

    def context_blocks(self):
        blocks = []
        if self.long_term:
            blocks.append(
                "Долговременная память - постоянные факты, профиль, решения и знания. "
                "Учитывай их во всех ответах:\n"
                + json.dumps(self.long_term, ensure_ascii=False, indent=2)
            )
        if self.working:
            blocks.append(
                "Рабочая память - данные текущей задачи. Это активный контекст работы:\n"
                + json.dumps(self.working, ensure_ascii=False, indent=2)
            )
        return blocks

    def build_messages(self, system_message, extra_system=None, include_dialog=True, window_n=WINDOW_N):
        messages = [{"role": "system", "content": system_message}]
        for block in extra_system or []:
            if block:
                messages.append({"role": "system", "content": block})
        for block in self.context_blocks():
            messages.append({"role": "system", "content": block})
        if include_dialog:
            messages.extend(self.short_term[-window_n:])
        return messages

    def stats(self):
        return {
            "short_term": len(self.short_term),
            "working": len(self.working),
            "long_term": len(self.long_term),
        }
