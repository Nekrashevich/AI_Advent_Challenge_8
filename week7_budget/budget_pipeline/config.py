import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
RUNTIME_DIR = ROOT / "runtime"
GENERATED_DIR = RUNTIME_DIR / "generated"

TRANSACTIONS_CSV = DATA_DIR / "transactions.csv"
SUPPORT_JSON = DATA_DIR / "support.json"

PROXY_API_URL = os.getenv(
    "PROXY_API_URL",
    "https://api.proxyapi.ru/openai/v1/chat/completions",
)
PROXY_MODEL = os.getenv("PROXY_MODEL", "gpt-4.1-mini")
PROXY_FALLBACK_MODEL = os.getenv("PROXY_FALLBACK_MODEL", "gpt-4o-mini")
PROXY_TIMEOUT = float(os.getenv("PROXY_TIMEOUT", "60"))
PROXY_MAX_TOKENS = int(os.getenv("PROXY_MAX_TOKENS", "500"))

PRIMARY_USER_ID = "U-1001"
REVIEW_MARKER = "<!-- week7-budget-ai-review -->"

