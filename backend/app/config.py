from functools import lru_cache
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"


class Settings:
    def __init__(self) -> None:
        self.database_path = Path(os.getenv("DATABASE_PATH", DATA_DIR / "arxiv_wiki.sqlite3"))
        self.upload_dir = Path(os.getenv("UPLOAD_DIR", DATA_DIR / "uploads"))
        self.session_cookie_name = os.getenv("SESSION_COOKIE_NAME", "paperwiki_session").strip()
        self.session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "604800"))
        self.session_cookie_secure = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        self.llm_chat_model = os.getenv("LLM_CHAT_MODEL", "deepseek-v4-flash")
        self.llm_json_response_format = os.getenv(
            "LLM_JSON_RESPONSE_FORMAT", "true"
        ).lower() in {"1", "true", "yes"}
        self.llm_streaming = os.getenv("LLM_STREAMING", "true").lower() in {
            "1",
            "true",
            "yes",
        }
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
