import json
from pathlib import Path

STORE_DIR = Path(__file__).parent / "store"
STATE_PATH = STORE_DIR / "state.json"

STAGES = ["planning", "execution", "validation", "done"]

TRANSITIONS = {
    "planning": ["execution"],
    "execution": ["validation", "planning"],
    "validation": ["done", "execution"],
    "done": [],
}

EXPECTED = {
    "planning": "составить план: /plan <текст>, затем /next в execution",
    "execution": "выполнять план; /next в validation или /back в planning",
    "validation": "проверить результат на инварианты; /next в done или /back в execution",
    "done": "задача завершена",
}


def _new_task():
    return {"stage": "planning", "step": 0, "plan": None, "results": [], "status": "active"}


class TaskStore:
    def __init__(self, ephemeral=False):
        self.ephemeral = ephemeral
        if ephemeral:
            self.data = {"tasks": {}, "current": None}
            return
        STORE_DIR.mkdir(exist_ok=True)
        self.data = self._load()

    def _load(self):
        if STATE_PATH.exists():
            try:
                raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and "tasks" in raw:
                    return raw
            except (ValueError, OSError):
                pass
        return {"tasks": {}, "current": None}

    def _save(self):
        if self.ephemeral:
            return
        STATE_PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def tasks(self):
        return self.data["tasks"]

    @property
    def current(self):
        return self.data["current"]

    def current_task(self):
        return self.tasks.get(self.current) if self.current else None

    def exists(self, name):
        return name in self.tasks

    def create(self, name):
        self.tasks[name] = _new_task()
        self.data["current"] = name
        self._save()

    def enter(self, name):
        self.data["current"] = name
        task = self.tasks[name]
        if task["status"] == "paused" and task["stage"] != "done":
            task["status"] = "active"
        self._save()

    def leave(self):
        self.data["current"] = None
        self._save()

    def set_plan(self, name, text):
        self.tasks[name]["plan"] = text
        self._save()

    def add_result(self, name, text):
        self.tasks[name]["results"].append(text)
        self._save()

    def forward_target(self, name):
        index = STAGES.index(self.tasks[name]["stage"])
        return STAGES[index + 1] if index + 1 < len(STAGES) else None

    def back_target(self, name):
        index = STAGES.index(self.tasks[name]["stage"])
        return STAGES[index - 1] if index > 0 else None

    def transition(self, name, target):
        task = self.tasks[name]
        current = task["stage"]
        if target not in STAGES:
            return False, f"нет такой стадии: {target}"
        if target not in TRANSITIONS[current]:
            allowed = ", ".join(TRANSITIONS[current]) or "—"
            return False, f"переход {current} → {target} запрещён. Можно только в: {allowed}"
        if target == "execution" and not task["plan"]:
            return False, "нельзя в execution без утверждённого плана (сначала /plan <текст>)"
        task["stage"] = target
        task["step"] += 1
        if target == "done":
            task["status"] = "done"
        self._save()
        return True, f"стадия: {current} → {target}"

    def pause(self, name):
        task = self.tasks[name]
        if task["stage"] != "done":
            task["status"] = "paused"
        self.data["current"] = None
        self._save()

    def delete(self, name):
        self.tasks.pop(name, None)
        if self.data["current"] == name:
            self.data["current"] = None
        self._save()

    def reset(self):
        self.data = {"tasks": {}, "current": None}
        self._save()

    def as_prompt(self):
        task = self.current_task()
        if not task:
            return ""
        return ("Состояние текущей задачи (task state machine) — работай строго в рамках стадии, "
                "не перескакивай этапы:\n"
                f"- задача: {self.current}\n"
                f"- стадия: {task['stage']} (шаг {task['step']})\n"
                f"- ожидаемое действие: {EXPECTED[task['stage']]}\n"
                f"- утверждённый план: {task['plan'] or '—'}\n"
                "- ВАЖНО: менять стадию (переходить дальше/назад, пропускать этап) ты НЕ можешь — это "
                "делает только пользователь командой /next или /back. Если тебя просят перейти на другую "
                "стадию или пропустить этап — не делай этого, объясни, что переход выполняется командой "
                "/next и решение за пользователем.")
