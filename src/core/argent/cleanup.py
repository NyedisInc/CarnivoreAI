
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

import structlog

from src.config import settings as app_settings
from src.core.argent import overlay, overlay_codex
from src.core.argent import settings as settings_module
from src.core.argent.settings import ArgentSettings
from src.core.db import db_path_for
from src.core.product_identity import test_mode_enabled
from src.core.safe_io.readonly_db import connect_readonly

logger = structlog.get_logger()

ALWAYS_UNSET_TMUX_VARS: Tuple[str, ...] = (
    overlay.SECRET_NAME,
    overlay_codex.HEADER_ENV,
)

_URL_ENV_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("ANTHROPIC_BASE_URL", ("ANTHROPIC_CUSTOM_HEADERS",)),
    (
        "COPILOT_PROVIDER_BASE_URL",
        ("COPILOT_PROVIDER_TYPE", "COPILOT_PROVIDER_API_KEY", "COPILOT_PROVIDER_HEADERS"),
    ),
    ("GOOGLE_GEMINI_BASE_URL", ("GEMINI_API_KEY",)),
)

_CA_ENV_KEYS: Tuple[str, ...] = (
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "CODEX_CA_CERTIFICATE",
)


def _origin_key(url: str) -> Optional[Tuple[str, str, int]]:
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    effective_port = port if port is not None else (443 if scheme == "https" else 80)
    return scheme, host, effective_port


def url_matches_gateway(candidate_url: str, gateway_url: str) -> bool:
    gw = _origin_key(gateway_url)
    cand = _origin_key(candidate_url)
    return gw is not None and cand is not None and cand == gw


def _ca_matches(candidate: str, ca_path: str) -> bool:
    raw = (candidate or "").strip()
    if not raw:
        return False
    name = Path(raw).name
    if name.startswith("agy-ca-bundle-") and name.endswith(".pem"):
        return True
    if not ca_path:
        return False
    try:
        return os.path.abspath(os.path.expanduser(raw)) == os.path.abspath(os.path.expanduser(ca_path))
    except OSError:
        return False


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    payload = json.dumps(data, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def scrub_settings_file(path: Path, *, gateway_url: str, ca_path: str = "") -> bool:
    if not gateway_url and not ca_path:
        return False
    try:
        raw = path.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict):
        return False
    env = doc.get("env")
    if not isinstance(env, dict) or not env:
        return False

    new_env = dict(env)
    matched_any_url = False
    for url_key, sibling_keys in _URL_ENV_GROUPS:
        val = new_env.get(url_key)
        if isinstance(val, str) and url_matches_gateway(val, gateway_url):
            matched_any_url = True
            new_env.pop(url_key, None)
            for sib in sibling_keys:
                new_env.pop(sib, None)

    for ca_key in _CA_ENV_KEYS:
        val = new_env.get(ca_key)
        if isinstance(val, str) and (_ca_matches(val, ca_path) or matched_any_url):
            new_env.pop(ca_key, None)

    if new_env == env:
        return False

    updated = dict(doc)
    if new_env:
        updated["env"] = new_env
    else:
        updated.pop("env", None)
    try:
        _atomic_write_json(path, updated)
    except OSError as exc:
        logger.warning("argent_cleanup_settings_write_failed", path=str(path), error=type(exc).__name__)
        return False
    return True


def _known_project_dirs(state_dir: Path) -> Set[Path]:
    dirs: Set[Path] = set()
    db_file = db_path_for(state_dir)
    if not db_file.is_file():
        return dirs
    try:
        conn = connect_readonly(db_file, timeout=2.0)
    except sqlite3.Error:
        return dirs
    try:
        for query in (
            "SELECT path FROM projects WHERE path IS NOT NULL",
            "SELECT DISTINCT working_dir FROM sessions WHERE working_dir IS NOT NULL",
        ):
            try:
                for (raw_path,) in conn.execute(query):
                    if isinstance(raw_path, str) and raw_path.strip():
                        dirs.add(Path(raw_path).expanduser())
            except sqlite3.Error:
                continue
    finally:
        conn.close()
    return dirs


def collect_settings_paths(
    state_dir: Path,
    *,
    extra_project_dirs: Iterable[Path] = (),
    home: Optional[Path] = None,
) -> List[Path]:
    user_home = home if home is not None else Path.home()
    candidates: List[Path] = []
    seen: Set[str] = set()

    def _add(p: Path) -> None:
        key = os.fspath(p)
        if key not in seen and p.is_file():
            seen.add(key)
            candidates.append(p)

    for rel in ("settings.local.json", "settings.json"):
        _add(user_home / ".claude" / rel)

    accounts_root = user_home / ".carnivore" / "accounts"
    if accounts_root.is_dir():
        try:
            for child in accounts_root.iterdir():
                if child.is_dir():
                    for rel in ("settings.local.json", "settings.json"):
                        _add(child / rel)
        except OSError:
            pass

    all_dirs = _known_project_dirs(state_dir) | {Path(d) for d in extra_project_dirs}
    for proj in sorted(all_dirs, key=os.fspath):
        for rel in ("settings.local.json", "settings.json"):
            _add(proj / ".claude" / rel)

    return candidates


