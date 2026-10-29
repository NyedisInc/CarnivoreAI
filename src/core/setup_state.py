
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.product_identity import env_value

SETUP_COMPLETE = "complete"

SETUP_INCOMPLETE = "incomplete"

SETUP_UNDETERMINED = "undetermined"

LOOPBACK_HOST = "127.0.0.1"

PAIRED_SENTINEL_NAME = ".totp_paired"

JOINED_MARKER_NAME = ".pack_joined"

PACK_LEFT_NAME = ".pack_left"


@dataclass(frozen=True)
class SetupCheck:

    key: str
    title: str
    passed: Optional[bool]
    detail: str


@dataclass(frozen=True)
class SetupState:

    status: str
    checks: tuple[SetupCheck, ...]
    joined: Optional[bool] = None
    pack_left: bool = False

    @property
    def is_complete(self) -> bool:
        return self.status == SETUP_COMPLETE

    def outstanding(self) -> tuple[SetupCheck, ...]:
        return tuple(c for c in self.checks if c.passed is not True)


@dataclass(frozen=True)
class Exposure:

    bind_host: str
    configured_bind_host: str
    locked_down: bool
    wizard_requires_auth: bool
    reason: str

    @property
    def restart_required_to_apply(self) -> bool:
        return self.bind_host != self.configured_bind_host


def _sentinel_path(config_path: Path) -> Path:
    return config_path.parent / PAIRED_SENTINEL_NAME


def joined_marker_path(config_path: Path) -> Path:
    return config_path.parent / JOINED_MARKER_NAME


def pack_left_path(config_path: Path) -> Path:
    return config_path.parent / PACK_LEFT_NAME


def _exists(path: Path) -> Optional[bool]:
    try:
        return path.exists()
    except OSError:
        return None


def evaluate_setup_state(
    config_path: Path,
    totp_secret: Optional[str],
    jwt_secret: Optional[str],
) -> SetupState:
    checks: list[SetupCheck] = []

    config_ok: Optional[bool]
    if not config_path.exists():
        config_ok = False
        config_detail = (
            f"No configuration file at {config_path}. The wizard will write "
            "one when you finish."
        )
    else:
        try:
            json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            config_ok = None
            config_detail = (
                f"{config_path} exists but is not valid JSON ({exc}), so "
                "whether it is set up correctly cannot be determined. Fix or "
                "move the file; nothing here will overwrite it."
            )
        except OSError as exc:
            config_ok = None
            config_detail = (
                f"{config_path} could not be read ({exc}), so its state "
                "cannot be determined."
            )
        else:
            config_ok = True
            config_detail = f"Configuration file present and readable at {config_path}."

    checks.append(
        SetupCheck(
            key="config_file",
            title="Configuration file",
            passed=config_ok,
            detail=config_detail,
        )
    )

    checks.append(
        SetupCheck(
            key="totp_secret",
            title="Two-factor secret",
            passed=bool(totp_secret and totp_secret.strip()),
            detail=(
                "A TOTP secret is configured."
                if totp_secret and totp_secret.strip()
                else "No TOTP secret is configured, so nothing can log in yet."
            ),
        )
    )

    checks.append(
        SetupCheck(
            key="jwt_secret",
            title="Session signing key",
            passed=bool(jwt_secret and jwt_secret.strip()),
            detail=(
                "A JWT signing secret is configured."
                if jwt_secret and jwt_secret.strip()
                else "No JWT signing secret is configured, so no session can "
                "be issued."
            ),
        )
    )

    joined = _exists(joined_marker_path(config_path))
    sentinel = _exists(_sentinel_path(config_path))
    paired_ok: Optional[bool]
    if joined is True or sentinel is True:
        paired_ok = True
        paired_detail = (
            "This computer joined a pack, whose owner holds the authenticator."
            if joined
            else "An authenticator has been paired with this instance."
        )
    elif joined is None or sentinel is None:
        paired_ok = None
        paired_detail = "Whether an authenticator has been paired could not be determined."
    else:
        paired_ok = False
        paired_detail = (
            "No authenticator has been paired yet. Until one is, this "
            "instance has no owner, so it stays on loopback only."
        )

    checks.append(
        SetupCheck(
            key="totp_paired",
            title="Authenticator paired",
            passed=paired_ok,
            detail=paired_detail,
        )
    )

    if any(c.passed is None for c in checks):
        status = SETUP_UNDETERMINED
    elif all(c.passed is True for c in checks):
        status = SETUP_COMPLETE
    else:
        status = SETUP_INCOMPLETE

    return SetupState(status=status, checks=tuple(checks), joined=joined,
                      pack_left=_exists(pack_left_path(config_path)) is not False)


