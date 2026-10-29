
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp.common import ToolError

_MACHINE = {"machine": {"type": "string", "maxLength": 64,
                        "description": "a machine's install id or label (as computers_list with detail specs lists), or \"self\""}}


def _master(call: ra.Call) -> Any:
    from src.api.pack_machines_routes import MasterBody

    return call.route(MasterBody(machine=call.args["machine"]), call.request)


def _settings(call: ra.Call) -> Any:
    from src.api.pack_machines_routes import SettingsBody

    return call.route(SettingsBody(**{k: v for k, v in call.args.items() if k != "huddle_item"}), call.request)


def _get(call: ra.Call) -> Any:
    return call.route(call.args["machine"], call.request)


def _tracks_get(call: ra.Call) -> Any:
    return call.route(call.request)


def _tracks_set(call: ra.Call) -> Any:
    from src.api.pack_machines_routes import TracksMasterBody

    return call.route(TracksMasterBody(tracks_master=call.args["tracks_master"]), call.request)


def _reserve_set(call: ra.Call) -> Any:
    from src.api.pack_machines_routes import ReserveBody

    body = {k: v for k, v in call.args.items() if k not in ("machine", "huddle_item")}
    return call.route(call.args["machine"], ReserveBody(**body), call.request)


def _restrictions_set(call: ra.Call) -> Any:
    from src.api.pack_machines_routes import RestrictionsBody

    body = {k: v for k, v in call.args.items() if k not in ("machine", "huddle_item")}
    if "may_receive_credentials" in body and body["may_receive_credentials"] is not False:
        raise ToolError("may_receive_credentials can only be switched on by the owner in the app")
    return call.route(call.args["machine"], RestrictionsBody(**body), call.request)


def _summary(verb: str):
    return lambda args, _target: f"{verb} ({', '.join(f'{k}={v}' for k, v in args.items() if k != 'huddle_item')[:200]})"


SPECS = (
    ra.RouteTool(
        name="pack_master_set", route="src.api.pack_machines_routes:put_master", gate=ra.ACT,
        description="Make one computer the Pack master (it holds the Pack-wide settings and runs SysOp). Run on the "
                    "current master it reaches the other computers by the exchange; run elsewhere it changes only this computer, "
                    "because the others accept only the master's signed change.",
        properties=_MACHINE, required=("machine",), invoke=_master, summary=_summary("make a computer the Pack master"),
        example={"machine": "studio"},
    ),
    ra.RouteTool(
        name="pack_settings_update", route="src.api.pack_machines_routes:put_settings", gate=ra.ACT,
        description="Change Pack-wide settings: placement_mode (stats or enhanced), auto_distribute, placement_model "
                    "({connection, model} or null). Only on the master; elsewhere it answers 409 not_alpha.",
        properties={"placement_mode": {"type": "string", "enum": ["stats", "enhanced"]}, "auto_distribute": {"type": "boolean"},
                    "placement_model": {"type": ["object", "null"],
                                        "properties": {"connection": {"type": "string"}, "model": {"type": "string"}}}},
        invoke=_settings, summary=_summary("change the Pack settings"), example={"auto_distribute": True},
    ),
    ra.RouteTool(
        name="pack_tracks_master_get", route="src.api.pack_machines_routes:get_tracks_master", gate=ra.READ,
        description="Whether this computer follows the master: when on (the default), a Carnivore change landed on another Pack "
                    "computer refreshes this one's install too.",
        properties={}, invoke=_tracks_get, example={},
    ),
    ra.RouteTool(
        name="pack_tracks_master_set", route="src.api.pack_machines_routes:put_tracks_master", gate=ra.ACT,
        description="Turn this computer's follow-the-master refresh on or off (it still needs the computer's own may_update_carnivore rule).",
        properties={"tracks_master": {"type": "boolean"}}, required=("tracks_master",), invoke=_tracks_set,
        summary=_summary("change whether this computer follows the master"), example={"tracks_master": True},
    ),
    ra.RouteTool(
        name="pack_reserve_get", route="src.api.pack_machines_routes:get_reserve", gate=ra.READ,
        description="One computer's compute reserve settings (in use and away levels, schedule, keyboard rule) and the level in force now.",
        properties=_MACHINE, required=("machine",), invoke=_get, example={"machine": "self"},
    ),
    ra.RouteTool(
        name="pack_reserve_set", route="src.api.pack_machines_routes:put_reserve", gate=ra.ACT,
        description="Edit one computer's compute reserve from any computer. in_use and away are {cpu_pct, mem_pct}; schedule is "
                    "{in_use_from, in_use_to, days}; keyboard_rule is {enabled, idle_minutes}. That computer enforces it.",
        properties={**_MACHINE, "in_use": {"type": "object"}, "away": {"type": "object"}, "schedule": {"type": "object"},
                    "keyboard_rule": {"type": "object"}},
        required=("machine",), invoke=_reserve_set, summary=_summary("change a computer's compute reserve"),
        example={"machine": "self", "in_use": {"cpu_pct": 30}},
    ),
    ra.RouteTool(
        name="pack_restrictions_get", route="src.api.pack_machines_routes:get_restrictions", gate=ra.READ,
        description="One computer's restrictions: may_install_tools, may_receive_credentials, may_update_carnivore, may_host_agents, "
                    "may_receive_projects, max_agents, allowed_projects, allowed_companies.",
        properties=_MACHINE, required=("machine",), invoke=_get, example={"machine": "self"},
    ),
    ra.RouteTool(
        name="pack_restrictions_set", route="src.api.pack_machines_routes:put_restrictions", gate=ra.ACT,
        description="Change a computer's restrictions. On this computer any change; on another computer only a tightening "
                    "(that computer refuses a loosening: only its own owner loosens).",
        properties={**_MACHINE, "may_install_tools": {"type": "boolean"}, "may_receive_credentials": {"type": "boolean"},
                    "may_update_carnivore": {"type": "boolean"}, "may_host_agents": {"type": "boolean"},
                    "may_receive_projects": {"type": "boolean"}, "max_agents": {"type": ["integer", "null"], "minimum": 0},
                    "allowed_projects": {"type": "array", "items": {"type": "string"}},
                    "allowed_companies": {"type": "array", "items": {"type": "string"}}},
        required=("machine",), invoke=_restrictions_set, summary=_summary("change a computer's restrictions"),
        example={"machine": "self", "max_agents": 4},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
