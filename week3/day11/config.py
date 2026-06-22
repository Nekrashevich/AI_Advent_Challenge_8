from pathlib import Path

API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
MODEL = "gpt-4o-mini"
MAX_COMPLETION_TOKENS = 1000
WINDOW_N = 8
BASE_DIR = Path(__file__).parent
STORE_DIR = BASE_DIR / "store"

SYSTEM_MESSAGE = 'Ты - ассистент с явной моделью памяти из трех слоев: краткосрочная память текущего диалога, рабочая память текущей задачи и долговременная память профиля, решений и знаний. Отвечай по существу. Не выдумывай факты, которых нет в вопросе или памяти.'
