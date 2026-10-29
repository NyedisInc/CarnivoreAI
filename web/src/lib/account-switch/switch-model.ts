
export interface ActiveAccountState {
  provider: 'claude' | 'codex';
  account_id: string | null;
  source: 'pointer' | 'default_login' | 'none';
  pointer: string | null;
  next_order?: string[];
}

export interface LastSwitch {
  provider: string;
  from_account_id: string | null;
  to_account_id: string;
  reason: 'manual' | 'auto' | 'auto_restart';
  window_kind: string | null;
  used_pct: number | null;
  window_seconds: number | null;
  at: string;
}

export interface AccountSwitchState {
  auto_switch: boolean;
  threshold_percent: number;
  active: ActiveAccountState[];
  last_switch: LastSwitch | null;
  restarts_running_sessions: boolean;
}

export interface RunningElsewhere {
  session_id: string;
  tmux_session: string;
  label: string | null;
  status: string | null;
  provider: string;
  account_id: string;
  active_account_id: string;
}

export interface AccountActivated {
  state: AccountSwitchState;
  running_elsewhere: RunningElsewhere[];
}

export type RowSwitchState = 'active' | 'available' | 'needs_setup' | 'unknown';

export interface SwitchableAccount {
  id: string;
  provider: string;
  setup_complete?: boolean | null;
}

export function activeAccountId(state: AccountSwitchState | null, provider: string): string | null {
  if (!state) return null;
  return state.active.find((entry) => entry.provider === provider)?.account_id ?? null;
}

export function rowSwitchState(
  state: AccountSwitchState | null,
  account: SwitchableAccount,
): RowSwitchState {
  if (!state) return 'unknown';
  const entry = state.active.find((item) => item.provider === account.provider);
  if (!entry) return 'unknown';
  if (entry.account_id === account.id) return 'active';
  return account.setup_complete === false ? 'needs_setup' : 'available';
}

export function refusalCode(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const detail = (payload as { detail?: unknown }).detail;
  if (!detail || typeof detail !== 'object') return null;
  const code = (detail as { code?: unknown }).code;
  return typeof code === 'string' ? code : null;
}

export function switchRank(
  state: AccountSwitchState | null,
  account: { id: string; provider: string },
): number {
  const entry = state?.active.find((item) => item.provider === account.provider);
  if (!entry) return Infinity;
  if (entry.account_id === account.id) return 0;
  const at = (entry.next_order ?? []).indexOf(account.id);
  return at < 0 ? Infinity : at + 1;
}
