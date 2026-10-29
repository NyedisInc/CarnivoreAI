
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.provider_ledger.codex_credentials import CODEX_AUTH_FILE
from src.core.provider_ledger.credentials import claude_identity_path

PathStamp = Optional[Tuple[int, int]]


def signal_paths(account: ProviderAccount) -> List[Path]:
    profile_dir = profile_dir_for(account)
    directory = Path(os.path.expanduser(profile_dir))
    if account.provider == "claude":
        identity_file = claude_identity_path(profile_dir)
    else:
        identity_file = directory / CODEX_AUTH_FILE
    return [identity_file, directory]


def signal_stamp(paths: List[Path]) -> Tuple[PathStamp, ...]:
    stamps: List[PathStamp] = []
    for path in paths:
        try:
            info = path.stat()
        except OSError:
            stamps.append(None)
        else:
            stamps.append((info.st_mtime_ns, info.st_size))
    return tuple(stamps)
