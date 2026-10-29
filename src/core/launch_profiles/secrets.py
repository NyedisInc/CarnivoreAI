
from __future__ import annotations

import asyncio
import re
from typing import Dict, Optional

from src.core.byoai.keys import KeyStore
from src.core.launch_profiles.plan import LaunchPlan
from src.core.launch_profiles.render import STAGING_PREFIX

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class SecretError(RuntimeError):
    """A launch's secrets could not be materialized. The message never carries a value."""


class PreviewRefused(SecretError):
    pass


class KeyUnavailable(SecretError):
    pass


def staging_name(index: int) -> str:
    return f"{STAGING_PREFIX}{index}"


async def materialize(plan: LaunchPlan, *, keys: Optional[KeyStore] = None) -> Dict[str, str]:
    if plan.purpose not in ("pane", "headless"):
        raise PreviewRefused("a preview launch never reads a secret")
    store = keys or KeyStore()
    staged: Dict[str, str] = {}
    for index, (name, ref) in enumerate(plan.secret_refs):
        value = await asyncio.to_thread(store.get, ref)
        if not value or _CONTROL.search(value):
            raise KeyUnavailable(f"no usable key for {name} (reference {ref}): not stored, or the Keychain is locked")
        staged[staging_name(index)] = value
    return staged
