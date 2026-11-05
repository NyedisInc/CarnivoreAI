
from __future__ import annotations

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REPO_SCRIPT = REPO / "scripts" / "deploy-dmg.sh"
LIB_FILES = ("deploy-engine-stop.sh", "deploy-rollback.sh", "deploy-dry-run.sh", "deploy-backup.sh")
_SOURCE_LINE = re.compile(r'^source "\$\(dirname "\$0"\)/lib/deploy-')


def lib_dir(script: Path) -> Path:
    override = os.environ.get("DEPLOY_DMG_LIB_DIR")
    return Path(override) if override else script.parent / "lib"


def script_text(script: Path | None = None) -> str:
    script = script or Path(os.environ.get("DEPLOY_DMG_SCRIPT") or REPO_SCRIPT)
    text = "\n".join(l for l in script.read_text(encoding="utf-8").splitlines() if not _SOURCE_LINE.match(l))
    return text + "\n" + "\n".join((lib_dir(script) / name).read_text(encoding="utf-8") for name in LIB_FILES)
