"""DDL for schema v18: the derived content-block index.

  Cross-check: 1,302,387 + 45,111 = 1,347,498, which is exactly
  assistant 845,778 + user 501,720. Every assistant and user body has
  ``message.content`` and no other record type does. The 1,099,530 with
  no ``message`` key are progress (917,436), attachment (73,012),
  queue-operation (50,163), system (26,091) and 12 smaller types, which
  carry ``data``, ``attachment`` or a TOP-LEVEL ``content`` instead.
  Those are deliberately OUT OF SCOPE here - they are a different shape
  and folding them in would put four unrelated things in one column.

  Blocks per body: min 1, p50 1, p95 1, p99 1, max 9. 1,301,852 of the
  1,302,387 array bodies hold exactly one block. The table is therefore
  roughly ONE row per content-bearing body, not the 10M row explosion
  the shape suggests.

  Block types, complete census: tool_result 452,443, tool_use 450,501,
  text 258,703, thinking 140,769, image 605, document 92, fallback 3.
  Seven types, no others.

THIS TABLE IS DERIVED AND IT IS NEVER AUTHORITATIVE. ``body_json``
remains the source of truth for byte-exact export. If the two ever
disagree, ``body_json`` wins and this table is rebuilt. Nothing in the
export path reads it - ``tests/test_message_block_derived_only.py``
asserts that structurally, by dropping the tables and exporting anyway.
That is the whole reason it may be rebuilt at will: dropping it can cost
query speed and can never cost data.

WHY A SEPARATE STATUS TABLE, AND NOT A NULLABLE COLUMN. Absence must
never read as emptiness. Three states are genuinely different and a
caller has to be able to tell them apart:

  body absent from message_body_block_status  NEVER PROCESSED
  status row, block_count 0                   processed, genuinely none
  status 'unparseable_body'                   COULD NOT EVALUATE

A single "0 blocks" answer collapses all three into the one that looks
like good news, which is the exact false-green this repo's THREE-OUTCOME
RULE exists to stop. The status table is also what makes the backfill
resumable: the work remaining is the antijoin against it, so an
interrupted run resumes instead of starting over.

SECRETS. A block's text is a SUBSTRING of the body text that
``archive_snippet_gate`` already governs, so it inherits exactly the
same exposure and must inherit exactly the same gate. Every block row
carries ``body_id``, which is the key the gate's layer 1 already uses,
and its text is a valid gate WINDOW for layers 2 and 3. There is
therefore no new gate and no second policy - see
message_block_preview.gated_block_preview, which is the only supported
way to serve this text to a caller.
"""

from __future__ import annotations

from typing import Tuple

EXTRACTOR_VERSION: int = 1

# not present in
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

# could not
STATUS_COULD_NOT_EVALUATE: Tuple[str, ...] = (
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

V18_INDEX_NAMES: Tuple[str, ...] = (
    "ix_message_content_blocks_tool_use_id",
    "ix_message_content_blocks_type_tool",
    "ix_message_body_block_status_status",
)