def resolve_exposure(configured_bind_host: str, state: SetupState) -> Exposure:
    if state.joined:
        exposure = Exposure(
            bind_host=LOOPBACK_HOST,
            configured_bind_host=configured_bind_host,
            locked_down=configured_bind_host != LOOPBACK_HOST,
            wizard_requires_auth=True,
            reason=(
                "this computer joined a pack: it listens only on this computer and is reached "
                "through main"
            ),
        )
    elif state.is_complete:
        exposure = Exposure(
            bind_host=configured_bind_host,
            configured_bind_host=configured_bind_host,
            locked_down=False,
            wizard_requires_auth=True,
            reason=(
                "Setup is complete, so the configured bind address is in "
                "force and the wizard requires a login."
            ),
        )
    else:
        exposure = Exposure(
            bind_host=LOOPBACK_HOST,
            configured_bind_host=configured_bind_host,
            locked_down=configured_bind_host != LOOPBACK_HOST,
            wizard_requires_auth=False,
            reason=(
                "Setup is not complete, so the setup wizard is open without "
                "a login and the server is pinned to loopback until it is. "
                f"The configured address {configured_bind_host} takes effect "
                "after setup finishes and the server restarts."
            ),
        )

    if not exposure.wizard_requires_auth and exposure.bind_host != LOOPBACK_HOST:
        raise RuntimeError(
            "refusing to start: the setup wizard would be reachable without "
            f"authentication on {exposure.bind_host}. This combination is a "
            "remote takeover path and is never valid."
        )

    return exposure


BOUND_HOST_ENV = "CLOUDE_BOUND_HOST"


def record_bound_host(host: str) -> None:
    os.environ[BOUND_HOST_ENV] = host


def recorded_bound_host() -> Optional[str]:
    value = (env_value("BOUND_HOST") or "").strip()
    return value or None


def bind_report(configured_host: str) -> dict:
    effective = recorded_bound_host()

    if effective is None:
        return {
            "effective_host": None,
            "effective_host_known": False,
            "configured_host": configured_host,
            "locked_down": None,
            "restart_required": None,
            "reason": (
                "The address in force was not measured, so it is unknown. "
                f"Configuration asks for {configured_host}, which is what "
                "was requested and not evidence of what is listening."
            ),
        }

    differs = effective != configured_host
    if differs:
        reason = (
            f"Listening on {effective}. Configuration asks for "
            f"{configured_host}, which needs a server restart to apply - "
            "uvicorn binds its socket once at startup and cannot rebind."
        )
    else:
        reason = f"Listening on {effective}, which is what configuration asks for."

    return {
        "effective_host": effective,
        "effective_host_known": True,
        "configured_host": configured_host,
        "locked_down": differs,
        "restart_required": differs,
        "reason": reason,
    }


def current_bind_report() -> dict:
    from src.config import settings  # noqa: PLC0415

    return bind_report(settings.host)


def current_setup_state() -> SetupState:
    from src.config import settings  # noqa: PLC0415

    return evaluate_setup_state(
        Path(settings.auth_config_file).expanduser(),
        settings.totp_secret,
        settings.jwt_secret,
    )


def current_exposure() -> Exposure:
    from src.config import settings  # noqa: PLC0415

    return resolve_exposure(settings.host, current_setup_state())


def mark_setup_complete(config_path: Path) -> None:
    path = _sentinel_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return
    os.close(fd)
