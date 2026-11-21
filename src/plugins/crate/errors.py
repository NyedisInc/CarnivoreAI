
from __future__ import annotations

from typing import Any, Awaitable, Dict

from fastapi import HTTPException


class CrateApiError(Exception):

    def __init__(self, status: int, code: str, detail: Any) -> None:
        super().__init__(f"{code}: {detail}")
        self.status, self.code, self.detail = status, code, detail

    def body(self) -> Dict[str, Any]:
        return {"code": self.code, "detail": self.detail}

    def sentence(self) -> str:
        detail = self.detail if isinstance(self.detail, str) else repr(self.detail)[:600]
        return f"{self.code}: {detail}"


def not_found(code: str, detail: str) -> CrateApiError:
    return CrateApiError(404, code, detail)


def conflict(code: str, detail: Any) -> CrateApiError:
    return CrateApiError(409, code, detail)


def invalid(code: str, detail: str) -> CrateApiError:
    return CrateApiError(422, code, detail)


async def answered(work: Awaitable[Any]) -> Any:
    try:
        return await work
    except CrateApiError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.body()) from exc
