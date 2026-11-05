
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp.common import ToolError


def _status(call: ra.Call) -> Any:
    return call.route()


def _set(call: ra.Call) -> Any:
    from src.api.pack_relay_routes import RelayBody

    if call.args["machines"] != []:
        raise ToolError("only the owner can turn the relay on, in the app; an empty list (switching it off) is allowed")
    return call.route(call.args["account"], RelayBody(machines=call.args["machines"]), call.request)


def _use(call: ra.Call) -> Any:
    return call.route(call.args["account"], call.request)


SPECS = (
    ra.RouteTool(
        name="pack_relay_status", route="src.api.pack_relay_routes:get_relay", gate=ra.READ,
        description="The credential relay (Claude and Codex accounts): for each account, the computers it mirrors to, each one's state (on, pushed, "
                    "failed, refused) and the expiry last pushed. An account with no stored choice is on by default (listed as on for each paired computer); default_on names those accounts.",
        properties={}, invoke=_status, example={},
    ),
    ra.RouteTool(
        name="pack_relay_set", route="src.api.pack_relay_routes:put_relay", gate=ra.ACT,
        description="Set exactly which other computers mirror a Claude or Codex account's access token (never its refresh token). "
                    "Only an empty list works here (it switches the account's relay off); turning it on is the owner's, in the app.",
        properties={"account": {"type": "string", "maxLength": 64, "description": "the provider-ledger account id"},
                    "machines": {"type": "array", "items": {"type": "string", "maxLength": 64}, "maxItems": 32,
                                 "description": "install ids or labels of the target computers"}},
        required=("account", "machines"), invoke=_set,
        summary=lambda args, _t: f"relay account {str(args.get('account'))[:64]} to {len(args.get('machines') or [])} computer(s)",
        example={"account": "larkspur", "machines": []},
    ),
    ra.RouteTool(
        name="pack_relay_account_use", route="src.api.provider_ledger_routes:activate_provider_account", gate=ra.ACT,
        description="Make an account the one this computer's NEW Claude sessions launch on (the providers page switch). Works for a "
                    "relayed account (its id is in the provider ledger with relayed true): new sessions here then need no login. "
                    "Running sessions are not touched.",
        properties={"account": {"type": "string", "maxLength": 80, "description": "the provider-ledger account id, e.g. a relayed row's id"}},
        required=("account",), invoke=_use,
        summary=lambda args, _t: f"make Claude account {str(args.get('account'))[:80]} the default for new sessions",
        example={"account": "0123456789ab-larkspur-relay"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
