
from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException

from src.config.launch_profiles import LaunchProfile
from src.core.notifications.catalog_lines import read_prefixed

PIN_UNSUPPORTED_CODE = "pin_unsupported"
PIN_UNSUPPORTED_KEY = "api.error.launch_profile_pin_unsupported"
_FALLBACK_SENTENCE = "a launch profile cannot be pinned to an account yet; use follow the active account."


@lru_cache(maxsize=1)
def pin_sentence() -> str:
    return read_prefixed((PIN_UNSUPPORTED_KEY,)).get(PIN_UNSUPPORTED_KEY, _FALLBACK_SENTENCE)


def is_pinned(profile: LaunchProfile) -> bool:
    return profile.account.mode == "pinned"


def refuse_pinned_account(profile: LaunchProfile) -> None:
    if is_pinned(profile):
        sentence = pin_sentence()
        raise HTTPException(status_code=422, detail={
            "code": PIN_UNSUPPORTED_CODE, "message": sentence, "detail": sentence})
