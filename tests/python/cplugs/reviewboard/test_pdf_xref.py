
from __future__ import annotations

import time
import zlib

import pytest

from src.cplugs.reviewboard import pdf_doc, pdf_scan, pdf_xref
from src.cplugs.reviewboard.pdf_lexer import Meter
from src.cplugs.reviewboard.pdf_objects import Dict as PdfDict, Name
from src.cplugs.reviewboard.pdf_streams import Budget, PdfUnreadable
from src.cplugs.sdk.file_secrets import Deadline
from tests.python.cplugs.reviewboard.pdf_fixtures import (BYPASSES, CLEAN_CAT, PAGE, PAGES, ROUND9_REVIEW, broken_primary_xref, classic, deep_prev_chain, gap_backtrack,
                                                          ordinary_xref_stream_predictor, prev_chain_into_body, type2_hidden_objstm,
                                                          unparseable_chained_section, xref_stream_into_body)

INTO_BODY = ["xref_stream_predictor_into_body", "xref_stream_flate_into_body", "xref_prev_chain_into_body", "xref_type2_hidden_objstm"]
_BUILD = {"xref_stream_predictor_into_body": lambda: xref_stream_into_body(True), "xref_stream_flate_into_body": lambda: xref_stream_into_body(False),
          "xref_prev_chain_into_body": prev_chain_into_body, "xref_type2_hidden_objstm": type2_hidden_objstm}
NO_SEP_INTO_BODY = ["hidden_gen_glued_obj", "hidden_plus_gen", "hidden_minus_gen", "hidden_plus_gen_glued_obj", "hidden_leadingzero_glued_obj",
                    "hidden_obj_glued_to_dict", "hidden_mixed_ws_then_glued_obj", "hidden_comment_before_obj", "hidden_comment_between_numbers",
                    "hidden_leading_comment_at_offset", *ROUND9_REVIEW]


def _meter_budget(data: bytes):
    return Meter.for_input(Deadline(), len(data)), Budget.for_input(Deadline(), len(data))


@pytest.mark.parametrize("name", INTO_BODY)
def test_cross_reference_verification_catches_into_body_attacks_even_with_the_header_scan_off(name, monkeypatch):
    monkeypatch.setattr(pdf_doc, "_refuse_hidden_objects", lambda *a, **k: None)
    with pytest.raises(PdfUnreadable) as exc:
        pdf_scan.features(_BUILD[name](), Deadline())
    assert exc.value.reason == "hidden_object"


@pytest.mark.parametrize("name", NO_SEP_INTO_BODY)
def test_the_cross_reference_check_alone_catches_no_separator_and_comment_headers(name, monkeypatch):
    monkeypatch.setattr(pdf_doc, "_refuse_hidden_objects", lambda *a, **k: None)
    with pytest.raises(PdfUnreadable) as exc:
        pdf_scan.features(BYPASSES[name](), Deadline())
    assert exc.value.reason == "hidden_object"


def test_a_cross_reference_chain_longer_than_the_cap_is_refused_not_silently_truncated():
    assert pdf_scan.features(deep_prev_chain(50), Deadline()) == frozenset()
    with pytest.raises(PdfUnreadable) as exc:
        pdf_scan.features(deep_prev_chain(pdf_xref.MAX_SECTIONS + 50), Deadline())
    assert exc.value.reason == "xref_unresolved"


def test_a_chained_section_this_module_cannot_parse_is_refused_but_a_broken_primary_is_left_to_the_header_scan():
    with pytest.raises(PdfUnreadable) as exc:
        pdf_scan.features(unparseable_chained_section(), Deadline())
    assert exc.value.reason == "xref_unresolved"
    assert pdf_scan.features(broken_primary_xref(), Deadline()) == frozenset()


def test_a_flate_png_predictor_cross_reference_stream_is_read_and_stays_clean():
    data = ordinary_xref_stream_predictor()
    assert pdf_scan.features(data, Deadline()) == frozenset()
    entries = pdf_xref.resolve_xref(data, *_meter_budget(data))
    assert entries is not None and set(entries) >= {1, 2, 3} and all(e.offset is not None for e in entries.values())


def test_resolve_xref_reads_a_classic_table_a_stream_and_a_prev_chain():
    classic_entries = pdf_xref.resolve_xref(*(lambda d: (d, *_meter_budget(d)))(classic({1: CLEAN_CAT, 2: PAGES, 3: PAGE})))
    assert classic_entries is not None and set(classic_entries) >= {1, 2, 3}
    prev = prev_chain_into_body()
    entries = pdf_xref.resolve_xref(prev, *_meter_budget(prev))
    assert entries is not None and entries[4].offset is not None and 4 in entries


def test_an_unsupported_cross_reference_stream_filter_is_refused_not_trusted():
    data = _lzw_xref_stream()
    meter, budget = _meter_budget(data)
    with pytest.raises(PdfUnreadable) as exc:
        pdf_xref.resolve_xref(data, meter, budget)
    assert exc.value.reason == "unsupported_filter"


