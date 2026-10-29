
import asyncio
import errno
import os
import pty
import signal
import struct
import fcntl
import termios
import select
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional
import structlog

from src.core.session_backend import SessionBackend
from src.core.tmux_listing import REASON_NOT_APPLICABLE, TmuxListing

logger = structlog.get_logger()

STOP_GRACE_SECONDS = 2.0
STOP_POLL_SECONDS = 0.05

CHILD_EXEC_FAILED_STATUS = 127


class PTYSessionError(Exception):
    pass


class PTYSession:

    def __init__(
        self,
        session_id: str,
        working_dir: Path,
        on_output: Optional[Callable[[bytes], None]] = None
    ):
        self.session_id = session_id
        self.working_dir = working_dir
        self.on_output = on_output

        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.pid: Optional[int] = None
        self.running = False

        self._reader_task: Optional[asyncio.Task] = None

    async def start(
        self,
        command: Optional[str] = None,
        initial_cols: Optional[int] = None,
        initial_rows: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        if self.running:
            raise PTYSessionError("Session is already running")

        try:
            self.pid, self.master_fd = pty.fork()

            if self.pid == 0:
                self._exec_child(command, env)

            else:
                self.running = True

                flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
                fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                pass

                if initial_cols and initial_rows:
                    self._set_terminal_size(initial_cols, initial_rows)
                else:
                    self._set_terminal_size(80, 24)

                self._reader_task = asyncio.create_task(self._read_output())

                logger.info(
                    "pty_session_started",
                    session_id=self.session_id,
                    pid=self.pid,
                    working_dir=str(self.working_dir)
                )

        except (OSError, struct.error) as e:
            logger.error("pty_session_start_failed", error=str(e))
            raise PTYSessionError(f"Failed to start PTY session: {e}") from e

    def _exec_child(self, command: Optional[str], extra_env: Optional[Dict[str, str]]) -> None:
        try:
            os.chdir(str(self.working_dir))
            child_env = os.environ.copy()
            child_env.update(extra_env or {})
            child_env['TERM'] = 'xterm-256color'
            child_env['COLORTERM'] = 'truecolor'
            argv = ['/bin/bash', '-c', command] if command else ['/bin/bash', '-l']
            os.execvpe('/bin/bash', argv, child_env)
        except BaseException as exc:  # noqa: BLE001
            try:
                os.write(2, f"pty child failed to start: {exc}\n".encode("utf-8", "replace"))
            finally:
                os._exit(CHILD_EXEC_FAILED_STATUS)

    async def _read_output(self):
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                await loop.run_in_executor(None, self._wait_for_output)

                if not self.running:
                    break

                try:
                    data = os.read(self.master_fd, 4096)
                    if data and self.on_output:
                        await self._call_output_callback(data)
                except OSError as e:
                    if e.errno == errno.EIO:
                        logger.info("pty_process_exited", session_id=self.session_id)
                        self.running = False
                        break
                    elif e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        await asyncio.sleep(0.01)
                        continue
                    else:
                        logger.error("pty_read_error", error=str(e))
                        await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.error("pty_read_error", error=str(e), exc_info=True)
                await asyncio.sleep(0.1)

    def _wait_for_output(self):
        if not self.running:
            return
        select.select([self.master_fd], [], [], 0.1)

    async def _call_output_callback(self, data: bytes):
        if asyncio.iscoroutinefunction(self.on_output):
            await self.on_output(data)
        else:
            self.on_output(data)

    async def write(self, data: bytes):
        if not self.running or self.master_fd is None:
            raise PTYSessionError("Session is not running")

        try:
            os.write(self.master_fd, data)
        except OSError as e:
            logger.error("pty_write_failed", error=str(e))
            raise PTYSessionError(f"Failed to write to PTY: {e}") from e

    async def send_command(self, command: str):
        await self.write(command.encode('utf-8') + b'\n')

    def resize(self, cols: int, rows: int):
        if not self.running or self.master_fd is None:
            return

        self._set_terminal_size(cols, rows)

        if self.pid:
            try:
                os.kill(self.pid, signal.SIGWINCH)
            except ProcessLookupError:
                pass

    def _set_terminal_size(self, cols: int, rows: int):
        if self.master_fd is None:
            return

        size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, size)

    async def stop(self):
        if not self.running:
            return

        logger.info("stopping_pty_session", session_id=self.session_id)

        self.running = False

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

        if self.pid:
            await self._terminate_child(self.pid)

        logger.info("pty_session_stopped", session_id=self.session_id)

    @staticmethod
    def _reap(pid: int) -> bool:
        try:
            reaped, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True
        return reaped == pid

    async def _terminate_child(self, pid: int) -> None:
        for sig in (signal.SIGHUP, signal.SIGTERM):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                break
        deadline = time.monotonic() + STOP_GRACE_SECONDS
        while not self._reap(pid):
            if time.monotonic() >= deadline:
                logger.warning("pty_child_killed", session_id=self.session_id, pid=pid)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    return
                deadline = time.monotonic() + STOP_GRACE_SECONDS
            await asyncio.sleep(STOP_POLL_SECONDS)

    def is_alive(self) -> bool:
        if not self.running or not self.pid:
            return False
        return not self._reap(self.pid)


class PTYBackend(SessionBackend):

    def __init__(
        self,
        session_id: str,
        working_dir: Path,
        on_output: Optional[Callable[[bytes], Any]] = None,
    ) -> None:
        super().__init__(session_id, working_dir, on_output)
        self._pty: Optional[PTYSession] = None

    async def start(
        self,
        command: Optional[str] = None,
        env: Optional[dict] = None,
        initial_cols: Optional[int] = None,
        initial_rows: Optional[int] = None,
    ) -> None:
        if self._pty is not None:
            raise RuntimeError("PTYBackend already running")

        self._pty = PTYSession(
            session_id=self.session_id,
            working_dir=self.working_dir,
            on_output=self.on_output,
        )
        await self._pty.start(
            command=command,
            initial_cols=initial_cols,
            initial_rows=initial_rows,
            env=env,
        )

    async def stop(self) -> None:
        if self._pty is None:
            return
        try:
            await self._pty.stop()
        finally:
            self._pty = None

    async def write(self, data: bytes) -> None:
        if self._pty is None:
            raise RuntimeError("PTYBackend is not running")
        await self._pty.write(data)

    async def paste_and_submit(
        self,
        text: str,
        gate: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        raise NotImplementedError(
            "one-shot paste needs tmux: a PTY backend cannot mark a payload "
            "as a paste or measure that it landed"
        )

    def resize(self, cols: int, rows: int) -> None:
        if self._pty is None:
            return
        self._pty.resize(cols, rows)

    def is_alive(self) -> bool:
        return self._pty is not None and self._pty.is_alive()

    async def read_async(self) -> None:
        return None

    async def attach_existing(self) -> None:
        raise NotImplementedError(
            "PTYBackend does not persist across process restarts; "
            "use a fresh start() instead"
        )

    def discover_existing(self) -> TmuxListing:
        return TmuxListing.answered([], reason=REASON_NOT_APPLICABLE)

    def list_attachable_sessions(
        self,
        owned_names: Optional[set] = None,  # noqa: ARG002
        owned_instances: Optional[set] = None,  # noqa: ARG002
    ) -> TmuxListing:
        return TmuxListing.answered([], reason=REASON_NOT_APPLICABLE)

    def capture_scrollback(self, lines: int = 3000) -> bytes:  # noqa: ARG002
        return b""

    @property
    def pid(self) -> Optional[int]:
        return self._pty.pid if self._pty is not None else None
