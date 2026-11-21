
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

BACKUP_DIRNAME = "config-backups"


def back_up_config(config_path: Path, state_dir: Path) -> tuple[Path, str]:
    backup_dir = state_dir / BACKUP_DIRNAME
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"config.{stamp}.json"

    if not config_path.exists():
        return target, "NOT_PRESENT"

    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, target)

    if not target.exists() or target.stat().st_size != config_path.stat().st_size:
        raise RuntimeError(
            f"backup of {config_path} did not land at {target}; refusing to "
            "modify the config without a verified copy"
        )

    manifest = backup_dir / ".manifest"
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write(f"BACKED_UP\tconfig\t{target.name}\n")

    return target, "BACKED_UP"
