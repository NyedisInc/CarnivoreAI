from __future__ import annotations

import secrets as _secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import setup_auth  # noqa: E402


def _synthetic_base32(length: int = 32) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    return "".join(_secrets.choice(alphabet) for _ in range(length))


def _synthetic_jwt() -> str:
    return _secrets.token_urlsafe(32)


def _read_key(env_path: Path, key: str) -> str | None:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


@pytest.fixture()
def env_dir(tmp_path: Path) -> Path:
    (tmp_path / ".env.example").write_text(
        "# Authentication Secrets\n"
        "TOTP_SECRET=\n"
        "JWT_SECRET=\n"
        "\n"
        "AUTH_CONFIG_FILE=./config.json\n",
        encoding="utf-8",
    )
    return tmp_path


def test_second_run_preserves_totp_secret(env_dir: Path) -> None:
    env_path = env_dir / ".env"

    first_totp = _synthetic_base32()
    first_jwt = _synthetic_jwt()
    setup_auth.update_env_file(env_path, first_totp, first_jwt)
    after_first = _read_key(env_path, "TOTP_SECRET")

    setup_auth.update_env_file(env_path, _synthetic_base32(), _synthetic_jwt())
    after_second = _read_key(env_path, "TOTP_SECRET")

    assert after_second == after_first, (
        "second setup run replaced an existing TOTP_SECRET; "
        "the paired authenticator is now useless"
    )


def test_second_run_preserves_jwt_secret(env_dir: Path) -> None:
    env_path = env_dir / ".env"

    setup_auth.update_env_file(env_path, _synthetic_base32(), _synthetic_jwt())
    after_first = _read_key(env_path, "JWT_SECRET")

    setup_auth.update_env_file(env_path, _synthetic_base32(), _synthetic_jwt())

    assert _read_key(env_path, "JWT_SECRET") == after_first


