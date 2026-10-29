
from __future__ import annotations

from typing import Dict, List, Optional

from src.core.agent_families import DEFAULT_FAMILY, wrappers_for_family


class WrapperNotFoundError(ValueError):
    pass


class DuplicateWrapperError(ValueError):
    """A wrapper with that id already exists."""


class ReservedWrapperIdError(ValueError):
    pass


def family_of(wrapper: Dict) -> str:
    return wrapper.get("family") or DEFAULT_FAMILY


def find_index(wrappers: List[Dict], wrapper_id: str) -> Optional[int]:
    return next((i for i, w in enumerate(wrappers) if w.get("id") == wrapper_id), None)


def clear_family_default(
    wrappers: List[Dict], family_name: str, skip_index: Optional[int] = None
) -> None:
    for i, w in enumerate(wrappers):
        if i == skip_index:
            continue
        if family_of(w) == family_name:
            w["default"] = False


def add(wrappers: List[Dict], new_wrapper: Dict, reserved_ids) -> List[Dict]:
    wrapper_id = new_wrapper["id"]
    if wrapper_id in reserved_ids:
        raise ReservedWrapperIdError(
            f"'{wrapper_id}' is a reserved agent type, not usable as a wrapper id"
        )
    result = [dict(w) for w in wrappers]
    if find_index(result, wrapper_id) is not None:
        raise DuplicateWrapperError(f"Wrapper '{wrapper_id}' already exists")
    if new_wrapper.get("default"):
        clear_family_default(result, family_of(new_wrapper))
    result.append(dict(new_wrapper))
    return result


KEPT_WHEN_ABSENT = ("icon",)


def update(wrappers: List[Dict], wrapper_id: str, new_wrapper: Dict) -> List[Dict]:
    if new_wrapper["id"] != wrapper_id:
        raise ValueError(
            "wrapper id cannot be changed via update; delete and re-add instead"
        )
    result = [dict(w) for w in wrappers]
    idx = find_index(result, wrapper_id)
    if idx is None:
        raise WrapperNotFoundError(f"Wrapper '{wrapper_id}' not found")
    if new_wrapper.get("default"):
        clear_family_default(result, family_of(new_wrapper), skip_index=idx)
    replacement = dict(new_wrapper)
    for key in KEPT_WHEN_ABSENT:
        if key not in replacement and key in result[idx]:
            replacement[key] = result[idx][key]
    result[idx] = replacement
    return result


def set_icon(wrappers: List[Dict], wrapper_id: str, icon: Optional[str]) -> List[Dict]:
    result = [dict(w) for w in wrappers]
    idx = find_index(result, wrapper_id)
    if idx is None:
        raise WrapperNotFoundError(f"Wrapper '{wrapper_id}' not found")
    result[idx]["icon"] = icon
    return result


def delete(wrappers: List[Dict], wrapper_id: str) -> List[Dict]:
    result = [dict(w) for w in wrappers]
    idx = find_index(result, wrapper_id)
    if idx is None:
        raise WrapperNotFoundError(f"Wrapper '{wrapper_id}' not found")
    removed = result.pop(idx)
    if removed.get("default"):
        siblings = wrappers_for_family(result, family_of(removed))
        if siblings:
            siblings[0]["default"] = True
    return result


def set_default(wrappers: List[Dict], wrapper_id: str) -> List[Dict]:
    result = [dict(w) for w in wrappers]
    idx = find_index(result, wrapper_id)
    if idx is None:
        raise WrapperNotFoundError(f"Wrapper '{wrapper_id}' not found")
    family_name = family_of(result[idx])
    for w in wrappers_for_family(result, family_name):
        w["default"] = (w.get("id") == wrapper_id)
    return result
