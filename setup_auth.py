#!/usr/bin/env python3
import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Callable

from src.core.app_restart.restart import (
    RestartOutcome,
    app_is_running,
    engine_owns_port,
    is_installed_engine_root,
    parse_port,
    port_accepts,
    restart_app_and_engine,
)
from src.core.owner_identity.otpauth import ISSUER
from src.core.product_identity import PRODUCT_NAME

DEFAULT_SERVER_PORT = 8000


def check_and_setup_venv():
    project_root = Path(__file__).parent
    venv_path = project_root / "venv"
    venv_python = venv_path / "bin" / "python3"

    if not venv_python.exists():
        print("❌ venv not found at: venv/")
        print("Please create it first:")
        print("  python3 -m venv venv")
        sys.exit(1)

    try:
        import pyotp
        import qrcode
        import jwt
        print("✅ All dependencies available\n")
        return
    except ImportError as e:
        missing_module = str(e).split("'")[1] if "'" in str(e) else "unknown"
        print(f"📦 Missing dependency: {missing_module}")
        print("Installing auth dependencies in venv...\n")

    try:
        result = subprocess.run([
            str(venv_python), "-m", "pip", "install", "-q",
            "pyotp", "qrcode", "pillow", "pyjwt"
        ], check=True, capture_output=True, text=True)

        print("✅ Dependencies installed successfully\n")

        print("🔄 Re-running with venv python...\n")
        subprocess.run([str(venv_python), __file__] + sys.argv[1:])
        sys.exit(0)

    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        print(f"Error output: {e.stderr}")
        sys.exit(1)


def generate_totp_secret():
    import pyotp
    return pyotp.random_base32()


def generate_jwt_secret():
    return secrets.token_urlsafe(32)


AUTH_SECRET_KEYS = ("TOTP_SECRET", "JWT_SECRET")

PAIRED_SENTINEL_NAME = ".totp_paired"


def read_env_value(env_path: Path, key: str):
    if not env_path.exists():
        return None
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


def capture_auth_secrets(env_path: Path) -> dict:
    return {key: read_env_value(env_path, key) for key in AUTH_SECRET_KEYS}


def paired_sentinel_path(env_path: Path) -> Path:
    configured = read_env_value(env_path, "AUTH_CONFIG_FILE") or "./config.json"
    config_path = Path(configured).expanduser()
    if not config_path.is_absolute():
        config_path = (env_path.parent / config_path).resolve()
    return config_path.parent / PAIRED_SENTINEL_NAME


def apply_auth_secrets(
    env_path: Path,
    captured: dict,
    *,
    rotate_totp: bool = False,
    rotate_jwt: bool = False,
) -> dict:
    existing_totp = captured.get("TOTP_SECRET")
    existing_jwt = captured.get("JWT_SECRET")

    if existing_totp and not rotate_totp:
        totp_secret, totp_action = existing_totp, "kept"
    else:
        totp_secret = generate_totp_secret()
        totp_action = "rotated" if existing_totp else "created"

    if existing_jwt and not rotate_jwt:
        jwt_secret, jwt_action = existing_jwt, "kept"
    else:
        jwt_secret = generate_jwt_secret()
        jwt_action = "rotated" if existing_jwt else "created"

    update_env_file(
        env_path,
        totp_secret,
        jwt_secret,
        overwrite_totp=True,
        overwrite_jwt=True,
    )

    sentinel_cleared = False
    if totp_action != "kept":
        sentinel = paired_sentinel_path(env_path)
        try:
            if sentinel.exists():
                sentinel.unlink()
                sentinel_cleared = True
        except OSError as e:
            print(f"WARNING: could not clear {sentinel}: {e}")
            print("         Delete it by hand or the setup screen will refuse to re-pair.")

    return {
        "totp_action": totp_action,
        "jwt_action": jwt_action,
        "totp_secret": totp_secret,
        "show_qr": totp_action != "kept",
        "sentinel_cleared": sentinel_cleared,
    }


