
import os
import subprocess

from src.core.attention import record_identity as ri

START = "Thu Oct 15 15:52:02 2026"


class Clock:

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make(answers, clock=None):
    calls = []

    def lstarts(pids):
        pids = sorted(pids)
        calls.append(pids)
        return answers if answers is None else {p: s for p, s in answers.items() if p in pids}

    return ri.RecordIdentity(lstarts=lstarts, clock=clock or Clock()), calls


def test_a_matching_lstart_is_proven_and_a_recycled_pid_is_not():
    identity, _ = make({1: START, 2: "Thu Oct 15 09:00:00 2026"})
    identity.refresh([(1, START), (2, START)])
    assert identity.proven(1, START) is True
    assert identity.proven(2, START) is False


def test_a_failed_ps_or_a_missing_procstart_is_unmeasured_never_proven():
    identity, _ = make(None)
    identity.refresh([(1, START)])
    assert identity.proven(1, START) is None
    assert identity.proven(1, None) is None


def test_proofs_are_batched_and_revalidated_every_thirty_seconds():
    clock = Clock()
    identity, calls = make({1: START, 2: START, 3: START}, clock)
    identity.refresh([(1, START), (2, START)])
    identity.refresh([(1, START), (2, START)])
    identity.refresh([(1, START), (2, START), (3, START)])
    clock.now += ri.REVALIDATE_SECONDS
    identity.refresh([(1, START), (2, START), (3, START)])
    assert calls == [[1, 2], [3], [1, 2, 3]]


def test_the_real_ps_reader_proves_this_process():
    pid = os.getpid()
    found = ri.read_lstarts([pid])
    assert found is not None and pid in found
    ours = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                          text=True, check=True).stdout.strip()
    assert " ".join(found[pid].split()) == " ".join(ours.split())
