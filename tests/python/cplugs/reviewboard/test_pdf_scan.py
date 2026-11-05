
from __future__ import annotations

import asyncio
import base64
import inspect
import os
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path

import pytest

from src.cplugs.reviewboard import attachment_pdf, pdf_actions, pdf_doc, pdf_lexer, pdf_scan, pdf_streams
from src.cplugs.reviewboard.errors import ActiveContentFile, ScannerBusy, UnscannableFile
from src.cplugs.reviewboard.pdf_streams import PdfUnreadable
from src.cplugs.sdk.file_secrets import CpuDeadline, Deadline, ScanTimeout
from tests.python.cplugs.reviewboard.pdf_fixtures import BASE, CLEAN_CAT, HIDDEN, T, classic, objstm, stm
from tests.python.cplugs.reviewboard.test_attachment_secrets import post
from tests.python.cplugs.reviewboard.test_attachments import MD, PDF, board, client, env, sidecar, tree  # noqa: F401


def scan(data: bytes) -> frozenset:
    return pdf_scan.features(data, Deadline())


def reason(data: bytes) -> str:
    with pytest.raises(PdfUnreadable) as exc:
        scan(data)
    return exc.value.reason


def doc(obj: bytes) -> bytes:
    return classic({**BASE, 4: b"<< >>", 6: obj, 1: b"<< /Type /Catalog /Pages 2 0 R /Names 4 0 R >>"})


def test_a_plain_pdf_and_ordinary_ones_pass():
    assert scan(PDF) == frozenset()
    assert scan(doc(b"<< /Type /Catalog /JSONData 1 >>")) == frozenset()
    assert scan(classic({1: CLEAN_CAT, 2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", 3: b"<< /Type /Page /Parent 2 0 R /Annots [4 0 R] >>",
                         4: b"<< /Subtype /Link /A << /S /URI /URI (http://a.example) >> >>"})) == frozenset()


@pytest.mark.parametrize("obj,feature", [
    (b"<< /Type /Action /S /JavaScript /JS (app.alert(1)) >>", "JavaScript"),
    (b"<< /Type /Action /S /J#61vaScr#69pt >>", "JavaScript"),
    (b"<< /OpenAction << /S /Launch /F (cmd.exe) >> >>", "Launch"),
    (b"<< /Type /EmbeddedFile /Subtype /application#2Fpdf >>", "EmbeddedFile"),
    (b"<< /Names << /EmbeddedFiles 4 0 R >> >>", "EmbeddedFile"),
    (b"<< /Subtype /RichMedia >>", "RichMedia"),
    (b"<< /AcroForm << /XFA 5 0 R >> >>", "XFA"),
    (b"<< /AA << /E << /S /SubmitForm /F (http://x) >> >> >>", "SubmitForm"),
    (b"<< /S /ImportData >>", "ImportData"),
    (b"<< /Type /Action /JS (x) >>", "JavaScript"),
])
def test_active_content_in_a_plain_object_is_found(obj, feature):
    assert feature in scan(doc(obj))


