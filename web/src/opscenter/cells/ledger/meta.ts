
import type { ColumnSpec, PhoneSummary } from '../../engine/types';
import type { AccountUsage, LedgerSnapshot, UsageWindow } from '../../api';
import { ledger } from '../../api';
import { parseServerTime } from '../../lib/format';
import { t } from '../../../lib/i18n/index.svelte';
import { switchRank, type AccountSwitchState } from '../../../lib/account-switch/switch-model';

export type LedgerTotal = LedgerSnapshot['total'];

export const columns: ColumnSpec[] = [
  { key: 'name', headKey: 'opscenter.column.account', minPx: 142, weight: 2, insetPx: 12 },
  { key: 'provider', headKey: 'opscenter.column.provider', minPx: 84, weight: 1, insetPx: 10 },
  { key: 'plan', headKey: 'opscenter.column.plan', minPx: 66, weight: 1, insetPx: 10 },
  { key: 'window', headKey: 'opscenter.column.used', minPx: 120, weight: 2, insetPx: 10 },
  { key: 'resets', headKey: 'opscenter.column.resets', minPx: 88, weight: 1, insetPx: 10, align: 'end' },
  { key: 'identity', headKey: 'opscenter.column.identity', minPx: 126, weight: 2, insetPx: 10 },
  { key: 'windows', headKey: 'opscenter.column.windows', minPx: 116, weight: 2, insetPx: 10 },
];

export const COLUMNS_AT: Readonly<Record<string, readonly string[]>> = {
  name: ['name'],
  provider: ['name', 'provider'],
  plan: ['name', 'provider', 'plan'],
  window: ['name', 'provider', 'plan', 'window'],
  resets: ['name', 'provider', 'plan', 'window', 'resets'],
  identity: ['name', 'provider', 'plan', 'window', 'resets', 'identity'],
  full: ['name', 'provider', 'plan', 'window', 'resets', 'identity', 'windows'],
};

export function columnsFor(state: string): ColumnSpec[] {
  const keys = COLUMNS_AT[state] ?? COLUMNS_AT.name ?? [];
  return keys
    .map((key) => columns.find((column) => column.key === key))
    .filter((column): column is ColumnSpec => Boolean(column));
}

export interface RowPlan {
  rows: number;
  head: boolean;
  total: boolean;
  big: boolean;
  rowHeight: number;
}

export function rowPlanFor(state: string): RowPlan {
  switch (state) {
    case 'rows-bare':
      return { rows: 2, head: false, total: false, big: false, rowHeight: 28 };
    case 'rows':
      return { rows: 3, head: true, total: false, big: false, rowHeight: 28 };
    case 'rows-total':
      return { rows: 4, head: true, total: true, big: false, rowHeight: 28 };
    case 'rows-big':
      return { rows: 4, head: true, total: true, big: true, rowHeight: 46 };
    default:
      return { rows: 0, head: false, total: false, big: false, rowHeight: 28 };
  }
}

export const WARN_AT_PCT = 70;
export const HIGH_AT_PCT = 90;

export type Tone = 'ok' | 'warn' | 'high' | 'unknown';

export function percentTone(pct: number | null): Tone {
  if (typeof pct !== 'number' || !Number.isFinite(pct)) return 'unknown';
  if (pct >= HIGH_AT_PCT) return 'high';
  if (pct >= WARN_AT_PCT) return 'warn';
  return 'ok';
}

export function credentialTone(state: string): Tone {
  switch (state) {
    case 'ok':
      return 'ok';
    case 'expired':
    case 'rate_limited':
      return 'warn';
    case 'missing':
    case 'refused':
    case 'error':
      return 'high';
    default:
      return 'unknown';
  }
}

const CREDENTIAL_LABEL_KEYS: Readonly<Record<string, string>> = {
  ok: 'opscenter.ledger.credential.ok',
  expired: 'opscenter.ledger.credential.expired',
  missing: 'opscenter.ledger.credential.missing',
  refused: 'opscenter.ledger.credential.refused',
  rate_limited: 'opscenter.ledger.credential.rate_limited',
  error: 'opscenter.ledger.credential.error',
  unknown: 'opscenter.ledger.credential.unknown',
};

export function credentialLabel(state: string): string {
  const known = CREDENTIAL_LABEL_KEYS[state];
  if (known) return t(known);
  return t('opscenter.ledger.credential.unrecognised', { state });
}

export function isUnmeasured(account: AccountUsage, nowMs: number): boolean {
  if (account.credential_state !== 'unknown') return false;
  if (!account.next_poll_at) return false;
  const at = parseServerTime(account.next_poll_at);
  return Number.isFinite(at) && at < nowMs;
}

export function barWidth(pct: number | null): number {
  if (typeof pct !== 'number' || !Number.isFinite(pct)) return 0;
  return Math.min(100, Math.max(0, pct));
}

export function formatPercent(pct: number | null): string {
  if (typeof pct !== 'number' || !Number.isFinite(pct)) return t('opscenter.value.unknown');
  return `${Math.round(pct)}%`;
}

