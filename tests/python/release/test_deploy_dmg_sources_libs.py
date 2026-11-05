
from __future__ import annotations

from pathlib import Path

from tests.python.release.deploy_text import LIB_FILES, REPO_SCRIPT

LIB = REPO_SCRIPT.parent / "lib"


def missing_or_late(text: str) -> list[str]:
    first_use = min(text.index("on_exit() {"), text.index("trap on_exit EXIT"))
    bad = []
    for name in LIB_FILES:
        line = f'source "$(dirname "$0")/lib/{name}"'
        if line not in text or text.index(line) > first_use:
            bad.append(name)
    return bad


def test_every_lib_file_exists_and_is_sourced_before_on_exit() -> None:
    assert all((LIB / name).is_file() for name in LIB_FILES)
    assert missing_or_late(REPO_SCRIPT.read_text()) == []


def test_deleting_a_source_line_goes_red() -> None:
    text = REPO_SCRIPT.read_text().replace('source "$(dirname "$0")/lib/deploy-rollback.sh"\n', "", 1)
    assert missing_or_late(text) == ["deploy-rollback.sh"]


def test_sourcing_after_the_trap_goes_red() -> None:
    line = 'source "$(dirname "$0")/lib/deploy-backup.sh"\n'
    text = REPO_SCRIPT.read_text().replace(line, "", 1) + line
    assert missing_or_late(text) == ["deploy-backup.sh"]
