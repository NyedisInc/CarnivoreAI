
from __future__ import annotations

TABLE: str = "conversation_index"
FTS_TABLE: str = "conversation_index_fts"

FTS_SHADOW_TABLES: tuple = tuple(f"{FTS_TABLE}_{part}" for part in ("data", "idx", "docsize", "config"))

STATE_NONE: str = "none"
STATE_QUEUED: str = "queued"
STATE_RUNNING: str = "running"
STATE_DONE: str = "done"
STATE_FAILED: str = "failed"
SUMMARY_STATES: tuple = (STATE_NONE, STATE_QUEUED, STATE_RUNNING, STATE_DONE, STATE_FAILED)

ENDED_REASONS: tuple = ("clear", "fork", "resume", "kill", "remove", "switch")

KEY_AUTO_SUMMARIES: str = "index_auto_summaries"
KEY_RECENT_MESSAGES: str = "index_recent_messages"
KEY_PAUSED: str = "index_summaries_paused"
DEFAULT_AUTO_SUMMARIES: bool = True
DEFAULT_RECENT_MESSAGES: int = 6
MIN_RECENT_MESSAGES: int = 1
MAX_RECENT_MESSAGES: int = 30

FIRST_PROMPT_CHARS: int = 600
FILES_TOUCHED_MAX: int = 20
PATH_CHARS: int = 300
SUMMARY_CHARS: int = 12_000

FIRST_PROMPT_MAX_BYTES: int = 2 * 1024
RECENT_MESSAGES_MAX_BYTES: int = 8 * 1024
FILES_TOUCHED_MAX_BYTES: int = 4 * 1024
RETENTION_DAYS: int = 180

EST_SECONDS_LOW: int = 60
EST_SECONDS_HIGH: int = 90

SEARCH_LIMIT_DEFAULT: int = 20
SEARCH_LIMIT_MAX: int = 100
SNIPPET_TOKENS: int = 24
BM25_WEIGHTS: tuple = (4.0, 1.0, 3.0, 2.0, 3.0)
