from functools import lru_cache
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"


class Settings:
    def __init__(self) -> None:
        self.database_path = Path(os.getenv("DATABASE_PATH", DATA_DIR / "arxiv_wiki.sqlite3"))
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_chat_model = os.getenv("LLM_CHAT_MODEL", "gpt-4o-mini")
        self.llm_embed_model = os.getenv("LLM_EMBED_MODEL", "text-embedding-3-small")
        self.enable_mock_llm = os.getenv("ENABLE_MOCK_LLM", "true").lower() != "false"
        categories = os.getenv("ARXIV_DEFAULT_CATEGORIES", "cs.AI,cs.CL,cs.LG")
        self.default_categories = [item.strip() for item in categories.split(",") if item.strip()]

    @property
    def should_use_mock_llm(self) -> bool:
        return self.enable_mock_llm or not self.llm_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
