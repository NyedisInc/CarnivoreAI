import os
from pathlib import Path

_NESTED = "PYTEST_CURRENT_TEST" in os.environ
_DIR = "" if _NESTED else os.environ.get("CLOUDE_SUITE_STATE_DIR", "")
_FAILS = "" if _NESTED else os.environ.get("CLOUDE_SUITE_FAILURES_FILE", "")
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "main")


_RUNS_TESTS = [_WORKER != "main"]


def pytest_configure(config) -> None:
    if _DIR:
        Path(_DIR).mkdir(parents=True, exist_ok=True)
        (Path(_DIR) / f"{_WORKER}.pid").write_text(str(os.getpid()))
        if _WORKER == "main":
            _RUNS_TESTS[0] = not config.getoption("numprocesses", None)


def pytest_runtest_logstart(nodeid, location) -> None:
    if _DIR and _RUNS_TESTS[0]:
        (Path(_DIR) / f"{_WORKER}.cur").write_text(nodeid)


def pytest_runtest_logfinish(nodeid, location) -> None:
    if _DIR and _RUNS_TESTS[0]:
        (Path(_DIR) / f"{_WORKER}.cur").unlink(missing_ok=True)


def _record(kind: str, nodeid: str) -> None:
    if _FAILS and _WORKER == "main":
        with open(_FAILS, "a") as fh:
            fh.write(f"{kind} {nodeid}\n")


def pytest_runtest_logreport(report) -> None:
    if report.failed:
        _record("FAILED" if report.when == "call" else "ERROR", report.nodeid)


def pytest_collectreport(report) -> None:
    if report.failed:
        _record("ERROR", report.nodeid)
