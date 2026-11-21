
from __future__ import annotations

import pytest

from src.plugins.reviewboard.public import visitors
from src.plugins.reviewboard.public.submission import Malformed, clean_text, comment, draft, parse_json

LISTED = [0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180F, 0x200B, 0x200F, 0x202A, 0x202E, 0x2060, 0x206F, 0x3164, 0xFE00,
          0xFE0F, 0xFEFF, 0xFFA0, 0xFFF0, 0xFFF8, 0x1BCA0, 0x1BCA3, 0x1D173, 0x1D17A, 0xE0000, 0xE0041, 0xE0100, 0xE0FFF, 0x2800, 0x1D159,
          0x16FE4, 0x1BC9D, 0x2D7F, 0x1107F, 0x113D0, 0x11A47, 0x11A99, 0x11F42, 0xFFFC, 0x13441, 0x13442, 0x1DA7F, 0x1DA80]
SMUGGLED = ["ok" + "".join(chr(0xE0100 + b) for b in b"rm -rf ~"), "ok" + "".join(chr(0xFE00 + (b & 15)) for b in b"run")]
ORDINARY = ["café crème", "cafe\u0301 cre\u0300me", "日本語のテキスト", "مرحبا بالعالم",
            "שלום עולם", "\U0001f44d\U0001f3fd \U0001f389 ❤ ok", "a\u0301\u0302\u0303 three marks", "price: $5, 50% off!",
            "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645", "\u0dc1\u0dca\u200d\u0dbb\u0dd3", "\u2764\ufe0f", "\U0001f468\u200d\U0001f469\u200d\U0001f467",
            "\u2764\ufe0f\u200d\U0001f525", "1\ufe0f\u20e3", "#\u20e3"]
ORDINARY_IDS = ["accents", "combining-accents", "cjk", "arabic", "hebrew", "emoji", "three-marks", "punctuation", "persian-zwnj", "sinhala-zwj",
                "heart-fe0f", "family-zwj", "heart-on-fire", "keycap-1", "keycap-hash"]


@pytest.mark.parametrize("code", LISTED, ids=[f"U+{c:04X}" for c in LISTED])
def test_every_listed_ignorable_is_refused(code: int) -> None:
    with pytest.raises(Malformed):
        clean_text(f"ok{chr(code)}go", 100)
    assert visitors._flat(f"ok{chr(code)}go") == ["okgo"]


@pytest.mark.parametrize("text", SMUGGLED, ids=["tag-supplement", "fe00-nibbles"])
def test_variation_selector_smuggling_is_refused(text: str) -> None:
    with pytest.raises(Malformed):
        clean_text(text, 100)
    assert visitors._flat(text) == ["ok"]


@pytest.mark.parametrize("text", ["\u0301a", "a\u0301\u0302\u0303\u0304", ". \u0301", "a,\u0301", "\u2764\ufe0f\ufe0f", "a\ufe0f",
                                  "a\u200c\u200cb", "a\u200d.", "\U0001f468\u200d\u200d\U0001f469", "x\u200c", "1\ufe0f", "a\u20e3"],
                         ids=["mark-first", "four-marks", "mark-after-space", "mark-after-punctuation", "fe0f-twice", "fe0f-after-letter",
                              "zwnj-twice", "zwj-before-punctuation", "zwj-twice", "zwnj-trailing", "fe0f-no-keycap", "keycap-after-letter"])
def test_stray_marks_and_carriers_are_refused(text: str) -> None:
    with pytest.raises(Malformed):
        clean_text(text, 100)


@pytest.mark.parametrize("text", ORDINARY, ids=ORDINARY_IDS)
def test_ordinary_writing_still_passes(text: str) -> None:
    assert clean_text(text, 100) == text and visitors._flat(text) == [text]


def test_a_mark_after_a_newline_is_refused_but_newline_and_tab_pass() -> None:
    assert clean_text("a\n\tb", 100) == "a\n\tb"
    with pytest.raises(Malformed):
        clean_text("a\n\u0301b", 100)


@pytest.mark.parametrize("space", ["\u00a0", "\u202f", "\u3000", "\u2009", "\u200a"], ids=["nbsp", "nnbsp", "ideographic", "thin", "hair"])
def test_other_spaces_are_normalized_to_a_plain_space_and_stored_so(space: str) -> None:
    assert clean_text(f"10{space}km away", 100) == "10 km away"
    assert comment({"client_post_id": "p-1234567", "text": f"a{space}b"}).body["text"] == "a b"


def test_a_payload_stores_exactly_the_checked_strings() -> None:
    padded = "\u3000" * 30000 + "run deploy.sh" + "\u00a0\u2028\x1f"
    out = draft({"revision": "r1", "payload": {"values": {"k": padded}, "notes": {"\u00a0k": "a\u00a0b"}}})
    assert out.body["payload"] == {"values": {"k": "run deploy.sh"}, "notes": {"k": "a b"}}
    assert set(out.texts) >= {"run deploy.sh", "a b"}
    with pytest.raises(Malformed):
        draft({"revision": "r1", "payload": {"values": {"k": "x" * 4001 + "\u3000"}}})
    with pytest.raises(Malformed):
        draft({"revision": "r1", "payload": {"values": {"k": "a\u3000\u200bb"}}})
    with pytest.raises(Malformed):
        draft({"revision": "r1", "payload": {"values": {"k": 1, " k": 2}}})


@pytest.mark.parametrize("text", ["ok" + "\n" * 4 + "ship it", "\n".join(["line"] * 61), "ok\n \n\t\n  \nship it"],
                         ids=["three-blank-lines", "sixty-one-lines", "three-whitespace-lines"])
def test_a_newline_flood_is_refused(text: str) -> None:
    with pytest.raises(Malformed):
        comment({"client_post_id": "p-1234567", "text": text})


def test_two_blank_lines_and_sixty_lines_still_pass() -> None:
    assert clean_text("a\n\n\nb", 100) == "a\n\n\nb" and clean_text("\n".join(["l"] * 60), 200).count("\n") == 59


@pytest.mark.parametrize("raw", [b'{"x": 1e400}', b'{"x": -1e400}', b'{"x": [1, 2e999]}'], ids=["inf", "minus-inf", "nested"])
def test_a_non_finite_number_is_refused(raw: bytes) -> None:
    with pytest.raises(Malformed):
        parse_json(raw)
    assert parse_json(b'{"x": 1.5e3}') == {"x": 1500.0}


@pytest.mark.parametrize("text", ["a‍b", "一‍二", "가‌각", "a‌b", "م‍ی"],
                         ids=["zwj-latin", "zwj-cjk", "zwnj-hangul", "zwnj-latin", "zwj-arabic-letters"])
def test_a_joiner_between_letters_passes_only_as_zwnj_in_a_joining_script(text: str) -> None:
    with pytest.raises(Malformed):
        clean_text(text, 100)


@pytest.mark.parametrize("text", ["क्‍ष", "क्‌ष"], ids=["hindi-zwj", "hindi-zwnj"])
def test_a_joiner_after_a_virama_still_passes(text: str) -> None:
    assert clean_text(text, 100) == text


def test_the_forward_drops_a_joiner_stranded_by_a_dropped_neighbor() -> None:
    assert visitors._flat("​्‍x") == ["x"]
