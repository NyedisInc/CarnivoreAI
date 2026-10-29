
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.core.notifications import catalog_lines, kind_specs, types

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "client/js/i18n/catalog.en.js"


def test_every_type_label_description_and_copy_key_resolves() -> None:
    notify = catalog_lines.read_prefixed(("notify.",), CATALOG)
    assert notify and "notify.copy.session.finished.title" in notify
    notify.update(catalog_lines.read_plugin_slices(("notify.",)))
    for row in types.TYPES:
        for key in (row.label_key, row.description_key, row.copy_title_key, row.copy_body_key):
            assert notify.get(key, "").strip(), key
        if row.id.startswith("cplug."):
            assert row.copy_title_key.startswith(f"cplug.{row.id.split('.')[1]}.notify.copy.")
        else:
            assert row.copy_title_key.startswith("notify.copy.") and row.label_key.startswith("notify.type.")
    for family in types.FAMILIES:
        assert notify[f"notify.family.{family}"]
    for kind in kind_specs.KINDS:
        assert notify[kind.label_key]


def test_copy_is_lowercase_plain_with_name_placeholders_only() -> None:
    import re

    for key, text in catalog_lines.read_prefixed(("notify.copy.", "notify.type.", "notify.family.", "notify.kind."),
                                                  CATALOG).items():
        assert text == text.lower(), key
        assert not re.search("[" + chr(0x2013) + chr(0x2014) + "]", text), key
        assert set(re.findall(r"\{(\w+)\}", text)) <= {"session", "project", "computer", "from_account", "to_account", "limit"}, key
        assert "`" not in text and "${" not in text, key


def test_reader_is_scoped_resolves_escapes_and_refuses_junk(tmp_path: Path) -> None:
    cat = tmp_path / "c.js"
    cat.write_text(
        "export default {\n    'other.a': 'x',\n    'notify.copy.a.title': 'it\\'s {name}',\n"
        "    'notify.copy.b.title': \"double 'q'\",\n    'notify.plural': {\n        one: 'x',\n    },\n};\n",
        encoding="utf-8")
    with pytest.raises(ValueError):
        catalog_lines.read_prefixed(("notify.",), cat)
    got = catalog_lines.read_prefixed(("notify.copy.",), cat)
    assert got == {"notify.copy.a.title": "it's {name}", "notify.copy.b.title": "double 'q'"}
    assert catalog_lines.read_prefixed(("absent.",), cat) == {}


def test_catalog_file_still_passes_the_js_syntax_check() -> None:
    result = subprocess.run([sys.executable, "scripts/js_syntax_check.py", "client/js/i18n/catalog.en.js"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