def update_env_file(
    env_path: Path,
    totp_secret: str,
    jwt_secret: str,
    *,
    overwrite_totp: bool = False,
    overwrite_jwt: bool = False,
):
    if env_path.exists():
        with open(env_path) as f:
            lines = f.readlines()
    else:
        example_path = env_path.parent / ".env.example"
        if example_path.exists():
            with open(example_path) as f:
                lines = f.readlines()
        else:
            lines = []

    totp_found = False
    jwt_found = False

    for i, line in enumerate(lines):
        if line.startswith("TOTP_SECRET="):
            totp_found = True
            existing = line.split("=", 1)[1].strip()
            if not existing or overwrite_totp:
                lines[i] = f"TOTP_SECRET={totp_secret}\n"
        elif line.startswith("JWT_SECRET="):
            jwt_found = True
            existing = line.split("=", 1)[1].strip()
            if not existing or overwrite_jwt:
                lines[i] = f"JWT_SECRET={jwt_secret}\n"

    if not totp_found:
        insert_index = len(lines)
        for i, line in enumerate(lines):
            if "# Authentication Secrets" in line:
                insert_index = i + 2
                break

        if insert_index >= len(lines):
            lines.append(f"\n# Authentication Secrets (generated by setup_auth.py)\n")
            lines.append(f"TOTP_SECRET={totp_secret}\n")
        else:
            lines.insert(insert_index, f"TOTP_SECRET={totp_secret}\n")

    if not jwt_found:
        for i, line in enumerate(lines):
            if line.startswith("TOTP_SECRET="):
                lines.insert(i + 1, f"JWT_SECRET={jwt_secret}\n")
                break
        else:
            lines.append(f"JWT_SECRET={jwt_secret}\n")

    with open(env_path, 'w') as f:
        f.writelines(lines)
    try:
        Path(env_path).chmod(0o600)
    except OSError:
        pass


def generate_qr_code(secret: str, account_name: str = ISSUER):
    import pyotp
    import qrcode

    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(
        name=account_name,
        issuer_name=ISSUER
    )

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(uri)
    qr.make(fit=True)

    qr.print_ascii()

    img = qr.make_image(fill_color="black", back_color="white")
    qr_path = Path(__file__).parent / "totp-qr.png"
    img.save(str(qr_path))

    return uri, qr_path

def prompt_with_default(prompt_text, default_value=""):
    if default_value:
        user_input = input(f"{prompt_text} [{default_value}]: ").strip()
        return user_input if user_input else default_value
    else:
        return input(f"{prompt_text}: ").strip()


