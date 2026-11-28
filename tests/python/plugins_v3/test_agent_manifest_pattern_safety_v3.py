
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from src.core.agent_manifests import _pattern_safety, engine as agent_engine
from src.plugins.host.plugin_manifest import SidecarManifestError, load_sidecar_manifest


@pytest.mark.parametrize(
    ("pattern", "whole_region"),
    [
        (r"^[^\x00-\xff\u017f\u1e9e-\u2c00\ufb01\u0500]+[^\x00-\xff\u017f\u1e9e-\u2c00\ufb01\u0501]+!$", True),
        (r"^[\u0300-\u031f]+[^\x00-\xff\u017f\u1e9e-\u2c00\ufb01\u0300\u030f\u031f]+!$", True),
        (
            r"^[^\x00-\u2c00\ufb01\ufb02]+[^\x00-\u2c00\ufb01\ufb03]+[^\x00-\u2c00\ufb01\ufb02]+[^\x00-\u2c00\ufb01\ufb03]+[^\x00-\u2c00\ufb01\ufb02]+!$",
            False,
        ),
        (r"^[\u0300-\u031f]+[^\x00-\xff\u017f\u1e9e-\u2c00\ufb01\u0300\u030f\u031f]+!$", False),
        (r"(?i)^ı+i+ı+i+!$", False),
        (r"(?i)^ı+i+ı+i+!$", True),
        (r"^(?i:ı)+i+ı+i+!$", False),
        (r"^(?i:ı)+i+ı+i+!$", True),
        (r"(?i)^ﬅ+ﬆ+ﬅ+ﬆ+!$", False),
        (r"(?i)^ﬅ+ﬆ+ﬅ+ﬆ+!$", True),
        (r"^(?i:ﬅ)+ﬆ+ﬅ+ﬆ+!$", False),
        (r"(?i)^ᲀ+в+ᲀ+в+!$", False),
        (r"^(?i:ᲀ)+в+ᲀ+в+!$", False),
    ],
)
def test_agent_manifest_rejects_r4_negate_range_and_extra_casefix_vectors(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError, match="overlapping repeats"):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)


