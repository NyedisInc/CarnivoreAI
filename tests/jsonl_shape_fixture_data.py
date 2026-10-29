
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

ENVELOPE_KEYS: Tuple[str, ...] = ("isSidechain", "agentId")

NOT_AN_OBJECT: str = "__not_an_object__"


@dataclass(frozen=True)
class ShapeFixture:

    name: str
    covers: str
    line: str
    style: str
    key_order: Any
    envelope_keys_expected: List[str] = field(default_factory=list)


def split_line(text: str, key_order: Any) -> Tuple[Any, Dict[str, Any]]:
    value = json.loads(text)
    if key_order == NOT_AN_OBJECT or not isinstance(value, dict):
        return value, {}
    body: Dict[str, Any] = {}
    envelope: Dict[str, Any] = {}
    for key, item in value.items():
        if key in ENVELOPE_KEYS:
            envelope[key] = item
        else:
            body[key] = item
    return body, envelope


FIXTURES: Tuple[ShapeFixture, ...] = (
    ShapeFixture(
        name="class_compact_env_issidechain",
        covers="corpus class 1 of 6: compact, envelope {isSidechain}, "
               "envelope key in the middle (698 signatures)",
        line='{"parentUuid":null,"isSidechain":false,"type":"user",'
             '"uuid":"uuid-0001","timestamp":"2026-01-01T00:00:00.000Z"}',
        style="compact",
        key_order=["parentUuid", "isSidechain", "type", "uuid", "timestamp"],
        envelope_keys_expected=["isSidechain"],
    ),
    ShapeFixture(
        name="class_compact_env_both",
        covers="corpus class 2 of 6: compact, envelope {agentId, "
               "isSidechain}, both in the middle (578 signatures)",
        line='{"parentUuid":"uuid-0000","isSidechain":true,'
             '"agentId":"a0123456789abcdef","type":"progress",'
             '"uuid":"uuid-0002","timestamp":"2026-01-01T00:00:01.000Z"}',
        style="compact",
        key_order=["parentUuid", "isSidechain", "agentId", "type", "uuid",
                   "timestamp"],
        envelope_keys_expected=["agentId", "isSidechain"],
    ),
    ShapeFixture(
        name="class_compact_env_empty",
        covers="corpus class 3 of 6: compact, NO envelope keys at all "
               "(65 signatures)",
        line='{"type":"summary","summary":"synthetic summary text",'
             '"leafUuid":"uuid-0003"}',
        style="compact",
        key_order=["type", "summary", "leafUuid"],
        envelope_keys_expected=[],
    ),
    ShapeFixture(
        name="class_spaced_env_issidechain",
        covers="corpus class 4 of 6: the spaced style, which occurs on "
               "720 corpus rows and is easy to assume away (3 signatures)",
        line='{"parentUuid": null, "isSidechain": false, "type": "system", '
             '"uuid": "uuid-0004"}',
        style="spaced",
        key_order=["parentUuid", "isSidechain", "type", "uuid"],
        envelope_keys_expected=["isSidechain"],
    ),
    ShapeFixture(
        name="class_compact_env_agentid_only",
        covers="corpus class 5 of 6: agentId WITHOUT isSidechain, the "
               "envelope state easiest to assume impossible (2 signatures)",
        line='{"agentId":"a0fedcba98765432","type":"assistant",'
             '"uuid":"uuid-0005","message":{"role":"assistant",'
             '"model":"synthetic-model","content":[{"type":"text",'
             '"text":"synthetic"}],"stop_reason":"end_turn",'
             '"usage":{"input_tokens":1,"output_tokens":2}}}',
        style="compact",
        key_order=["agentId", "type", "uuid", "message"],
        envelope_keys_expected=["agentId"],
    ),

    ShapeFixture(
        name="gap_compact_ascii",
        covers="census gap: serializer_style compact_ascii, zero corpus "
               "rows. Non-ASCII escaped as \\uXXXX",
        line='{"type":"user","uuid":"uuid-0006","text":"caf\\u00e9"}',
        style="compact_ascii",
        key_order=["type", "uuid", "text"],
    ),
    ShapeFixture(
        name="gap_spaced_ascii",
        covers="census gap: serializer_style spaced_ascii, zero corpus rows",
        line='{"type": "user", "uuid": "uuid-0007", "text": "caf\\u00e9"}',
        style="spaced_ascii",
        key_order=["type", "uuid", "text"],
    ),
    ShapeFixture(
        name="unicode_unescaped_compact",
        covers="19.66 percent of corpus bodies are non-ASCII and every "
               "one was written with escaping OFF",
        line='{"type":"user","uuid":"uuid-0008","text":"café"}',
        style="compact",
        key_order=["type", "uuid", "text"],
    ),
    ShapeFixture(
        name="unicode_astral_unescaped",
        covers="astral-plane characters above U+FFFF, on 1.22 percent of "
               "corpus bodies, unescaped",
        line='{"type":"user","uuid":"uuid-0009","text":"\U0001D11E"}',
        style="compact",
        key_order=["type", "uuid", "text"],
    ),
    ShapeFixture(
        name="unicode_astral_escaped",
        covers="an astral character under compact_ascii becomes a "
               "SURROGATE PAIR, which is where a naive escaper breaks",
        line='{"type":"user","uuid":"uuid-0010","text":"\\ud834\\udd1e"}',
        style="compact_ascii",
        key_order=["type", "uuid", "text"],
    ),

    ShapeFixture(
        name="gap_not_an_object_array",
        covers="census gap: a line whose top-level JSON is an ARRAY, so "
               "there is no key order to walk",
        line='[1,2,3]',
        style="compact",
        key_order=NOT_AN_OBJECT,
    ),
    ShapeFixture(
        name="gap_not_an_object_string",
        covers="census gap: a bare top-level STRING line",
        line='"a synthetic bare string line"',
        style="compact",
        key_order=NOT_AN_OBJECT,
    ),
    ShapeFixture(
        name="gap_not_an_object_number",
        covers="census gap: a bare top-level NUMBER line",
        line='42',
        style="compact",
        key_order=NOT_AN_OBJECT,
    ),
    ShapeFixture(
        name="gap_not_an_object_null",
        covers="census gap: a bare top-level null, which must not be "
               "confused with an absent body",
        line='null',
        style="compact",
        key_order=NOT_AN_OBJECT,
    ),

    ShapeFixture(
        name="gap_envelope_key_first",
        covers="census gap: an envelope key at position 0. Measured over "
               "the whole corpus, isSidechain is NEVER first, so this "
               "interleaving has no live exemplar",
        line='{"isSidechain":true,"agentId":"a1111111","type":"user",'
             '"uuid":"uuid-0011"}',
        style="compact",
        key_order=["isSidechain", "agentId", "type", "uuid"],
        envelope_keys_expected=["agentId", "isSidechain"],
    ),
    ShapeFixture(
        name="envelope_key_last",
        covers="an envelope key at the FINAL position, which occurs on "
               "474 corpus appearances",
        line='{"type":"user","uuid":"uuid-0012","agentId":"a2222222"}',
        style="compact",
        key_order=["type", "uuid", "agentId"],
        envelope_keys_expected=["agentId"],
    ),
    ShapeFixture(
        name="envelope_only_object",
        covers="a line consisting of nothing BUT an envelope key, so the "
               "stored body is an empty object",
        line='{"isSidechain":false}',
        style="compact",
        key_order=["isSidechain"],
        envelope_keys_expected=["isSidechain"],
    ),
    ShapeFixture(
        name="empty_object",
        covers="an empty object line, whose key order is [] and must not "
               "be confused with the not-an-object sentinel",
        line='{}',
        style="compact",
        key_order=[],
    ),

    ShapeFixture(
        name="gap_content_absent",
        covers="census gap: message present, content key ABSENT",
        line='{"type":"assistant","uuid":"uuid-0013","message":'
             '{"role":"assistant","model":"synthetic-model"}}',
        style="compact",
        key_order=["type", "uuid", "message"],
    ),
    ShapeFixture(
        name="gap_content_null",
        covers="census gap: message.content explicitly null, distinct "
               "from absent",
        line='{"type":"assistant","uuid":"uuid-0014","message":'
             '{"role":"assistant","content":null}}',
        style="compact",
        key_order=["type", "uuid", "message"],
    ),
    ShapeFixture(
        name="gap_content_number",
        covers="census gap: message.content as a number",
        line='{"type":"assistant","uuid":"uuid-0015","message":'
             '{"role":"assistant","content":7}}',
        style="compact",
        key_order=["type", "uuid", "message"],
    ),
    ShapeFixture(
        name="gap_content_object",
        covers="census gap: message.content as an object rather than a "
               "string or array",
        line='{"type":"assistant","uuid":"uuid-0016","message":'
             '{"role":"assistant","content":{"type":"text"}}}',
        style="compact",
        key_order=["type", "uuid", "message"],
    ),
    ShapeFixture(
        name="gap_usage_null",
        covers="census gap: message.usage null, never observed live",
        line='{"type":"assistant","uuid":"uuid-0017","message":'
             '{"role":"assistant","usage":null}}',
        style="compact",
        key_order=["type", "uuid", "message"],
    ),
    ShapeFixture(
        name="gap_non_object_content_block",
        covers="census gap: a content array holding non-object blocks",
        line='{"type":"assistant","uuid":"uuid-0018","message":'
             '{"role":"assistant","content":["bare string block",42]}}',
        style="compact",
        key_order=["type", "uuid", "message"],
    ),
    ShapeFixture(
        name="gap_non_string_block_type",
        covers="census gap: a content block whose type is not a string",
        line='{"type":"assistant","uuid":"uuid-0019","message":'
             '{"role":"assistant","content":[{"type":5}]}}',
        style="compact",
        key_order=["type", "uuid", "message"],
    ),

    ShapeFixture(
        name="nested_key_order_not_alphabetical",
        covers="a NESTED object whose keys are in non-alphabetical order. "
               "This is the exact shape that broke when body storage "
               "sorted keys - the line stays valid JSON and the bytes move",
        line='{"type":"user","uuid":"uuid-0020","payload":'
             '{"z":1,"m":2,"a":0}}',
        style="compact",
        key_order=["type", "uuid", "payload"],
    ),
    ShapeFixture(
        name="deep_nesting",
        covers="ten levels of nesting, the deepest measured in the corpus",
        line='{"type":"user","uuid":"uuid-0021","d":{"d":{"d":{"d":{"d":'
             '{"d":{"d":{"d":1}}}}}}}}',
        style="compact",
        key_order=["type", "uuid", "d"],
    ),
    ShapeFixture(
        name="scalar_types_preserved",
        covers="every JSON scalar type in one line, so an integer cannot "
               "come back as a float or a bool as a number",
        line='{"type":"user","uuid":"uuid-0022","n":0,"f":1.5,"t":true,'
             '"g":false,"z":null}',
        style="compact",
        key_order=["type", "uuid", "n", "f", "t", "g", "z"],
    ),
    ShapeFixture(
        name="string_escapes",
        covers="quote, backslash, newline, tab and a control character "
               "inside a string value",
        line='{"type":"user","uuid":"uuid-0023",'
             '"s":"a\\"b\\\\c\\nd\\te\\u0001f"}',
        style="compact",
        key_order=["type", "uuid", "s"],
    ),
    ShapeFixture(
        name="forward_slash_unescaped",
        covers="a forward slash, which JSON permits escaped or not and "
               "which Python does not escape - a real byte-level trap",
        line='{"type":"user","uuid":"uuid-0024","p":"/a/b"}',
        style="compact",
        key_order=["type", "uuid", "p"],
    ),
)