@pytest.mark.parametrize("catalog,label", [
    (b"<< /Type /Catalog /OpenAction << /S /URI /URI (http://x.example) >> >>", "OpenURI"),
    (b"<< /Type /Catalog /OpenAction << /S /GoToR /F (other.pdf) /D [0 /Fit] >> >>", "OpenGoToR"),
    (b"<< /Type /Catalog /OpenAction << /S /GoToE /T << /R /C >> /D [0 /Fit] >> >>", "OpenGoToE"),
    (b"<< /Type /Catalog /AA << /WC << /S /URI /URI (http://x.example) >> >> >>", "OpenURI"),
    (b"<< /Type /Catalog /OpenAction << /S /GoTo /D [3 0 R /Fit] /Next << /S /URI /URI (http://x) >> >> >>", "OpenURI"),
    (b"<< /Type /Catalog /OpenAction 4 0 R >>", "OpenURI"),
    (b"<< /Type /Catalog /OpenAction << /URI (http://x.example) >> >>", "OpenURI"),
])
def test_an_outside_action_that_fires_on_open_is_found(catalog, label):
    objs = {1: catalog, 2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", 3: b"<< /Type /Page /Parent 2 0 R >>", 4: b"<< /S /URI /URI (http://x) >>"}
    assert scan(classic(objs)) == {label}


def test_an_action_inside_an_object_stream_is_found_on_open_too():
    inner = {**HIDDEN, 6: b"<< /S /URI /URI (http://x) >>"}
    inner.pop(4), inner.pop(5)
    assert scan(objstm(T, inner=inner)) == {"OpenURI"}


def test_an_unreadable_pdf_is_refused_as_unscannable_never_passed():
    enc = classic(BASE).replace(b"/Root 1 0 R", b"/Root 1 0 R /Encrypt 9 0 R")
    cases = {
        "encrypted": enc,
        "truncated": classic(BASE)[:-12],
        "truncated_no_endstream": b"%PDF-1.7\n1 0 obj\n<< /Length 5 >>\nstream\nabcde",
        "unsupported_filter": objstm(b"/Type /ObjStm /Filter /LZWDecode", lambda d: d),
        "corrupt_data": objstm(T, lambda d: b"not flate at all"),
        "ambiguous_stream": classic({**BASE, 7: stm(b"", b"abc").replace(b"/Length 3", b"/Length 1")}),
        "malformed_pdf": classic({**BASE, 6: b"<< /S ) >>"}),
    }
    for expected, data in cases.items():
        assert reason(data) == expected.split("_no_")[0], expected
    assert reason(doc(b"[" * 70 + b"]" * 70)) == "malformed_pdf"
    assert reason(doc(b"<< /X " + b"9" * 6000 + b" >>")) == "malformed_pdf"
    late_length = classic({**BASE, 4: stm(b"", b"abcdefghij").replace(b"/Length 10", b"/Length 5 0 R"), 5: b"3"})
    assert reason(late_length) == "ambiguous_stream"
    assert reason(objstm(T + b" /DecodeParms << /Predictor 12 >>")) == "unsupported_filter"
    assert reason(objstm(T + b" /Filter /FlateDecode")) == "ambiguous_stream"


def test_a_flate_bomb_is_refused_before_it_is_held(monkeypatch):
    bomb = zlib.compress(b"\0" * (80 * 1024 * 1024), 9)
    assert len(bomb) < 100 * 1024 and reason(objstm(T, lambda d: bomb)) == "too_much_data"
    padded = {4: b"<< /A [" + b"1 " * 30000 + b"] >>"}
    monkeypatch.setattr(pdf_streams, "MIN_TOTAL_BYTES", 1000)
    assert reason(objstm(T, inner=padded)) == "too_much_data"
    monkeypatch.undo()
    assert scan(objstm(T, inner=padded)) == frozenset()
    monkeypatch.setattr(pdf_streams, "MAX_STREAM_BYTES", 1000)
    assert reason(objstm(T, inner=padded)) == "too_much_data"


def test_a_highly_compressed_real_object_stream_is_not_a_bomb():
    filler = {4: b"<< /Pad [" + b"0 " * 60000 + b"] >>"}
    assert len(zlib.compress(filler[4])) * 100 < len(filler[4]) and scan(objstm(T, inner=filler)) == frozenset()


def test_an_encrypted_file_is_refused_as_encrypted_before_its_ciphertext_is_read():
    data = objstm(b"/Type /ObjStm /Filter /FlateDecode", lambda d: b"\xb5o$\x95not flate").replace(b"/Root 1 0 R", b"/Root 1 0 R /Encrypt 9 0 R")
    assert reason(data) == "encrypted"


def test_every_pass_is_bounded_by_the_deadline_and_the_token_budget(monkeypatch):
    monkeypatch.setattr(attachment_pdf, "scan_deadline", lambda: Deadline(-1))
    with pytest.raises(UnscannableFile) as exc:
        attachment_pdf.check_pdfs([("a.pdf", classic(BASE))], slug="b")
    assert exc.value.extra["files"] == [{"file": "a.pdf", "reason": "scan_timeout"}]
    monkeypatch.undo()
    made, built = [], attachment_pdf.scan_deadline
    monkeypatch.setattr(attachment_pdf, "scan_deadline", lambda: made.append(1) or Deadline(1000))
    attachment_pdf.check_pdfs([("a.pdf", PDF)], slug="b")
    assert made == [1] and attachment_pdf.SCAN_CPU_SECONDS == 20.0 and isinstance(built(), CpuDeadline)
    monkeypatch.undo()
    with pytest.raises(ScanTimeout):
        pdf_scan.features(classic(BASE), Deadline(-1))
    monkeypatch.setattr(pdf_lexer, "MIN_TOKENS", 500)
    flood = {4: b"<< /A [" + b"1 " * 5000 + b"] >>"}
    assert reason(objstm(T, inner=flood)) == "too_much_data"
    assert pdf_lexer.Meter.for_input(Deadline(), 10_000_000).tokens_left == 10_000_000 and pdf_streams.Budget.for_input(Deadline(), 10_000_000).raw_left == 80_000_000


def test_a_name_hidden_only_in_text_the_reader_view_skipped_is_a_disagreement():
    assert reason(doc(b"<< /Note (see /JavaScript) >>")) == "parser_disagreement"


def test_an_active_name_in_an_object_stream_outside_its_listed_objects_is_a_disagreement():
    assert reason(objstm(T, inner={4: b"<< >>\n/JS"})) == "parser_disagreement"


def test_the_attach_refuses_with_names_only_and_scans_a_pdf_under_any_name(monkeypatch):
    bad = doc(b"<< /S /JavaScript /JS (SECRETSCRIPT) >>")
    with pytest.raises(ActiveContentFile) as exc:
        attachment_pdf.check_pdfs([("s.pdf", bad), ("notes.md", MD)], slug="b")
    assert exc.value.extra["files"] == [{"file": "s.pdf", "features": ["JavaScript"]}] and "SECRETSCRIPT" not in str(exc.value)
    with pytest.raises(ActiveContentFile):
        attachment_pdf.check_pdfs([("renamed.txt", bad)], slug="b")
    with pytest.raises(UnscannableFile):
        attachment_pdf.check_pdfs([("t.dat", classic(BASE)[:-8])], slug="b")
    attachment_pdf.check_pdfs([("notes.md", MD), ("fine.pdf", PDF)], slug="b")
    assert not hasattr(attachment_pdf, "POLICY") and not hasattr(attachment_pdf, "FLAG")


def test_the_route_refuses_the_whole_attach_and_stores_nothing(env, client, board):
    before = tree(env.root)
    r = post(client, board, ("ok.md", MD), ("evil.pdf", objstm(T)))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "reviewboard_file_active_content" and detail["files"] == [{"file": "evil.pdf", "features": ["JavaScript"]}]
    r = post(client, board, ("enc.pdf", classic(BASE).replace(b"/Root 1 0 R", b"/Root 1 0 R /Encrypt 9 0 R")))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reviewboard_file_unscannable"
    assert tree(env.root) == before and "attachments" not in sidecar(env, board["slug"]).get("ext", {})
    assert post(client, board, ("fine.pdf", PDF)).status_code == 200


def test_the_action_walk_is_bounded(monkeypatch):
    objs = {1: b"<< /Type /Catalog /OpenAction 4 0 R >>", 2: b"<< >>", 3: b"<< >>"}
    objs.update({4 + i: b"<< /S /GoTo /Next %d 0 R >>" % (5 + i) for i in range(6)})
    monkeypatch.setattr(pdf_actions, "MAX_VISITS", 3)
    assert reason(classic(objs)) == "too_much_data"


class _Spy:

    def __init__(self) -> None:
        self.callers = set()

    def check(self) -> None:
        self.callers.add(inspect.stack()[1].function)


def test_every_pass_looks_at_the_clock(monkeypatch):
    monkeypatch.setattr(pdf_lexer, "CHECK_EVERY", 1)
    monkeypatch.setattr(pdf_actions, "_TICK", 1)
    monkeypatch.setattr(pdf_scan, "_TICK", 1)
    monkeypatch.setattr(pdf_doc, "_TICK", 1)
    spy = _Spy()
    pdf_scan.features(objstm(T, inner={1: CLEAN_CAT, 2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", 3: b"<< /Type /Page >>"}), spy)
    assert {"_spend", "parse", "decode", "_inflate", "_raw_names", "_roots", "open_time_features", "find_headers"} <= spy.callers, spy.callers


def test_the_decoders_refuse_bad_ascii_data_and_an_expired_clock():
    budget = pdf_streams.Budget(Deadline())
    for name, body in (("ASCIIHexDecode", b"zz>"), ("ASCII85Decode", b"vvvvv~>")):
        with pytest.raises(PdfUnreadable) as exc:
            pdf_streams.decode(body, [name], budget)
        assert exc.value.reason == "corrupt_data"
    assert pdf_streams.decode(b"4a4B>", ["AHx"], budget) == b"JK" and pdf_streams.decode(base64.a85encode(b"hi") + b"~>", ["A85"], budget) == b"hi"
    with pytest.raises(PdfUnreadable) as many:
        pdf_streams.decode(b"x", ["Fl"] * 5, budget)
    assert many.value.reason == "unsupported_filter"
    dead = pdf_streams.Budget(Deadline(-1))
    for call in (lambda: pdf_streams.decode(zlib.compress(b"a"), ["FlateDecode"], dead), lambda: pdf_streams._inflate(zlib.compress(b"a"), dead)):
        with pytest.raises(ScanTimeout):
            call()
    shared = pdf_streams.Budget(Deadline())
    shared.raw_left = 3000
    assert pdf_streams.decode(zlib.compress(b"a" * 2000), ["Fl"], shared) == b"a" * 2000
    with pytest.raises(PdfUnreadable) as total:
        pdf_streams.decode(zlib.compress(b"a" * 2000), ["Fl"], shared)
    assert total.value.reason == "too_much_data"
    assert set(pdf_streams.decode(zlib.compress(b"a" * 1000)[:-6], ["Fl"], budget)) <= {97}
    with pytest.raises(PdfUnreadable) as junk:
        pdf_streams.decode(b"not flate data", ["Fl"], budget)
    assert junk.value.reason == "corrupt_data"



def test_a_header_a_reader_accepts_is_found_with_nul_white_space_and_a_repeated_key_is_refused():
    hidden = classic({**BASE, 7: stm(b"", b"4\x000\x00obj\n<< /S /JavaScript >>\nendobj")})
    assert reason(hidden) == "hidden_object"
    for obj in (b"<< /Type /Catalog /Pages 2 0 R /OpenAction [3 0 R /Fit] /OpenAction [3 0 R /XYZ 0 0 0] >>",
                b"<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /GoTo /D [3 0 R /Fit] /D [3 0 R /XYZ 0 0 0] >> >>"):
        assert reason(classic({1: obj, 2: BASE[2], 3: BASE[3]})) == "ambiguous_object"


def test_only_one_pdf_scan_runs_at_a_time_and_a_late_upload_is_refused_as_busy(monkeypatch):
    running, peak, lock = [0], [0], threading.Lock()

    def slow_features(data, deadline):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        return frozenset()

    monkeypatch.setattr(pdf_scan, "features", slow_features)

    async def together() -> None:
        await asyncio.gather(*[attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b") for _ in range(4)])

    asyncio.run(together())
    assert peak[0] == 1
    loops = [threading.Thread(target=lambda: asyncio.run(together())) for _ in range(3)]
    [t.start() for t in loops], [t.join() for t in loops]
    assert peak[0] == 1

    async def busy() -> None:
        monkeypatch.setattr(attachment_pdf, "SCAN_WAIT_SECONDS", 0.1)
        slot = attachment_pdf._slot()
        await slot.acquire()
        try:
            with pytest.raises(ScannerBusy) as late:
                await attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b")
            assert late.value.status == 503 and late.value.code == "reviewboard_scanner_busy"
            await attachment_pdf.refuse_active_content([("notes.md", MD)], slug="b")
        finally:
            slot.release()
        await attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b")

    asyncio.run(busy())


def test_the_slot_is_released_on_a_refusal_an_error_and_a_cancel(monkeypatch):
    async def go() -> None:
        for bad in (doc(b"<< /S /JavaScript /JS (x) >>"), None, "cancel"):
            if bad is None:
                monkeypatch.setattr(pdf_scan, "features", lambda d, dl: (_ for _ in ()).throw(RuntimeError("boom")))
                with pytest.raises(RuntimeError):
                    await attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b")
                monkeypatch.undo()
            elif bad == "cancel":
                monkeypatch.setattr(pdf_scan, "features", lambda d, dl: (time.sleep(0.2), frozenset())[1])
                task = asyncio.create_task(attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b"))
                await asyncio.sleep(0.05)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                monkeypatch.undo()
            else:
                with pytest.raises(ActiveContentFile):
                    await attachment_pdf.refuse_active_content([("evil.pdf", bad)], slug="b")
            await asyncio.wait_for(attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b"), 5)

    asyncio.run(go())


def test_queued_pdf_uploads_do_not_starve_the_default_thread_pool(monkeypatch):
    monkeypatch.setattr(pdf_scan, "features", lambda data, deadline: (time.sleep(0.1), frozenset())[1])

    async def main() -> float:
        uploads = [asyncio.create_task(attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b")) for _ in range(40)]
        await asyncio.sleep(0.3)
        started = time.monotonic()
        await asyncio.to_thread(lambda: None)
        waited = time.monotonic() - started
        await asyncio.gather(*uploads)
        return waited

    assert asyncio.run(main()) < 0.5


def test_a_fast_upload_queued_behind_a_running_scan_is_told_busy_not_blamed(monkeypatch):
    busy = threading.Event()
    monkeypatch.setattr(pdf_scan, "features", lambda data, deadline: (busy.wait(5), frozenset())[1] if data.endswith(b"%slow") else frozenset())
    monkeypatch.setattr(attachment_pdf, "SCAN_WAIT_SECONDS", 0.3)

    async def go() -> None:
        slow = asyncio.create_task(attachment_pdf.refuse_active_content([("slow.pdf", PDF + b"%slow")], slug="s"))
        await asyncio.sleep(0.1)
        slow.cancel()
        with pytest.raises(asyncio.CancelledError):
            await slow
        with pytest.raises(ScannerBusy):
            await attachment_pdf.refuse_active_content([("fast.pdf", PDF)], slug="s")
        busy.set()
        for _ in range(200):
            if attachment_pdf._WORKER.started is None and attachment_pdf._WORKER._jobs.empty():
                return
            await asyncio.sleep(0.05)

    asyncio.run(go())


def test_the_scan_clock_counts_thread_cpu_time_with_a_wall_backstop(monkeypatch):
    from src.core.secret_scanning import deadline as dl
    cpu, wall = [0.0], [0.0]
    monkeypatch.setattr(dl, "_thread_now", lambda: cpu[0])
    monkeypatch.setattr(dl, "_now", lambda: wall[0])
    loaded = dl.CpuDeadline(cpu_seconds=10, wall_seconds=100)
    cpu[0], wall[0] = 5, 90
    loaded.check()
    cpu[0] = 11
    with pytest.raises(dl.ScanTimeout):
        loaded.check()
    cpu[0], wall[0] = 0, 0
    blocked = dl.CpuDeadline(cpu_seconds=10, wall_seconds=100)
    cpu[0], wall[0] = 1, 101
    with pytest.raises(dl.ScanTimeout):
        blocked.check()


def test_a_scan_stuck_past_its_deadline_is_refused_frees_the_slot_and_fails_the_next_upload_fast(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(pdf_scan, "features", lambda data, deadline: (release.wait(10), frozenset())[1])
    monkeypatch.setattr(attachment_pdf, "SCAN_WALL_BACKSTOP_SECONDS", 0.2)
    monkeypatch.setattr(attachment_pdf, "SCAN_WAIT_SECONDS", 5.0)

    async def go() -> float:
        started = time.monotonic()
        with pytest.raises(UnscannableFile) as overrun:
            await attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b")
        assert overrun.value.extra["files"] == [{"file": "a.pdf", "reason": "scan_timeout"}] and time.monotonic() - started < 2
        await asyncio.sleep(0.15)
        quick = time.monotonic()
        with pytest.raises(ScannerBusy):
            await attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b")
        waited = time.monotonic() - quick
        release.set()
        for _ in range(100):
            if attachment_pdf._WORKER.started is None:
                break
            await asyncio.sleep(0.05)
        monkeypatch.setattr(pdf_scan, "features", lambda data, deadline: frozenset())
        await attachment_pdf.refuse_active_content([("a.pdf", PDF)], slug="b")
        return waited

    assert asyncio.run(go()) < 0.5


def test_a_running_scan_does_not_hold_the_interpreter_at_exit():
    repo = Path(__file__).resolve().parents[4]
    script = ("import sys, time; sys.path.insert(0, %r)\n"
              "from src.cplugs.reviewboard import attachment_pdf\n"
              "attachment_pdf._WORKER.submit(lambda: time.sleep(30)); attachment_pdf._WORKER.submit(lambda: None); time.sleep(0.3)\n"
              "print(time.time(), flush=True)\n") % str(repo)
    done = subprocess.run([sys.executable, "-c", script], cwd=repo, capture_output=True, text=True, timeout=60, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0, done.stderr[-500:]
    assert time.time() - float(done.stdout.split()[-1]) < 5


def test_the_worker_cancels_what_is_still_queued_at_exit():
    gate, ran = threading.Event(), []
    worker = attachment_pdf._ScanWorker()
    first = worker.submit(lambda: gate.wait(5))
    time.sleep(0.1)
    second = worker.submit(lambda: ran.append("second"))
    worker.cancel_pending()
    gate.set()
    first.done.result(timeout=5)
    assert second.done.cancelled() and ran == []
