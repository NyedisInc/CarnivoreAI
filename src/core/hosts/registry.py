
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict, Optional, Set

import structlog

from src.core.hosts import store
from src.core.hosts.ddl import LOCAL_HOST_KEY, LOCAL_HOST_LABEL
from src.core.hosts.probe import PROBE_OK
from src.core.hosts.remote_host import RemoteHost, RemoteHostUnavailable
from src.core.hosts.ssh_exec import SshArgumentError, SshDestination
from src.core.hosts.ssh_master import UP, SshTransportError
from src.core.hosts.ssh_pool import SshMasterPool
from src.core.hosts.tmux_control import TmuxControlChannel

logger = structlog.get_logger()

HOST_STATE_UP = "up"
HOST_STATE_DOWN = "down"

HOST_CODES: Dict[str, int] = {
    "host_key_invalid": 400,
    "host_not_found": 404,
    "host_disabled": 409,
    "host_not_probed": 409,
    "host_unreachable": 502,
    "hosts_unavailable": 503,
}


class HostUnavailable(RuntimeError):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status = HOST_CODES.get(code, 502)


ConnectionFactory = Callable[[], Optional[sqlite3.Connection]]


class HostRegistry:

    def __init__(self, connection_factory: ConnectionFactory, *,
                 pool_options: Optional[Dict[str, Any]] = None,
                 channel_options: Optional[Dict[str, Any]] = None,
                 host_options: Optional[Dict[str, Any]] = None) -> None:
        self._connect_db = connection_factory
        self._pool_options = dict(pool_options or {})
        self._channel_options = dict(channel_options or {})
        self._host_options = dict(host_options or {})
        self._hosts: Dict[str, RemoteHost] = {}
        self._records: Dict[str, store.Host] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._tasks: Set[asyncio.Task[Any]] = set()


    def record(self, host_key: str) -> Optional[store.Host]:
        return self._records.get(host_key)

    def label(self, host_key: str) -> str:
        if host_key == LOCAL_HOST_KEY:
            return LOCAL_HOST_LABEL
        record = self._records.get(host_key)
        return record.label if record is not None else host_key

    def state(self, host_key: str) -> str:
        if host_key == LOCAL_HOST_KEY:
            return HOST_STATE_UP
        host = self._hosts.get(host_key)
        return HOST_STATE_UP if host is not None and host.is_up else HOST_STATE_DOWN


    def _read_record(self, host_key: str) -> store.Host:
        try:
            conn = self._connect_db()
        except (sqlite3.Error, OSError) as exc:
            raise HostUnavailable("hosts_unavailable", f"the datastore could not be opened: {exc}")
        if conn is None:
            raise HostUnavailable("hosts_unavailable", "there is no datastore to read hosts from")
        with closing(conn):
            try:
                return store.get_host(conn, host_key)
            except store.HostNotFound:
                raise HostUnavailable("host_not_found", f"no host {host_key!r}")
            except (store.HostsUnavailable, sqlite3.Error) as exc:
                raise HostUnavailable("hosts_unavailable", f"hosts could not be read: {exc}")

    @staticmethod
    def _check(record: store.Host) -> None:
        if record.is_local:
            raise HostUnavailable("host_key_invalid", "'local' is this machine, not a remote host")
        if record.kind != "ssh":
            raise HostUnavailable("host_key_invalid", f"host {record.key} is a {record.kind} host, not an ssh host")
        if not record.enabled:
            raise HostUnavailable("host_disabled", f"host {record.key} is disabled")
        if record.probe_state != PROBE_OK or not record.tmux_path or not record.login_shell:
            raise HostUnavailable(
                "host_not_probed",
                f"host {record.key} has no successful probe (state {record.probe_state}); "
                "probe it first")

    async def get(self, host_key: str) -> RemoteHost:
        if host_key == LOCAL_HOST_KEY or store.KEY_RE.fullmatch(host_key or "") is None:
            raise HostUnavailable("host_key_invalid", f"not a remote host key: {host_key!r}")
        lock = self._locks.setdefault(host_key, asyncio.Lock())
        async with lock:
            host = self._hosts.get(host_key)
            if host is not None:
                if not host.is_up:
                    raise HostUnavailable("host_unreachable",
                                          f"host {host_key} is not connected right now")
                return host
            record = await asyncio.to_thread(self._read_record, host_key)
            self._check(record)
            host = await self._connect(record)
            self._hosts[host_key] = host
            self._records[host_key] = record
            return host

    async def _connect(self, record: store.Host) -> RemoteHost:
        try:
            dest = SshDestination(record.ssh_target or "", record.ssh_port)
        except SshArgumentError as exc:
            raise HostUnavailable("host_key_invalid", f"host {record.key}: {exc}")
        socket = record.socket or store.DEFAULT_REMOTE_SOCKET
        pool = SshMasterPool(record.key, dest, login_shell=record.login_shell, **self._pool_options)
        channel = TmuxControlChannel(record.key, pool.spawn, str(record.tmux_path), socket,
                                     **self._channel_options)
        host = RemoteHost(record.key, pool, channel, tmux_path=str(record.tmux_path),
                          socket=socket, login_path=record.login_path, **self._host_options)
        try:
            status = await pool.connect()
            if status.state != UP:
                raise HostUnavailable("host_unreachable", f"host {record.key}: ssh is "
                                      f"{status.state} ({status.failure or 'no reason given'})")
            control = await channel.start()
            if not channel.is_up:
                raise HostUnavailable("host_unreachable",
                                      f"host {record.key}: the tmux channel is {control.state}")
            await host.prepare()
        except (HostUnavailable, RemoteHostUnavailable, SshTransportError) as exc:
            await self._teardown(host)
            if isinstance(exc, HostUnavailable):
                raise
            raise HostUnavailable("host_unreachable", str(exc))
        logger.info("remote_host_connected", host=record.key)
        return host

    @staticmethod
    async def _teardown(host: RemoteHost) -> None:
        await host.close()
        await host.channel.stop()
        await host.pool.disconnect()

    def hold(self, task: "asyncio.Task[Any]") -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close_all(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        hosts, self._hosts = list(self._hosts.values()), {}
        for host in hosts:
            await self._teardown(host)
            logger.info("remote_host_disconnected", host=host.host_key)
