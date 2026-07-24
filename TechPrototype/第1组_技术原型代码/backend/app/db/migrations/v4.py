from __future__ import annotations

import sqlite3

from .runner import Migration


def migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE paper_uploads (
            paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
            owner_user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT,
            visibility TEXT NOT NULL CHECK(visibility IN ('private', 'public')),
            provenance TEXT NOT NULL CHECK(provenance IN ('user_upload', 'legacy_upload')),
            moderation_status TEXT NOT NULL
                CHECK(moderation_status IN ('unreviewed', 'approved', 'rejected')),
            original_filename TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(provenance = 'legacy_upload' OR owner_user_id IS NOT NULL)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO paper_uploads(
            paper_id, owner_user_id, visibility, provenance, moderation_status
        )
        SELECT id, NULL, 'public', 'legacy_upload', 'approved'
        FROM papers WHERE source = 'upload'
        """
    )
    conn.execute(
        "CREATE INDEX idx_paper_uploads_owner ON paper_uploads(owner_user_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX idx_paper_uploads_visibility ON paper_uploads(visibility, moderation_status)"
    )


MIGRATION = Migration(version=4, name="upload-visibility", apply=migrate_v3_to_v4)
