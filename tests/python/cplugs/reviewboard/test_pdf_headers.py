
from __future__ import annotations

import itertools
import time

import pytest

from src.cplugs.reviewboard import pdf_scan
from src.cplugs.reviewboard.pdf_streams import PdfUnreadable
from src.cplugs.sdk.file_secrets import Deadline

SEPARATORS = [b"\x00", b"\x0b", b"\t", b"\n", b"\x0c", b"\r", b" ", b"\r\n", b"%c\n", b"%c\r", b"%\x00 junk (\n", b"%\n", b" \x00\t\n\x0c\r ", b" %x\r\n\x00%y\n ", b"%" + b"c" * 3000 + b"\n"]
SCRIPT = b"<< /S /JavaScript /JS (x) >>\nendobj\n"


def hidden(header: bytes) -> bytes:
    body = header + b"\n" + SCRIPT
    return b"%PDF-1.7\n1 0 obj\n<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream\nendobj\n%%EOF\n"


def visible(header: bytes) -> bytes:
    return b"%PDF-1.7\n" + header + b"\n" + SCRIPT + b"%%EOF\n"


def refused(data: bytes) -> str:
    try:
        return "found:" + ",".join(sorted(pdf_scan.features(data, Deadline())))
    except PdfUnreadable as exc:
        return exc.reason


@pytest.mark.parametrize("first,second", list(itertools.product(SEPARATORS, repeat=2)))
def test_every_separator_pair_is_caught_when_hidden_and_read_when_visible(first, second):
    header = b"4" + first + b"0" + second + b"obj"
    assert refused(hidden(header)) == "hidden_object"
    assert refused(visible(header)) == ("hidden_object" if b"\x0b" in header else "found:JavaScript")


@pytest.mark.parametrize("header", [b"4 000000 obj", b"4 0000000000 obj", b"12345678901 0 obj", b"+4 0 obj", b"4 +0 obj", b"-4 0 obj", b"0004 0 obj",
                                    b"4 % a\n0 % b\nobj", b"4\x00%x\n\x000\r%y\robj", b"4" + b" " * 5000 + b"0 obj"])
def test_number_shapes_signs_and_comments_are_caught(header):
    assert refused(hidden(header)) == "hidden_object"
    assert refused(visible(header)) == "found:JavaScript"


def test_a_number_past_the_length_cap_is_malformed_and_ordinary_text_is_not_a_header():
    assert refused(hidden(b"4 " + b"9" * 50 + b" obj")) == "malformed_pdf"
    for text in (b"4 0 object", b"4 0 objs", b"4 0 R", b"a4 0 b", b"1 2 3 4 5 6 7 8 9 obj"[:-4], b"4 0 x obj", b"4 0 /N obj", b"obj 4 0"):
        assert refused(hidden(text)) == "found:", text


def test_a_long_run_of_comment_starts_is_scanned_in_linear_time_and_never_slips_through_slowly():
    data = b"%PDF-1.7\n" + b"1 %" * 30000 + b"\n%%EOF\n"
    started = time.monotonic()
    result = refused(data)
    assert time.monotonic() - started < 1.0, result
    assert result in ("found:", "hidden_object", "malformed_pdf")


def test_a_split_header_after_a_long_comment_is_still_found():
    assert refused(hidden(b"4 %" + b"c" * 200000 + b"\n0 obj")) == "hidden_object"


@pytest.mark.parametrize("leading", [b"", b"9 ", b"7 8 9 ", b"5 6 7 8 9 ", b"1 2 3 4 5 6 7 8 ", b"8\x0b", b"8 %x\n"])
def test_a_run_of_leading_integers_odd_or_even_does_not_hide_the_header(leading):
    assert refused(hidden(leading + b"4 0 obj")) == "hidden_object"


@pytest.mark.parametrize("header", [b"4 0obj", b"4+0 obj", b"4-0 obj", b"4+0obj", b"4 00obj", b"1+2 obj", b"1 2+3 obj", b"4 0obj<<", b"4 \t\r\n0obj"])
def test_glued_signed_and_no_separator_headers_are_caught(header):
    assert refused(hidden(header)) == "hidden_object", header


@pytest.mark.parametrize("header", [b"4 0 obj\x0b", b"4 0 obj\x0b\x0b", b"4 0 obj\x0c"])
def test_a_vertical_tab_or_form_feed_right_after_obj_does_not_hide_the_header(header):
    assert refused(hidden(header)) == "hidden_object"
