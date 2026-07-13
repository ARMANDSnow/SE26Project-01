from functools import lru_cache
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
PROJECT_DIR = BASE_DIR.parent


def _read_api_key() -> str:
    value = os.getenv("LLM_API_KEY", "").strip()
    if value:
        return value
    key_path = Path(os.getenv("LLM_API_KEY_FILE", PROJECT_DIR / "apikey.txt"))
    try:
        return key_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class Settings:
    def __init__(self) -> None:
        self.database_path = Path(os.getenv("DATABASE_PATH", DATA_DIR / "arxiv_wiki.sqlite3"))
        self.upload_dir = Path(os.getenv("UPLOAD_DIR", DATA_DIR / "uploads"))
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.llm_api_key = _read_api_key()
        self.llm_chat_model = os.getenv("LLM_CHAT_MODEL", "deepseek-v4-flash")
        self.llm_context_window = int(os.getenv("LLM_CONTEXT_WINDOW", "131072"))
        self.llm_max_output_tokens = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "4096"))
        categories = os.getenv("ARXIV_DEFAULT_CATEGORIES", "cs.AI,cs.CL,cs.LG")
        self.default_categories = [item.strip() for item in categories.split(",") if item.strip()]

    @property
    def llm_available(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
