from copy import deepcopy

from config import STORE_DIR
from storage import read_json, write_json


PROFILE_PATH = STORE_DIR / "profiles.json"

DEFAULT_PROFILES = {
    "active": "Саша",
    "profiles": {
        "Саша": {
            "предпочтения": "хочет слушать про воду",
            "формат": "два четверостишья",
        },
        "Дима": {
            "предпочтения": "хочет слушать про парки",
            "формат": "1 абзац",
        },
    },
}

FIELDS = {
    "предпочтения": "какие темы любит пользователь",
    "формат": "формат ответа",
    "ограничения": "что не предлагать и чего избегать",
}

class ProfileStore:
    def __init__(self):
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        self.data = read_json(PROFILE_PATH, deepcopy(DEFAULT_PROFILES))
        if "profiles" not in self.data:
            self.data = deepcopy(DEFAULT_PROFILES)
        if self.data.get("active") not in self.data["profiles"]:
            self.data["active"] = "Саша"
            self.data["profiles"].setdefault("Саша", deepcopy(DEFAULT_PROFILES["profiles"]["Саша"]))
        self.save()

    @property
    def active_name(self):
        return self.data["active"]

    @property
    def active(self):
        return self.data["profiles"].setdefault(self.active_name, {})

    def save(self):
        write_json(PROFILE_PATH, self.data)

    def switch(self, name):
        name = name.strip() or "default"
        self.data["profiles"].setdefault(name, {})
        self.data["active"] = name
        self.save()

    def set(self, key, value):
        self.active[key] = value
        self.save()

    def unset(self, key):
        existed = key in self.active
        self.active.pop(key, None)
        self.save()
        return existed

    def clear_active(self):
        self.data["profiles"][self.active_name] = {}
        self.save()

    def list_profiles(self):
        return self.data["profiles"]

    def as_prompt(self, profile=None, name=None):
        profile = self.active if profile is None else profile
        if not profile:
            return ""
        title = name or self.active_name
        lines = "\n".join(f"- {key}: {value}" for key, value in profile.items())
        return (
            f"Профиль пользователя '{title}' - персонализация. "
            "Автоматически учитывай стиль, формат, уровень и ограничения пользователя:\n"
            + lines
        )
