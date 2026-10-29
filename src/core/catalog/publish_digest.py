
from __future__ import annotations

import hashlib
from typing import Dict, Iterable, List, Tuple

from src.core.skills.digest import MODE_REGULAR, DigestEntry, digest_entries

Members = Iterable[Tuple[str, bytes]]


def file_map(members: Members) -> Dict[str, str]:
    return {path: hashlib.sha256(content).hexdigest() for path, content in members}


def hosted_digest(members: Members) -> str:
    return digest_entries(DigestEntry(path, MODE_REGULAR, sha) for path, sha in file_map(members).items())


def changed_paths(sent: Dict[str, str], now: Dict[str, str]) -> List[str]:
    return sorted(path for path in sent.keys() | now.keys() if sent.get(path) != now.get(path))
