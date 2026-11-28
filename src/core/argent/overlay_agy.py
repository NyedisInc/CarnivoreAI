
from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from pathlib import Path

import structlog


class OverlayAgyError(ValueError):
    pass


logger = structlog.get_logger(__name__)

TOOL = "agy"
ENV_NAMES = ("GEMINI_API_KEY", "GOOGLE_GEMINI_BASE_URL", "SSL_CERT_FILE")
SETTINGS_JSON = json.dumps({"modelProvider": "gemini"}, separators=(",", ":"))


_SYSTEM_ROOTS = "/System/Library/Keychains/SystemRootCertificates.keychain"


def ca_bundle(ca_path: str, state_dir: Path) -> str:
    if not ca_path:
        return ""
    try:
        ca = Path(ca_path).expanduser().read_bytes()
        target = state_dir / f"agy-ca-bundle-{hashlib.sha256(ca).hexdigest()[:16]}.pem"
        if target.is_file():
            return str(target)
        roots = subprocess.run(["security", "find-certificate", "-a", "-p", _SYSTEM_ROOTS], capture_output=True, check=True, timeout=30).stdout
        if b"BEGIN CERTIFICATE" not in roots:
            raise OverlayAgyError("no system roots exported")
        state_dir.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(roots + b"\n" + ca)
        tmp.replace(target)
        for old in state_dir.glob("agy-ca-bundle-*.pem"):
            if old != target:
                old.unlink(missing_ok=True)
        return str(target)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.warning("argent_agy_ca_bundle_failed", error=type(exc).__name__)
        return ""


def preamble(read_key: str, gateway_url: str, proxy: str = "", bundle: str = "") -> str:
    ca = f"export SSL_CERT_FILE={shlex.quote(bundle)}; " if bundle else ""
    return (
        read_key +
        f'if [ -n "$_ak" ] && [ "$_ak" != "-" ]; then {proxy}export GEMINI_API_KEY="$_ak" GOOGLE_GEMINI_BASE_URL="${{_cb:-{shlex.quote(gateway_url.rstrip("/"))}}}"; {ca}'
        f'set -- --settings {shlex.quote(SETTINGS_JSON)} "$@"; fi; unset _ak _i _cb'
    )
