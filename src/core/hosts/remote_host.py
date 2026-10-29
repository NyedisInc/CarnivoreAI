
from __future__ import annotations

import asyncio
import contextlib
import re
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

import structlog

from src.core.hosts.ssh_exec import ExecResult, posix_quote
from src.core.hosts.ssh_master import SshTransportError, default_instance_tag
from src.core.hosts.tmux_control import (
    ControlChannelError,
    ControlReply,
    ControlReplyTooLarge,
    ControlTimeout,
)

logger = structlog.get_logger()

REMOTE_STATE_DIR = ".cache/carnivore"

REMOTE_MAX_PIPE_BYTES = 10 * 1024 * 1024

_HOME_RE = re.compile(r"/[^\x00-\x1f\x7f]{0,1023}")


class RemoteHostUnavailable(ConnectionError):

    def __init__(self, message: str, *, timed_out: bool = False) -> None:
        super().__init__(message)
        self.timed_out = timed_out


class RemoteSyncOnLoopError(RuntimeError):
    pass


class RemoteHost:

    def __init__(self, host_key: str, pool: Any, channel: Any, *, tmux_path: str, socket: str,
                 login_path: Optional[str] = None, instance_tag: Optional[str] = None,
                 mirror_dir: Optional[Path] = None, command_timeout: float = 10.0,
                 exec_timeout: float = 30.0, rotate_interval: float = 60.0,
                 max_pipe_bytes: int = REMOTE_MAX_PIPE_BYTES) -> None:
        self.host_key = host_key
        self.pool = pool
        self.channel = channel
        self.tmux_path = tmux_path
        self.socket = socket
        self.login_path = login_path
        self.instance_tag = instance_tag or default_instance_tag()
        self._mirror_dir = mirror_dir
        self.command_timeout = command_timeout
        self.exec_timeout = exec_timeout
        self._rotate_interval = rotate_interval
        self._max_pipe_bytes = max_pipe_bytes
        self.home: Optional[str] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._rotation: Optional[asyncio.Task[None]] = None
        self.last_status_map: Any = None


    @property
    def is_up(self) -> bool:
        return self.home is not None and bool(self.channel.is_up)

    @property
    def state_dir(self) -> str:
        if self.home is None:
            raise RemoteHostUnavailable(f"host {self.host_key} is not prepared")
        return f"{self.home.rstrip('/')}/{REMOTE_STATE_DIR}"

    @property
    def pipe_dir(self) -> str:
        return f"{self.state_dir}/pipes"

    def pipe_path(self, slug: str) -> str:
        return f"{self.pipe_dir}/{self.instance_tag}_{slug}.pipe"

    def mirror_path(self, slug: str) -> Path:
        directory = self._mirror_dir
        if directory is None:
            from src.config import settings

            directory = Path(settings.get_log_dir())
        return directory / f"tmux_rh_{self.host_key}_{slug}.pipe"


    async def prepare(self) -> str:
        self.loop = asyncio.get_running_loop()
        script = 'umask 077; mkdir -p "$HOME"/' + REMOTE_STATE_DIR + '/pipes && printf "%s\\n" "$HOME"'
        result = await self.exec(script=script)
        home = result.stdout_text.rstrip("\n").rsplit("\n", 1)[-1]
        if result.returncode != 0 or _HOME_RE.fullmatch(home) is None:
            raise RemoteHostUnavailable(
                f"host {self.host_key}: preparing its state directory failed "
                f"(rc {result.returncode}, {result.stderr_text.strip()[:200] or 'no error text'})")
        self.home = home
        if self._rotation is None or self._rotation.done():
            self._rotation = asyncio.create_task(self._rotate_loop(),
                                                 name=f"remote-rotate-{self.host_key}")
        logger.info("remote_host_prepared", host=self.host_key)
        return home

    async def close(self) -> None:
        task, self._rotation = self._rotation, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


    async def command(self, verb: str, *args: str, timeout: Optional[float] = None) -> ControlReply:
        try:
            return await self.channel.command(verb, *args, timeout=timeout or self.command_timeout)
        except ControlReplyTooLarge as exc:
            return ControlReply(ok=False, lines=(str(exc).encode("utf-8"),), number=-1)
        except ControlTimeout as exc:
            raise RemoteHostUnavailable(f"host {self.host_key}: {verb} timed out ({exc})",
                                        timed_out=True) from exc
        except ControlChannelError as exc:
            raise RemoteHostUnavailable(f"host {self.host_key}: {exc}") from exc

    async def exec(self, argv: Optional[Sequence[str]] = None, *, script: Optional[str] = None,
                   stdin_data: Optional[bytes] = None, timeout: Optional[float] = None) -> ExecResult:
        try:
            result = await self.pool.run(argv, script=script, stdin_data=stdin_data,
                                         timeout=timeout or self.exec_timeout)
        except SshTransportError as exc:
            raise RemoteHostUnavailable(f"host {self.host_key}: {exc}") from exc
        if result.failure is not None:
            raise RemoteHostUnavailable(f"host {self.host_key}: exec failed ({result.failure})",
                                        timed_out=result.timed_out)
        return result

    async def spawn(self, script: str) -> Any:
        try:
            return await self.pool.spawn(script=script, stdin=asyncio.subprocess.PIPE,
                                         stdout=asyncio.subprocess.PIPE,
                                         stderr=asyncio.subprocess.PIPE)
        except SshTransportError as exc:
            raise RemoteHostUnavailable(f"host {self.host_key}: {exc}") from exc

    async def file_size(self, path: str) -> int:
        quoted = posix_quote(path)
        result = await self.exec(script=f"if [ -f {quoted} ]; then wc -c < {quoted}; else echo 0; fi")
        text = result.stdout_text.strip()
        if result.returncode != 0 or not text.isdigit():
            raise RemoteHostUnavailable(f"host {self.host_key}: could not measure a pipe file")
        return int(text)


    def rotation_script(self) -> str:
        return (f"for f in {posix_quote(self.pipe_dir)}/{self.instance_tag}_*.pipe; do "
                '[ -f "$f" ] || continue; s=$(wc -c < "$f"); '
                f'if [ "$s" -gt {int(self._max_pipe_bytes)} ]; then : > "$f"; fi; done; exit 0')

    async def rotate_once(self) -> None:
        await self.exec(script=self.rotation_script())

    async def _rotate_loop(self) -> None:
        while True:
            await asyncio.sleep(self._rotate_interval)
            try:
                await self.rotate_once()
            except RemoteHostUnavailable as exc:
                logger.info("remote_pipe_rotation_skipped", host=self.host_key, error=str(exc))
