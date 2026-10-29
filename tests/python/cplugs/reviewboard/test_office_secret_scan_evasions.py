
from __future__ import annotations

import io
import random
import string
import time
import zipfile

import pytest

from src.cplugs.reviewboard import office_text, office_xml
from src.cplugs.reviewboard.errors import UnscannableFile
from tests.python.cplugs.reviewboard.test_office_secret_scan import BODY, FAKE, W, counts, docx, make_zip, xlsx

HIT = [("a.docx", {"aws_access_key_id": 1})]


def hit(name: str, data: bytes):
    return counts(name, data)


def body(inner: str) -> bytes:
    return make_zip({BODY: f"<w:document {W}><w:body><w:p>{inner}</w:p></w:body></w:document>"})



@pytest.mark.parametrize("inner", [
    f"<w:r><w:t>AWS key</w:t><w:br/><w:t>{FAKE}</w:t></w:r>",
    f"<w:r><w:t>Key</w:t><w:tab/><w:t>{FAKE}</w:t></w:r>",
    f"<w:r><w:t>Key</w:t><w:cr/><w:t>{FAKE}</w:t></w:r>",
    f"<w:del><w:r><w:delText>old</w:delText></w:r></w:del><w:r><w:t>{FAKE}</w:t></w:r>",
    f"<w:r><w:t>id</w:t></w:r><!-- c --><w:r><w:t>{FAKE}</w:t></w:r>",
    f"<w:r><w:t>id</w:t></w:r><w:r><w:t>{FAKE}</w:t></w:r>",
])
def test_a_key_glued_to_the_word_before_it_is_found(inner):
    assert hit("a.docx", body(inner)) == HIT


def test_a_pptx_line_break_does_not_hide_a_key():
    slide = f"<p:sld><a:p><a:r><a:t>token</a:t></a:r><a:br/><a:r><a:t>{FAKE}</a:t></a:r></a:p></p:sld>"
    assert hit("a.pptx", make_zip({"ppt/slides/slide1.xml": slide})) == [("a.pptx", {"aws_access_key_id": 1})]


def test_a_pptx_key_split_across_runs_and_a_clean_slide():
    split = f"<p:sld><a:p><a:r><a:t>{FAKE[:7]}</a:t></a:r><a:r><a:t>{FAKE[7:]}</a:t></a:r></a:p></p:sld>"
    assert hit("a.pptx", make_zip({"ppt/slides/slide1.xml": split})) == [("a.pptx", {"aws_access_key_id": 1})]
    assert hit("b.pptx", make_zip({"ppt/slides/slide1.xml": "<p:sld><a:p><a:r><a:t>agenda</a:t></a:r></a:p></p:sld>"})) == []


def test_a_key_split_by_a_tab_is_not_a_key():
    assert hit("a.docx", body(f"<w:r><w:t>{FAKE[:9]}</w:t><w:tab/><w:t>{FAKE[9:]}</w:t></w:r>")) == []



@pytest.mark.parametrize("name,xml", [
    ("word/Document.xml", f"<w:t>{FAKE}</w:t>"),
    ("word/document2.xml", f"<w:t>{FAKE}</w:t>"),
    ("word/glossary/document.xml", f"<w:t>{FAKE}</w:t>"),
    ("word/diagrams/data1.xml", f"<dgm:dataModel><a:t>{FAKE}</a:t></dgm:dataModel>"),
    ("word/charts/chart1.xml", f"<c:chartSpace><c:v>{FAKE}</c:v></c:chartSpace>"),
    ("docProps/custom.xml", f"<Properties><vt:lpwstr>{FAKE}</vt:lpwstr></Properties>"),
    ("docProps/core.xml", f"<cp:coreProperties><dc:description>{FAKE}</dc:description></cp:coreProperties>"),
    ("customXml/item1.xml", f"<root>{FAKE}</root>"),
    ("xl/drawings/drawing1.xml", f"<xdr:wsDr><a:p><a:r><a:t>{FAKE}</a:t></a:r></a:p></xdr:wsDr>"),
    ("xl/threadedComments/threadedComment1.xml", f"<ThreadedComments><text>{FAKE}</text></ThreadedComments>"),
    ("xl/workbook.xml", f'<workbook><definedNames><definedName name="k">"{FAKE}"</definedName></definedNames></workbook>'),
    ("xl/sheets/data.xml", f'<worksheet><sheetData><row><c t="inlineStr"><is><t>{FAKE}</t></is></c></row></sheetData></worksheet>'),
    ("ppt/slideLayouts/slideLayout1.xml", f"<p:sldLayout><a:t>{FAKE}</a:t></p:sldLayout>"),
    ("ppt/slideMasters/slideMaster1.xml", f"<p:sldMaster><a:t>{FAKE}</a:t></p:sldMaster>"),
    ("word/drawings/vmlDrawing1.VML", f"<xml><v:textbox>{FAKE}</v:textbox></xml>"),
    ("word/afchunk.htm", f"<html><body>{FAKE}</body></html>"),
    ("word/afchunk2.HTML", f"<!DOCTYPE html><html><body>{FAKE}</body></html>"),
])
def test_a_key_in_any_part_is_found(name, xml):
    assert hit("a.docx", make_zip({name: xml})) == HIT



