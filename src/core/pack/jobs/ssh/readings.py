
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

import structlog

from src.core.pack.jobs.ssh import far_script
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobError
from src.core.pack.machines import can_block, probe as probe_mod
from src.core.pack.reserve import model as reserve_model, pressure as pressure_mod
from src.core.pack.reserve.holds import Holds

log = structlog.get_logger(__name__)

CACHE_S = 15.0
READ_TIMEOUT_S = 3.0
FRESH_S = 30.0
CAN_DUE_S = 24 * 3600.0
PROBE_GAP_S = 60.0
PROBE_TIMEOUT_S = 20.0
STAT_MAX_AGE_S = 60.0
NO_ANSWER = "did not answer over ssh"
GPU_BUSY = "gpu busy"
GPU_UTIL_PCT = 50.0
GPU_MIN_FREE_GB = 2.0
WSL_LABEL = "wsl"
_KB_PER_GB = 1024.0 * 1024.0
_OS_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+_-]{0,63}$")
_PLAYWRIGHT = "playwright_browsers"


@dataclass(frozen=True)
class SshReading:

    host_key: str
    label: str
    takes_work: bool
    pinned: bool
    usable: bool
    reason: Optional[str]
    taken_at: float
    can: Optional[Dict[str, Any]] = None
    load: Optional[Dict[str, Any]] = None
    pressure: Optional[Dict[str, Any]] = None
    reserve: Dict[str, Any] = field(default_factory=dict)
    last_ok: Optional[float] = None
    last_error: Optional[str] = None

    def to_dict(self, now: Optional[float] = None) -> Dict[str, Any]:
        at = time.time() if now is None else now
        return {"host_key": self.host_key, "label": self.label, "takes_work": self.takes_work, "pinned": self.pinned, "usable": self.usable,
                "reason": self.reason, "taken_at": self.taken_at, "age_s": max(0.0, at - self.taken_at), "can": self.can, "load": self.load,
                "pressure": self.pressure, "reserve": self.reserve, "last_ok": self.last_ok,
                "last_ok_age_s": None if self.last_ok is None else max(0.0, at - self.last_ok), "last_error": self.last_error}


class Link(NamedTuple):

    label: str
    conn: Any


def default_link(host_key: str) -> Link:
    from src.core.pack.jobs.ssh.target import ssh_target_for

    target = ssh_target_for(host_key)
    return Link(target.label, target._conn)



def _float(text: Optional[str], low: float = 0.0, high: float = 1e12) -> Optional[float]:
    try:
        value = float((text or "").split()[0])
    except (ValueError, IndexError):
        return None
    return value if low <= value <= high else None


def _gpu_rows(values: List[str]) -> List[Tuple[Optional[float], Optional[float]]]:
    rows: List[Tuple[Optional[float], Optional[float]]] = []
    for line in values[:8]:
        util, _, free = line.partition(",")
        mib = _float(free, 0, 1e9)
        rows.append((_float(util, 0, 100), None if mib is None else round(mib / 1024.0, 2)))
    return rows


def parse_probe(answer: "far_script.FarAnswer", now: float) -> Dict[str, Any]:
    uname = answer.fields.get("uname", "").split()
    release = uname[1] if len(uname) > 1 else ""
    found = {line.split()[0] for line in answer.all("tool") if line.split()}
    tools = {name: name in found for name in can_block.TOOL_NAMES if name != "brew"}
    tools[_PLAYWRIGHT] = bool(answer.all("playwright"))
    cores = _float(answer.fields.get("cores"), 1, 4096)
    kb = _float(answer.fields.get("memtotal_kb"), 0, 1e12)
    return {"probed_at": now, "os": "linux", "os_version": release if _OS_VERSION.fullmatch(release) else None,
            "arch": uname[2] if len(uname) > 2 and re.fullmatch(r"[A-Za-z0-9_]{1,16}", uname[2]) else None,
            "cores": None if cores is None else int(cores), "mem_gb": None if kb is None else round(kb / _KB_PER_GB, 1),
            "gpus": [g for g in probe_mod._gpus_nvidia("\n".join(answer.all("gpu"))) if g["vram_gb"] <= 65536], "tools": tools, "brew": False,
            "wsl": "microsoft" in release.lower() or answer.fields.get("wsl") == "1"}


