
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.agent_manifests import _pattern_safety, engine as agent_engine
from src.plugins.host.plugin_manifest import SidecarManifestError, load_sidecar_manifest

_NB_R11 = "".join(f"{chr(0x10000 + i * 4)}-{chr(0x10002 + i * 4)}" for i in range(11))
_NB_R12 = "".join(f"{chr(0x10000 + i * 4)}-{chr(0x10002 + i * 4)}" for i in range(12))
_NB_R13 = "".join(f"{chr(0x10000 + i * 4)}-{chr(0x10002 + i * 4)}" for i in range(13))
_NB11 = "".join(chr(0x10000 + i * 2) for i in range(11))
_NB12 = "".join(chr(0x10000 + i * 2) for i in range(12))
_NB40 = "".join(chr(0x10000 + i) for i in range(40))
_NB79 = "".join(chr(0x10001 + i) for i in range(79))
_NB80 = "".join(chr(0x10000 + i) for i in range(80))
_NB240 = "".join(chr(0x10000 + i) for i in range(240))

_CHALLENGER_R14_VECTORS = [
    ("nbr11a", rf"[^\W\d\s_{_NB_R11}]+?(?i:sﬅ)"),
    ("nbr11b", rf"^[^\W\d\s_{_NB_R11}]+?[^\W\d\s_{_NB_R11}]+?(?i:si)"),
    ("nb11a", rf"[^\W\d\s_{_NB11}]+?(?i:si)"),
    ("nb11b", rf"[^\W\d\s_{_NB11}]+?(?i:sﬅ)"),
    ("nb11c", rf"(?:[^\W\d\s_{_NB11}]|!)[^\W\d\s_{_NB11}]+?(?i:si)"),
    ("nb11d", rf"(?:[^\W\d\s_{_NB11}]|!)[^\W\d\s_{_NB11}]+?(?i:sﬅ)"),
    ("nb11e", rf"^[^\W\d\s_{_NB11}]+?[^\W\d\s_{_NB11}]+?(?i:si)"),
    ("nb11f", rf"^[^\W\d\s_{_NB11}]+?[^\W\d\s_{_NB11}]+?(?i:sﬅ)"),
    ("nb12a", rf"[^\W\d\s{_NB12}]+?(?i:sﬅ)"),
    ("nbr11c", rf"[^\W\d\s_{_NB_R11}]+?aaab"),
    ("nbr11d", rf"^[^\W\d\s_{_NB_R11}]+?[^\W\d\s_{_NB_R11}]+?aaab"),
    ("nbr11e", rf"[^\W\d\s_{_NB_R11}]+?(?i:ai)"),
    ("nbr11f", rf"[^\W\d\s_{_NB_R11}]+?(?i:aﬅ)"),
    ("nb11g", rf"[^\W\d\s_{_NB11}]+?(?i:aﬅ)"),
    ("u2lj", r"(?:[^\W\d\s_љ]|!)[^\W\d\s_љ]+?(?i:si)"),
]

_EXPLORER_R15_LINEAR_IN_VECTORS = [
    ("posnb40a", rf"[{_NB40}a]+?aaab"),
    ("posnb40b", rf"^[{_NB40}a]+?[{_NB40}a]+?aaab"),
    ("posnb80a", rf"[{_NB80}a]+?aaab"),
    ("posnb80w", rf"[{_NB80}\w]+?aaab"),
    ("posnb80wd2", rf"^[{_NB80}\w]+?[{_NB80}\w]+?aaab"),
    ("posnb79u", rf"[{_NB79}\U00010000]+?aaab"),
    ("posnb240p", rf"abcd[{_NB240}a-d]+?xyz"),
    ("neg1catnb", rf"[^\W{_NB_R13}]+?(?i:sﬅ)"),
    ("neg2catnb1", rf"[^\W\d_{_NB_R11}]+?(?i:sﬅ)"),
    ("neg2catnb2", rf"^[^\W\d_{_NB_R11}]+?[^\W\d_{_NB_R11}]+?(?i:si)"),
    ("neg2catnb3", rf"[^\W\d_{_NB_R12}]+?(?i:sﬅ)"),
    ("neg2catnb4", rf"[^\W\d{_NB_R12}]+?(?i:sﬅ)"),
    ("neg2catnb5", rf"[^\W\s_{_NB_R12}]+?(?i:sﬅ)"),
    ("neg3catbig", r"(?:[^\W\d\s_\u0459\u045a\u045b]|!)[^\W\d\s_\u0459\u045a\u045b]+?(?i:sﬅ)"),
    ("branchnb", r"(?:a|[\U0001f680-\U0001f68f])+?aaab"),
    ("seqnb", r"(?:a[\U0001f680\U0001f681])+?aaab"),
    ("subpatnb", r"(?:(?:[\U0001f680-\U0001f68f]))+?aaab"),
    ("partanchnb", r"(?:^a|[\U0001f680\U0001f681]+?)aaab"),
    ("optnestnb", r"(?:[\U0001f680\U0001f681]+?)?aaab"),
]


