import { describe, expect, test } from 'vitest';
import type { AccountUsage, UsageWindow } from '../../opscenter/api/types';
import { recommend, type ProviderAdvice } from './recommend';

const NOW = Date.parse('2026-09-24T12:00:00Z');
const inHours = (h: number): string => new Date(NOW + h * 3_600_000).toISOString();

function win(kind: string, used: number, resetHours: number | null, seconds: number | null = null): UsageWindow {
  return {
    kind,
    label: kind,
    used_pct: used,
    window_seconds: seconds,
    resets_at: resetHours === null ? null : inHours(resetHours),
  };
}

function account(name: string, windows: UsageWindow[], extra: Partial<AccountUsage> = {}): AccountUsage {
  return {
    id: name,
    name,
    short_name: null,
    provider: 'claude',
    plan: null,
    identity: null,
    credential_state: 'ok',
    fetched_at: null,
    next_poll_at: null,
    error: null,
    windows,
    color: null,
    managed: false,
    ...extra,
  };
}

function only(accounts: AccountUsage[]): ProviderAdvice {
  const [advice] = recommend(accounts, NOW);
  if (!advice) throw new Error('expected one provider');
  return advice;
}

const pickName = (accounts: AccountUsage[], provider = 'claude'): string | null =>
  recommend(accounts, NOW).find((a) => a.provider === provider)?.pick?.account.name ?? null;

describe('recommend', () => {
  test('an ordinary pick: the most weekly headroom per hour to reset wins', () => {
    const accounts = [
      account('a', [win('five_hour', 10, 2), win('seven_day', 40, 24)]),
      account('b', [win('five_hour', 10, 2), win('seven_day', 10, 120)]),
      account('c', [win('five_hour', 10, 2), win('seven_day', 80, 4)]),
    ];
    const advice = only(accounts);
    expect(advice.pick?.account.name).toBe('c');
    expect(advice.pick?.urgency).toBeCloseTo(5);
  });

  test('the tightest weekly window is the long one', () => {
    const a = account('a', [win('seven_day', 20, 10), win('seven_day_opus', 90, 10)]);
    const b = account('b', [win('seven_day', 50, 20)]);
    expect(pickName([a, b])).toBe('b');
  });

  test('a tie on urgency goes to more short headroom, then the earlier reset', () => {
    const roomy = account('roomy', [win('five_hour', 5, 1), win('seven_day', 50, 10)]);
    const tight = account('tight', [win('five_hour', 60, 1), win('seven_day', 50, 10)]);
    expect(pickName([tight, roomy])).toBe('roomy');
    const early = account('early', [win('five_hour', 5, 1), win('seven_day', 75, 5)]);
    const late = account('late', [win('five_hour', 5, 1), win('seven_day', 50, 10)]);
    expect(pickName([late, early])).toBe('early');
  });

  test('a short window at 95% or a full long window cannot take work', () => {
    const busy = account('busy', [win('five_hour', 95, 1), win('seven_day', 10, 2)]);
    const full = account('full', [win('five_hour', 0, 1), win('seven_day', 100, 2)]);
    const ok = account('ok', [win('five_hour', 94, 1), win('seven_day', 10, 150)]);
    const advice = only([busy, full, ok]);
    expect(advice.pick?.account.name).toBe('ok');
    expect(advice.skipped).toEqual({ maxed: 2 });
  });

  test('expired and not-yet-polled accounts are excluded, however urgent', () => {
    const expired = account('expired', [win('seven_day', 0, 1)], { credential_state: 'expired' });
    const pending = account('pending', [], { credential_state: 'unknown' });
    const ok = account('ok', [win('seven_day', 50, 100)]);
    const advice = only([expired, pending, ok]);
    expect(advice.pick?.account.name).toBe('ok');
    expect(advice.skipped).toEqual({ login: 1, pending: 1 });
  });

  test('a null reset, a missing weekly or a reset already passed is unread', () => {
    const noReset = account('no-reset', [win('seven_day', 10, null)]);
    const noWeekly = account('no-weekly', [win('five_hour', 10, 1)]);
    const passed = account('passed', [win('seven_day', 90, -1)]);
    const advice = only([noReset, noWeekly, passed]);
    expect(advice.pick).toBeNull();
    expect(advice.skipped).toEqual({ unread: 3 });
  });

  test('nothing eligible answers no pick and counts why, never a fabricated one', () => {
    const advice = only(
      [
        account('x', [win('seven_day', 100, 5)]),
        account('y', [], { credential_state: 'refused' }),
      ],
    );
    expect(advice).toEqual({ provider: 'claude', pick: null, skipped: { maxed: 1, login: 1 } });
    expect(recommend([], NOW)).toEqual([]);
  });

  test('one pick per provider, and only providers that exist', () => {
    const accounts = [
      account('claude-a', [win('seven_day', 10, 100)]),
      account('codex-a', [win('primary', 10, 1), win('secondary', 30, 50)], { provider: 'codex' }),
      account('codex-b', [win('primary', 10, 1), win('secondary', 80, 50)], { provider: 'codex' }),
    ];
    const advice = recommend(accounts, NOW);
    expect(advice.map((a) => a.provider)).toEqual(['claude', 'codex']);
    expect(pickName(accounts, 'codex')).toBe('codex-a');
    expect(pickName(accounts, 'claude')).toBe('claude-a');
  });

  test('a codex account whose only window is a weekly primary is judged on it', () => {
    const acct = account('weekly', [win('primary', 40, 48, 604_800)], { provider: 'codex' });
    const advice = only([acct]);
    expect(advice.pick?.long.kind).toBe('primary');
    expect(advice.pick?.short).toBeNull();
    expect(advice.pick?.urgency).toBeCloseTo(60 / 48);
    expect(only([account('high', [win('primary', 96, 48, 604_800)], { provider: 'codex' })]).pick).not.toBeNull();
  });

  test('a claude account with sized 5h and 7d windows reads them as before', () => {
    const acct = account('both', [win('five_hour', 30, 2, 18_000), win('seven_day', 40, 24, 604_800)]);
    const advice = only([acct]);
    expect(advice.pick?.long.kind).toBe('seven_day');
    expect(advice.pick?.short?.kind).toBe('five_hour');
    expect(only([account('busy', [win('five_hour', 95, 2, 18_000), win('seven_day', 40, 24, 604_800)])]).skipped)
      .toEqual({ maxed: 1 });
  });

  test('a null window_seconds falls back to the kind name', () => {
    const unsized = account('u', [win('primary', 96, 1), win('secondary', 10, 48)], { provider: 'codex' });
    expect(only([unsized]).skipped).toEqual({ maxed: 1 });
    const unknownKind = account('k', [win('mystery', 10, 5)]);
    expect(only([unknownKind]).skipped).toEqual({ unread: 1 });
  });

  test('an unknown provider falls back to the longest window by length', () => {
    const acct = account('z', [win('daily', 10, 5, 86_400), win('monthly', 40, 100, 2_592_000)], {
      provider: 'other',
    });
    const advice = only([acct]);
    expect(advice.pick?.long.kind).toBe('monthly');
  });
});
