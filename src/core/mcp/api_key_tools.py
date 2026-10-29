
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


def _list(call: ra.Call) -> Any:
    return call.route()


def _revoke(call: ra.Call) -> Any:
    return call.route(call.args["key_id"])


SPECS = (
    ra.RouteTool(
        name="api_keys_list", route="src.api.api_keys_routes:list_api_keys", gate=ra.READ,
        description="The owner's API keys for scripts: id, name, display prefix (cak_ plus 6 characters), created, last "
                    "used and revoked times (epoch seconds). Never a key or its hash; keys are made only in the app.",
        properties={}, invoke=_list, example={},
    ),
    ra.RouteTool(
        name="api_key_delete", route="src.api.api_keys_routes:revoke_api_key", gate=ra.ACT,
        description="Revoke one API key by id (from api_keys_list); every script holding it gets 401 from then on. "
                    "Always waits for the owner.",
        properties={"key_id": {"type": "string", "maxLength": 64, "description": "the key id, key_ plus 12 hex characters"}},
        required=("key_id",), invoke=_revoke,
        summary=lambda args, _t: f"revoke api key {str(args.get('key_id'))[:64]}",
        example={"key_id": "key_000000000000"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
