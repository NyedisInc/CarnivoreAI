
from __future__ import annotations

from typing import Any, List, Mapping

ZONE_HOSTS = ("home", "terminal", "drawer")
REQUIRED_FIXTURES = ("data", "empty")


def problems_in(record: Mapping[str, Any]) -> List[str]:
    problems: List[str] = []
    hosts = record.get("hosts", [])
    if "glance" in hosts and "glance" not in record:
        problems.append("hosts: glance is a host but no glance height is declared")
    if "glance" in record and "glance" not in hosts:
        problems.append("glance: a glance height is declared but glance is not one of the hosts")
    if "popout" in hosts and "home" not in hosts:
        problems.append("hosts: popout draws the home host in its own window, so it needs home")
    if record.get("instancing") == "singleton" and record.get("max_per_surface") not in (None, 1):
        problems.append("max_per_surface: a singleton can only declare 1")
    return problems


def missing_fixtures(record: Mapping[str, Any]) -> List[str]:
    have = record.get("fixtures", [])
    return [name for name in REQUIRED_FIXTURES if name not in have]
