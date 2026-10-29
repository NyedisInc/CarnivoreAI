
import type { AccountUsage, UsageWindow } from '../../opscenter/api/types';
import { parseServerTime } from '../../opscenter/lib/format';

export const SHORT_FULL_PCT = 95;
export const LONG_FULL_PCT = 100;
export const MIN_HOURS = 0.1;

export const SHORT_MAX_SECONDS = 5 * 3600;
const WEEK_SECONDS = 7 * 24 * 3600;
const KIND_SECONDS: Readonly<Record<string, number>> = {
  five_hour: SHORT_MAX_SECONDS,
  primary: SHORT_MAX_SECONDS,
  seven_day: WEEK_SECONDS,
  seven_day_opus: WEEK_SECONDS,
  seven_day_sonnet: WEEK_SECONDS,
  secondary: WEEK_SECONDS,
};
const HOUR_MS = 3_600_000;

export type SkipReason = 'pending' | 'login' | 'unread' | 'maxed';

export interface LedgerPick {
  account: AccountUsage;
  long: UsageWindow;
  short: UsageWindow | null;
  urgency: number;
}

export interface ProviderAdvice {
  provider: string;
  pick: LedgerPick | null;
  skipped: Partial<Record<SkipReason, number>>;
}

function measured(window: UsageWindow): boolean {
  return typeof window.used_pct === 'number' && Number.isFinite(window.used_pct);
}

function tightest(windows: UsageWindow[]): UsageWindow | null {
  return windows.reduce<UsageWindow | null>(
    (worst, w) => (worst === null || w.used_pct > worst.used_pct ? w : worst),
    null,
  );
}

export function lengthOf(window: UsageWindow): number | null {
  const seconds = window.window_seconds;
  if (typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0) return seconds;
  return KIND_SECONDS[window.kind] ?? null;
}

function sized(account: AccountUsage): UsageWindow[] {
  return (account.windows ?? []).filter((w) => measured(w) && lengthOf(w) !== null);
}

export function longWindow(account: AccountUsage): UsageWindow | null {
  const windows = sized(account);
  const longest = Math.max(0, ...windows.map((w) => lengthOf(w) as number));
  if (longest <= SHORT_MAX_SECONDS) return null;
  return tightest(windows.filter((w) => lengthOf(w) === longest));
}

export function shortWindow(account: AccountUsage): UsageWindow | null {
  return tightest(sized(account).filter((w) => (lengthOf(w) as number) <= SHORT_MAX_SECONDS));
}

function assess(account: AccountUsage, nowMs: number): LedgerPick | SkipReason {
  if (account.credential_state === 'unknown') return 'pending';
  if (account.credential_state !== 'ok') return 'login';
  const long = longWindow(account);
  const resetAt = long ? parseServerTime(long.resets_at) : Number.NaN;
  if (!long || !Number.isFinite(resetAt) || resetAt <= nowMs) return 'unread';
  const short = shortWindow(account);
  if (long.used_pct >= LONG_FULL_PCT || (short && short.used_pct >= SHORT_FULL_PCT)) return 'maxed';
  const hours = Math.max((resetAt - nowMs) / HOUR_MS, MIN_HOURS);
  return { account, long, short, urgency: (100 - long.used_pct) / hours };
}

function rank(a: LedgerPick, b: LedgerPick): number {
  if (a.urgency !== b.urgency) return b.urgency - a.urgency;
  const room = (p: LedgerPick): number => (p.short ? 100 - p.short.used_pct : -1);
  if (room(a) !== room(b)) return room(b) - room(a);
  const reset = parseServerTime(a.long.resets_at) - parseServerTime(b.long.resets_at);
  if (reset !== 0) return reset;
  return a.account.id < b.account.id ? -1 : a.account.id > b.account.id ? 1 : 0;
}

export function recommend(accounts: readonly AccountUsage[], nowMs: number): ProviderAdvice[] {
  const byProvider = new Map<string, ProviderAdvice & { candidates: LedgerPick[] }>();
  for (const account of accounts) {
    let entry = byProvider.get(account.provider);
    if (!entry) {
      entry = { provider: account.provider, pick: null, skipped: {}, candidates: [] };
      byProvider.set(account.provider, entry);
    }
    const verdict = assess(account, nowMs);
    if (typeof verdict === 'string') entry.skipped[verdict] = (entry.skipped[verdict] ?? 0) + 1;
    else entry.candidates.push(verdict);
  }
  return [...byProvider.values()]
    .sort((a, b) => a.provider.localeCompare(b.provider))
    .map(({ provider, skipped, candidates }) => ({
      provider,
      skipped,
      pick: candidates.sort(rank)[0] ?? null,
    }));
}
