
from __future__ import annotations

from src.cplugs.sdk.transcript_files import CAP_ENV_VAR, DEFAULT_CAP_BYTES, LIMITS_FILE_NAME, TREE_DIR_NAME  # noqa: F401
from src.cplugs.sdk.transcript_files import SCOPE_ALL, SCOPE_HUMAN, SCOPE_SUBSESSIONS

CODEC_ZSTD: str = "zstd"
CODEC_LZMA: str = "lzma"

CAPTURE_SCOPES: tuple = (SCOPE_HUMAN, SCOPE_SUBSESSIONS, SCOPE_ALL)
DEFAULT_CAPTURE_SCOPE: str = SCOPE_HUMAN
SCOPE_CONFIG_BLOCK: str = "save_pipeline"
SCOPE_CONFIG_FIELD: str = "capture_scope"

TEMP_PREFIX: str = ".tmp-"
