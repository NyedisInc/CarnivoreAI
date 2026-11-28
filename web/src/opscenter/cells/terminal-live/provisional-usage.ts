import type { AccountUsage, LedgerSnapshot, SessionInfo, SessionTokenUsage, TokenUsageFamily } from '../../api/types';

const PROVISIONAL_FAMILIES = new Set<string>(['claude', 'codex']);

function matchAccount(row: SessionInfo, ledgerSnap: LedgerSnapshot | null | undefined): AccountUsage | null {
  const accounts = ledgerSnap?.accounts;
  if (!accounts || !accounts.length) return null;
  if (row.account_id) {
    return accounts.find((a) => a.id === row.account_id) ?? null;
  }
  return null;
}

export function provisionalUsage(
  row: SessionInfo | null | undefined,
  ledgerSnap: LedgerSnapshot | null | undefined,
): SessionTokenUsage | null {
  if (!row) return null;
  const family = (row.agent_family ?? '').toLowerCase();
  if (!PROVISIONAL_FAMILIES.has(family)) return null;

  const account = matchAccount(row, ledgerSnap);
  const usedPct = typeof row.running_context_used_pct === 'number' && Number.isFinite(row.running_context_used_pct)
    ? Math.max(0, Math.min(100, row.running_context_used_pct))
    : null;
  const model = row.running_model ?? null;

  if (!model && usedPct === null && !account) return null;

  return {
    state: 'ok',
    family: family as TokenUsageFamily,
    model,
    model_display_name: model,
    model_cost_tier: row.running_model_tier ?? null,
    effort: row.running_model_effort ?? null,
    input_tokens: null,
    output_tokens: null,
    cache_read_input_tokens: null,
    cache_creation_input_tokens: null,
    total_tokens: null,
    cost_estimate_usd: null,
    context_used_tokens: null,
    context_window_tokens: null,
    context_remaining_pct: usedPct !== null ? Math.max(0, Math.min(100, 100 - usedPct)) : null,
    as_of: '',
    detail: null,
    account,
  };
}
