
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_format.model import ConversationRecord
from src.core.crate_format.model_files import FileRecord
from src.core.crate_format.reader import CrateReader
from src.core.crate_import.model import B_ENC_UNMODELED, COPY_ROLES, MODE_RELOCATE, W_ENC_UNMAPPED, Collector
from src.core.project_move.paths import PathMapping

CWD_SCAN_LINES = 64
MAX_ENC_CHARS = 200
VERIFIED_LINE_CWD = "line_cwd"
VERIFIED_WORKING_DIR = "working_dir"
UNMAPPED = "unmapped"


@dataclass(frozen=True)
class EncEntry:

    source: str
    target: str
    verified_by: str
    launch_folder: Optional[str] = None

    def as_json(self) -> Dict[str, str]:
        return {"from": self.source, "to": self.target, "verified_by": self.verified_by}


def first_cwd(lines: Iterable[bytes]) -> Optional[str]:
    for index, raw in enumerate(lines):
        if index >= CWD_SCAN_LINES:
            break
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        cwd = value.get("cwd") if isinstance(value, dict) else None
        if isinstance(cwd, str) and cwd:
            return cwd
    return None


def _head_lines(reader: CrateReader, record: FileRecord) -> List[bytes]:
    buffer = b""
    for chunk in reader.file_chunks(record):
        buffer += chunk
        if buffer.count(b"\n") >= CWD_SCAN_LINES:
            break
    return buffer.split(b"\n")[:CWD_SCAN_LINES]


def launch_folder(reader: CrateReader, conversations: Iterable[ConversationRecord], files: Iterable[FileRecord],
                  enc_folder: str) -> Tuple[Optional[str], str]:
    mains = {c.main_rel: c for c in conversations if c.main_rel}
    for record in files:
        if record.rel in mains and record.enc_folder == enc_folder and record.family != "codex":
            cwd = first_cwd(_head_lines(reader, record))
            if cwd and slugify_project_dir(cwd) == enc_folder:
                return cwd, VERIFIED_LINE_CWD
    for conv in conversations:
        if conv.enc_folder == enc_folder and conv.working_dir and slugify_project_dir(conv.working_dir) == enc_folder:
            return conv.working_dir, VERIFIED_WORKING_DIR
    return None, UNMAPPED


def plan_enc(reader: CrateReader, conversations: List[ConversationRecord], files: List[FileRecord], mapping: PathMapping,
             mode: str, col: Collector) -> Dict[str, EncEntry]:
    sources = sorted({c.enc_folder for c in conversations if c.enc_folder}
                     | {f.enc_folder for f in files if f.enc_folder and f.role not in COPY_ROLES})
    out: Dict[str, EncEntry] = {}
    for enc in sources:
        launch, how = launch_folder(reader, conversations, files, enc)
        mapped = mapping.apply(launch) if launch else None
        if mode != MODE_RELOCATE and (mapped is None or mapped == launch):
            out[enc] = EncEntry(enc, enc, how, launch)
            continue
        if mapped is None:
            out[enc] = EncEntry(enc, enc, UNMAPPED, launch)
            col.warn(W_ENC_UNMAPPED, enc)
            continue
        target = slugify_project_dir(mapped)
        if len(target) > MAX_ENC_CHARS:
            col.block(B_ENC_UNMODELED, target[:60])
        out[enc] = EncEntry(enc, target, how, launch)
    return out