@pytest.mark.parametrize(
    ("field_name", "pattern"),
    [
        ("regex", r"^[^\x00-\xff\u017f\u1e9e-\u2c00\ufb01\u0500]+[^\x00-\xff\u017f\u1e9e-\u2c00\ufb01\u0501]+!$"),
        ("line_regex", r"(?i)^ﬅ+ﬆ+ﬅ+ﬆ+!$"),
        ("line_regex", r"^(?i:ﬅ)+ﬆ+ﬅ+ﬆ+!$"),
    ],
)
def test_tier0_sidecar_load_rejects_r4_and_extra_casefix_harness_patterns(
    tmp_path: Path, field_name: str, pattern: str
) -> None:
    code = tmp_path / "code" / "r4harness"
    code.mkdir(parents=True)
    (code / "evade.toml").write_text(
        f'id = "evade"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field_name} = [{json.dumps(pattern)}]\n",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "r4harness"
name = "R4 Harness"
version = "1.0.0"
kind = "plugin"
description = "Rejects R4 probe evasion and _EXTRA_CASES vectors"
author = "Tester"

[harnesses]
files = ["evade.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError, match="overlapping repeats"):
        load_sidecar_manifest(code, "r4harness")


@pytest.mark.parametrize(
    ("pattern", "whole_region"),
    [
        (
            r"[^\W]*?(?:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)?"
            r"(?:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)?"
            r"(?:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)?"
            r"(?:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)?!",
            False,
        ),
        (r"[^\W]*?(?:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)?!", False),
        (r"a*?(?:a|aa)(?:a|aa)(?:a|aa)(?:a|aa)!", False),
        (r"(?s)(?:[ab]*?|[\w\d]?)(?:A+?|[ab])\u212a*\s?x\Z", False),
        (r"^\w+\w+(?:a|aa)(?:a|aa)!", False),
        (r"^\w+\w+(?:a|aa)!", False),
        (r"^\w+\w+" + "a" * 50 + "!", False),
        (r"(?s)a*?.??b*c*d*!", False),
        (r"a*b*c*d*e*f*g*h*!", False),
        (
            r"a{1,8}(?:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)?"
            r"(?:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)?"
            r"(?:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)?"
            r"(?:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)?!",
            True,
        ),
    ],
)
def test_agent_manifest_rejects_r5_unanchored_and_d2_branching_redos(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)

    field = "regex" if whole_region else "line_regex"
    toml_text = (
        f'id = "r5"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field} = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


def test_agent_manifest_allows_shipped_unanchored_and_d2_patterns() -> None:
    assert agent_engine.compile_pattern(r"(?i)opencode.*esc (again to )?interrupt", whole_region=False)
    assert agent_engine.compile_pattern(r"(■|⬝){4,}", whole_region=True)
    assert agent_engine.compile_pattern(r"(?i)\b[1-9][0-9]*\s+background\s+tasks?\b", whole_region=False)
    assert agent_engine.compile_pattern(r"(?i)^\s*(?:→\s*)?run .*\(y\)", whole_region=False)
    assert agent_engine.compile_pattern(r"^\s*(⬡|⬢|[\u2800-\u28FF]+)\s+[^\W\d_]+\w*ing\b", whole_region=False)


@pytest.mark.parametrize(
    ("pattern", "whole_region"),
    [
        (r"(?i)^\s*(?:a|aa|aaa)[ab]+[^\W]+" + r"[^\W]" * 15 + "!", False),
        (r"^(?:a|aa|aaa)\w+\w+" + r"\w" * 15 + "!", False),
        (r"(?s)^(?:a|aa|aaa)a+\w+" + r"\w" * 10 + "!", False),
        (r"^\w+\w+" + r"[^\W]" * 15 + "!", False),
        (r"^[^\W]+[^\W]+" + r"[^\W]" * 15 + "!", False),
        (r"^\w+\w+" + r"\w" * 15 + "!", False),
        (r"abcd[^\W]*?(?:" + r"\w" * 110 + ")?!", False),
        (r"abcd.*(?:" + r"\w" * 115 + ")?!", False),
        (r"abcd.*" + r"\w" * 100 + "!", False),
        (r"abcd.*(?:" + r"\w" * 50 + "|" + r"\w" * 51 + ")!", False),
        (r"\w*?" + r"[^\W]" * 12 + "!", False),
        (r"[^\W]*?" + r"[^\W]" * 12 + "!", False),
        (r"[^\W]*?" + "a" * 12 + "!", False),
        (r"(?:a|aa)\w*?[^\W]!", False),
        (r"(?i)(?:a|aa)[^\W\d_]+\s[^\W]{3}!", False),
    ],
)
def test_agent_manifest_rejects_r6_weighted_and_branching_redos(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)

    field = "regex" if whole_region else "line_regex"
    toml_text = (
        f'id = "r6"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field} = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


@pytest.mark.parametrize(
    ("field_name", "pattern"),
    [
        ("line_regex", r"(?i)^\s*(?:a|aa|aaa)[ab]+[^\W]+" + r"[^\W]" * 15 + "!"),
        ("line_regex", r"^\w+\w+" + r"[^\W]" * 15 + "!"),
        ("line_regex", r"abcd[^\W]*?(?:" + r"\w" * 110 + ")?!"),
        ("line_regex", r"\w*?" + r"[^\W]" * 12 + "!"),
    ],
)
def test_tier0_sidecar_load_rejects_r6_redos_harness_patterns(
    tmp_path: Path, field_name: str, pattern: str
) -> None:
    code = tmp_path / "code" / "r6harness"
    code.mkdir(parents=True)
    (code / "r6.toml").write_text(
        f'id = "r6h"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field_name} = [{json.dumps(pattern)}]\n",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "r6harness"
name = "R6 Harness"
version = "1.0.0"
kind = "plugin"
description = "Rejects R6 ReDoS bypass vectors"
author = "Tester"

[harnesses]
files = ["r6.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "r6harness")


def test_agent_manifest_allows_all_9_shipped_rules_toml() -> None:
    rules_dir = Path(agent_engine.RULES_DIR)
    rule_files = sorted(rules_dir.glob("*.toml"))
    assert len(rule_files) == 9

    def _compile_gate_patterns(raw_gate: dict) -> int:
        compiled = 0
        for pat in raw_gate.get("regex", ()):
            assert agent_engine.compile_pattern(pat, whole_region=True)
            compiled += 1
        for pat in raw_gate.get("line_regex", ()):
            assert agent_engine.compile_pattern(pat, whole_region=False)
            compiled += 1
        for nested_key in ("all", "any", "not"):
            for sub in raw_gate.get(nested_key, ()):
                compiled += _compile_gate_patterns(sub)
        return compiled

    total_compiled = 0
    for path in rule_files:
        text = path.read_text(encoding="utf-8")
        manifest = agent_engine.parse_manifest(text)
        assert manifest is not None, f"{path.name} unexpectedly skipped"
        assert manifest.rules, f"{path.name} produced no rules"
        raw = tomllib.loads(text)
        for rule in raw.get("rules", ()):
            total_compiled += _compile_gate_patterns(rule)
    assert total_compiled >= 14


@pytest.mark.parametrize(
    ("pattern", "whole_region"),
    [
        (
            r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?"
            r"[^\W\d_bcdefghijklmnopqrs][^\W\d_bcdefghijklmnopqrs]$",
            False,
        ),
        (r"^[^\W\d_]+?[^\W\d_]+?[^\W\d_][^\W\d_]$", False),
        (
            r"^[^\W\d_\W\d_\W\d_\W\d_\W\d_]+?[^\W\d_\W\d_\W\d_\W\d_\W\d_]+?"
            r"[^\W\d_\W\d_\W\d_\W\d_\W\d_][^\W\d_\W\d_\W\d_\W\d_\W\d_]$",
            False,
        ),
        (r"^[^\W\d_]+[^\W\d_]+[^\W\d_][^\W\d_]$", False),
        (
            "^(?:\u00e1|b|c|d|e|f|g|h|i|j|k|l|m|n|o|p)"
            + r"[^\W\d_]+?[^\W\d_]+?[^\W\d_][^\W\d_]$",
            False,
        ),
    ],
)
def test_agent_manifest_rejects_r7_d2_negated_multicat_redos(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)

    field = "regex" if whole_region else "line_regex"
    toml_text = (
        'id = "r7"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field} = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


@pytest.mark.parametrize(
    ("field_name", "pattern"),
    [
        (
            "line_regex",
            r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?"
            r"[^\W\d_bcdefghijklmnopqrs][^\W\d_bcdefghijklmnopqrs]$",
        ),
        ("line_regex", r"^[^\W\d_]+?[^\W\d_]+?[^\W\d_][^\W\d_]$"),
        (
            "line_regex",
            r"^[^\W\d_\W\d_\W\d_\W\d_\W\d_]+?[^\W\d_\W\d_\W\d_\W\d_\W\d_]+?"
            r"[^\W\d_\W\d_\W\d_\W\d_\W\d_][^\W\d_\W\d_\W\d_\W\d_\W\d_]$",
        ),
    ],
)
def test_tier0_sidecar_load_rejects_r7_d2_negated_multicat_harness_patterns(
    tmp_path: Path, field_name: str, pattern: str
) -> None:
    code = tmp_path / "code" / "r7harness"
    code.mkdir(parents=True)
    (code / "r7.toml").write_text(
        'id = "r7h"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field_name} = [{json.dumps(pattern)}]\n",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "r7harness"
name = "R7 Harness"
version = "1.0.0"
kind = "plugin"
description = "Rejects R7 d==2 negated multi-category ReDoS vectors"
author = "Tester"

[harnesses]
files = ["r7.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "r7harness")


@pytest.mark.parametrize(
    ("pattern", "whole_region"),
    [
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + r"\B" * 5 + "aaaa$", False),
        (r"^[^\W\d_]+?[^\W\d_]+?" + r"\B" * 10 + "aaaa$", False),
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + r"\B" * 10 + "$", False),
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + r"\B" * 10 + "aaaa$", False),
        (r"(?i)abcd[^\W\d_xyz]*?" + r"\B" * 80 + "aaaa$", False),
        (r"^(?:a\B{20})+?(?:a\B{20})+?$", False),
        (r"^[^\W\d_]+?[^\W\d_]+?" + r"\B" * 20 + "$", False),
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + r"\B" * 50 + "aaaa$", False),
        (r"(?i)[^\W\d_bcdefghijklmnopqrs]*?" + r"\B" * 50 + "aaab", False),
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + r"\B" * 80 + "$", False),
        (r"^a+?a+?" + r"\B" * 100 + "$", False),
        (r"^[^\W\d_]+?[^\W\d_]+?" + r"\B" * 100 + "$", False),
        (r"[^\W\d_]*?" + r"\B" * 100 + "aaab", False),
        (r"(?i)[^\W\d_bcdefghijklmnopqrs]*?aaa\B$", False),
        (r"(?i)[^\W\d_bcdefghijklmnopqrs]*?" + r"\B" * 100 + "b", False),
        (r"(?i)[^\W\d_bcdefghijklmnopqrs]*?a" + r"\B" * 10 + "b", False),
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + "()" * 10 + "$", False),
        ("(?i)^" + "(" * 30 + r"[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + ")" * 30 + "aaaa$", False),
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + "()" * 20 + "$", False),
        ("^" + "(" * 60 + "a+?" + ")" * 60 + "(" * 60 + "a+?" + ")" * 60 + "$", False),
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + "(" * 30 + "a" + ")" * 30 + "$", False),
        ("^" + "(" * 100 + "a+?a+?" + ")" * 100 + "aaaa$", False),
        (r"[^\W\d_]*?" + "(" * 90 + "aaab" + ")" * 90, False),
        (r"^a+?a+?" + "(" * 100 + "a" + ")" * 100 + "$", False),
        (r"^a+?a+?" + "()" * 100 + "$", False),
        (r"[^\W\d_]*?" + "()" * 100 + "aaab", False),
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?(a)(a)(a)(a)$", False),
        (r"(?i)^((((" + r"[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + "))))aaaa$", False),
    ],
)
def test_agent_manifest_rejects_r8_at_and_capturing_subpattern_redos(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)

    field = "regex" if whole_region else "line_regex"
    toml_text = (
        'id = "r8"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field} = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


@pytest.mark.parametrize(
    ("field_name", "pattern"),
    [
        ("line_regex", r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + r"\B" * 5 + "aaaa$"),
        ("line_regex", r"^[^\W\d_]+?[^\W\d_]+?" + r"\B" * 100 + "$"),
        ("line_regex", r"[^\W\d_]*?" + r"\B" * 100 + "aaab"),
        ("line_regex", r"(?i)abcd[^\W\d_xyz]*?" + r"\B" * 80 + "aaaa$"),
        ("line_regex", r"^(?:a\B{20})+?(?:a\B{20})+?$"),
        ("line_regex", r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + r"\B" * 10 + "aaaa$"),
        ("line_regex", r"^a+?a+?" + "(" * 100 + "a" + ")" * 100 + "$"),
        ("line_regex", r"(?i)^[^\W\d_bcdefghijklmnopqrs]+?[^\W\d_bcdefghijklmnopqrs]+?" + "()" * 10 + "$"),
        ("line_regex", "^" + "(" * 100 + "a+?a+?" + ")" * 100 + "aaaa$"),
        ("line_regex", "^" + "(" * 60 + "a+?" + ")" * 60 + "(" * 60 + "a+?" + ")" * 60 + "$"),
        ("line_regex", r"[^\W\d_]*?" + "()" * 100 + "aaab"),
    ],
)
def test_tier0_sidecar_load_rejects_r8_at_and_capturing_subpattern_harness_patterns(
    tmp_path: Path, field_name: str, pattern: str
) -> None:
    code = tmp_path / "code" / "r8harness"
    code.mkdir(parents=True)
    (code / "r8.toml").write_text(
        'id = "r8h"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field_name} = [{json.dumps(pattern)}]\n",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "r8harness"
name = "R8 Harness"
version = "1.0.0"
kind = "plugin"
description = "Rejects R8 AT and capturing SUBPATTERN ReDoS vectors"
author = "Tester"

[harnesses]
files = ["r8.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "r8harness")


@pytest.mark.parametrize(
    ("pattern", "whole_region"),
    [
        (r"(?is)([^\W\d_xyz])*(?:\B)?ab", False),
        (r"(?a)([^\W\d_xyz])*(?:\B)?ab", False),
        (r"(?ia)\B([^\W\d_bcdefghijklmnopqrs])+?(?:\b)?aaab", False),
        (r"(?i)([^\W\d_bcdefghijklmnopqrs])*(?:\B)?ab", False),
        (r"([^\W\d_])*?(?:\B)?ab", False),
        (r"(?i)([^\W\d_" + r"\W" * 55 + r"])*?(?:\B)?ab", False),
        (r"(?i)([^\W\d_bcdefghijklmnopqrs])*(?:\b)?aab", False),
        (r"(a)*(?:\B)?ab", False),
        (r"(a)*?(?:\B)?ab", False),
        (r"(?i)[^\W\d_bcdefghijklmnopqrs]*?(?:\B)?ab", False),
        (r"[^\W\d_]*?(?:\B)?ab", False),
        (r"(?i)[^\W\d_bcdefghijklmnopqrs]*?(?:\b)?aab", False),
        (r"(?i)([^\W\d_bcdefghijklmnopqrs])*(?:!)?aaab", False),
        (r"(?i)([^\W\d_])+?(?:\B)?a$", False),
        (r"(?i)([^\W\d_bcdefghijklmnopqrs])*(?:\B|\B)ab", False),
        (r"(?i)([^\W\d_bcdefghijklmnopqrs])*?(?:\B|\b)ab", False),
        (r"([^\W\d_])*?(?:\B|\b)ab", False),
        (r"(?i)[^\W\d_bcdefghijklmnopqrs]*?(?:\B|\B)ab", False),
        (r"(?i)[^\W\d_bcdefghijklmnopqrs]*?(?:\B|\b)ab", False),
        (r"(?i)([^\W\d_bcdefghijklmnopqrs])*(?:!|@)aaab", False),
        (r"(?i)^[^\W\d_bcdefghijklmnopqrs]+([^\W\d_bcdefghijklmnopqrs])+aaab", False),
        (r"^[^\W\d_]+([^\W\d_])+aaab", False),
        (r"(?i)([^\W\d_bcdefghijklmnopqrs])*aab", False),
        (r"(?i)[^\W\d_bcdefghijklmnopqrs]*?\wb", False),
        (r"(?i)abcd[^\W\d_]*?(abcd)?(abcd)?(abcd)?x", False),
        (r"(?ia)[^\W\d_xyz]+?\s+b*\Zabcd", False),
        (r"^([^\W\d_]+\w*)ing\b", False),
    ],
)
def test_agent_manifest_rejects_r9_r10_redos_vectors(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)

    field = "regex" if whole_region else "line_regex"
    toml_text = (
        'id = "r9r10"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field} = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


@pytest.mark.parametrize(
    ("field_name", "pattern"),
    [
        ("line_regex", r"(?is)([^\W\d_xyz])*(?:\B)?ab"),
        ("line_regex", r"(?i)([^\W\d_bcdefghijklmnopqrs])*(?:\B)?ab"),
        ("line_regex", r"(?i)([^\W\d_" + r"\W" * 55 + r"])*?(?:\B)?ab"),
        ("line_regex", r"([^\W\d_])*?(?:\B)?ab"),
        ("line_regex", r"(?i)([^\W\d_bcdefghijklmnopqrs])*(?:\b)?aab"),
        ("line_regex", r"(a)*(?:\B)?ab"),
        ("line_regex", r"(?i)[^\W\d_bcdefghijklmnopqrs]*?(?:\B)?ab"),
        ("line_regex", r"(?i)([^\W\d_bcdefghijklmnopqrs])*(?:\B|\B)ab"),
        ("line_regex", r"(?i)[^\W\d_bcdefghijklmnopqrs]*?(?:\b)?aab"),
        ("line_regex", r"(?i)([^\W\d_bcdefghijklmnopqrs])*(?:!)?aaab"),
        ("line_regex", r"(?i)^[^\W\d_bcdefghijklmnopqrs]+([^\W\d_bcdefghijklmnopqrs])+aaab"),
        ("line_regex", r"(?i)([^\W\d_bcdefghijklmnopqrs])*aab"),
        ("line_regex", r"(?i)[^\W\d_bcdefghijklmnopqrs]*?\wb"),
        ("line_regex", r"(?i)abcd[^\W\d_]*?(abcd)?(abcd)?(abcd)?x"),
        ("line_regex", r"(?ia)[^\W\d_xyz]+?\s+b*\Zabcd"),
        ("line_regex", r"^([^\W\d_]+\w*)ing\b"),
    ],
)
def test_tier0_sidecar_load_rejects_r9_r10_harness_patterns(
    tmp_path: Path, field_name: str, pattern: str
) -> None:
    code = tmp_path / "code" / "r9harness"
    code.mkdir(parents=True)
    (code / "r9.toml").write_text(
        'id = "r9h"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field_name} = [{json.dumps(pattern)}]\n",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "r9harness"
name = "R9 R10 Harness"
version = "1.0.0"
kind = "plugin"
description = "Rejects R9 and R10 ReDoS vectors"
author = "Tester"

[harnesses]
files = ["r9.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "r9harness")


@pytest.mark.parametrize(
    "pattern",
    [
        r"a(?=b)",
        r"(?:a(?=b))+",
        r"^a+a+(?=b)",
        r"a(?!b)",
        r"(?:a(?!b))?",
        r"(?<=a)b",
        r"(?<!a)b",
        r"(?>a+)b",
        r"(?:(?>a))+",
        r"(a)\1",
        r"(a)(?:\1)?",
        r"(a)(?(1)b|c)",
    ],
)
def test_agent_manifest_rejects_unsupported_re_opcodes(tmp_path: Path, pattern: str) -> None:
    with pytest.raises(agent_engine.RuleFileError, match="unsupported regex construct"):
        agent_engine.compile_pattern(pattern)

    toml_text = (
        'id = "op"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"line_regex = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError, match="unsupported regex construct"):
        agent_engine.parse_manifest(toml_text)

    code = tmp_path / "code" / "opharness"
    code.mkdir(parents=True)
    (code / "op.toml").write_text(toml_text, encoding="utf-8")
    (code / "carnivore.toml").write_text(
        'schema = 2\nid = "opharness"\nname = "Op"\nversion = "1.0.0"\nkind = "plugin"\ndescription = "d"\nauthor = "T"\n[harnesses]\nfiles = ["op.toml"]\n',
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError, match="unsupported regex construct"):
        load_sidecar_manifest(code, "opharness")


def test_pattern_safety_rejects_unknown_in_subopcode_at_code_and_category() -> None:
    with pytest.raises(agent_engine.RuleFileError, match="unsupported regex IN sub-opcode"):
        _pattern_safety.validate_pattern_ast(
            [("IN", [("UNKNOWN_SUBOP", 1)])], "fake", error_cls=agent_engine.RuleFileError
        )
    with pytest.raises(agent_engine.RuleFileError, match="unsupported regex category"):
        _pattern_safety.validate_pattern_ast(
            [("IN", [("CATEGORY", "CATEGORY_UNKNOWN")])], "fake", error_cls=agent_engine.RuleFileError
        )
    with pytest.raises(agent_engine.RuleFileError, match="unsupported regex assertion"):
        _pattern_safety.validate_pattern_ast(
            [("AT", "AT_UNKNOWN")], "fake", error_cls=agent_engine.RuleFileError
        )


_HEAVY_CLASS = r"[^\W\d_bcdefghijklmnopqrs]"


@pytest.mark.parametrize(
    ("pattern", "whole_region"),
    [
        (r"(?i)[a-f]*[g-l]*[m-r]*[s-x]*\bzzz", False),
        (r"(?i)[a-f]*[g-h]*[i-j]*[k-l]*zzzz", False),
        (r"(?i)[a-f]*[g-l]*[m-r]*[s-x]*zzzz", False),
        (r"(?i)(?:a|b)[ab]*[cd]*[ef]*[gh]*zzzz", False),
        (r"(?i)[a-f]*[g-l]*[m-r]*[s-x]*!", False),
        (r"(?i)[a-p]*[q-z]*[0-9]*[!@#]*zzzz", False),
        (r"(?i)[acegikmoqsuwy]*[bdfhjlnprtvxz]*[0-9]*[!@#]*zzzz", False),
        (r"(?i)(?:a|c|e|g|i|k|m|o)*[b]*[d]*[f]*zzzz", False),
        (r"(?i)a*b*c*d*zzzz", False),
        (r"[a-f]*[g-l]*[m-r]*[s-x]*zzzz", False),
        (r"(?i)[a-f]*[g-l]*", False),
        (r"(?i)[a-f]*\s+[a-f]*zzzz", False),
        (r"(?i)[a-f]*[g-l]+zzzz", False),
        (f"(?i)(?:(?:{_HEAVY_CLASS}*?){{1}}?){{1}}?a{{1}}?a{{1}}?ab", False),
        (f"(?i)^({_HEAVY_CLASS}+)(?:(?:(?:(?:{_HEAVY_CLASS}+?){{1}}?){{1}}?){{1}}?){{1}}?aaab", False),
        (f"(?i)^{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?a{{1}}?a{{1}}?a{{1}}?b{{1}}?", False),
        (f"(?i){_HEAVY_CLASS}*?a{{1}}?a{{1}}?a{{1}}?b{{1}}?", False),
        (r"(?:(?:(?:(?:[a-z]*[0-9]*[A-Z]*[_]*){1}?){1}?){1}?){1}?zzzz", False),
        (r"(?:(?:(?:(?:[a-z]*[0-9]*[A-Z]*[_]*){1}){1}){1}){1}zzzz", False),
        (f"(?i)(?:(?:{_HEAVY_CLASS}*?){{1}}){{1}}a{{1}}a{{1}}ab", False),
        (f"(?i)(?:(?:(?:(?:{_HEAVY_CLASS}*?){{1}}?){{1}}?){{1}}?){{1}}?aaab", False),
        (f"(?i)^(?:(?:(?:(?:{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?){{1}}?){{1}}?){{1}}?){{1}}?aaab", False),
        (f"(?i)^{_HEAVY_CLASS}+?(?:(?:(?:(?:{_HEAVY_CLASS}+?){{1}}?){{1}}?){{1}}?){{1}}?aaab", False),
        (f"(?i)(?:(?:(?:{_HEAVY_CLASS}*?){{1}}?){{1}}?){{1}}?aaab", False),
        (f"(?i)(?:(?:(?:(?:{_HEAVY_CLASS}*?){{1}}){{1}}){{1}}){{1}}aaab", False),
        (f"(?i)(?:(?:(?:{_HEAVY_CLASS}*?){{1}}){{1}}){{1}}aaab", False),
        (r"(?i)a*[_]*[0-9]*[h-n]*a{1}?a{1}?a{1}?b{1}?", False),
        (r"(?i)[b-g]*a*[h-n]*a{1}?a{1}?a{1}?b{1}?", False),
        (r"(?a)a*[A-Z]*[h-n]*[b-g]*a{1}?a{1}?a{1}?b{1}?", False),
        (r"(?i)[a-z]*[0-9]*a{1}?a{1}?a{1}?b{1}?", False),
        (r"(?i)(?:(?:(?:a*[h-n]*[_]*[b-g]*){1}?){1}){1}zzzz", False),
        (r"(?i)^(?:a|b|c|d|e|f|g|h)(?:(?:(?:(?:(a)*[^\W\d_xyz]*){1}?){1}){1}){1}?aab\Z", False),
        (r"(?is)^(?:(?:(?:\w)+?[^\W\d_]+?){1}){1}?a{1}a{1}?b", False),
        (r"(?i)a*a{1}+b", False),
        (r"a{0}b", False),
    ],
)
def test_agent_manifest_rejects_r10_simple_greedy_chains_and_unit_quantifier_redos(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)

    field = "regex" if whole_region else "line_regex"
    toml_text = (
        'id = "r10"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field} = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


@pytest.mark.parametrize(
    ("field_name", "pattern"),
    [
        ("line_regex", r"(?i)[a-f]*[g-l]*[m-r]*[s-x]*\bzzz"),
        ("line_regex", r"(?i)[a-f]*[g-h]*[i-j]*[k-l]*zzzz"),
        ("line_regex", r"(?i)(?:a|b)[ab]*[cd]*[ef]*[gh]*zzzz"),
        ("line_regex", r"(?i)(?:a|c|e|g|i|k|m|o)*[b]*[d]*[f]*zzzz"),
        ("line_regex", r"(?i)a*[_]*[0-9]*[h-n]*a{1}?a{1}?a{1}?b{1}?"),
        ("line_regex", f"(?i)(?:(?:{_HEAVY_CLASS}*?){{1}}?){{1}}?a{{1}}?a{{1}}?ab"),
        ("line_regex", f"(?i)^({_HEAVY_CLASS}+)(?:(?:(?:(?:{_HEAVY_CLASS}+?){{1}}?){{1}}?){{1}}?){{1}}?aaab"),
        ("line_regex", f"(?i)^{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?a{{1}}?a{{1}}?a{{1}}?b{{1}}?"),
        ("line_regex", f"(?i){_HEAVY_CLASS}*?a{{1}}?a{{1}}?a{{1}}?b{{1}}?"),
        ("line_regex", r"(?:(?:(?:(?:[a-z]*[0-9]*[A-Z]*[_]*){1}?){1}?){1}?){1}?zzzz"),
        ("line_regex", r"(?:(?:(?:(?:[a-z]*[0-9]*[A-Z]*[_]*){1}){1}){1}){1}zzzz"),
        ("line_regex", f"(?i)^(?:(?:(?:(?:{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?){{1}}?){{1}}?){{1}}?){{1}}?aaab"),
        ("line_regex", r"(?i)a*a{1}+b"),
    ],
)
def test_tier0_sidecar_load_rejects_r10_simple_greedy_and_unit_quantifier_patterns(
    tmp_path: Path, field_name: str, pattern: str
) -> None:
    code = tmp_path / "code" / "r10harness"
    code.mkdir(parents=True)
    (code / "r10.toml").write_text(
        'id = "r10h"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field_name} = [{json.dumps(pattern)}]\n",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "r10harness"
name = "R10 Harness"
version = "1.0.0"
kind = "plugin"
description = "Rejects R10 simple_greedy chains and {1}/{1}? ReDoS vectors"
author = "Tester"

[harnesses]
files = ["r10.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "r10harness")


_R11_BRANCH_OPTIONAL_VECTORS = [
    (f"(?i)^({_HEAVY_CLASS}+?)(?:" + "|".join([f"{_HEAVY_CLASS}+?"] * 7) + ")aaab", False),
    (f"(?i)^{_HEAVY_CLASS}+?(?:" + "|".join([f"{_HEAVY_CLASS}+?"] * 7) + ")aaab", False),
    (f"(?i)^{_HEAVY_CLASS}+(?:" + "|".join([f"{_HEAVY_CLASS}+"] * 7) + ")aaab", False),
    (r"(?i)^[^\W\d_]+?(?:" + "|".join([r"[^\W\d_]+?"] * 7) + ")aaab", False),
    (
        f"(?i)^{_HEAVY_CLASS}+?(?:(?:{_HEAVY_CLASS}+?|{_HEAVY_CLASS}+?)|"
        f"(?:{_HEAVY_CLASS}+?|{_HEAVY_CLASS}+?))aaab",
        False,
    ),
    (f"(?i)^{_HEAVY_CLASS}+?(?:" + "|".join([f"{_HEAVY_CLASS}++"] * 7) + ")aaab", False),
    (r"^(?i:[a-z]+)(?i:[a-z]+|[a-z]+|[a-z]+|[a-z]+|[a-z]+|[a-z]+|[a-z]+)zzzz", False),
    (r"^(?a:\w+?)(?:\w+?|\w+?|\w+?|\w+?|\w+?|\w+?|\w+?)zzzz", False),
    (f"(?i)^{_HEAVY_CLASS}+?(?:{_HEAVY_CLASS}+?|{_HEAVY_CLASS}+?)?aaab", False),
    (r"^[a-z]+?(?:[a-z]+?|[a-z]+?|[a-z]+?|[a-z]+?|[a-z]+?|[a-z]+?|[a-z]+?)zzzz", False),
    (f"(?i)^{_HEAVY_CLASS}+?(?:{_HEAVY_CLASS}+?|{_HEAVY_CLASS}+?)aaab", False),
    (r"^[a-z]+(?:[a-z]+|[a-z]+|[a-z]+|[a-z]+|[a-z]+|[a-z]+|[a-z]+)zzzz", False),
    (f"(?i)^{_HEAVY_CLASS}+?(?:{_HEAVY_CLASS}+?)?aaab", False),
    (f"(?i)^(?:{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?|{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?|"
     f"{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?|{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?)aaab", False),
    (f"(?i)^(?:{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?)?aaab", False),
    (r"(?i)(?:[^\W\d_]*?aaab|[^\W\d_]*?aaab)", False),
    (rf"(?m)^(?:a[^\W\d_]+?|b[^\W\d_]+?){_HEAVY_CLASS}+?aaab", False),
    (rf"(?i)^(((([^\W\d_]+?)))){_HEAVY_CLASS}+?$", False),
]


@pytest.mark.parametrize(("pattern", "whole_region"), _R11_BRANCH_OPTIONAL_VECTORS)
def test_agent_manifest_rejects_r11_branch_and_optional_d2_redos(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)

    field = "regex" if whole_region else "line_regex"
    toml_text = (
        'id = "r11"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field} = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


@pytest.mark.parametrize(("pattern", "_whole_region"), _R11_BRANCH_OPTIONAL_VECTORS)
def test_tier0_sidecar_load_rejects_r11_branch_and_optional_patterns(
    tmp_path: Path, pattern: str, _whole_region: bool
) -> None:
    code = tmp_path / "code" / "r11harness"
    code.mkdir(parents=True)
    (code / "r11.toml").write_text(
        'id = "r11h"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"line_regex = [{json.dumps(pattern)}]\n",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "r11harness"
name = "R11 Harness"
version = "1.0.0"
kind = "plugin"
description = "Rejects R11 BRANCH and OPTIONAL ReDoS vectors"
author = "Tester"

[harnesses]
files = ["r11.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "r11harness")


def test_agent_manifest_allows_literal_alternation_after_unanchored_anchored_repeat(tmp_path: Path) -> None:
    pattern = r"(?i)^\s*❯.*(yes|allow)"
    compiled = agent_engine.compile_pattern(pattern, whole_region=False)
    assert compiled.search("  ❯ Yes, proceed") is not None
    assert compiled.search("  ❯ Allow once") is not None
    assert compiled.search("  ❯ Cancel") is None

    toml_text = (
        'id = "litbranch"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "blocked"\n'
        f"line_regex = [{json.dumps(pattern)}]\n"
    )
    manifest = agent_engine.parse_manifest(toml_text)
    assert manifest is not None
    matched = agent_engine.evaluate(manifest, "  ❯ Yes, proceed\n")
    assert matched is not None
    assert matched.state == "blocked"

    code = tmp_path / "code" / "litbranchharness"
    code.mkdir(parents=True)
    (code / "lit.toml").write_text(toml_text, encoding="utf-8")
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "litbranchharness"
name = "Literal Branch Harness"
version = "1.0.0"
kind = "plugin"
description = "Allows literal-only alternation after .*"
author = "Tester"

[harnesses]
files = ["lit.toml"]
""",
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(code, "litbranchharness")
    assert sm.harnesses == ("lit.toml",)


_R12_IN_UNI_IGNORE_VECTORS = [
    (r"(?i)^[^\W\d_bdfhjlnprtvxz]+?[^\W\d_bdfhjlnprtvxz]+?αααβ", False),
    (
        r"(?i)^[^\W\d_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ]+?"
        r"[^\W\d_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ]+?αααβ",
        False,
    ),
    (f"(?i)^{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?\\u03b1\\u03b1\\u03b1\\u03b2", False),
    (f"(?i)(?:{_HEAVY_CLASS}|!){_HEAVY_CLASS}*?\\u03b1\\u03b1\\u03b1\\u03b2", False),
    (
        f"(?i)^(?:\\u03b1|b|c|d|e|f|g|h|i|j|k|l|m|n|o|p){_HEAVY_CLASS}+?{_HEAVY_CLASS}+?\\u03b1\\u03b1\\u03b1\\u03b2",
        False,
    ),
    (
        f"(?i)^{_HEAVY_CLASS}+?(?:\\u03b1|b|c|d|e|f|g|h|i|j|k|l|m|n|o|p){_HEAVY_CLASS}+?\\u03b1\\u03b1\\u03b1\\u03b2",
        False,
    ),
    (f"(?i)^{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?\\ufb05\\ufb05\\ufb05\\ufb06", False),
    (f"(?i){_HEAVY_CLASS}*?\\u03b1\\u03b1\\u03b1\\u03b2", False),
    (r"(?i)[^\W\d_b]*?\u03b1\u03b1\u03b2", False),
    (f"^{_HEAVY_CLASS}+?{_HEAVY_CLASS}+?(?i:\\u03b1\\u03b1\\u03b1\\u03b2)", False),
]


@pytest.mark.parametrize(("pattern", "whole_region"), _R12_IN_UNI_IGNORE_VECTORS)
def test_agent_manifest_rejects_r12_in_uni_ignore_redos_vectors(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)

    field = "regex" if whole_region else "line_regex"
    toml_text = (
        'id = "r12"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field} = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


@pytest.mark.parametrize(("pattern", "_whole_region"), _R12_IN_UNI_IGNORE_VECTORS)
def test_tier0_sidecar_load_rejects_r12_in_uni_ignore_patterns(
    tmp_path: Path, pattern: str, _whole_region: bool
) -> None:
    code = tmp_path / "code" / "r12harness"
    code.mkdir(parents=True)
    (code / "r12.toml").write_text(
        'id = "r12h"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"line_regex = [{json.dumps(pattern)}]\n",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "r12harness"
name = "R12 Harness"
version = "1.0.0"
kind = "plugin"
description = "Rejects R12 IN_UNI_IGNORE and LITERAL_UNI_IGNORE ReDoS vectors"
author = "Tester"

[harnesses]
files = ["r12.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "r12harness")


_UNI75 = "".join(chr(0x0400 + i) for i in range(75))
_UNI90 = "".join(chr(0x0400 + i) for i in range(90))
_UNI220 = "".join(chr(0x0400 + i) for i in range(220))
_H75 = rf"[^\W\d_{_UNI75}]"
_H90 = rf"[^\W\d_{_UNI90}]"
_H220 = rf"[^\W\d_{_UNI220}]"
_H16 = rf"[^\W\d_{_UNI75[:12]}]"

_R13_LONGS_VECTORS = [
    (f"^{_H90}+?{_H90}+?(?i:sssk)", False),
    (f"^\\w+?{_H220}+?(?i:sssk)", False),
    (f"{_H220}*?(?i:sssk)", False),
    (f"(?:{_H90}|!){_H90}*?(?i:sssk)", False),
    (f"^(?:\\u017f|b|c|d|e|f|g|h|i|j|k|l|m|n|o|p){_H75}+?{_H75}+?(?i:sssk)", False),
    (f"^{_H75}+?(?:\\u017f|b|c|d|e|f|g|h|i|j|k|l|m|n|o|p){_H75}+?(?i:sssk)", False),
    (f"{_H16}*?(?i:iiik)", False),
]


@pytest.mark.parametrize(("pattern", "whole_region"), _R13_LONGS_VECTORS)
def test_agent_manifest_rejects_r13_longs_uni_ignore_redos_vectors(
    pattern: str, whole_region: bool
) -> None:
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.compile_pattern(pattern, whole_region=whole_region)

    field = "regex" if whole_region else "line_regex"
    toml_text = (
        'id = "r13"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"{field} = [{json.dumps(pattern)}]\n"
    )
    with pytest.raises(agent_engine.RuleFileError):
        agent_engine.parse_manifest(toml_text)


@pytest.mark.parametrize(("pattern", "_whole_region"), _R13_LONGS_VECTORS)
def test_tier0_sidecar_load_rejects_r13_longs_uni_ignore_patterns(
    tmp_path: Path, pattern: str, _whole_region: bool
) -> None:
    code = tmp_path / "code" / "r13harness"
    code.mkdir(parents=True)
    (code / "r13.toml").write_text(
        'id = "r13h"\nversion = "1"\n[[rules]]\nid = "r1"\nstate = "working"\n'
        f"line_regex = [{json.dumps(pattern)}]\n",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "r13harness"
name = "R13 Harness"
version = "1.0.0"
kind = "plugin"
description = "Rejects R13 non-(?i) negated CATEGORY IN + scoped (?i:sssk) ReDoS vectors"
author = "Tester"

[harnesses]
files = ["r13.toml"]
""",
        encoding="utf-8",
    )
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(code, "r13harness")