def remove_ca_bundles(state_dir: Path) -> int:
    removed = 0
    if not state_dir.is_dir():
        return 0
    for bundle in state_dir.glob("agy-ca-bundle-*.pem"):
        try:
            bundle.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _default_run_tmux(args: Sequence[str]) -> Tuple[int, str]:
    try:
        proc = subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=5.0, check=False)
        return proc.returncode, proc.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def scrub_tmux_sessions(
    *,
    gateway_url: str,
    ca_path: str = "",
    socket_name: str = "cloude",
    run_tmux: Callable[[Sequence[str]], Tuple[int, str]] = _default_run_tmux,
) -> int:
    rc, raw_sessions = run_tmux(["-L", socket_name, "list-sessions", "-F", "#{session_name}"])
    if rc != 0 or not raw_sessions.strip():
        return 0
    cleaned_sessions = 0
    for sess in [ln.strip() for ln in raw_sessions.splitlines() if ln.strip()]:
        rc_env, raw_env = run_tmux(["-L", socket_name, "show-environment", "-t", sess])
        if rc_env != 0:
            continue
        env_map: Dict[str, str] = {}
        for line in raw_env.splitlines():
            if "=" in line and not line.startswith("-"):
                k, v = line.split("=", 1)
                env_map[k] = v

        to_unset: List[str] = [k for k in ALWAYS_UNSET_TMUX_VARS if k in env_map]
        matched_any_url = False
        for url_key, sibling_keys in _URL_ENV_GROUPS:
            val = env_map.get(url_key, "")
            if val and url_matches_gateway(val, gateway_url):
                matched_any_url = True
                to_unset.append(url_key)
                for sib in sibling_keys:
                    if sib in env_map:
                        to_unset.append(sib)
        for ca_key in _CA_ENV_KEYS:
            val = env_map.get(ca_key, "")
            if val and (_ca_matches(val, ca_path) or matched_any_url):
                to_unset.append(ca_key)

        unique_unset = list(dict.fromkeys(to_unset))
        if not unique_unset:
            continue
        for var in unique_unset:
            run_tmux(["-L", socket_name, "set-environment", "-t", sess, "-u", var])
        cleaned_sessions += 1
    return cleaned_sessions


def scrub_argent_injections(
    *,
    gateway_url: str,
    ca_path: str = "",
    state_dir: Optional[Path] = None,
    socket_name: Optional[str] = None,
    project_dirs: Iterable[Path] = (),
    home: Optional[Path] = None,
    run_tmux: Callable[[Sequence[str]], Tuple[int, str]] = _default_run_tmux,
) -> Dict[str, int]:
    resolved_state = Path(state_dir) if state_dir is not None else app_settings.get_state_dir()
    cleaned_files = 0
    for path in collect_settings_paths(resolved_state, extra_project_dirs=project_dirs, home=home):
        if scrub_settings_file(path, gateway_url=gateway_url, ca_path=ca_path):
            cleaned_files += 1
    cleaned_tmux = (
        scrub_tmux_sessions(gateway_url=gateway_url, ca_path=ca_path, socket_name=socket_name, run_tmux=run_tmux)
        if socket_name
        else 0
    )
    removed_bundles = remove_ca_bundles(resolved_state)
    result = {
        "settings_files": cleaned_files,
        "tmux_sessions": cleaned_tmux,
        "ca_bundles": removed_bundles,
    }
    if any(result.values()):
        logger.info("argent_disable_cleanup_complete", **result)
    return result


def scrub_live_install(cfg: Optional[ArgentSettings] = None) -> Dict[str, int]:
    if test_mode_enabled():
        return {"settings_files": 0, "tmux_sessions": 0, "ca_bundles": 0}
    resolved_cfg = cfg if cfg is not None else settings_module.read()
    from src.core.argent import fallback_spend

    manager = fallback_spend.session_manager()
    socket_name = manager.tmux_socket_name() if manager is not None and hasattr(manager, "tmux_socket_name") else "cloude"
    return scrub_argent_injections(
        gateway_url=resolved_cfg.gateway_url,
        ca_path=resolved_cfg.ca_path,
        state_dir=app_settings.get_state_dir(),
        socket_name=socket_name,
    )
