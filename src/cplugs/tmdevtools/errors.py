
from __future__ import annotations


class DevToolsError(Exception):

    status = 400
    code = "tmdevtools_error"


class BadArguments(DevToolsError):

    code = "tmdevtools_invalid"


class NotFound(DevToolsError):

    status = 404
    code = "tmdevtools_not_found"


class NoTaskManager(DevToolsError):

    status = 409
    code = "tmdevtools_no_task_manager"
