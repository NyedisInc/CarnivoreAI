
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

import structlog

from src.config import settings
from src.core.cli_command import service as cli_service
from src.core.cli_command.token_store import LockBusy, TokenPair, TokenStore

logger = structlog.get_logger(__name__)

TOKEN_ENV = "CARNIVORE_API_TOKEN"
URL_ENV = "CARNIVORE_URL"
DEFAULT_ACCESS_TTL_S = 900.0
DOOR_TIMEOUT_S = 5.0


class CliAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeTarget:

    base_url: str
    door_sock: Optional[Path]
    pid: Optional[int] = None


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def discover_runtime(state_dir: Path, base_override: Optional[str] = None) -> RuntimeTarget:
    env_url = (base_override or os.environ.get(URL_ENV, "")).strip().rstrip("/")
    runtime_file = cli_service.runtime_info_path(state_dir)
    info: Dict[str, Any] = {}
    if runtime_file.is_file() and not runtime_file.is_symlink():
        try:
            raw = json.loads(runtime_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                info = raw
        except (OSError, ValueError):
            info = {}

    pid = info.get("pid")
    alive = _pid_alive(pid) if pid is not None else False
    door_raw = info.get("door_sock")
    door_sock = Path(door_raw) if isinstance(door_raw, str) and door_raw.strip() else None
    if door_sock is None:
        from src.core.computers.join_helper import fed_dir  # noqa: PLC0415
        from src.core.hosts.ssh_master import default_instance_tag  # noqa: PLC0415

        door_sock = fed_dir() / f"door-{default_instance_tag()}.sock"

    if env_url:
        return RuntimeTarget(base_url=env_url, door_sock=door_sock, pid=pid if alive else None)

    port = info.get("port") if alive and isinstance(info.get("port"), int) else int(settings.port)
    host = str(info.get("host") or "127.0.0.1") if alive else "127.0.0.1"
    return RuntimeTarget(base_url=f"http://{host}:{port}", door_sock=door_sock, pid=pid if alive else None)


def request_door_cli_token(door_sock: Path, *, timeout: float = DOOR_TIMEOUT_S) -> TokenPair:
    if not door_sock.exists():
        raise CliAuthError(f"door socket not found at {door_sock}")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(door_sock))
        sock.sendall(b'{"op":"cli_token"}\n')
        buf = bytearray()
        while b"\n" not in buf:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > 65536:
                raise CliAuthError("door response too large")
    except OSError as exc:
        raise CliAuthError(f"door connection failed ({type(exc).__name__})") from exc
    finally:
        sock.close()
    line = bytes(buf).splitlines()[0] if buf else b""
    if not line:
        raise CliAuthError("empty response from door")
    try:
        doc = json.loads(line.decode("utf-8"))
    except ValueError as exc:
        raise CliAuthError("invalid JSON from door") from exc
    if not isinstance(doc, dict) or doc.get("error"):
        err = doc.get("error") if isinstance(doc, dict) else "invalid_response"
        raise CliAuthError(f"door refused cli_token: {err}")
    access = doc.get("access_token")
    refresh = doc.get("refresh_token")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        raise CliAuthError("door response missing tokens")
    ttl = float(doc.get("expires_in") or DEFAULT_ACCESS_TTL_S)
    return TokenPair(access_token=access, refresh_token=refresh, access_expires_at=time.time() + ttl)


class CliHttpClient:

    def __init__(
        self,
        *,
        state_dir: Optional[Path] = None,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        door_sock: Optional[Path] = None,
    ) -> None:
        self.state_dir = Path(state_dir) if state_dir is not None else settings.get_state_dir()
        target = discover_runtime(self.state_dir, base_override=base_url)
        self.base_url = target.base_url
        self.door_sock = door_sock if door_sock is not None else target.door_sock
        self.explicit_token = (token if token is not None else os.environ.get(TOKEN_ENV, "")).strip()
        self.store = TokenStore(self.state_dir)

    def _refresh_via_http(self, pair: TokenPair) -> Optional[TokenPair]:
        req = urllib.request.Request(
            f"{self.base_url}/api/v1/auth/refresh",
            data=json.dumps({"refresh_token": pair.refresh_token}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        access = body.get("access_token") or body.get("token")
        refresh = body.get("refresh_token")
        if not isinstance(access, str) or not isinstance(refresh, str):
            return None
        ttl = float(body.get("expires_in") or DEFAULT_ACCESS_TTL_S)
        return TokenPair(access_token=access, refresh_token=refresh, access_expires_at=time.time() + ttl)

    def resolve_token(self, *, force_refresh: bool = False) -> str:
        if self.explicit_token:
            return self.explicit_token

        pair = self.store.load()
        if pair is not None and pair.access_fresh() and not force_refresh:
            return pair.access_token

        try:
            with self.store.locked(timeout=5.0):
                current = self.store.load()
                if current is not None and current.access_fresh() and not force_refresh:
                    return current.access_token
                if current is not None:
                    refreshed = self._refresh_via_http(current)
                    if refreshed is not None:
                        self.store.save(refreshed)
                        return refreshed.access_token
                    self.store.clear_if(current.refresh_token)
                if self.door_sock is not None:
                    bootstrapped = request_door_cli_token(self.door_sock)
                    self.store.save(bootstrapped)
                    return bootstrapped.access_token
        except LockBusy as exc:
            raise CliAuthError("token store lock busy") from exc

        raise CliAuthError("no CARNIVORE_API_TOKEN, tui_auth.json, or local Door socket available")

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Tuple[int, Any]:
        for attempt in range(2):
            token = self.resolve_token(force_refresh=(attempt == 1))
            data = None if json_body is None else json.dumps(json_body).encode("utf-8")
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            if data is not None:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method.upper())
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    parsed = json.loads(raw) if raw.strip() else {}
                    return int(resp.status), parsed
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0 and not self.explicit_token:
                    continue
                raw_err = exc.read().decode("utf-8", errors="replace")
                try:
                    err_doc = json.loads(raw_err) if raw_err.strip() else {"detail": raw_err}
                except ValueError:
                    err_doc = {"detail": raw_err}
                return int(exc.code), err_doc
        raise CliAuthError("authentication failed after retry")

    def stream_sse(self, path: str, *, timeout: float = 60.0) -> Iterator[Tuple[str, Dict[str, Any]]]:
        token = self.resolve_token()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            event_name = "message"
            data_lines: list[str] = []
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    if data_lines:
                        raw_data = "\n".join(data_lines)
                        try:
                            doc = json.loads(raw_data)
                        except ValueError:
                            doc = {"raw": raw_data}
                        yield event_name, doc if isinstance(doc, dict) else {"value": doc}
                        event_name = "message"
                        data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip() or "message"
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
