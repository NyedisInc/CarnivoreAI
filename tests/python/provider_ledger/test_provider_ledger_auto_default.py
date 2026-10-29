
from __future__ import annotations

from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR, ProviderAccount
from src.core.provider_ledger import poller_scan


def test_an_empty_list_gets_one_synthetic_default_row():
    result = poller_scan.with_auto_default([])
    assert len(result) == 1
    row = result[0]
    assert row.id == poller_scan.AUTO_DEFAULT_ACCOUNT_ID
    assert row.provider == "claude"
    assert row.claude_config_dir == DEFAULT_CLAUDE_CONFIG_DIR
    assert row.managed is False


def test_a_configured_row_on_the_default_dir_is_never_shadowed():
    configured = [ProviderAccount(id="mine", name="Mine", provider="claude")]
    assert poller_scan.with_auto_default(configured) == configured


def test_the_synthetic_id_is_a_legal_provider_account_id():
    row = poller_scan.with_auto_default([])[0]
    assert row.id == "auto-claude-default"
