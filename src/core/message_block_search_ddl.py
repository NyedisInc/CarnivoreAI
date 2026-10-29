
from __future__ import annotations

from typing import Tuple

BLOCK_SEARCH_TABLE: str = "message_block_search"

BLOCK_SEARCH_TOKENIZER: str = "unicode61 remove_diacritics 2"

BLOCK_SEARCH_TRIGGERS: Tuple[str, ...] = (
    "message_block_search_ai",
    "message_block_search_ad",
    "message_block_search_au",
)

DDL_MESSAGE_BLOCK_SEARCH = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {BLOCK_SEARCH_TABLE} USING fts5(
  text,
  content='',
  contentless_delete=1,
  tokenize="{BLOCK_SEARCH_TOKENIZER}"
)
"""

DDL_TRIGGER_BLOCK_SEARCH_INSERT = f"""
CREATE TRIGGER IF NOT EXISTS message_block_search_ai
AFTER INSERT ON message_content_blocks
WHEN new.text IS NOT NULL AND new.text <> ''
BEGIN
  INSERT INTO {BLOCK_SEARCH_TABLE}(rowid, text) VALUES (new.id, new.text);
END
"""

DDL_TRIGGER_BLOCK_SEARCH_DELETE = f"""
CREATE TRIGGER IF NOT EXISTS message_block_search_ad
AFTER DELETE ON message_content_blocks
BEGIN
  DELETE FROM {BLOCK_SEARCH_TABLE} WHERE rowid = old.id;
END
"""

DDL_TRIGGER_BLOCK_SEARCH_UPDATE = f"""
CREATE TRIGGER IF NOT EXISTS message_block_search_au
AFTER UPDATE ON message_content_blocks
BEGIN
  DELETE FROM {BLOCK_SEARCH_TABLE} WHERE rowid = old.id;
  INSERT INTO {BLOCK_SEARCH_TABLE}(rowid, text)
    SELECT new.id, new.text WHERE new.text IS NOT NULL AND new.text <> '';
END
"""

DDL_V31: Tuple[str, ...] = (
    DDL_MESSAGE_BLOCK_SEARCH,
    DDL_TRIGGER_BLOCK_SEARCH_INSERT,
    DDL_TRIGGER_BLOCK_SEARCH_DELETE,
    DDL_TRIGGER_BLOCK_SEARCH_UPDATE,
)

V31_OBJECT_NAMES: Tuple[str, ...] = (
    BLOCK_SEARCH_TABLE,
) + BLOCK_SEARCH_TRIGGERS