@pytest.mark.parametrize("sheet", [
    f'<sheetData><row><c r="A1" t="str"><v>{FAKE}</v></c></row></sheetData>',
    f'<sheetData><row><c t="str"><f>A2</f><v>{FAKE}</v></c></row></sheetData>',
    f"<headerFooter><oddHeader>&amp;C{FAKE}</oddHeader></headerFooter>",
    f'<dataValidations><dataValidation type="list"><formula1>"{FAKE},b"</formula1></dataValidation></dataValidations>',
])
def test_a_key_in_a_worksheet_value_header_or_validation_is_found(sheet):
    assert hit("a.xlsx", make_zip({"xl/worksheets/sheet1.xml": f"<worksheet>{sheet}</worksheet>"})) == [("a.xlsx", {"aws_access_key_id": 1})]



@pytest.mark.parametrize("name,xml", [
    (BODY, f'<w:document {W}><wp:docPr id="1" name="p" descr="{FAKE}"/></w:document>'),
    ("xl/connections.xml", f"<connections><dbPr connection='Provider=x;Password={FAKE}'/></connections>"),
    ("xl/worksheets/_rels/sheet1.xml.rels", f'<Relationships><Relationship Id="r1" Target="https://x.test/?k={FAKE}" TargetMode="External"/></Relationships>'),
])
def test_a_key_in_an_attribute_value_is_found(name, xml):
    assert hit("a.docx", make_zip({name: xml})) == HIT



@pytest.mark.parametrize("inner", [
    f"<w:t><![CDATA[x<y {FAKE}]]></w:t>",
    f"<w:t><![CDATA[x>y {FAKE}]]></w:t>",
    f"<w:t><![CDATA[{FAKE}",
    f"<!-- a<b {FAKE} -->",
    f"<!-- {FAKE}",
    f"<!-- a>b --><w:t>{FAKE}</w:t>",
])
def test_a_key_in_cdata_or_a_comment_with_angle_brackets_is_found(inner):
    assert hit("a.docx", body(inner)) == HIT



def test_an_embedded_workbook_is_opened_one_level_deep():
    inner = xlsx(shared=f"<si><t>{FAKE}</t></si>")
    assert hit("a.docx", make_zip({BODY: "<w:document/>", "word/embeddings/Sheet1.xlsx": inner})) == HIT


def test_a_zip_nested_deeper_than_the_limit_is_refused():
    chain = xlsx(shared=f"<si><t>{FAKE}</t></si>")
    for n in range(office_text.MAX_DEPTH + 1):
        chain = make_zip({f"word/embeddings/e{n}.docx": chain})
    with pytest.raises(UnscannableFile) as exc:
        hit("a.docx", chain)
    assert exc.value.extra["files"] == [{"file": "a.docx", "reason": "nested_too_deep"}]


def test_a_part_that_starts_like_a_zip_but_is_not_one_is_refused():
    with pytest.raises(UnscannableFile):
        hit("a.docx", make_zip({"word/embeddings/b.xlsx": b"PK\x03\x04junk".decode("latin-1")}))


@pytest.mark.parametrize("raw", [b"\x00\x01 " + FAKE.encode() + b"\x00\x02", b"\x00\x01" + FAKE.encode("utf-16-le") + b"\x00\x02"])
def test_a_plain_key_in_an_ole_bin_is_found(raw):
    assert hit("a.docx", _zip_bytes({BODY: b"<w:document/>", "word/embeddings/oleObject1.bin": raw})) == HIT


def test_a_clean_ole_bin_passes():
    noise = bytes(random.Random(5).randrange(256) for _ in range(5000))
    assert hit("a.docx", _zip_bytes({BODY: b"<w:document/>", "word/embeddings/oleObject1.bin": noise})) == []


