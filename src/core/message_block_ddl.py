
from __future__ import annotations

from typing import Tuple

EXTRACTOR_VERSION: int = 1

DERIVED_TYPE_STRING_CONTENT = "_string_content"

DERIVED_TYPE_NON_OBJECT = "_non_object_block"

DERIVED_TYPE_UNTYPED = "_untyped_block"

STATUS_BLOCKS_EXTRACTED = "blocks_extracted"
STATUS_CONTENT_STRING = "content_string"
STATUS_NO_MESSAGE_CONTENT = "no_message_content"
STATUS_UNPARSEABLE_BODY = "unparseable_body"
STATUS_UNEXPECTED_CONTENT_SHAPE = "unexpected_content_shape"

BLOCK_STATUSES: Tuple[str, ...] = (
    STATUS_BLOCKS_EXTRACTED,
    STATUS_CONTENT_STRING,
    STATUS_NO_MESSAGE_CONTENT,
    STATUS_UNPARSEABLE_BODY,
    STATUS_UNEXPECTED_CONTENT_SHAPE,
)


DDL_MESSAGE_BLOCK_TYPES = """
CREATE TABLE IF NOT EXISTS message_block_types (
  id     INTEGER PRIMARY KEY,
  value  TEXT NOT NULL UNIQUE
)
"""

DDL_MESSAGE_CONTENT_BLOCKS = """
CREATE TABLE IF NOT EXISTS message_content_blocks (
  id             INTEGER PRIMARY KEY,
  body_id        INTEGER NOT NULL
                  REFERENCES message_bodies(id) ON DELETE CASCADE,
  seq            INTEGER NOT NULL,
  block_type_id  INTEGER NOT NULL REFERENCES message_block_types(id),
  text           TEXT,
  text_length    INTEGER NOT NULL DEFAULT 0,
  tool_name      TEXT,
  tool_use_id    TEXT,
  is_error       INTEGER CHECK (is_error IN (0, 1)),
  UNIQUE (body_id, seq)
)
"""

DDL_MESSAGE_BODY_BLOCK_STATUS = """
CREATE TABLE IF NOT EXISTS message_body_block_status (
  body_id            INTEGER PRIMARY KEY
                      REFERENCES message_bodies(id) ON DELETE CASCADE,
  status             TEXT NOT NULL
                      CHECK (status IN ('blocks_extracted', 'content_string',
                                        'no_message_content',
                                        'unparseable_body',
                                        'unexpected_content_shape')),
  block_count        INTEGER NOT NULL DEFAULT 0,
  detail             TEXT,
  extractor_version  INTEGER NOT NULL,
  processed_at       TEXT NOT NULL
)
"""

DDL_IX_MESSAGE_CONTENT_BLOCKS_TOOL_USE_ID = (
    "CREATE INDEX IF NOT EXISTS ix_message_content_blocks_tool_use_id "
    "ON message_content_blocks (tool_use_id)"
)

DDL_IX_MESSAGE_CONTENT_BLOCKS_TYPE_TOOL = (
    "CREATE INDEX IF NOT EXISTS ix_message_content_blocks_type_tool "
    "ON message_content_blocks (block_type_id, tool_name)"
)

DDL_IX_MESSAGE_BODY_BLOCK_STATUS_STATUS = (
    "CREATE INDEX IF NOT EXISTS ix_message_body_block_status_status "
    "ON message_body_block_status (status)"
)


DDL_V18: Tuple[str, ...] = (
    DDL_MESSAGE_BLOCK_TYPES,
    DDL_MESSAGE_CONTENT_BLOCKS,
    DDL_MESSAGE_BODY_BLOCK_STATUS,
    DDL_IX_MESSAGE_CONTENT_BLOCKS_TOOL_USE_ID,
    DDL_IX_MESSAGE_CONTENT_BLOCKS_TYPE_TOOL,
    DDL_IX_MESSAGE_BODY_BLOCK_STATUS_STATUS,
)

V18_TABLE_NAMES: Tuple[str, ...] = (
    "message_block_types",
    "message_content_blocks",
    "message_body_block_status",
)
