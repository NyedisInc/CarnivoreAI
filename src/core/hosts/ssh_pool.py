
from __future__ import annotations

import asyncio
import contextlib
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, Optional, Sequence, Set

import structlog

from src.core.hosts import ssh_exec
from src.core.hosts.ssh_exec import (
    SSH_BINARY,
    ExecResult,
    SshArgumentError,
    SshDestination,
    argv_command,
    is_posix_shell,
    mux_argv,
    sh_c,
    signal_group,
)
from src.core.hosts.ssh_master import (
    UP,
    MasterStatus,
    SshMaster,
    SshTransportError,
    backoff_delay,
    control_path_for,
    default_control_dir,
    default_instance_tag,
    ensure_control_dir,
)

logger = structlog.get_logger()

DEFAULT_CHANNEL_BUDGET = 8

DEFAULT_MAX_SLOTS = 4


class HostNotConnected(SshTransportError):

    def __init__(self, status: MasterStatus) -> None:
        self.status = status
        reason = f": {status.detail}" if status.detail else ""
        super().__init__(f"host {status.host_key} slot {status.slot} is {status.state}{reason}")


class ChannelBudgetExhausted(SshTransportError):
    pass


class ShellNotVerified(SshTransportError):
    pass


class RemoteChannel:

    def __init__(self, process: asyncio.subprocess.Process, slot: int, host_key: str) -> None:
        self.process = process
        self.slot = slot
        self.host_key = host_key

    async def close(self, grace: float = 2.0) -> Optional[int]:
        proc = self.process
        signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace)
        except TimeoutError:
            signal_group(proc, signal.SIGKILL)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=grace)
        return proc.returncode


@dataclass
class _Slot:

    index: int
    master: SshMaster
    used: int = 0
    idle: Optional[asyncio.TimerHandle] = None


