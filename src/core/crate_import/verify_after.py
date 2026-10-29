
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from src.core.blobcodec.place import file_matches
from src.core.crate_import.analysis import Analysis
from src.core.crate_import.env import ImportEnv
from src.core.crate_import import files_place
from src.core.session_imported_restart import DIRECTORY_MEASURED, resume_directory

W_ENC_UNVERIFIED = "enc_unverified"
W_FILE_MISMATCH = "file_mismatch"


@dataclass
class Checks:

    resume_measured: List[str] = field(default_factory=list)
    resume_unverified: Dict[str, str] = field(default_factory=dict)
    file_mismatch: List[str] = field(default_factory=list)

    def warnings(self) -> List[Dict[str, str]]:
        return ([{"code": W_ENC_UNVERIFIED, "detail": f"{u}: {o}"} for u, o in sorted(self.resume_unverified.items())]
                + [{"code": W_FILE_MISMATCH, "detail": p} for p in self.file_mismatch])


def run(a: Analysis, env: ImportEnv, conn: sqlite3.Connection, written: Sequence[str], session_ids: Iterable[int]) -> Checks:
    checks = Checks()
    expect = {str(p.dest): p.record for p in a.placements if p.dest is not None and p.action == files_place.ACT_PLACE}
    for path in written:
        record = expect.get(path)
        if record is None or not file_matches(Path(path), record.content_sha256, record.length):
            checks.file_mismatch.append(path)
    wanted = list(session_ids)
    marks = ", ".join("?" for _ in wanted)
    rows = conn.execute(f"SELECT session_uuid, working_dir, claude_session_uuid, agent_family FROM sessions WHERE id IN ({marks})", wanted).fetchall() if wanted else []
    root = env.claude_projects_root()
    pinned = {c: h / "projects" for c, h in a.homes.items()}
    for row in rows:
        if row["agent_family"] == "codex" or not row["claude_session_uuid"]:
            continue
        got = resume_directory(row["working_dir"], row["claude_session_uuid"], corpus_root=pinned.get(row["claude_session_uuid"], root))
        if got.outcome == DIRECTORY_MEASURED:
            checks.resume_measured.append(row["session_uuid"])
        else:
            checks.resume_unverified[row["session_uuid"]] = got.outcome
    return checks
