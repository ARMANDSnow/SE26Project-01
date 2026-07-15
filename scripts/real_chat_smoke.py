from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import get_settings
from backend.app.database import init_schema
from backend.app.services.conversations import create_thread, prepare_run, stream_run


EXPECTED = "GENERAL_CHAT_SMOKE_OK"


def main() -> int:
    if os.getenv("RUN_REAL_LLM_TESTS", "").lower() not in {"1", "true", "yes"}:
        print("SKIP: set RUN_REAL_LLM_TESTS=1 to run the paid real-chat smoke.")
        return 0
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.llm_available:
        print("FAIL: real-chat smoke requires a non-empty LLM_API_KEY.")
        return 2

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    try:
        thread = create_thread(conn, None, title="real-chat-smoke")
        run = prepare_run(
            conn,
            thread_id=thread["id"],
            user_message={
                "id": "real-chat-user-1",
                "parent_id": None,
                "content": f"只回复以下文本，不要添加其他内容：{EXPECTED}",
            },
            parent_message_id=None,
            assistant_message_id="real-chat-assistant-1",
            source_message_id=None,
            message_token_limit=12000,
        )
        events = list(stream_run(conn, run))
        failed = next((data for event, data in events if event == "run.failed"), None)
        if failed is not None:
            print(f"FAIL: real-chat smoke returned {failed.get('message', 'unknown error')}.")
            return 3
        completed = next((data for event, data in events if event == "message.completed"), None)
        content = completed.get("content", "") if completed else ""
        if EXPECTED not in content:
            print("FAIL: real-chat smoke response did not contain the expected marker.")
            return 4
        print(f"PASS: real-chat smoke completed with {settings.llm_chat_model}.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