class SshMasterPool:

    def __init__(self, host_key: str, dest: SshDestination, *, login_shell: Optional[str] = None,
                 control_dir: Optional[Path] = None, instance_tag: Optional[str] = None,
                 ssh_binary: str = SSH_BINARY, channel_budget: int = DEFAULT_CHANNEL_BUDGET,
                 max_slots: int = DEFAULT_MAX_SLOTS, idle_slot_linger: float = 60.0,
                 connect_timeout: float = 30.0, check_interval: float = 30.0,
                 stable_after: float = 30.0, delay: Callable[[int], float] = backoff_delay,
                 on_change: Optional[Callable[[MasterStatus], None]] = None) -> None:
        if channel_budget < 1 or max_slots < 1:
            raise SshTransportError("a pool needs a channel budget and a slot count of at least 1")
        self.host_key = host_key
        self._dest = dest
        self._login_shell = login_shell
        self._control_dir = control_dir or default_control_dir()
        self._instance_tag = instance_tag or default_instance_tag()
        self._ssh_binary = ssh_binary
        self._budget = channel_budget
        self._max_slots = max_slots
        self._linger = idle_slot_linger
        self._master_options = dict(ssh_binary=ssh_binary, connect_timeout=connect_timeout,
                                    check_interval=check_interval, stable_after=stable_after,
                                    delay=delay)
        self._lock = asyncio.Lock()
        self._channels: Set[RemoteChannel] = set()
        self._tasks: Set[asyncio.Task[None]] = set()
        self._slots: Dict[int, _Slot] = {0: self._new_slot(0, on_change)}


    @property
    def status(self) -> MasterStatus:
        return self._slots[0].master.status

    def usage(self) -> Dict[int, int]:
        return {index: slot.used for index, slot in sorted(self._slots.items())}

    def set_login_shell(self, login_shell: Optional[str]) -> None:
        self._login_shell = login_shell

    async def connect(self, *, wait: bool = True) -> MasterStatus:
        ensure_control_dir(self._control_dir)
        return await self._slots[0].master.connect(wait=wait)

    async def disconnect(self) -> None:
        await asyncio.gather(*(channel.close() for channel in list(self._channels)))
        async with self._lock:
            slots = list(self._slots.values())
            for slot in slots:
                if slot.idle is not None:
                    slot.idle.cancel()
                    slot.idle = None
            self._slots = {0: self._slots[0]}
        await asyncio.gather(*(slot.master.disconnect() for slot in slots))
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def spawn(self, argv: Optional[Sequence[str]] = None, *, script: Optional[str] = None,
                    stdin: int = asyncio.subprocess.PIPE, stdout: int = asyncio.subprocess.PIPE,
                    stderr: int = asyncio.subprocess.PIPE) -> RemoteChannel:
        command = self._command(argv, script)
        slot = await self._acquire()
        try:
            proc = await asyncio.create_subprocess_exec(
                *mux_argv(self._dest, slot.master.control_path, command, ssh_binary=self._ssh_binary),
                stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True)
        except OSError as exc:
            self._release(slot)
            raise SshTransportError(f"ssh could not be started ({type(exc).__name__}: {exc})") from exc
        except BaseException:
            self._release(slot)
            raise
        channel = RemoteChannel(proc, slot.index, self.host_key)
        self._channels.add(channel)
        self._track(self._release_on_exit(channel, slot))
        logger.info("ssh_channel_opened", host=self.host_key, slot=slot.index, used=slot.used,
                    command_bytes=len(command))
        return channel

    async def run(self, argv: Optional[Sequence[str]] = None, *, script: Optional[str] = None,
                  stdin_data: Optional[bytes] = None, timeout: float = 30.0,
                  max_output: int = 1 << 20) -> ExecResult:
        command = self._command(argv, script)
        slot = await self._acquire()
        try:
            return await ssh_exec.run_process(
                mux_argv(self._dest, slot.master.control_path, command, ssh_binary=self._ssh_binary),
                stdin_data=stdin_data, timeout=timeout, max_output=max_output, verb="run",
                host=self.host_key)
        finally:
            self._release(slot)


    def _new_slot(self, index: int, on_change: Optional[Callable[[MasterStatus], None]] = None
                  ) -> _Slot:
        path = control_path_for(self._control_dir, self.host_key, self._instance_tag, index)
        master = SshMaster(self.host_key, self._dest, path, slot=index, on_change=on_change,
                           **self._master_options)
        return _Slot(index, master)

    def _command(self, argv: Optional[Sequence[str]], script: Optional[str]) -> str:
        if not is_posix_shell(self._login_shell):
            raise ShellNotVerified(
                f"host {self.host_key}: the login shell {self._login_shell or '(not probed)'} is not "
                "measured as sh, bash, zsh, dash or ksh, so quoted commands cannot be sent")
        if (argv is None) == (script is None):
            raise SshArgumentError("pass exactly one of argv or script")
        return argv_command(argv) if argv is not None else sh_c(script or "")

    async def _acquire(self) -> _Slot:
        async with self._lock:
            primary = self._slots[0].master
            if not primary.is_up:
                raise HostNotConnected(primary.status)
            for index in sorted(self._slots):
                slot = self._slots[index]
                if slot.master.is_up and slot.used < self._budget:
                    return self._take(slot)
            free = [i for i in range(self._max_slots) if i not in self._slots]
            if not free:
                raise ChannelBudgetExhausted(
                    f"host {self.host_key}: {len(self._slots)} masters of {self._budget} channels "
                    "are full")
            slot = self._new_slot(free[0])
            self._slots[slot.index] = slot
            status = await slot.master.connect(wait=True)
            if status.state != UP:
                del self._slots[slot.index]
                await slot.master.disconnect()
                raise HostNotConnected(status)
            return self._take(slot)

    def _take(self, slot: _Slot) -> _Slot:
        slot.used += 1
        if slot.idle is not None:
            slot.idle.cancel()
            slot.idle = None
        return slot

    def _release(self, slot: _Slot) -> None:
        slot.used = max(0, slot.used - 1)
        if slot.index and not slot.used and slot.idle is None and self._slots.get(slot.index) is slot:
            slot.idle = asyncio.get_running_loop().call_later(
                self._linger, lambda: self._track(self._close_idle(slot)))

    async def _close_idle(self, slot: _Slot) -> None:
        async with self._lock:
            slot.idle = None
            if self._slots.get(slot.index) is not slot or slot.used:
                return
            del self._slots[slot.index]
        logger.info("ssh_slot_closed_idle", host=self.host_key, slot=slot.index)
        await slot.master.disconnect()

    async def _release_on_exit(self, channel: RemoteChannel, slot: _Slot) -> None:
        try:
            returncode = await channel.process.wait()
        finally:
            self._channels.discard(channel)
            self._release(slot)
        logger.info("ssh_channel_closed", host=self.host_key, slot=slot.index, rc=returncode)

    def _track(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
