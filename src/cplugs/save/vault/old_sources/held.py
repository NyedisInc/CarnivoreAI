
from __future__ import annotations

from typing import Callable, Dict, Iterable, Iterator, Optional, Set, Tuple

import structlog

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.manifest import FileEntry
from src.cplugs.save.vault.old_sources import model, names
from src.cplugs.save.vault.old_sources.plan import HELD_PREFIX
from src.cplugs.save.vault.store import Vault
from src.cplugs.save.vault.units import Scanner, Sources
from src.cplugs.sdk.blob_codec import BlobCorrupt, BlobMissing

logger = structlog.get_logger()

VAULT_SOURCE, DISK_SOURCE = HELD_PREFIX + "vault", HELD_PREFIX + "disk"
_LINE_ROLES = (K.ROLE_TRANSCRIPT, K.ROLE_CODEX_ROLLOUT, K.ROLE_SUBAGENT)


def _entry_opener(vault: Vault, entry: FileEntry) -> Callable[[], Iterator[bytes]]:
    def open_bytes() -> Iterator[bytes]:
        for ref in entry.chunks:
            yield vault.blobs.get(ref)
    return open_bytes


def vault_copies(vault: Vault, keys: Set[Tuple[str, str]], intake: model.Intake) -> Iterator[model.Copy]:
    """Every transcript and sub-agent file of every point of the units whose conversation key is in ``keys``. Blocking.

    A unit is the conversation id or ``<id>@<8 hex>``. An unreadable manifest or damaged chunk is listed as refused (that held copy then
    decides nothing, so the old copy is planned as if it were not held: it is added, never lost).
    """
    wanted = {conv for _family, conv in keys}
    measured: Dict[str, Tuple[int, str]] = {}
    for unit in vault.manifests.units():
        if unit.split("@", 1)[0] not in wanted:
            continue
        for manifest in vault.manifests.points(unit):
            for entry in manifest.files:
                ident = names.identify(entry.rel) if entry.role in _LINE_ROLES else None
                if ident is None or (ident.family, ident.conv) not in keys and (ident.family, ident.parent) not in keys:
                    continue
                if entry.sha256 not in measured:
                    try:
                        measured[entry.sha256] = model.measure(_entry_opener(vault, entry))
                    except (BlobMissing, BlobCorrupt, OSError) as exc:
                        intake.refused.append(model.Refusal(VAULT_SOURCE, f"{unit}/{manifest.point_id}/{entry.rel}", type(exc).__name__))
                        continue
                length, sha = measured[entry.sha256]
                yield model.Copy(VAULT_SOURCE, f"vault:{unit}/{manifest.point_id}/{entry.rel}", ident, length, sha,
                                 float(manifest.created_epoch), _entry_opener(vault, entry))


def disk_copies(sources: Sources, keys: Iterable[Tuple[str, str]], intake: model.Intake) -> Iterator[model.Copy]:
    scanner = Scanner(sources)
    for family, conv in sorted(set(keys)):
        found: Optional[object] = scanner.plan_claude(conv) if family == "claude" else scanner.codex().get(conv)
        if found is None:
            continue
        for planned in found.files:
            ident = names.identify(planned.rel) if planned.role in _LINE_ROLES else None
            if ident is None:
                continue
            path = planned.path

            def open_bytes(p=path) -> Iterator[bytes]:
                with open(p, "rb") as handle:
                    while block := handle.read(model.READ_BLOCK):
                        yield block

            try:
                length, sha = model.measure(open_bytes)
                yield model.Copy(DISK_SOURCE, f"file:{path}", ident, length, sha, path.stat().st_mtime, open_bytes)
            except OSError as exc:
                intake.refused.append(model.Refusal(DISK_SOURCE, f"file:{path}", type(exc).__name__))
