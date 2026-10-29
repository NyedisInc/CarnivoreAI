
import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { demoLedgerSnapshot } from '../data/ledger';
import type { LedgerSnapshot } from './types';
import { parseServerTime } from '../lib/format';
import { t } from '../../lib/i18n/index.svelte';

export const LEDGER_POLL_MS = 30000;

export const CREDENTIAL_NOTICE_KEYS: Readonly<Record<string, string>> = {
  ok: '',
  expired: 'opscenter.ledger.notice.expired',
  missing: 'opscenter.ledger.notice.missing',
  refused: 'opscenter.ledger.notice.refused',
  rate_limited: 'opscenter.ledger.notice.rate_limited',
  error: 'opscenter.ledger.notice.error',
  unknown: 'opscenter.ledger.notice.unknown',
};

export function tightestWindow<W extends { used_pct: number }>(holder: { windows: readonly W[] }): W | null {
  if (!holder.windows.length) return null;
  return holder.windows.reduce((worst, window) => (window.used_pct > worst.used_pct ? window : worst));
}

export function secondsToReset(window: { resets_at: string | null }, now = Date.now()): number | null {
  if (!window.resets_at) return null;
  const at = parseServerTime(window.resets_at);
  if (!Number.isFinite(at)) return null;
  return Math.max(0, Math.round((at - now) / 1000));
}

function demoLedger(): LedgerSnapshot {
  return demoLedgerSnapshot();
}

export const ledger: Resource<LedgerSnapshot> = resource<LedgerSnapshot>(
  () => authFetch<LedgerSnapshot>('/provider-ledger'),
  { intervalMs: LEDGER_POLL_MS, name: 'ledger', demo: demoLedger, topics: ['provider_ledger'] },
);