def setup_env_file(env_path):
    current_values = {}
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    current_values[key] = value

    print("=" * 70)
    print("Local paths")
    print("=" * 70)
    print()

    import shutil
    auto_claude_path = shutil.which('claude')
    if not auto_claude_path:
        common_paths = [
            str(Path.home() / '.claude' / 'local' / 'claude'),
            '/usr/local/bin/claude',
            '/opt/homebrew/bin/claude'
        ]
        for path_str in common_paths:
            if Path(path_str).exists():
                auto_claude_path = path_str
                break

    default_claude_path = current_values.get('CLAUDE_CLI_PATH', auto_claude_path or '/path/to/claude')
    if auto_claude_path:
        print(f"📍 Detected Claude CLI at: {auto_claude_path}")

    claude_cli_path = prompt_with_default(
        "Claude CLI path (leave empty for auto-detect)",
        default_claude_path if not auto_claude_path else auto_claude_path
    )

    default_working_dir = current_values.get('DEFAULT_WORKING_DIR', '~/carnivore-projects')
    working_dir = prompt_with_default(
        "Default working directory for projects",
        default_working_dir
    )

    default_log_dir = current_values.get('LOG_DIRECTORY', '/tmp/cloude-code-logs')
    log_dir = prompt_with_default(
        "Log directory",
        default_log_dir
    )

    print()

    env_template_path = env_path.parent / ".env.example"
    if env_template_path.exists():
        with open(env_template_path) as f:
            content = f.read()
    else:
        content = (
            "# Server Configuration\n"
            "HOST=0.0.0.0\n"
            "PORT=8000\n"
            "\n"
            "# Session Configuration\n"
            "DEFAULT_WORKING_DIR=~/carnivore-projects\n"
            "SESSION_TIMEOUT=3600\n"
            "\n"
            "# Claude CLI Configuration\n"
            "CLAUDE_CLI_PATH=/path/to/claude\n"
            "\n"
            "# Logging\n"
            "LOG_BUFFER_SIZE=1000\n"
            "LOG_FILE_RETENTION=7\n"
            "LOG_DIRECTORY=/tmp/cloude-code-logs\n"
            "\n"
            "# Security (Optional)\n"
            "API_KEY=\n"
            "# ALLOWED_ORIGINS defaults to [\"*\"] - only set if you need to restrict origins\n"
            "\n"
            "# Authentication Secrets\n"
            "TOTP_SECRET=\n"
            "JWT_SECRET=\n"
            "\n"
            "# Authentication Configuration\n"
            "AUTH_CONFIG_FILE=./config.json\n"
        )

    import re

    if 'CLAUDE_CLI_PATH=' in content:
        content = re.sub(r'^CLAUDE_CLI_PATH=.*$', f'CLAUDE_CLI_PATH={claude_cli_path}', content, flags=re.MULTILINE)
    else:
        content += f"\nCLAUDE_CLI_PATH={claude_cli_path}\n"

    if 'DEFAULT_WORKING_DIR=' in content:
        content = re.sub(r'^DEFAULT_WORKING_DIR=.*$', f'DEFAULT_WORKING_DIR={working_dir}', content, flags=re.MULTILINE)
    else:
        content += f"DEFAULT_WORKING_DIR={working_dir}\n"

    if 'LOG_DIRECTORY=' in content:
        content = re.sub(r'^LOG_DIRECTORY=.*$', f'LOG_DIRECTORY={log_dir}', content, flags=re.MULTILINE)
    else:
        content += f"LOG_DIRECTORY={log_dir}\n"

    with open(env_path, 'w') as f:
        f.write(content)
    try:
        Path(env_path).chmod(0o600)
    except OSError:
        pass

    print()
    print(f"✅ Configuration written to {env_path}")
    print()

    if claude_cli_path and claude_cli_path != '/path/to/claude':
        if not Path(claude_cli_path).exists():
            print(f"⚠️  Claude CLI not found at: {claude_cli_path}")
            print("   This may cause issues when creating projects.")
            print("   You can update CLAUDE_CLI_PATH in .env later.")
            print()

    return claude_cli_path, working_dir, log_dir


def confirm_rotation(
    *, rotate_totp: bool, rotate_jwt: bool, assume_yes: bool = False
) -> bool:
    print()
    print("=" * 70)
    print("DESTRUCTIVE ROTATION REQUESTED")
    print("=" * 70)
    print()
    if rotate_totp:
        print("  --rotate-totp replaces your TOTP secret.")
        print("    Your authenticator app STOPS WORKING the moment this runs.")
        print("    You must scan the new QR code printed below to log in again.")
        print()
    if rotate_jwt:
        print("  --rotate-jwt replaces your JWT signing secret.")
        print("    EVERY logged-in session and device is signed out immediately.")
        print()
    if assume_yes:
        print("Proceeding (--yes given).")
        print()
        return True
    answer = input("Type 'rotate' to confirm, anything else to cancel: ").strip()
    print()
    return answer == "rotate"


def report_secret_outcome(outcome: dict) -> None:
    words = {
        "kept": "kept the existing value (unchanged)",
        "created": "generated (none was set)",
        "rotated": "REPLACED with a new value",
    }
    print(f"  TOTP_SECRET: {words[outcome['totp_action']]}")
    print(f"  JWT_SECRET:  {words[outcome['jwt_action']]}")
    if outcome["jwt_action"] == "rotated":
        print("  -> every logged-in session has been signed out.")
    if outcome["sentinel_cleared"]:
        print(f"  -> cleared the stale {PAIRED_SENTINEL_NAME} pairing marker,")
        print("     open carnivore on this computer (http://127.0.0.1:<port>) to pair, or scan the QR printed here.")
    print()


