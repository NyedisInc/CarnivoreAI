
from __future__ import annotations

from src.api.error_response import error_sentences

from .plugin_code_scan import raised_codes

BUILT_AT_RUN_TIME = frozenset({"invalid_ui_document"})


def test_every_plugin_host_code_has_a_catalog_sentence() -> None:
    codes = raised_codes() | BUILT_AT_RUN_TIME
    missing = sorted(code for code in codes if code not in error_sentences())
    assert not missing, f"add api.error.<code> to client/js/i18n/catalog.en.js for: {missing}"


def test_the_scan_sees_the_known_shapes() -> None:
    codes = raised_codes()
    assert {"cplug_unknown", "needs_approval", "consent_required", "grant_never", "secrets_unreadable",
            "git_failed", "safe_mode_forced", "peer_forbidden"} <= codes
    assert "unrestricted" not in codes and "sends_transcripts" not in codes
