
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from src.core.blobcodec.codec import decompress
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.plan import ExportRequest
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk.crate_sources import PaneListing
from tests.python.inventory.world_build import build_world
from tests.python.inventory.world import UUID_A, UUID_B  # noqa: F401

ASLEEP = PaneListing(ok=True, panes=())


def make_world(tmp_path: Path) -> SimpleNamespace:
    return build_world(tmp_path)


def env_for(w: SimpleNamespace, listing: PaneListing = ASLEEP, **settings: Any) -> CrateEnv:
    work = Path(w.state) / "cplugs" / "crate"
    work.mkdir(parents=True, exist_ok=True)
    return CrateEnv(state=Path(w.state), locations=w.locations, work=work, settings=dict(settings),
                    live_panes=lambda: listing)


def project_request(w: SimpleNamespace, variant: str = "own", **kw: Any) -> ExportRequest:
    return ExportRequest("project", w.root1, variant, **kw)


def session_request(uuid: str = UUID_A, variant: str = "own", **kw: Any) -> ExportRequest:
    return ExportRequest("session", uuid, variant, **kw)


def crate_text(path: Path, identity: Optional[str] = None) -> bytes:
    out = []
    with cf.open_crate(path, identity) as reader:
        for member in reader.members():
            found = member.name.startswith("blobs/") and reader.blob_member(member.name.split("/")[-1].split(".")[0])
            raw = reader.read_member(member.name)
            out.append(decompress(raw, found[1]) if found else raw)
    return b"\n".join(out)