def restart_running_install(env_path: Path, restart: Callable[[int], RestartOutcome] = restart_app_and_engine) -> RestartOutcome:
    return restart(parse_port(read_env_value(env_path, "PORT"), DEFAULT_SERVER_PORT))


def secrets_changed(outcome: dict) -> bool:
    return outcome["totp_action"] != "kept" or outcome["jwt_action"] != "kept"


def start_server(project_root: Path) -> None:
    venv_python = project_root / "venv" / "bin" / "python3"
    if not venv_python.exists():
        print("Could not find venv, please start server manually with: ./start.sh")
        return
    try:
        subprocess.Popen([str(venv_python), '-m', 'src.main'], cwd=str(project_root),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        print(f"Could not start server: {e}")
        print("   Start manually with: ./start.sh")
        return
    print("Server started in background")


def apply_running_install(project_root: Path, env_path: Path, changed: bool) -> None:
    if not changed:
        port = parse_port(read_env_value(env_path, "PORT"), DEFAULT_SERVER_PORT)
        if not port_accepts(port):
            start_server(project_root)
        elif engine_owns_port(port):
            print(f"{PRODUCT_NAME} is already running; no secret changed, so nothing was restarted.")
        else:
            print(f"Port {port} is held by something other than the {PRODUCT_NAME} engine; no server was started.")
        return
    if not is_installed_engine_root(project_root):
        port = parse_port(read_env_value(env_path, "PORT"), DEFAULT_SERVER_PORT)
        if not port_accepts(port) and not app_is_running():
            start_server(project_root)
            return
        print(f"This folder is not the installed {PRODUCT_NAME} engine's folder, so the running engine")
        print(f"does not read the .env written here. Nothing was restarted: restart {PRODUCT_NAME} yourself")
        print("after copying the new secret to the installed engine's .env.")
        return
    print(f"Restarting {PRODUCT_NAME} to apply changes...")
    print()
    outcome = restart_running_install(env_path)
    for note in outcome.notes:
        print(f"WARNING: {note}")
    if not outcome.restarted:
        print(f"{PRODUCT_NAME} was NOT restarted and no second server was started.")
        print("The new secret takes effect the next time you restart the app.")
    elif outcome.reopened:
        print(f"{PRODUCT_NAME} restarted (it starts its own server)")
    else:
        start_server(project_root)


def finish_setup(project_root: Path, env_path: Path, config_path: Path, changed: bool) -> None:
    print()
    print("=" * 70)
    print("Setup Complete!")
    print("=" * 70)
    print()
    print(f"✅ Configuration: {env_path}")
    print(f"✅ App config: {config_path}")
    print()
    print("You can find and modify the app config here:")
    print(f"   {config_path}")
    print()
    apply_running_install(project_root, env_path, changed)

    print()
    print("This window will close in 3 seconds...")
    import time
    time.sleep(3)

    subprocess.run(['osascript', '-e', 'tell application "Terminal" to close first window'],
                  check=False)



def main():
    parser = argparse.ArgumentParser(
        description=f"{PRODUCT_NAME} authentication setup",
        add_help=True,
    )
    parser.add_argument(
        "--rotate-totp",
        action="store_true",
        help=(
            "DESTRUCTIVE: replace TOTP_SECRET. This UNPAIRS your "
            "authenticator app; you must scan the new QR to get back in."
        ),
    )
    parser.add_argument(
        "--rotate-jwt",
        action="store_true",
        help=(
            "DESTRUCTIVE: replace JWT_SECRET. This SIGNS OUT every "
            "logged-in session and device immediately."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the typed confirmation for --rotate-totp / --rotate-jwt.",
    )
    args = parser.parse_args()

    if (args.rotate_totp or args.rotate_jwt) and not confirm_rotation(
        rotate_totp=args.rotate_totp,
        rotate_jwt=args.rotate_jwt,
        assume_yes=args.yes,
    ):
        print("Rotation cancelled. Nothing was changed.")
        sys.exit(1)

    check_and_setup_venv()

    print("=" * 70)
    print(f"{PRODUCT_NAME} Authentication Setup")
    print("=" * 70)
    print()

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"🐍 Python {python_version}")
    print()

    project_root = Path(__file__).parent
    env_path = project_root / ".env"

    captured_secrets = capture_auth_secrets(env_path)

    claude_cli_path, working_dir, log_dir = setup_env_file(env_path)

    import os
    print("Creating directories...")
    log_dir_expanded = os.path.expanduser(os.path.expandvars(log_dir))
    working_dir_expanded = os.path.expanduser(os.path.expandvars(working_dir))

    try:
        Path(log_dir_expanded).mkdir(parents=True, exist_ok=True)
        print(f"✅ Created log directory: {log_dir_expanded}")
    except Exception as e:
        print(f"⚠️  Could not create log directory: {e}")

    try:
        Path(working_dir_expanded).mkdir(parents=True, exist_ok=True)
        print(f"✅ Created projects directory: {working_dir_expanded}")
    except Exception as e:
        print(f"⚠️  Could not create projects directory: {e}")

    print()

    print("Authentication secrets...")
    secret_outcome = apply_auth_secrets(
        env_path,
        captured_secrets,
        rotate_totp=args.rotate_totp,
        rotate_jwt=args.rotate_jwt,
    )
    totp_secret = secret_outcome["totp_secret"]
    report_secret_outcome(secret_outcome)

    config_path = project_root / "config.json"

    if config_path.exists():
        print(f"📄 Config file exists at: {config_path}")

        try:
            with open(config_path) as f:
                data = json.load(f)

            if "totp_secret" in data or "jwt_secret" in data:
                data.pop("totp_secret", None)
                data.pop("jwt_secret", None)

                with open(config_path, 'w') as f:
                    json.dump(data, f, indent=2)

                print("✅ Removed secrets from config.json (now in .env)\n")
            else:
                print("✅ Config file already clean (no secrets)\n")

        except Exception as e:
            print(f"⚠️  Error cleaning config: {e}\n")

    else:
        example_path = project_root / "config.example.json"
        with open(example_path) as f:
            config = json.load(f)

        config.pop("totp_secret", None)
        config.pop("jwt_secret", None)

        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        print(f"✅ Configuration file created at: {config_path}\n")


    print("=" * 70)
    print("TOTP Setup")
    print("=" * 70)
    print()

    if not secret_outcome["show_qr"]:
        print("Your existing TOTP secret was kept, so your authenticator app")
        print("still works. There is nothing to scan and no new QR code.")
        print()
        print("If you have LOST your authenticator, re-run with:")
        print("   python3 setup_auth.py --rotate-totp")
        print()
        finish_setup(project_root, env_path, config_path, secrets_changed(secret_outcome))
        return

    uri, qr_path = generate_qr_code(totp_secret)

    print()
    print(f"📱 Opening QR code...")
    try:
        subprocess.run(['open', str(qr_path)], check=False)
        print(f"✅ QR code opened in Preview: {qr_path}")
    except Exception as e:
        print(f"⚠️  Could not open QR code automatically: {e}")
        print(f"   Please open manually: {qr_path}")

    print()
    print("=" * 70)
    print(f"📱 SCAN THE QR CODE that just opened in Preview!")
    print("=" * 70)
    print()
    print("Use Google Authenticator, Authy, or any TOTP app")
    print()
    print(f"Or manually enter this secret: {totp_secret}")
    print()

    input("Press Enter after scanning the QR code...")

    finish_setup(project_root, env_path, config_path, secrets_changed(secret_outcome))


if __name__ == "__main__":
    main()
