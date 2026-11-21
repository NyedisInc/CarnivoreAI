from pathlib import Path

from src.core.pack.jobs import policy
from src.core.pack.jobs.store import JobStore


def test_delegate_marks_names_marked_projects_and_counts_copies(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "state")
    policy.set_auto(store, "uid-on", True)
    store.auto_replica_add("uid-off", "iid-a")
    store.auto_replica_add("uid-off", "iid-b")
    marked, made = store.delegate_marks()
    assert marked == {"uid-on"}
    assert made == {"uid-off": 2}
    assert "uid-off" not in marked and "uid-none" not in marked
