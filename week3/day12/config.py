from pathlib import Path

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
MODEL = "gpt-4o-mini"
MAX_COMPLETION_TOKENS = 1000
WINDOW_N = 8
BASE_DIR = Path(__file__).parent
STORE_DIR = BASE_DIR / "store"

SYSTEM_MESSAGE = 'Ты - персонализированный ассистент. Учитывай профиль пользователя в каждом ответе: стиль, формат, уровень, роль и ограничения. Также используй слои памяти'
