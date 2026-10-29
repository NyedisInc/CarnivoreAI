
from __future__ import annotations

from typing import Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

NO_SANITIZE_FLAG: str = "-S"

UNKNOWN_NO_SANITIZE_FLAG_ERROR: str = f"unknown flag {NO_SANITIZE_FLAG}"

RunTmux = Callable[..., Awaitable[tuple[int, bytes, bytes]]]


class PasteBufferError(RuntimeError):
    pass


def paste_buffer_args(
    buf_name: str, target: str, *, bracketed: bool, sanitize_off: bool
) -> list[str]:
    args = ["paste-buffer", "-d", "-p" if bracketed else "-r"]
    if sanitize_off and not bracketed:
        args.append(NO_SANITIZE_FLAG)
    return args + ["-b", buf_name, "-t", target]


def is_unknown_no_sanitize_flag(stderr: bytes) -> bool:
    return UNKNOWN_NO_SANITIZE_FLAG_ERROR in stderr.decode("utf-8", errors="replace")


async def paste_loaded_buffer(
    run_tmux: RunTmux, buf_name: str, target: str, *, bracketed: bool
) -> None:
    sanitize_off = not bracketed
    rc, _, err = await run_tmux(
        *paste_buffer_args(
            buf_name, target, bracketed=bracketed, sanitize_off=sanitize_off
        ),
        check=False,
    )
    if rc != 0 and sanitize_off and is_unknown_no_sanitize_flag(err):
        logger.debug("tmux_paste_buffer_no_sanitize_flag_unsupported", target=target)
        rc, _, err = await run_tmux(
            *paste_buffer_args(
                buf_name, target, bracketed=bracketed, sanitize_off=False
            ),
            check=False,
        )
    if rc != 0:
        detail = err.decode("utf-8", errors="replace").strip()
        logger.error("tmux_paste_buffer_failed", target=target, stderr=detail)
        raise PasteBufferError(f"tmux paste-buffer failed: {detail}")