def _stat_totals(text: Optional[str]) -> Optional[Tuple[float, float]]:
    parts = (text or "").split()
    if len(parts) < 5 or parts[0] != "cpu":
        return None
    nums = [_float(p) for p in parts[1:9]]
    if any(n is None for n in nums):
        return None
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0.0)  # type: ignore[operator]
    return sum(n for n in nums if n is not None), idle


class Readings:

    def __init__(self, store: JobStore, conns: Callable[[str], Link] = default_link, clock: Callable[[], float] = time.time) -> None:
        self._store, self._conns, self._clock = store, conns, clock
        self._cache: List[SshReading] = []
        self._cache_at = float("-inf")
        self._stat: Dict[str, Tuple[float, float, float]] = {}
        self._live_at: Dict[str, float] = {}
        self._probe_at: Dict[str, float] = {}
        self._holds: Dict[str, Holds] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock: Optional[asyncio.Lock] = None
        self._guard = threading.Lock()
        self._tasks: set = set()


    def holds_for(self, host_key: str) -> Holds:
        with self._guard:
            return self._holds.setdefault(host_key, Holds())

    def hold(self, host_key: str, key: str, cpu: float, ram_gb: float, ttl_s: float) -> bool:
        return self.holds_for(host_key).try_hold(key, "ssh", cpu, ram_gb, ttl_s, lambda _c, _r: True)


    async def _ask(self, link: Link, row: Dict[str, Any], verb: str, timeout: float) -> "far_script.FarAnswer":
        values = {"root": str(row["far_root"])} if row.get("far_root") else {}
        nonce = far_script.new_nonce()
        try:
            script = far_script.render(verb, values, nonce=nonce)
            result = await asyncio.wait_for(link.conn.call(script, timeout), timeout + 1.0)
            if result.failure is not None:
                raise JobError("unreachable", NO_ANSWER, 502)
            answer = far_script.parse(result.stdout, nonce)
        except (ValueError, asyncio.TimeoutError, OSError) as exc:
            raise JobError("unreachable", NO_ANSWER, 502) from exc
        if answer.error is not None or answer.rc != 0:
            raise JobError("unreachable", NO_ANSWER, 502)
        return answer


    @staticmethod
    def _labels(row: Dict[str, Any], wsl: bool) -> List[str]:
        try:
            owner = json.loads(row.get("labels_json") or "[]")
        except ValueError:
            owner = []
        labels = [x for x in owner if isinstance(x, str)] if isinstance(owner, list) else []
        return [*labels, WSL_LABEL] if wsl and WSL_LABEL not in labels else labels

    def _stored_can(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            raw = json.loads(row.get("can_json") or "null")
        except ValueError:
            return None
        parsed = can_block.parse(raw)
        if parsed is None:
            return None
        can = parsed.model_dump()
        can["labels"] = self._labels(row, "microsoft" in str(can.get("os_version") or "").lower() or WSL_LABEL in (raw.get("labels") or []))
        return can

    async def refresh_can(self, host_key: str, reason: str, link: Optional[Link] = None, force: bool = False) -> Tuple[Dict[str, Any], bool]:
        self.bind()
        row = self._store.ssh_target_get(host_key) or {}
        old = self._stored_can(row)
        now = self._clock()
        if not force and now - self._probe_at.get(host_key, float("-inf")) < PROBE_GAP_S:
            if old is None:
                raise JobError("unreachable", NO_ANSWER, 502)
            return old, False
        self._probe_at[host_key] = now
        answer = await self._ask(link or self._conns(host_key), row, "probe", PROBE_TIMEOUT_S)
        probe = parse_probe(answer, now)
        block = can_block.build(probe, self._labels(row, bool(probe["wsl"])), None)
        self._store.ssh_target_put(host_key, can_json=json.dumps(block), probed_at=now)
        log.info("pack_ssh_probe", host=host_key[:12], reason=reason[:40], gpus=len(block["gpus"]))
        return block, old is None or old.get("rev") != block["rev"]


    def _pressure(self, host_key: str, answer: "far_script.FarAnswer", can: Optional[Dict[str, Any]], reserve: Dict[str, Any],
                  now: float) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        cores = _float(answer.fields.get("cores"), 1, 4096) or (can or {}).get("cores")
        cores = int(cores) if cores else None
        load1 = _float(answer.fields.get("loadavg"), 0, 1e6)
        busy: Optional[float] = None
        totals = _stat_totals(answer.fields.get("stat"))
        if totals is not None:
            before = self._stat.get(host_key)
            self._stat[host_key] = (totals[0], totals[1], now)
            if before is not None and now - before[2] > STAT_MAX_AGE_S:
                before = None
            if before is not None and cores and totals[0] > before[0]:
                busy = round(cores * max(0.0, 1.0 - (totals[1] - before[1]) / (totals[0] - before[0])), 2)
        avail_kb = _float(answer.fields.get("memavail_kb"), 0, 1e12)
        disk_kb = _float(answer.fields.get("disk_free_kb"), 0, 1e13)
        total_gb = (can or {}).get("mem_gb")
        load = {"cores": cores, "load_1": load1, "busy_cores": busy, "mem_total_gb": total_gb,
                "mem_available_gb": None if avail_kb is None else round(avail_kb / _KB_PER_GB, 1),
                "disk_free_gb": None if disk_kb is None else round(disk_kb / _KB_PER_GB, 1)}
        psi = pressure_mod.parse_psi("\n".join(answer.all("psi_mem"))) if answer.all("psi_mem") else None
        rq = (load1 / cores) if load1 is not None and cores else None
        line = cores * (1 - int(reserve.get("cpu_pct") or 0) / 100) if cores else None
        why: List[str] = []
        if busy is not None and line is not None and busy > line:
            why.append(f"busy cores {busy:.1f} over the reserve line {line:.1f}")
        if rq is not None and rq > pressure_mod.RUN_QUEUE_ON:
            why.append(f"run queue {rq:.1f} per core")
        if psi in (pressure_mod.MEM_WARN, pressure_mod.MEM_CRITICAL):
            why.append(f"memory pressure {psi}")
        if any((u is not None and u >= GPU_UTIL_PCT) or (f is not None and f < GPU_MIN_FREE_GB) for u, f in _gpu_rows(answer.all("gpu"))):
            why.append(GPU_BUSY)
        gauge = {"pegged": bool(why), "since": now if why else None, "why": "; ".join(why), "busy_cores": busy, "line": line, "cores": cores,
                 "run_queue_per_core": rq, "mem": psi, "throttled": 0}
        return load, gauge

    def _held(self, host_key: str) -> Dict[str, Any]:
        cpu, ram, count = self.holds_for(host_key).total()
        return {"cpu": cpu, "ram_gb": ram, "n": count}

    def _reading(self, host_key: str, row: Dict[str, Any], label: str, now: float, answer: Optional["far_script.FarAnswer"],
                 reason: Optional[str]) -> SshReading:
        can = self._stored_can(row)
        reserve = reserve_model.active(reserve_model.from_dict(_json(row.get("reserve_json"))), datetime.fromtimestamp(now), None)
        base = dict(host_key=host_key, label=label, takes_work=bool(row.get("takes_work")), pinned=bool(row.get("pinned_fp")),
                    taken_at=now, can=can, reserve=reserve, last_ok=row.get("last_ok"), last_error=row.get("last_error"))
        if answer is None:
            return SshReading(usable=False, reason=reason, **base)  # type: ignore[arg-type]
        load, gauge = self._pressure(host_key, answer, can, reserve, now)
        gauge["held"] = self._held(host_key)
        return SshReading(usable=True, reason=None, load=load, pressure=gauge, **{**base, "last_ok": now})  # type: ignore[arg-type]


    def bind(self) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            return

    def _label_of(self, host_key: str) -> str:
        try:
            return self._conns(host_key).label
        except JobError:
            return host_key[:12]

    async def _read_one(self, row: Dict[str, Any], timeout: float, link: Optional[Link] = None) -> SshReading:
        host_key, now = str(row["host_key"]), self._clock()
        if not row.get("takes_work") or not row.get("pinned_fp"):
            why = "is not set to take work" if not row.get("takes_work") else "has no pinned key"
            return self._reading(host_key, row, link.label if link else self._label_of(host_key), now, None, why)
        try:
            link = link or self._conns(host_key)
            if self._stored_can(row) is None:
                await self.refresh_can(host_key, "first placement read", link)
                row = self._store.ssh_target_get(host_key) or row
            elif now - float(row.get("probed_at") or 0.0) > CAN_DUE_S:
                self._spawn(self.refresh_can(host_key, "daily", link))
            answer = await self._ask(link, row, "pressure", timeout)
        except JobError as exc:
            self._store.ssh_target_put(host_key, last_error=NO_ANSWER)
            log.info("pack_ssh_read_failed", host=host_key[:12], code=exc.code)
            return self._reading(host_key, row, link.label if link else self._label_of(host_key), now, None, NO_ANSWER)
        self._store.ssh_target_put(host_key, last_ok=now, last_error=None)
        return self._reading(host_key, row, link.label, now, answer, None)

    def _spawn(self, coro: Any) -> None:
        async def guarded() -> None:
            try:
                await coro
            except JobError as exc:
                log.info("pack_ssh_probe_failed", code=exc.code)

        task = asyncio.get_running_loop().create_task(guarded())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def for_placement(self, timeout: float = READ_TIMEOUT_S) -> List[SshReading]:
        self.bind()
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._clock() - self._cache_at >= CACHE_S:
                rows = await asyncio.to_thread(self._store.ssh_targets_all)
                got = await asyncio.gather(*(self._read_one(r, timeout) for r in rows), return_exceptions=True)
                for row, item in zip(rows, got):
                    if isinstance(item, BaseException):
                        log.warning("pack_ssh_read_faulted", host=str(row.get("host_key"))[:12], error=type(item).__name__, exc_info=item)
                self._cache = [r for r in got if isinstance(r, SshReading)]
                self._cache_at = self._clock()
        return self.cached()

    def cached(self) -> List[SshReading]:
        return [replace(r, pressure={**r.pressure, "held": self._held(r.host_key)}) if r.pressure is not None else r for r in self._cache]

    def placement_blocking(self, timeout: float = READ_TIMEOUT_S) -> List[SshReading]:
        loop = self._loop
        try:
            on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if loop is None or on_loop or not loop.is_running():
            log.info("pack_ssh_readings_cached_only", bound=loop is not None)
            return self.cached()
        future = asyncio.run_coroutine_threadsafe(self.for_placement(timeout), loop)
        try:
            return future.result(timeout + 20.0 + 2.0)
        except (TimeoutError, OSError) as exc:
            future.cancel()
            log.info("pack_ssh_readings_overran", error=type(exc).__name__)
            return self.cached()

    async def poll_live(self, host_key: str, link: Optional[Link] = None) -> Dict[str, Any]:
        self.bind()
        self._live_at[host_key] = self._clock()
        row = self._store.ssh_target_get(host_key) or {"host_key": host_key}
        row = {**row, "host_key": host_key}
        got = await self._read_one(row, READ_TIMEOUT_S, link)
        self._cache = [got if r.host_key == host_key else r for r in self._cache] if any(r.host_key == host_key for r in self._cache) else [*self._cache, got]
        return got.to_dict(self._clock())


    async def poll_live_due(self, host_key: str, link: Optional[Link] = None) -> None:
        if self._clock() - self._live_at.get(host_key, float("-inf")) >= CACHE_S:
            await self.poll_live(host_key, link)


def _json(text: Any) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


_SHARED: Dict[str, Any] = {}


def shared(store: JobStore) -> Readings:
    held = _SHARED.get("readings")
    if held is None or held._store is not store:
        held = _SHARED["readings"] = Readings(store)
    return held
