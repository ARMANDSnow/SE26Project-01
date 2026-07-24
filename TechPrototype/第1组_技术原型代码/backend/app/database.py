"""Compatibility facade for split database and repository modules.

New production code should import from db or repositories directly.
This module remains temporarily stable for tests and pre-iter08 services.
"""

from .db.connection import connect
from .db.schema import (
    PAPER_CHUNKS_FTS_TABLE,
    SCHEMA_VERSION,
    IncompatibleSchemaError,
    init_db,
    init_paper_chunks_fts,
    init_schema,
    paper_chunks_fts_ready,
    rebuild_paper_chunks_fts,
    supports_fts5,
)
from .repositories.learning import add_note, add_reading_history, get_history, get_subscriptions, upsert_subscription
from .repositories.library import (
    create_library_folder,
    delete_library_folder,
    ensure_user_library,
    list_library_folders,
    list_library_items,
    move_library_item,
    set_favorite,
)
from .repositories.papers import (
    attach_concepts,
    find_existing_paper_id,
    get_paper_detail,
    get_paper_record,
    list_paper_chunks,
    list_papers,
    paper_exists,
    rebuild_concept_edges,
    replace_paper_chunks,
    replace_wiki_sections,
    row_to_paper,
    row_to_paper_record,
    set_paper_asset_id,
    upsert_paper,
)

__all__ = [
    "PAPER_CHUNKS_FTS_TABLE",
    "SCHEMA_VERSION",
    "IncompatibleSchemaError",
    "add_note",
    "add_reading_history",
    "attach_concepts",
    "connect",
    "create_library_folder",
    "delete_library_folder",
    "ensure_user_library",
    "find_existing_paper_id",
    "get_history",
    "get_paper_detail",
    "get_paper_record",
    "get_subscriptions",
    "init_db",
    "init_paper_chunks_fts",
    "init_schema",
    "list_library_folders",
    "list_library_items",
    "list_paper_chunks",
    "list_papers",
    "move_library_item",
    "paper_chunks_fts_ready",
    "paper_exists",
    "rebuild_concept_edges",
    "rebuild_paper_chunks_fts",
    "replace_paper_chunks",
    "replace_wiki_sections",
    "row_to_paper",
    "row_to_paper_record",
    "set_favorite",
    "set_paper_asset_id",
    "supports_fts5",
    "upsert_paper",
    "upsert_subscription",
]
