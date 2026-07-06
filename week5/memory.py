import json
from pathlib import Path

from model import chat, CHEAP_MODEL

STORE = Path(__file__).resolve().parent / "runtime_store"
HISTORY_WINDOW = 8

EXTRACT_SYSTEM = (
    "Ты ведёшь память задачи диалога. По последнему обмену обнови состояние. Верни строго JSON:\n"
    '{"goal": "цель диалога одной фразой (или прежняя)", '
    '"clarified": ["что пользователь уже уточнил"], '
    '"constraints": ["зафиксированные ограничения и договорённости"], '
    '"glossary": {"термин": "значение"}}\n'
    "Сохраняй прежние записи, добавляй новые, не выдумывай."
)


class ChatMemory:
    def __init__(self, name="default"):
        self.name = name
        self.history = []
        self.state = {"goal": "", "clarified": [], "constraints": [], "glossary": {}}
        self.path = STORE / f"chat-{name}.json"
        if self.path.is_file():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.history = saved.get("history", [])
            self.state = saved.get("state", self.state)

    def save(self):
        STORE.mkdir(parents=True, exist_ok=True)
        payload = {"history": self.history, "state": self.state}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def reset(self):
        self.history = []
        self.state = {"goal": "", "clarified": [], "constraints": [], "glossary": {}}
        if self.path.is_file():
            self.path.unlink()

    def recent_messages(self):
        return self.history[-HISTORY_WINDOW:]

    def history_text(self):
        return "\n".join(
            f"{'Пользователь' if m['role'] == 'user' else 'Ассистент'}: {m['content'][:300]}"
            for m in self.recent_messages()
        )

    def add_exchange(self, question, answer):
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer})

    def update_state(self, question, answer):
        prompt = (
            f"Текущее состояние:\n{json.dumps(self.state, ensure_ascii=False)}\n\n"
            f"Пользователь: {question}\nАссистент: {answer}"
        )
        raw = chat(
            [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": prompt}],
            model=CHEAP_MODEL,
            temperature=0,
            json_mode=True,
        )
        updated = json.loads(raw)
        for key in self.state:
            if key in updated:
                self.state[key] = updated[key]
        self.save()