def _assert_rejected_everywhere(tmp_path: Path, plug_id: str, pattern: str) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=False)

    toml_text = (
        f'id = "{plug_id}"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"line_regex = [{json.dumps(pattern, ensure_ascii=False)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)

    code = tmp_path / "code" / plug_id
    code.mkdir(parents=True, exist_ok=True)
    (code / "rules.toml").write_text(toml_text, encoding="utf-8")
    (code / "carnivore.toml").write_text(
        f'schema = 2\nid = "{plug_id}"\nname = "H"\nversion = "1.0.0"\nkind = "plugin"\n'
        'description = "linear-IN reject check"\nauthor = "Tester"\n'
        '[harnesses]\nfiles = ["rules.toml"]\n',
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError, match="rules\\.toml|linear|broad|unanchored|overlapping"):
        load_sidecar_manifest(code, plug_id)


@pytest.mark.parametrize(("plug_id", "pattern"), _CHALLENGER_R14_VECTORS)
def test_rejects_all_15_challenger_r14_linear_in_vectors(
    tmp_path: Path, plug_id: str, pattern: str
) -> None:
    _assert_rejected_everywhere(tmp_path, plug_id, pattern)


@pytest.mark.parametrize(("plug_id", "pattern"), _EXPLORER_R15_LINEAR_IN_VECTORS)
def test_rejects_explorer_r15_positive_and_negated_linear_in_vectors(
    tmp_path: Path, plug_id: str, pattern: str
) -> None:
    _assert_rejected_everywhere(tmp_path, plug_id, pattern)


def test_rejects_synthetic_duplicate_category_in_ast() -> None:
    max_rep = _pattern_safety._sre_constants.MAXREPEAT
    dup_cat_ast = [
        (
            "MAX_REPEAT",
            (1, max_rep, [("IN", [("CATEGORY", "CATEGORY_WORD"), ("CATEGORY", "CATEGORY_WORD")])]),
        ),
        ("LITERAL", 97),
    ]
    with pytest.raises(agent_engine.RuleFileError, match="linear"):
        _pattern_safety.validate_pattern_ast(
            dup_cat_ast, "[\\w\\w]+a", whole_region=False, error_cls=agent_engine.RuleFileError
        )

    dup_cat_d2_ast = [
        ("AT", "AT_BEGINNING"),
        ("MAX_REPEAT", (1, max_rep, [("IN", [("CATEGORY", "CATEGORY_WORD"), ("CATEGORY", "CATEGORY_WORD")])])),
        ("MAX_REPEAT", (1, max_rep, [("IN", [("CATEGORY", "CATEGORY_WORD")])])),
    ]
    with pytest.raises(agent_engine.RuleFileError, match="broad overlapping"):
        _pattern_safety.validate_pattern_ast(
            dup_cat_d2_ast, "^[\\w\\w]+\\w+", whole_region=False, error_cls=agent_engine.RuleFileError
        )


@pytest.mark.parametrize(
    ("plug_id", "pattern", "sample"),
    [
        ("posrocket", r"^[\U0001f680]+", "\U0001f680\U0001f680"),
        ("posminneg", r"^[^\W\d_]+$", "alpha"),
        ("pos3cat", r"^[^\W\d\s]+$", "alpha_"),
        ("pos3catnb", r"^[^\W\d\s_\U00010000]+$", "alpha"),
        ("posprefix", r"abcd\w+!", "abcdxyz!"),
        ("poscursor", r"^\s*(⬡|⬢|[\u2800-\u28FF]+)\s+[^\W\d_]+\w*ing\b", "  ⬡ Thinking"),
    ],
)
def test_allows_positive_controls_everywhere(
    tmp_path: Path, plug_id: str, pattern: str, sample: str
) -> None:
    compiled = agent_engine.compile_pattern(pattern, whole_region=False)
    assert compiled.search(sample) is not None

    toml_text = (
        f'id = "{plug_id}"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"line_regex = [{json.dumps(pattern, ensure_ascii=False)}]\n"
    )
    manifest = agent_engine.parse_manifest(toml_text)
    assert manifest is not None
    match = agent_engine.evaluate(manifest, sample)
    assert match is not None and match.state == "working"

    code = tmp_path / "code" / plug_id
    code.mkdir(parents=True)
    (code / "rules.toml").write_text(toml_text, encoding="utf-8")
    (code / "carnivore.toml").write_text(
        f'schema = 2\nid = "{plug_id}"\nname = "Pos"\nversion = "1.0.0"\nkind = "plugin"\n'
        'description = "positive control"\nauthor = "Tester"\n'
        '[harnesses]\nfiles = ["rules.toml"]\n',
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(code, plug_id)
    assert sm.harnesses == ("rules.toml",)


def test_cursor_toml_line61_spinner_working_positive_control() -> None:
    cursor_path = Path(agent_engine.RULES_DIR) / "cursor.toml"
    manifest = agent_engine.parse_manifest(cursor_path.read_text(encoding="utf-8"))
    assert manifest is not None
    match = agent_engine.evaluate(manifest, "  ⬡ Generating response")
    assert match is not None
    assert match.rule == "spinner_working"
    assert match.state == "working"