export function formatResetIn(resetsAt: string | null, nowMs: number): string {
  if (typeof resetsAt !== 'string' || !resetsAt.trim()) return t('opscenter.value.unknown');
  const at = parseServerTime(resetsAt);
  if (!Number.isFinite(at)) return t('opscenter.value.unknown');
  const delta = Math.round((at - nowMs) / 1000);
  if (delta <= 0) return t('opscenter.ledger.reset_now');
  if (delta < 60) return t('opscenter.ledger.reset_in_seconds', { count: delta });
  if (delta < 3600) return t('opscenter.ledger.reset_in_minutes', { count: Math.floor(delta / 60) });
  if (delta < 86400) {
    const hours = Math.floor(delta / 3600);
    const minutes = Math.floor((delta % 3600) / 60);
    return minutes === 0
      ? t('opscenter.ledger.reset_in_hours', { count: hours })
      : t('opscenter.ledger.reset_in_hours_minutes', { hours, minutes });
  }
  const days = Math.floor(delta / 86400);
  const hours = Math.floor((delta % 86400) / 3600);
  return hours === 0
    ? t('opscenter.ledger.reset_in_days', { count: days })
    : t('opscenter.ledger.reset_in_days_hours', { days, hours });
}

export function formatAge(iso: string | null, nowMs: number): string {
  if (typeof iso !== 'string' || !iso.trim()) return t('opscenter.ledger.no_pass_yet');
  const at = parseServerTime(iso);
  if (!Number.isFinite(at)) return t('opscenter.ledger.no_pass_yet');
  const ago = Math.max(0, Math.round((nowMs - at) / 1000));
  if (ago < 60) return t('opscenter.time.ago_seconds', { count: ago });
  if (ago < 3600) return t('opscenter.time.ago_minutes', { count: Math.floor(ago / 60) });
  if (ago < 86400) return t('opscenter.time.ago_hours', { count: Math.floor(ago / 3600) });
  return t('opscenter.time.ago_days', { count: Math.floor(ago / 86400) });
}

export function tightestTotal(total: LedgerTotal | null): UsageWindow | null {
  if (!total || !total.windows.length) return null;
  const worst = total.windows.reduce((held, entry) => (entry.used_pct > held.used_pct ? entry : held));
  return {
    kind: worst.kind,
    label: worst.label,
    used_pct: worst.used_pct,
    window_seconds: null,
    resets_at: worst.resets_at,
  };
}

/* label: ' */
export function windowLabel(value: UsageWindow): string {
  if (value.label && value.label.trim()) return value.label.trim();
  if (value.kind && value.kind.trim()) return value.kind.trim();
  return t('opscenter.value.unknown');
}

export function accountSwatch(value: string | null): string | null {
  if (typeof value !== 'string') return null;
  if (!value.startsWith('#')) return null;
  const body = value.slice(1);
  return /^[0-9a-f]{6}$/i.test(body) ? value : null;
}

export function providerIcon(provider: string): string {
  if (provider === 'claude') return 'cloud';
  if (provider === 'codex') return 'code';
  return 'cube';
}

export function sortAccounts(
  accounts: readonly AccountUsage[],
  state: AccountSwitchState | null = null,
): AccountUsage[] {
  return accounts
    .map((account, index) => ({ account, index }))
    .sort((left, right) => {
      const provider = left.account.provider.localeCompare(right.account.provider);
      if (provider !== 0) return provider;
      const l = switchRank(state, left.account);
      const r = switchRank(state, right.account);
      if (l !== r) return l === Infinity ? 1 : r === Infinity ? -1 : l - r;
      const name = left.account.name.localeCompare(right.account.name);
      if (name !== 0) return name;
      return left.index - right.index;
    })
    .map((entry) => entry.account);
}

export function titleCount(): number | null {
  return ledger.status === 'ok' ? (ledger.data?.accounts.length ?? null) : null;
}

export function phoneTotal(): number | null {
  return titleCount();
}

const TONE_MARKS: Readonly<Record<Tone, { tone: string; shape: 'solid' | 'hollow' }>> = {
  ok: { tone: 'oc-green-bright', shape: 'solid' },
  warn: { tone: 'oc-yellow-bright', shape: 'solid' },
  high: { tone: 'oc-coral', shape: 'solid' },
  unknown: { tone: 'oc-text-dim', shape: 'hollow' },
};

const TONE_ORDER: readonly Tone[] = ['high', 'warn', 'unknown', 'ok'];

/* could not be read */
export function phoneSummary(): PhoneSummary | null {
  if (ledger.status !== 'ok') return null;
  const snapshot = ledger.data;
  if (!snapshot) return null;
  const tones = snapshot.accounts.map((account) => credentialTone(account.credential_state));
  const worst = TONE_ORDER.find((tone) => tones.includes(tone)) ?? 'unknown';
  const mark = TONE_MARKS[worst];
  const window = tightestTotal(snapshot.total);
  const percent = window ? formatPercent(window.used_pct) : t('opscenter.value.unknown');
  return {
    marks: [
      {
        tone: mark.tone,
        shape: mark.shape,
        count: snapshot.accounts.length,
        label: t('opscenter.ledger.worst_credential', {
          count: snapshot.accounts.length,
          state: credentialLabel(
            snapshot.accounts.find((account) => credentialTone(account.credential_state) === worst)
              ?.credential_state ?? 'unknown',
          ),
        }),
      },
    ],
    note: window
      ? t('opscenter.ledger.phone_note', { percent, window: windowLabel(window) })
      : percent,
  };
}

export function phoneColumns(): ColumnSpec[] {
  return [
    { key: 'name', headKey: 'opscenter.column.account', minPx: 0, weight: 1.4, line: 1 },
    { key: 'window', headKey: 'opscenter.column.used', minPx: 0, weight: 1, align: 'end', line: 1 },
    { key: 'provider', headKey: 'opscenter.column.provider', minPx: 0, weight: 0, line: 2 },
    { key: 'plan', headKey: 'opscenter.column.plan', minPx: 0, weight: 1, line: 2 },
  ];
}