def test_a_file_with_no_parseable_cross_reference_is_left_to_the_header_scan():
    data = classic({1: CLEAN_CAT, 2: PAGES, 3: PAGE})
    data = data[:data.rindex(b"startxref")] + b"%%EOF\n"
    assert pdf_xref.resolve_xref(data, *_meter_budget(data)) is None
    assert pdf_scan.features(data, Deadline()) == frozenset()


def test_the_png_and_tiff_predictors_are_undone_correctly():
    rows = bytes((7 * r + c) * 11 % 251 for r in range(5) for c in range(7))
    cols = 5 * 7
    for predictor, encode in ((12, lambda d, c: _encode_png_mixed(d, 7)), (2, _encode_tiff2)):
        dic = PdfDict()
        dic["Filter"] = Name("FlateDecode")
        parms = PdfDict()
        parms["Predictor"], parms["Columns"], parms["Colors"], parms["BitsPerComponent"] = predictor, (7 if predictor == 12 else cols), 1, 8
        dic["DecodeParms"] = parms
        body = zlib.compress(encode(rows, cols))
        dic["Length"] = len(body)
        assert pdf_xref._decode_xref_stream(body, dic, _meter_budget(b"")[1]) == rows, predictor


def _encode_png_mixed(rows: bytes, cols: int) -> bytes:
    prev, out = bytes(cols), bytearray()
    for r, tag in enumerate((0, 1, 2, 3, 4)):
        row = rows[r * cols:(r + 1) * cols]
        enc = bytearray()
        for j in range(cols):
            left, up, upleft = (row[j - 1] if j else 0), prev[j], (prev[j - 1] if j else 0)
            base = {0: 0, 1: left, 2: up, 3: (left + up) // 2, 4: pdf_xref._paeth(left, up, upleft)}[tag]
            enc.append((row[j] - base) & 0xFF)
        out += bytes([tag]) + enc
        prev = row
    return bytes(out)


def test_the_paeth_tie_break_follows_the_png_spec_not_strict_less_than():
    prior, current = bytes([5, 10, 6, 9]), bytes([7, 12, 200, 3])

    def spec_paeth(a: int, b: int, c: int) -> int:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else (b if pb <= pc else c)

    enc = bytearray(b"\x00" + prior)
    row = bytearray()
    for j in range(4):
        row.append((current[j] - spec_paeth(current[j - 1] if j else 0, prior[j], prior[j - 1] if j else 0)) & 0xFF)
    enc += b"\x04" + bytes(row)
    body = zlib.compress(bytes(enc))
    dic = PdfDict()
    dic["Filter"] = Name("FlateDecode")
    parms = PdfDict()
    parms["Predictor"], parms["Columns"], parms["Colors"], parms["BitsPerComponent"] = 12, 4, 1, 8
    dic["DecodeParms"], dic["Length"] = parms, len(body)
    assert pdf_xref._decode_xref_stream(body, dic, _meter_budget(b"")[1]) == prior + current


def test_skip_ws_advances_past_every_pdf_white_space_byte():
    assert pdf_xref._skip_ws(b"  \t\r\n\x00\x0b4 0 obj", 0) == 7
    assert pdf_xref._skip_ws(b"4 0 obj", 0) == 0 and pdf_xref._skip_ws(b"   ", 0) == 3


def _encode_tiff2(rows: bytes, cols: int) -> bytes:
    out = bytearray()
    for i in range(0, len(rows), cols):
        row = rows[i:i + cols]
        out += bytes((row[j] - (row[j - 1] if j else 0)) & 0xFF for j in range(cols))
    return bytes(out)


def _lzw_xref_stream() -> bytes:
    from tests.python.cplugs.reviewboard.pdf_fixtures import HDR
    buf, offs = bytearray(HDR), {}
    for n, body in ((1, CLEAN_CAT), (2, PAGES), (3, PAGE)):
        offs[n] = len(buf)
        buf += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    offs[4] = len(buf)
    rows = b"".join(bytes([1]) + offs.get(n, 0).to_bytes(4, "big") + b"\0\0" for n in range(5))
    dic = b"<< /Type /XRef /Size 5 /W [1 4 2] /Root 1 0 R /Filter /LZWDecode /Length %d >>" % len(rows)
    buf += b"4 0 obj\n" + dic + b"\nstream\n" + rows + b"\nendstream\nendobj\n"
    return bytes(buf + b"startxref\n%d\n%%%%EOF\n" % offs[4])


@pytest.mark.parametrize("name", ROUND9_REVIEW)
def test_the_header_pass_alone_catches_a_bare_sign_generation_and_long_zero_runs(name, monkeypatch):
    monkeypatch.setattr(pdf_scan, "verify_against_walk", lambda *a, **k: None)
    with pytest.raises(PdfUnreadable) as exc:
        pdf_scan.features(BYPASSES[name](), Deadline())
    assert exc.value.reason in {"hidden_object", "malformed_pdf"}


def test_a_comment_gap_at_a_cross_reference_offset_is_matched_in_linear_time():
    data = gap_backtrack(27)
    started = time.monotonic()
    try:
        pdf_scan.features(data, Deadline())
    except PdfUnreadable:
        pass
    assert time.monotonic() - started < 1.0
