
from __future__ import annotations

import random
import subprocess
from pathlib import Path
from typing import Dict

import pytest

from src.core.message_model_secrets import VENDOR_DETECTORS
from tests.redaction_fuzz import (
    LEAK_RUN,
    Case,
    check_case,
    generate,
    make_case,
    negative_corpus,
    overstar,
    run_case,
    with_history,
)
from src.core.stream_redactor import DEFAULT_TAIL_BYTES

SEED = 20260922
PER_DETECTOR = 150
PER_DETECTOR_WITH_HISTORY = 30
REPO = Path(__file__).resolve().parent.parent


def test_every_generated_layout_leaves_no_readable_run_of_a_key() -> None:
    cases = generate(SEED, PER_DETECTOR)
    assert {case.detector for case in cases} == set(VENDOR_DETECTORS)
    assert all(case.secret_len >= LEAK_RUN for case in cases)
    failures = []
    for case in cases:
        problems = check_case(case, run_case(case))
        if problems:
            failures.append((case.detector, case.shape, problems))
    assert not failures, f"{len(failures)} of {len(cases)} cases leaked: {failures[:5]}"


def test_every_layout_behind_earlier_output_leaves_no_readable_run() -> None:
    rng = random.Random(SEED + 3)
    cases = [with_history(rng, make_case(rng, detector), DEFAULT_TAIL_BYTES)
             for _ in range(PER_DETECTOR_WITH_HISTORY)
             for detector in VENDOR_DETECTORS]
    assert all(next(i for i, cell in enumerate(case.cells) if cell[1] >= 0)
               > DEFAULT_TAIL_BYTES for case in cases)
    failures = []
    for case in cases:
        problems = check_case(case, run_case(case))
        if problems:
            failures.append((case.detector, case.shape, problems))
    assert not failures, f"{len(failures)} of {len(cases)} cases leaked: {failures[:5]}"


def test_the_check_goes_red_on_an_unredacted_stream() -> None:
    rng = random.Random(SEED)
    for detector in VENDOR_DETECTORS:
        case = make_case(rng, detector)
        assert check_case(case, case.stream), detector


def test_the_check_goes_red_on_a_length_or_escape_change() -> None:
    rng = random.Random(SEED + 1)
    case: Case = make_case(rng, VENDOR_DETECTORS[0])
    out = run_case(case)
    assert not check_case(case, out)
    assert check_case(case, out[:-1])
    escapes = [i for i, cell in enumerate(case.cells) if cell[2]]
    assert escapes
    broken = list(out)
    broken[escapes[0]] = "*"
    assert check_case(case, "".join(broken))


def _sources() -> Dict[str, str]:
    listed = subprocess.run(
        ["git", "ls-files", "src", "docs", "relay", "client/js"],
        capture_output=True, text=True, cwd=REPO, check=True,
    ).stdout.split()
    sources: Dict[str, str] = {}
    for path in listed:
        if path.endswith((".py", ".md", ".js")):
            try:
                sources[path] = (REPO / path).read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
    return sources


def test_over_starring_of_key_free_output_stays_bounded() -> None:
    sources = _sources()
    assert len(sources) > 100
    streams = negative_corpus(random.Random(SEED), sources)
    starred = total = whole = 0
    for stream in streams:
        stars, chars, rows = overstar(stream)
        starred += stars
        total += chars
        whole += rows
    assert total > 1_000_000
    assert whole == 0
    assert starred / total < 0.00015, f"over-starring rate {starred / total:.6%}"


def test_a_source_keeps_its_wrap_layout_when_another_file_is_added() -> None:
    base = {"a.py": ("x" * 1500 + "\n") * 5, "z.py": ("y" * 1500 + "\n") * 5}
    grown = {"a.py": base["a.py"], "b.py": ("w" * 1500 + "\n") * 5, "z.py": base["z.py"]}
    before = negative_corpus(random.Random(SEED), base)
    after = negative_corpus(random.Random(SEED), grown)
    assert before[1] == after[2]


def test_over_starring_check_goes_red_on_a_starred_row() -> None:
    row = "ordinary text on one row\r\n"
    assert overstar(row) == (0, len(row), 0)
    key = "gh" + "p_" + "Q7W2E9R4T6Y1U8I3O5P0ZXCVBNMLKJHGFDSA"
    assert overstar(key + "\r\n")[2] == 1


def test_a_sample_renders_with_no_readable_run_in_xterm() -> None:
    sync_api = pytest.importorskip(
        "playwright.sync_api",
        reason="playwright is not installed, so nothing was rendered",
    )
    xterm = REPO / "client" / "vendor" / "xterm" / "xterm.js"
    assert xterm.is_file()
    rng = random.Random(SEED + 2)
    cases = [make_case(rng, d) for _ in range(3) for d in VENDOR_DETECTORS]
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-mock-keychain"])
        page = browser.new_page()
        page.set_content('<div id="t" style="width:2400px;height:900px"></div>')
        page.add_script_tag(path=str(xterm))

        def screen(data: str) -> str:
            return page.evaluate(
                """(text) => new Promise(done => {
                    const host = document.getElementById('t');
                    host.innerHTML = '';
                    const term = new Terminal({cols: 260, rows: 60, scrollback: 400});
                    term.open(host);
                    term.write(text, () => {
                        const buf = term.buffer.active, rows = [];
                        for (let i = 0; i < buf.length; i++) {
                            rows.push(buf.getLine(i).translateToString(true));
                        }
                        term.dispose();
                        done(rows.join('\\n'));
                    });
                })""",
                data,
            )

        red = screen(cases[0].stream)
        secret0 = "".join(c for c, tag, _ in cases[0].cells if tag >= 0)
        assert _readable_run(red, secret0) >= LEAK_RUN
        for case in cases:
            secret = "".join(c for c, tag, _ in case.cells if tag >= 0)
            assert _readable_run(screen(run_case(case)), secret) < LEAK_RUN, case.shape
        browser.close()


def _readable_run(screen: str, secret: str) -> int:
    keep = "".join(
        c for c in screen if c.isalnum() or c in "+/=_-"
    )
    best = 0
    for start in range(len(secret)):
        low = best + 1
        while start + low <= len(secret) and secret[start:start + low] in keep:
            best = low
            low += 1
    return best
