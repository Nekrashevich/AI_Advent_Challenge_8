from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNTIME_DIR = ROOT / "runtime"
EXPENSES_CSV = DATA_DIR / "expenses.csv"
INDEX_JSON = RUNTIME_DIR / "budget-index.json"

OLLAMA_URL = "http://localhost:11434"
LOCAL_MODEL = "qwen2.5:7b"
EMBED_MODEL = "bge-m3"

PROXY_API_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
OPENAI_MODEL = "gpt-4.1-mini"
