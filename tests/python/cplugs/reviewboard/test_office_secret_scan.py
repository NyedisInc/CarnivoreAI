
from __future__ import annotations

import io
import random
import string
import time
import zipfile
from typing import Dict

import pytest
import structlog

from src.cplugs.reviewboard import attachment_secrets, office_text, office_xml
from src.cplugs.reviewboard.errors import SecretInFile, UnscannableFile
from tests.python.cplugs.reviewboard.test_attachment_secrets import post
from tests.python.cplugs.reviewboard.test_attachments import MD, board, client, env, sidecar, tree  # noqa: F401

FAKE = "AKIA" + "".join(random.Random(2661).choices(string.ascii_uppercase + string.digits, k=16))
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
BODY = "word/document.xml"


def make_zip(parts: Dict[str, str], *, method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return buf.getvalue()


def docx(*runs: str, part: str = BODY) -> bytes:
    body = "".join(f"<w:r><w:t>{r}</w:t></w:r>" for r in runs)
    return make_zip({part: f'<?xml version="1.0"?><w:document {W}><w:body><w:p>{body}</w:p></w:body></w:document>'})


def xlsx(shared: str = "", sheet_cells: str = "") -> bytes:
    return make_zip({"xl/sharedStrings.xml": f"<sst>{shared}</sst>",
                     "xl/worksheets/sheet1.xml": f"<worksheet><sheetData><row>{sheet_cells}</row></sheetData></worksheet>"})


def counts(name: str, data: bytes):
    return attachment_secrets.findings([(name, data)])


def test_a_key_in_the_docx_body_is_found():
    assert counts("a.docx", docx(f"deploy key {FAKE} here")) == [("a.docx", {"aws_access_key_id": 1})]


@pytest.mark.parametrize("part", ["word/header1.xml", "word/footer2.xml", "word/comments.xml", "word/footnotes.xml"])
def test_a_key_in_a_header_footer_comment_or_footnote_is_found(part):
    assert counts("a.docx", docx(FAKE, part=part)) == [("a.docx", {"aws_access_key_id": 1})]


def test_a_key_split_across_two_runs_is_rejoined():
    assert counts("a.docx", docx(FAKE[:9], FAKE[9:])) == [("a.docx", {"aws_access_key_id": 1})]


def test_a_key_hidden_as_numeric_entities_is_decoded():
    assert counts("a.docx", docx("".join(f"&#{ord(c)};" for c in FAKE))) == [("a.docx", {"aws_access_key_id": 1})]


def test_a_key_in_an_xlsx_shared_string_is_found():
    assert counts("a.xlsx", xlsx(shared=f'<si><r><t>{FAKE[:8]}</t></r><r><t>{FAKE[8:]}</t></r></si>')) == [("a.xlsx", {"aws_access_key_id": 1})]


def test_a_key_in_an_xlsx_inline_string_or_formula_is_found():
    inline = xlsx(sheet_cells=f'<c t="inlineStr"><is><t>{FAKE}</t></is></c>')
    formula = xlsx(sheet_cells=f'<c><f>CONCAT("{FAKE}")</f><v>1</v></c>')
    assert counts("a.xlsx", inline) == [("a.xlsx", {"aws_access_key_id": 1})]
    assert counts("b.xlsx", formula) == [("b.xlsx", {"aws_access_key_id": 1})]


def test_two_cells_never_fuse_into_a_false_key():
    assert counts("a.xlsx", xlsx(shared=f"<si><t>{FAKE[:8]}</t></si><si><t>{FAKE[8:]}</t></si>")) == []


def test_a_clean_docx_and_xlsx_pass():
    assert counts("a.docx", docx("quarterly notes", " and a sha " + "a" * 64)) == []
    assert counts("a.xlsx", xlsx(shared="<si><t>revenue</t></si>", sheet_cells='<c><v>42</v></c>')) == []



def test_a_zip_bomb_stops_at_the_cap_and_is_refused(monkeypatch):
    monkeypatch.setattr(office_text, "MAX_PART_BYTES", 1024 * 1024)
    bomb = make_zip({BODY: "<w:t>" + "A" * (office_text.MAX_PART_BYTES + 1000) + "</w:t>"})
    assert len(bomb) < 100_000
    start = time.monotonic()
    with pytest.raises(UnscannableFile) as exc:
        counts("bomb.docx", bomb)
    assert exc.value.extra["files"] == [{"file": "bomb.docx", "reason": "too_much_data"}]
    assert time.monotonic() - start < 5



def test_too_many_entries_is_refused():
    many = make_zip({f"media/i{n}.png": "" for n in range(office_text.MAX_MEMBERS + 1)})
    with pytest.raises(office_text.OfficeUnreadable) as exc:
        office_text.office_texts(many)
    assert exc.value.reason == office_text.REASON_TOO_MANY


def test_a_dtd_entity_bomb_is_refused_without_expanding():
    laughs = "".join(f'<!ENTITY l{n} "&l{n - 1};&l{n - 1};&l{n - 1};&l{n - 1};&l{n - 1};&l{n - 1};&l{n - 1};&l{n - 1};&l{n - 1};&l{n - 1};">' for n in range(1, 10))
    xml = f'<?xml version="1.0"?><!DOCTYPE w [<!ENTITY l0 "lol">{laughs}]><w:document {W}><w:p><w:t>&l9;</w:t></w:p></w:document>'
    start = time.monotonic()
    with pytest.raises(UnscannableFile) as exc:
        counts("lol.docx", make_zip({BODY: xml}))
    assert exc.value.extra["files"] == [{"file": "lol.docx", "reason": "dtd_in_part"}]
    assert time.monotonic() - start < 2



def test_a_corrupt_archive_is_refused_not_passed():
    with pytest.raises(UnscannableFile) as exc:
        counts("bad.docx", b"PK\x03\x04" + b"\x00" * 64)
    assert exc.value.extra["files"] == [{"file": "bad.docx", "reason": "corrupt_archive"}]


def test_a_bad_crc_is_refused_not_passed():
    data = bytearray(make_zip({BODY: "<w:t>hello world hello world</w:t>"}, method=zipfile.ZIP_STORED))
    data[data.index(b"hello")] ^= 0xFF
    with pytest.raises(UnscannableFile):
        counts("crc.docx", bytes(data))


def test_an_encrypted_member_is_refused():
    data = bytearray(make_zip({BODY: "<w:t>x</w:t>"}))
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        data[data.index(sig) + off] |= 0x1
    with pytest.raises(UnscannableFile) as exc:
        counts("enc.docx", bytes(data))
    assert exc.value.extra["files"][0]["reason"] == "encrypted"


@pytest.mark.parametrize("bad", ["../evil.xml", "/abs.xml", "a\\b.xml"])
def test_an_unsafe_entry_name_is_refused(bad):
    with pytest.raises(office_text.OfficeUnreadable) as exc:
        office_text.office_texts(make_zip({BODY: "<w:t>x</w:t>", bad: "x"}))
    assert exc.value.reason == office_text.REASON_BAD_NAME


def test_a_repeated_entry_name_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z, pytest.warns(UserWarning):
        z.writestr(BODY, "<w:t>one</w:t>")
        z.writestr(BODY, f"<w:t>{FAKE}</w:t>")
    with pytest.raises(office_text.OfficeUnreadable) as exc:
        office_text.office_texts(buf.getvalue())
    assert exc.value.reason == office_text.REASON_DUPLICATE


def test_a_utf16_part_is_read():
    xml = f"<w:p><w:t>{FAKE}</w:t></w:p>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(BODY, b"\xff\xfe" + xml.encode("utf-16-le"))
    assert counts("u.docx", buf.getvalue()) == [("u.docx", {"aws_access_key_id": 1})]



def test_the_route_refuses_a_docx_key_and_never_echoes_it(env, client, board):
    before = tree(env.root)
    with structlog.testing.capture_logs() as logs:
        r = post(client, board, ("ok.md", MD), ("plan.docx", docx(FAKE[:6], FAKE[6:])))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "reviewboard_file_has_secret" and detail["files"] == [{"file": "plan.docx", "detectors": {"aws_access_key_id": 1}}]
    assert FAKE not in r.text and FAKE[6:] not in r.text and FAKE not in repr(logs) and FAKE[6:] not in repr(logs)
    assert tree(env.root) == before


def test_the_route_refuses_an_unreadable_docx_and_attaches_a_clean_one(env, client, board):
    r = post(client, board, ("bad.docx", b"PK\x03\x04" + b"\x00" * 64))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reviewboard_file_unscannable"
    assert post(client, board, ("good.docx", docx("meeting notes")), ("good.xlsx", xlsx(shared="<si><t>q3</t></si>"))).status_code == 200
