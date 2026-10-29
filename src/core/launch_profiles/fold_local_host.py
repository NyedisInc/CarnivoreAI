
from __future__ import annotations

from typing import Any, Dict, Set

from src.config.byoai import BYOAI_KEY, ByoaiConfig, ConnectionConfig
from src.config.providers import ProvidersConfig
from src.core.byoai.presets import get_preset
from src.core.byoai.transport import key_origin

LMSTUDIO_CONNECTION_ID = "lmstudio"


def fold_local_host(data: Dict[str, Any]) -> Dict[str, Any]:
    providers = data.get("providers")
    raw = providers.get("local_host") if isinstance(providers, dict) else ""
    host = ProvidersConfig.model_validate({"local_host": raw if isinstance(raw, str) else ""}).local_host
    if not host:
        return data
    base_url = f"http://{host}/v1"
    block = ByoaiConfig.model_validate(data.get(BYOAI_KEY) or {})
    if any(c.preset == "lmstudio" and key_origin(c.base_url) == key_origin(base_url) for c in block.connections):
        return data
    taken: Set[str] = {c.id for c in block.connections}
    cid = LMSTUDIO_CONNECTION_ID
    n = 1
    while cid in taken:
        n += 1
        cid = f"{LMSTUDIO_CONNECTION_ID}-{n}"
    block.connections.append(ConnectionConfig(id=cid, preset="lmstudio", label=get_preset("lmstudio").label, base_url=base_url))
    block.revision += 1
    return {**data, BYOAI_KEY: block.model_dump(mode="json")}
