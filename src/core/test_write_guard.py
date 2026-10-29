
from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = [
    "OutsideTempWriteError",
    "TEST_MODE_ENV_VAR",
    "running_under_test",
    "temp_roots",
    "assert_test_write_allowed",
]

TEST_MODE_ENV_VAR: str = "CLOUDE_TEST_MODE"


class OutsideTempWriteError(RuntimeError):
    pass


def running_under_test() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return bool(os.environ.get(TEST_MODE_ENV_VAR))


def temp_roots() -> list[Path]:
    roots: list[Path] = []
    candidates: list[str] = []

    try:
        candidates.append(tempfile.gettempdir())
    except OSError:
        pass

    env_tmp = os.environ.get("TMPDIR")
    if env_tmp:
        candidates.append(env_tmp)

    for raw in candidates:
        try:
            resolved = Path(raw).resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def assert_test_write_allowed(path: Path) -> None:
    if not running_under_test():
        return

    roots = temp_roots()
    if not roots:
        raise OutsideTempWriteError(
            "Refusing a write during a test run: could not determine any "
            f"temp root, so the destination {path} cannot be shown safe. "
            "An undetermined destination is refused, never allowed."
        )

    try:
        resolved = path.resolve()
    except OSError as exc:
        raise OutsideTempWriteError(
            f"Refusing a write during a test run: {path} could not be "
            f"resolved ({exc}), so it cannot be shown safe."
        ) from exc

    for root in roots:
        if _is_under(resolved, root):
            return

    raise OutsideTempWriteError(
        f"Refusing a write during a test run to {resolved}, which is "
        "outside every temp root "
        f"({', '.join(str(r) for r in roots)}). A test must never modify "
        "real machine state. Pass an explicit path under pytest's "
        "tmp_path, or set the relevant redirect env var in "
        "tests/conftest.py."
    )
