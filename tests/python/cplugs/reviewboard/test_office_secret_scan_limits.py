
from __future__ import annotations

import itertools
import random
import time

import pytest

from src.core.secret_scanning import deadline as scan_deadline
from src.cplugs.reviewboard import office_text
from src.cplugs.reviewboard.errors import UnscannableFile
from tests.python.cplugs.reviewboard.test_office_secret_scan import BODY, FAKE, make_zip, xlsx
from tests.python.cplugs.reviewboard.test_office_secret_scan_evasions import HIT, _zip_bytes, hit

SHARED = xlsx(shared=f"<si><t>{FAKE}</t></si>")


def reason_of(name: str, data: bytes) -> str:
    with pytest.raises(UnscannableFile) as exc:
        hit(name, data)
    return exc.value.extra["files"][0]["reason"]



def test_a_tiny_zip_that_inflates_to_64_mib_is_refused_fast():
    bomb = make_zip({BODY: "<!---->" + "<a/>" * ((64 * 1024 * 1024 - 7) // 4)})
    assert len(bomb) < 200_000
    start = time.monotonic()
    assert reason_of("bomb.docx", bomb) == "compression_ratio"
    assert time.monotonic() - start < 3


def test_the_ratio_of_everything_read_is_judged_too():
    part = b"\x00" * (office_text.MIN_RATIO_BYTES - 1024)
    parts = {f"word/embeddings/o{n}.bin": part for n in range(12)}
    assert reason_of("many.docx", _zip_bytes({BODY: b"<w:document/>", **parts})) == "compression_ratio"


def test_the_raw_total_ceiling_is_100_mib():
    assert office_text.MAX_RAW_BYTES == 100 * 1024 * 1024


def test_the_deadline_trips_inside_the_scanner_loop(monkeypatch):
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(scan_deadline, "_now", lambda: float(next(ticks)))
    slow_path = "<!---->" + "<a/>" * 40_000
    assert reason_of("slow.docx", make_zip({BODY: slow_path})) == "scan_timeout"


def test_the_deadline_trips_between_parts(monkeypatch):
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(scan_deadline, "_now", lambda: float(next(ticks)))
    assert reason_of("many.docx", make_zip({f"word/p{n}.xml": "<w:t>x</w:t>" for n in range(10)})) == "scan_timeout"


def test_one_deadline_covers_every_file_of_an_attach(monkeypatch):
    from src.cplugs.reviewboard import attachment_secrets
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(scan_deadline, "_now", lambda: float(next(ticks)))
    files = [(f"{n}.docx", make_zip({f"word/p{n}.xml": "<w:t>x</w:t>" for n in range(2)})) for n in range(3)]
    with pytest.raises(UnscannableFile) as exc:
        attachment_secrets.findings(files)
    assert {f["reason"] for f in exc.value.extra["files"]} == {"scan_timeout"} and len(exc.value.extra["files"]) >= 2


def test_a_real_60000_row_sheet_still_passes():
    rng = random.Random(9)
    rows = "".join(f'<row r="{r}">' + "".join(f'<c r="{c}{r}" s="2"><v>{rng.random() * 1e5:.2f}</v></c>' for c in "ABCDEFGHIJ") + "</row>"
                    for r in range(1, 60_001))
    data = make_zip({"xl/worksheets/sheet1.xml": f"<worksheet><sheetData>{rows}</sheetData></worksheet>"})
    joined, separated = office_text.office_texts(data, scan_deadline.Deadline())
    assert separated == "" and len(joined) > 1_000_000
    assert hit("data.xlsx", data) == []


def test_a_doc_with_run_boundaries_gets_a_second_reading_and_a_plain_sheet_does_not():
    assert office_text.office_texts(make_zip({BODY: "<w:p><w:r><w:t>a</w:t></w:r><w:r><w:t>b</w:t></w:r></w:p>"}))[1] != ""
    assert office_text.office_texts(xlsx(sheet_cells="<c><v>1</v></c><c><v>2</v></c>"))[1] == ""



@pytest.mark.parametrize("name,payload", [
    ("word/main.dat", f"<w:document><w:p><w:t>{FAKE}</w:t></w:p></w:document>"),
    ("word/document", f"<w:document><w:p><w:t>{FAKE}</w:t></w:p></w:document>"),
    ("word/afchunk.txt", f"note {FAKE}"),
    ("word/afchunk.rtf", "{\\rtf1 " + FAKE + "}"),
    ("word/afchunk.mht", f"MIME-Version: 1.0\n\n<html>{FAKE}</html>"),
    ("customXml/item1.dat", f"<root>{FAKE}</root>"),
    ("word/media/font1.odttf", FAKE),
])
def test_a_part_is_read_by_its_content_not_its_name(name, payload):
    assert hit("a.docx", _zip_bytes({BODY: b"<w:document/>", name: payload.encode()})) == HIT


@pytest.mark.parametrize("name", [
    "word/embeddings/Macro_Worksheet.xlsm", "word/embeddings/Visio_Drawing.vsdx", "word/embeddings/package1.dat", "word/media/thing.xlsx", "word/odd/blob",
])
def test_a_zip_is_opened_wherever_it_sits_and_whatever_it_is_called(name):
    assert hit("a.docx", _zip_bytes({BODY: b"<w:document/>", name: SHARED})) == HIT


def test_a_workbook_two_levels_down_is_read():
    chart_workbook = xlsx(shared=f"<si><t>{FAKE}</t></si>")
    docx_with_chart = make_zip({BODY: "<w:document/>", "word/charts/chart1.xml": "<c:chartSpace/>", "word/embeddings/Microsoft_Excel_Worksheet.xlsx": chart_workbook})
    pptx = make_zip({"ppt/slides/slide1.xml": "<p:sld/>", "ppt/embeddings/Microsoft_Word_Document.docx": docx_with_chart})
    assert hit("a.pptx", pptx) == [("a.pptx", {"aws_access_key_id": 1})]


def test_images_and_fonts_are_skipped_by_their_first_bytes_not_their_names():
    png = b"\x89PNG\r\n\x1a\n" + random.Random(4).randbytes(4000)
    assert hit("a.docx", _zip_bytes({BODY: b"<w:document/>", "word/media/image1.xml": png})) == []
    assert hit("a.docx", _zip_bytes({BODY: b"<w:document/>", "word/media/image2.png": FAKE.encode()})) == HIT


def test_a_clean_real_shaped_docx_with_binary_parts_passes():
    rng = random.Random(6)
    parts = {BODY: b"<w:document><w:p><w:t>hello</w:t></w:p></w:document>", "word/embeddings/oleObject1.bin": rng.randbytes(300_000),
             "word/printerSettings/printerSettings1.bin": rng.randbytes(4096), "word/media/image1.png": b"\x89PNG\r\n\x1a\n" + rng.randbytes(200_000)}
    assert hit("clean.docx", _zip_bytes(parts)) == []


def test_an_ole_package_that_carries_a_zip_has_the_zip_read():
    ole = b"\xd0\xcf\x11\xe0" + b"\x00" * 200 + SHARED
    assert hit("a.docx", _zip_bytes({BODY: b"<w:document/>", "word/embeddings/oleObject1.bin": ole})) == HIT
    noise = b"\xd0\xcf\x11\xe0" + random.Random(2).randbytes(5000)
    assert hit("b.docx", _zip_bytes({BODY: b"<w:document/>", "word/embeddings/oleObject2.bin": noise})) == []