def test_missing_jwt_is_minted_while_present_totp_is_kept(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    existing_totp = _synthetic_base32()
    env_path.write_text(
        f"TOTP_SECRET={existing_totp}\nJWT_SECRET=\n", encoding="utf-8"
    )

    new_jwt = _synthetic_jwt()
    setup_auth.update_env_file(env_path, _synthetic_base32(), new_jwt)

    assert _read_key(env_path, "TOTP_SECRET") == existing_totp
    assert _read_key(env_path, "JWT_SECRET") == new_jwt


def test_rotation_flag_does_change_the_totp_secret(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    original = _synthetic_base32()
    setup_auth.update_env_file(env_path, original, _synthetic_jwt())

    replacement = _synthetic_base32()
    setup_auth.update_env_file(
        env_path, replacement, _synthetic_jwt(), overwrite_totp=True
    )

    assert _read_key(env_path, "TOTP_SECRET") == replacement


def test_rotation_flag_does_change_the_jwt_secret(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    setup_auth.update_env_file(env_path, _synthetic_base32(), _synthetic_jwt())
    kept_totp = _read_key(env_path, "TOTP_SECRET")

    replacement = _synthetic_jwt()
    setup_auth.update_env_file(
        env_path, _synthetic_base32(), replacement, overwrite_jwt=True
    )

    assert _read_key(env_path, "JWT_SECRET") == replacement
    assert _read_key(env_path, "TOTP_SECRET") == kept_totp


def test_apply_auth_secrets_survives_a_template_rewrite(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    original_totp = _synthetic_base32()
    original_jwt = _synthetic_jwt()
    env_path.write_text(
        f"TOTP_SECRET={original_totp}\nJWT_SECRET={original_jwt}\n",
        encoding="utf-8",
    )

    captured = setup_auth.capture_auth_secrets(env_path)

    env_path.write_text(
        (env_dir / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )

    outcome = setup_auth.apply_auth_secrets(env_path, captured)

    assert _read_key(env_path, "TOTP_SECRET") == original_totp
    assert _read_key(env_path, "JWT_SECRET") == original_jwt
    assert outcome["totp_action"] == "kept"
    assert outcome["jwt_action"] == "kept"


def test_apply_auth_secrets_mints_on_a_truly_empty_env(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    env_path.write_text(
        (env_dir / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )

    outcome = setup_auth.apply_auth_secrets(
        env_path, setup_auth.capture_auth_secrets(env_path)
    )

    assert outcome["totp_action"] == "created"
    assert outcome["jwt_action"] == "created"
    assert _read_key(env_path, "TOTP_SECRET")
    assert _read_key(env_path, "JWT_SECRET")


def test_kept_totp_leaves_the_paired_sentinel_alone(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    env_path.write_text(
        f"TOTP_SECRET={_synthetic_base32()}\nJWT_SECRET={_synthetic_jwt()}\n"
        "AUTH_CONFIG_FILE=./config.json\n",
        encoding="utf-8",
    )
    sentinel = env_dir / ".totp_paired"
    sentinel.touch()

    setup_auth.apply_auth_secrets(env_path, setup_auth.capture_auth_secrets(env_path))

    assert sentinel.exists()


def test_new_totp_clears_the_paired_sentinel(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    env_path.write_text(
        f"TOTP_SECRET={_synthetic_base32()}\nJWT_SECRET={_synthetic_jwt()}\n"
        "AUTH_CONFIG_FILE=./config.json\n",
        encoding="utf-8",
    )
    sentinel = env_dir / ".totp_paired"
    sentinel.touch()

    captured = setup_auth.capture_auth_secrets(env_path)
    outcome = setup_auth.apply_auth_secrets(env_path, captured, rotate_totp=True)

    assert outcome["totp_action"] == "rotated"
    assert not sentinel.exists()


def test_sentinel_path_follows_auth_config_file(tmp_path: Path) -> None:
    elsewhere = tmp_path / "state"
    elsewhere.mkdir()
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"AUTH_CONFIG_FILE={elsewhere / 'config.json'}\n", encoding="utf-8"
    )

    assert setup_auth.paired_sentinel_path(env_path) == elsewhere / ".totp_paired"


def test_rotation_is_reported_so_the_caller_can_show_a_qr(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    env_path.write_text(
        f"TOTP_SECRET={_synthetic_base32()}\nJWT_SECRET={_synthetic_jwt()}\n",
        encoding="utf-8",
    )
    captured = setup_auth.capture_auth_secrets(env_path)

    outcome = setup_auth.apply_auth_secrets(env_path, captured, rotate_totp=True)

    assert outcome["show_qr"] is True
    assert outcome["totp_secret"] == _read_key(env_path, "TOTP_SECRET")


def test_keeping_the_secret_shows_no_qr(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    env_path.write_text(
        f"TOTP_SECRET={_synthetic_base32()}\nJWT_SECRET={_synthetic_jwt()}\n",
        encoding="utf-8",
    )

    outcome = setup_auth.apply_auth_secrets(
        env_path, setup_auth.capture_auth_secrets(env_path)
    )

    assert outcome["show_qr"] is False


def test_whitespace_only_secret_counts_as_absent(env_dir: Path) -> None:
    env_path = env_dir / ".env"
    env_path.write_text("TOTP_SECRET=   \nJWT_SECRET=\n", encoding="utf-8")

    outcome = setup_auth.apply_auth_secrets(
        env_path, setup_auth.capture_auth_secrets(env_path)
    )

    assert outcome["totp_action"] == "created"
    assert _read_key(env_path, "TOTP_SECRET").strip()


LEGACY_NOTIFICATION_KEYS = ("ntfy_topic", "ntfy_base_url", "slack_webhook_url", "pushover_token", "public_base_url")


def test_setup_no_longer_writes_the_retired_notification_keys() -> None:
    source = Path(setup_auth.__file__).read_text(encoding="utf-8")
    assert "def main" in source
    for key in LEGACY_NOTIFICATION_KEYS:
        assert key not in source, key
    assert not hasattr(setup_auth, "setup_notifications_block")
    assert not hasattr(setup_auth, "rotate_topic_command")
    assert "--rotate-topic" not in source
