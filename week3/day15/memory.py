import json
from pathlib import Path


STORE_DIR = Path(__file__).parent / "store"
SHORT_TERM_PATH = STORE_DIR / "short_term.json"
WORKING_PATH = STORE_DIR / "working_memory.json"
LONG_TERM_PATH = STORE_DIR / "long_term_memory.json"

def read_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
