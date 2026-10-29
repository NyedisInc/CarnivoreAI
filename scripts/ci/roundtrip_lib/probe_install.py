#!/usr/bin/env python3
"""Report what ONE CloudeCode install can actually see, as JSON.

THREE OUTCOMES. A field the running version has no concept of reports
``NOT_SUPPORTED``; a field it has but could not read reports
``CANNOT_DETERMINE`` with the error text attached under ``errors``.
Neither is ever collapsed into an empty list, because an empty list and
"this version cannot answer" are the difference between a real data-loss
finding and a feature that simply does not exist yet.

Inputs (argv): --install-dir DIR (required), --label TEXT (required),
  --state-dir DIR (optional; when given, the cloude.db under it is
  probed too).
Output: one JSON object on stdout. Exit 0 whenever the probe itself ran,
  regardless of what it found - a non-zero exit here would mean the
  MEASUREMENT failed, not that the install is unhealthy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

NOT_SUPPORTED = "NOT_SUPPORTED"
CANNOT_DETERMINE = "CANNOT_DETERMINE"


def sha256_of(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return CANNOT_DETERMINE


def probe_config_file(config_path: Path, out: dict) -> dict:
    out["config_path"] = str(config_path)
    out["config_exists"] = config_path.exists()
    out["config_sha256"] = sha256_of(config_path) if config_path.exists() else NOT_SUPPORTED
    if not config_path.exists():
        out["config_top_keys"] = CANNOT_DETERMINE
        out["config_version_on_disk"] = CANNOT_DETERMINE
        return {}
    try:
        data = json.loads(config_path.read_text())
    except (OSError, ValueError) as e:
        out["config_top_keys"] = CANNOT_DETERMINE
        out["config_version_on_disk"] = CANNOT_DETERMINE
        out.setdefault("errors", []).append(f"config_parse: {e}")
        return {}
    out["config_top_keys"] = sorted(data.keys())
    out["config_version_on_disk"] = data.get("config_version", "ABSENT")
    agents = data.get("agents") or {}
    out["config_agents_keys"] = sorted(agents.keys()) if isinstance(agents, dict) else CANNOT_DETERMINE
    return data


def probe_settings(out: dict) -> None:
    try:
        from src.config import Settings  # noqa: PLC0415
    except Exception as e:
        out["settings_importable"] = False
        out.setdefault("errors", []).append(f"import_settings: {e}")
        for k in ("projects", "wrappers", "terminal_commands", "agent_commands"):
            out[k] = CANNOT_DETERMINE
        return

    out["settings_importable"] = True
    try:
        settings = Settings()
    except Exception as e:
        out["settings_constructible"] = False
        out.setdefault("errors", []).append(f"construct_settings: {e}")
        for k in ("projects", "wrappers", "terminal_commands", "agent_commands"):
            out[k] = CANNOT_DETERMINE
        return
    out["settings_constructible"] = True

    # state directory
    if hasattr(settings, "get_state_dir"):
        try:
            out["state_dir"] = str(settings.get_state_dir())
        except Exception as e:
            out["state_dir"] = f"{CANNOT_DETERMINE}: {e}"
    else:
        out["state_dir"] = NOT_SUPPORTED

    try:
        auth = settings.load_auth_config()
    except Exception as e:
        out["auth_config_loadable"] = False
        out.setdefault("errors", []).append(f"load_auth_config: {e}")
        for k in ("projects", "wrappers", "terminal_commands", "agent_commands"):
            out[k] = CANNOT_DETERMINE
        return
    out["auth_config_loadable"] = True

    # CANNOT_DETERMINE
    # could not be read
    try:
        from src.core.project_authority import MODE_DB, resolve_projects

        view = resolve_projects(settings.get_state_dir())
        if view.mode != MODE_DB:
            out["projects"] = CANNOT_DETERMINE
            out.setdefault("errors", []).append(f"projects: {view.mode}")
        else:
            out["projects"] = [
                {
                    "name": p["name"],
                    "path": p["path"],
                    "description": p["description"],
                }
                for p in view.projects
            ]
    except Exception as e:
        out["projects"] = CANNOT_DETERMINE
        out.setdefault("errors", []).append(f"projects: {e}")

    agents_obj = getattr(auth, "agents", None)
    if agents_obj is None or not hasattr(agents_obj, "wrappers"):
        out["wrappers"] = NOT_SUPPORTED
    else:
        try:
            out["wrappers"] = [
                {
                    "id": getattr(w, "id", None),
                    "label": getattr(w, "label", None),
                    "family": getattr(w, "family", NOT_SUPPORTED),
                }
                for w in (agents_obj.wrappers or [])
            ]
        except Exception as e:
            out["wrappers"] = CANNOT_DETERMINE
            out.setdefault("errors", []).append(f"wrappers: {e}")

    if not hasattr(auth, "terminal_commands"):
        out["terminal_commands"] = NOT_SUPPORTED
    else:
        try:
            out["terminal_commands"] = [
                {"id": getattr(c, "id", None), "label": getattr(c, "label", None),
                 "command": getattr(c, "command", None)}
                for c in (auth.terminal_commands or [])
            ]
        except Exception as e:
            out["terminal_commands"] = CANNOT_DETERMINE
            out.setdefault("errors", []).append(f"terminal_commands: {e}")

    # launch command
    cmds = {}
    getter = getattr(settings, "get_agent_command", None)
    if getter is None:
        out["agent_commands"] = NOT_SUPPORTED
    else:
        for family in ("claude", "codex", "hermes", "openclaw"):
            try:
                cmds[family] = getter(family)
            except TypeError:
                try:
                    cmds[family] = getter(agent_type=family)
                except Exception as e:
                    cmds[family] = f"{CANNOT_DETERMINE}: {e}"
            except Exception as e:
                cmds[family] = f"{CANNOT_DETERMINE}: {e}"
        out["agent_commands"] = cmds


def probe_db(state_dir: Path, out: dict) -> None:
    try:
        from src.core.db import db_path_for  # noqa: PLC0415

        db_path = db_path_for(state_dir)
    except Exception:
        db_path = state_dir / "carnivore.db"
    out["db_path"] = str(db_path)
    out["db_exists"] = db_path.exists()
    if not db_path.exists():
        out["db_tables"] = NOT_SUPPORTED
        out["db_row_counts"] = NOT_SUPPORTED
        out["db_schema_version"] = NOT_SUPPORTED
        return
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        out["db_tables"] = CANNOT_DETERMINE
        out["db_row_counts"] = CANNOT_DETERMINE
        out["db_schema_version"] = CANNOT_DETERMINE
        out.setdefault("errors", []).append(f"db_open: {e}")
        return
    try:
        tables = sorted(
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        )
        out["db_tables"] = tables
        counts = {}
        for t in tables:
            if t.startswith("sqlite_"):
                continue
            try:
                counts[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.Error as e:
                counts[t] = f"{CANNOT_DETERMINE}: {e}"
        out["db_row_counts"] = counts
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            out["db_schema_version"] = row[0] if row else "ABSENT"
        except sqlite3.Error:
            out["db_schema_version"] = CANNOT_DETERMINE
        try:
            out["db_projects"] = sorted(
                r[0] for r in conn.execute("SELECT name FROM projects")
            )
        except sqlite3.Error as e:
            out["db_projects"] = f"{CANNOT_DETERMINE}: {e}"
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install-dir", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--state-dir", default="")
    args = ap.parse_args()

    install = Path(args.install_dir).resolve()
    sys.path.insert(0, str(install))
    os.chdir(install)

    out: dict = {"label": args.label, "install_dir": str(install)}
    config_path = Path(
        os.environ.get("AUTH_CONFIG_FILE", str(install / "config.json"))
    ).expanduser()
    if not config_path.is_absolute():
        config_path = (install / config_path).resolve()
    probe_config_file(config_path, out)
    probe_settings(out)
    if args.state_dir:
        probe_db(Path(args.state_dir).expanduser(), out)
    else:
        out["db_exists"] = NOT_SUPPORTED

    json.dump(out, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
