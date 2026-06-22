import json
from pathlib import Path

STORE_DIR = Path(__file__).parent / "store"
INVARIANTS_PATH = STORE_DIR / "invariants.json"


class Invariants:
    def __init__(self):
        STORE_DIR.mkdir(exist_ok=True)
        self.items = self._load()

    def _load(self):
        if INVARIANTS_PATH.exists():
            return json.loads(INVARIANTS_PATH.read_text(encoding="utf-8"))
        return []

    def _save(self):
        INVARIANTS_PATH.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, rule, forbid):
        self.items.append({"rule": rule, "forbid": forbid})
        self._save()

    def clear(self):
        self.items = []
        self._save()

    def lint(self, text):
        low = text.lower()
        hits = []
        for item in self.items:
            for term in item["forbid"]:
                if term.lower() in low:
                    hits.append({"rule": item["rule"], "term": term})
        return hits

    def as_prompt(self):
        if not self.items:
            return ""
        lines = "\n".join(f"{i + 1}. {item['rule']}" for i, item in enumerate(self.items))
        return ("ИНВАРИАНТЫ — нерушимые ограничения проекта (хранятся отдельно от диалога). "
                "Ты обязан соблюдать их всегда. Если запрос пользователя противоречит инварианту — "
                "НЕ выполняй его: прямо откажись и объясни, какой именно инвариант нарушается и почему. "
                "Не предлагай обходных решений, нарушающих инварианты:\n" + lines)
