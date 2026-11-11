
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable, Optional

from src.core.argent import classifier

GIT_TIMEOUT = 5.0


async def _git(directory: str, *args: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec("git", "-C", directory, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), GIT_TIMEOUT)
    except (OSError, asyncio.TimeoutError):
        return ""
    return out.decode("utf-8", "replace") if proc.returncode == 0 else ""


async def gather(directory: str, last_prompt: str, extra_files: Iterable[str] = ()) -> classifier.Signals:
    if not directory:
        return classifier.Signals(last_prompt=last_prompt, files=tuple(dict.fromkeys(extra_files)))
    branch = (await _git(directory, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    status = await _git(directory, "status", "--porcelain", "-z")
    files = tuple(dict.fromkeys([*(e[3:] for e in status.split("\0") if len(e) > 3), *extra_files]))
    return classifier.Signals(branch=branch, files=files, last_prompt=last_prompt)


def last_prompt(transcript: Optional[Path]) -> str:
    if transcript is None:
        return ""
    from src.core.claude_title_sync import read_tail_records
    from src.core.session_conversations import prompt_texts

    tail = read_tail_records(str(transcript), tail_bytes=prompt_texts.TAIL_BYTES)
    prompts = prompt_texts.prompts_from_records(tail.records) if tail.readable else []
    return prompts[-1] if prompts else ""
