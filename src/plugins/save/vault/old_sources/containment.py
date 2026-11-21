
from __future__ import annotations

import hashlib
from typing import Callable, Dict, Iterator, List, Sequence, Tuple

Version = Tuple[str, int, Callable[[], Iterator[bytes]]]


def prefix_hashes(opener: Callable[[], Iterator[bytes]], lengths: Sequence[int]) -> Dict[int, str]:
    wanted = sorted(set(lengths))
    out: Dict[int, str] = {}
    digest, position, index = hashlib.sha256(), 0, 0
    while index < len(wanted) and wanted[index] == 0:
        out[0] = digest.hexdigest()
        index += 1
    for block in opener():
        start = 0
        while index < len(wanted) and wanted[index] <= position + len(block):
            cut = wanted[index] - position
            digest.update(block[start:cut])
            start = cut
            out[wanted[index]] = digest.copy().hexdigest()
            index += 1
        digest.update(block[start:])
        position += len(block)
    return out


def covered_by(versions: Sequence[Version]) -> Dict[str, str]:
    ordered: List[Version] = sorted(versions, key=lambda v: (-v[1], v[0]))
    result: Dict[str, str] = {}
    for i, (big_sha, big_len, big_open) in enumerate(ordered):
        candidates = [v for v in ordered[i + 1:] if v[1] < big_len and v[0] not in result]
        if not candidates:
            continue
        found = prefix_hashes(big_open, [v[1] for v in candidates])
        for sha, length, _open in candidates:
            if found.get(length) == sha:
                result[sha] = big_sha
    return result
