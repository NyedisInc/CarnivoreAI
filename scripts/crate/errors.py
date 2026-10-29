
from __future__ import annotations

from typing import Any, Dict, List, Optional

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_API = 4
EXIT_BLOCKED = 5
EXIT_JOB_FAILED = 6
EXIT_VERIFY = 7
EXIT_INTEGRITY = 8
EXIT_TIMEOUT = 9
EXIT_NETWORK = 10

EXIT_MEANING: Dict[int, str] = {
    EXIT_OK: "success",
    EXIT_USAGE: "bad command line",
    EXIT_AUTH: "no token, or the host refused it (401/403)",
    EXIT_API: "the host refused the call (any other 4xx/5xx; the error code is printed)",
    EXIT_BLOCKED: "the restore plan has blockers; nothing was written",
    EXIT_JOB_FAILED: "a job (export or restore) ended failed",
    EXIT_VERIFY: "the restore finished but its receipt does not match the crate",
    EXIT_INTEGRITY: "a checksum did not match on download or upload",
    EXIT_TIMEOUT: "a job did not finish in the allowed time",
    EXIT_NETWORK: "the host could not be reached",
}


class CrateScriptError(Exception):

    exit_code: int = EXIT_API

    def __init__(self, message: str, *, code: Optional[str] = None, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail

    def as_json(self) -> Dict[str, Any]:
        return {"ok": False, "error": {"class": type(self).__name__, "exit_code": self.exit_code, "code": self.code,
                                      "message": str(self), "detail": self.detail}}


class AuthError(CrateScriptError):

    exit_code = EXIT_AUTH


class ApiError(CrateScriptError):

    exit_code = EXIT_API

    def __init__(self, message: str, *, status: int, code: Optional[str] = None, detail: Any = None) -> None:
        super().__init__(message, code=code, detail=detail)
        self.status = status


class NetworkError(CrateScriptError):

    exit_code = EXIT_NETWORK


class BlockedError(CrateScriptError):

    exit_code = EXIT_BLOCKED

    def __init__(self, message: str, *, blockers: List[Dict[str, Any]]) -> None:
        super().__init__(message, code="blocked", detail=blockers)
        self.blockers = blockers


class JobFailedError(CrateScriptError):

    exit_code = EXIT_JOB_FAILED


class VerifyError(CrateScriptError):

    exit_code = EXIT_VERIFY


class IntegrityError(CrateScriptError):

    exit_code = EXIT_INTEGRITY


class JobTimeoutError(CrateScriptError):

    exit_code = EXIT_TIMEOUT
