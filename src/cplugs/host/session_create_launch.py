
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit

REMOTE_ROOT_PREFIXES = ("ssh://", "peer://")
SKIP_ALL = "skip_all"


class LaunchUnresolvable(LookupError):
    pass


@dataclass(frozen=True)
class Launch:

    project: str
    working_dir: str
    where: str
    agent_type: str
    profile_id: str
    profile_label: str
    permissions: str
    badge: str
    custom_command: bool = False

    @property
    def skips_permissions(self) -> bool:
        return self.permissions == SKIP_ALL

    @property
    def unchecked(self) -> bool:
        return self.custom_command and not self.skips_permissions

    @property
    def dangerous(self) -> bool:
        return self.skips_permissions or self.unchecked

    def shown(self) -> Dict[str, Any]:
        return {**asdict(self), "skips_permissions": self.skips_permissions, "unchecked": self.unchecked}


def resolve(project: Mapping[str, Any], family: Optional[str]) -> Launch:
    from src.config import settings  # noqa: PLC0415
    from src.core.launch_profiles.endpoints import EndpointRefused  # noqa: PLC0415
    from src.core.launch_profiles.resolve import LaunchProfileNotFound, LaunchRequest, pick_profile, resolve_launch  # noqa: PLC0415
    from src.core.launch_profiles.summary import summary_row  # noqa: PLC0415
    from src.core.opening_prompt import launch_agent_type  # noqa: PLC0415

    agent_type = launch_agent_type(settings, family or project.get("default_launch_profile") or None, project["name"])
    request = LaunchRequest(profiles=tuple(settings.get_launch_profiles()), agent_type=agent_type, connections=_connections(settings))
    try:
        profile = pick_profile(request)
        plan = resolve_launch(request, "preview")
    except (LaunchProfileNotFound, EndpointRefused, ValueError, NotImplementedError) as exc:
        raise LaunchUnresolvable(type(exc).__name__) from exc
    row = summary_row(profile)
    path = str(project["path"])
    return Launch(project=str(project["name"]), working_dir=path, where=_where(path), agent_type=agent_type, profile_id=str(row["id"]),
                  profile_label=str(row["label"]), permissions=plan.display.permissions, badge=str(row["permissions_badge"]),
                  custom_command=plan.script_file is not None or _runs_user_code(profile))


def _connections(settings: Any) -> tuple:
    from src.core.byoai.contracts import to_connection  # noqa: PLC0415

    byoai = getattr(settings.load_auth_config(), "byoai", None)
    return tuple(to_connection(c) for c in byoai.connections) if byoai is not None else ()


def _runs_user_code(profile: Any) -> bool:
    return bool((profile.before_launch or "").strip()) or any(row.name.strip().upper() == "PATH" for row in profile.env)


def _where(path: str) -> str:
    if not path.startswith(REMOTE_ROOT_PREFIXES):
        return path
    host = urlsplit(path).hostname or ""
    return f"paired computer {host}".strip()


def changed(asked: Launch, now: Launch) -> bool:
    return (asked.working_dir, asked.agent_type, asked.profile_id, asked.permissions, asked.custom_command) != (
        now.working_dir, now.agent_type, now.profile_id, now.permissions, now.custom_command)
