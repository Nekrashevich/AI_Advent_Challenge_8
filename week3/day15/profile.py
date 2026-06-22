import json
from copy import deepcopy
from pathlib import Path


STORE_DIR = Path(__file__).parent / "store"
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


def read_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class ProfileStore:
    def __init__(self):
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        self.store = read_json(PROFILE_PATH, deepcopy(DEFAULT_PROFILES))
        if "profiles" not in self.store:
            self.store = deepcopy(DEFAULT_PROFILES)
        if self.store.get("active") not in self.store["profiles"]:
            self.store["active"] = "Саша"
            self.store["profiles"].setdefault("Саша", deepcopy(DEFAULT_PROFILES["profiles"]["Саша"]))
        self.save()

    @property
    def active_name(self):
        return self.store["active"]

    @property
    def active(self):
        return self.store["profiles"].setdefault(self.active_name, {})

    @property
    def data(self):
        return self.active

    def save(self):
        write_json(PROFILE_PATH, self.store)

    def switch(self, name):
        name = name.strip() or "default"
        self.store["profiles"].setdefault(name, {})
        self.store["active"] = name
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
        self.store["profiles"][self.active_name] = {}
        self.save()

    def clear(self):
        self.clear_active()

    def list_profiles(self):
        return self.store["profiles"]

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


class Profile(ProfileStore):
    pass