def _zip_bytes(parts: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()



@pytest.mark.parametrize("codec,bom", [("utf-16-le", b""), ("utf-16-be", b""), ("utf-32-le", b""), ("utf-8", b"\xef\xbb\xbf")])
def test_a_part_without_a_byte_order_mark_is_still_decoded(codec, bom):
    xml = f'<?xml version="1.0"?><w:p><w:t>{FAKE}</w:t></w:p>'
    assert hit("a.docx", _zip_bytes({BODY: bom + xml.encode(codec)})) == HIT


def test_a_dtd_in_a_bom_less_utf16_part_is_still_refused():
    xml = '<!DOCTYPE w [<!ENTITY a "x">]><w:p><w:t>&a;</w:t></w:p>'
    with pytest.raises(UnscannableFile) as exc:
        hit("a.docx", _zip_bytes({BODY: xml.encode("utf-16-le")}))
    assert exc.value.extra["files"][0]["reason"] == "dtd_in_part"




def test_the_raw_inflation_ceiling_is_shared_and_refuses(monkeypatch):
    monkeypatch.setattr(office_text, "MAX_PART_BYTES", 4 * 1024 * 1024)
    monkeypatch.setattr(office_text, "MAX_RAW_BYTES", 14 * 1024 * 1024)
    chunk = random.Random(3).randbytes(office_text.MAX_PART_BYTES - 1024)
    parts = {f"word/embeddings/o{n}.bin": chunk for n in range(office_text.MAX_RAW_BYTES // len(chunk) + 1)}
    with pytest.raises(UnscannableFile) as exc:
        hit("a.docx", _zip_bytes({BODY: b"<w:document/>", **parts}))
    assert exc.value.extra["files"][0]["reason"] == "too_much_data"


def test_a_part_of_words_past_the_text_cap_is_refused(monkeypatch):
    monkeypatch.setattr(office_text, "MAX_TEXT_CHARS", 100_000)
    words = ("<w:t>" + "word " * 100 + "</w:t>") * 400
    with pytest.raises(UnscannableFile) as exc:
        hit("a.docx", make_zip({BODY: f"<w:p>{words}</w:p>"}))
    assert exc.value.extra["files"][0]["reason"] == "too_much_data"



@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_any_method_but_stored_or_deflate_is_refused(method):
    with pytest.raises(UnscannableFile) as exc:
        hit("a.docx", make_zip({BODY: f"<w:p><w:t>{FAKE}</w:t></w:p>"}, method=method))
    assert exc.value.extra["files"][0]["reason"] == "unsupported_compression"


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_stored_and_deflate_are_read(method):
    assert hit("a.docx", make_zip({BODY: f"<w:p><w:t>{FAKE}</w:t></w:p>"}, method=method)) == HIT


def test_a_zip64_entry_is_read():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z, z.open(BODY, "w", force_zip64=True) as h:
        h.write(f"<w:p><w:t>{FAKE}</w:t></w:p>".encode())
    assert hit("a.docx", buf.getvalue()) == HIT



def test_entities_decode_only_the_xml_five_and_numbers():
    assert office_xml.decode_entities("&amp;&lt;&#65;&#x42;&nbsp;&xxe;") == "&<AB&nbsp;&xxe;"
    assert office_xml.extract("<w:t>a &xxe; b</w:t>", limit=99).joined.strip() == "a &xxe; b"


def test_the_two_readings_differ_only_by_run_boundaries():
    r = office_xml.extract("<w:p><w:r><w:t>AK</w:t></w:r><w:r><w:t>IA</w:t></w:r></w:p>", limit=99)
    assert r.joined.strip() == "AKIA" and r.separated.split() == ["AK", "IA"]


def test_the_extracted_size_limit_stops_the_scanner():
    with pytest.raises(office_xml.SizeExceeded):
        office_xml.extract("<a>" + "x" * 1000 + "</a>", limit=100)


_N = 2_000_000
HOSTILE = {
    "open_brackets": "<" * _N,
    "open_tag_no_end": "<a " * (_N // 3),
    "comment_no_end": "<!--" * (_N // 4),
    "cdata_no_end": "<![CDATA[" * (_N // 9),
    "pi_no_end": "<?x " * (_N // 4),
    "quote_no_end": '<a b="' * (_N // 6),
    "gt_run": "<a>" * (_N // 3),
    "one_tag_many_attrs": "<a " + 'b="12345678901234" ' * (_N // 20) + ">",
    "mixed": "<a><!-- <![CDATA[ <?x <b " * (_N // 25),
}


@pytest.mark.parametrize("kind", sorted(HOSTILE))
def test_hostile_markup_is_scanned_in_linear_time(kind):
    start = time.monotonic()
    try:
        office_xml.extract(HOSTILE[kind], limit=64 * 1024 * 1024)
    except office_xml.SizeExceeded:
        pass
    assert time.monotonic() - start < 20, kind


def test_a_key_used_as_an_element_or_attribute_name_is_found():
    assert hit("a.docx", body(f"<{FAKE}/>")) == HIT
    assert hit("b.docx", body(f'<w:r {FAKE}="1"/>')) == [("b.docx", {"aws_access_key_id": 1})]


def test_the_fast_path_and_the_hand_scanner_read_a_part_the_same():
    xml = (f'<w:p><w:r><w:t>{FAKE[:7]}</w:t></w:r><w:r><w:t>{FAKE[7:]}</w:t></w:r><w:br/><w:t>AWS&amp;key</w:t>'
           f'<wp:docPr descr="{FAKE}"/></w:p><w:p><w:t>end</w:t></w:p>')
    fast, slow = office_xml.extract(xml, limit=10**6), office_xml.extract(xml + "<?x y?>", limit=10**6)
    drop = {"x", "y"}
    assert sorted(fast.joined.split()) == sorted(t for t in slow.joined.split() if t not in drop)
    assert sorted(fast.separated.split()) == sorted(t for t in slow.separated.split() if t not in drop)
