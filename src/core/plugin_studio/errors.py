
from __future__ import annotations

from typing import Any, Dict, Optional


class PluginStudioError(Exception):

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(detail)
        self.status = int(status)
        self.code = str(code)
        self.detail = str(detail)
        self.extra: Dict[str, Any] = dict(extra or {})

    def to_wire(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"code": self.code, "detail": self.detail}
        payload.update(self.extra)
        return payload


class WorkspaceNotFoundError(PluginStudioError):

    def __init__(self, studio_id: str) -> None:
        super().__init__(
            404,
            "studio_workspace_not_found",
            f"Plugin Studio workspace {studio_id!r} was not found.",
            extra={"studio_id": studio_id},
        )


class WorkspaceValidationError(PluginStudioError):

    def __init__(
        self,
        detail: str,
        *,
        code: str = "studio_validation_error",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(422, code, detail, extra=extra)


class WorkspaceConflictError(PluginStudioError):

    def __init__(
        self,
        detail: str,
        *,
        code: str = "studio_conflict",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(409, code, detail, extra=extra)


class AgyProfileNotConfiguredError(WorkspaceConflictError):

    def __init__(self) -> None:
        super().__init__(
            "No Antigravity (agy) launch profile is configured in Carnivore settings.",
            code="agy_profile_not_configured",
        )


class StudioActionError(PluginStudioError):

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(status, code, detail, extra=extra)
