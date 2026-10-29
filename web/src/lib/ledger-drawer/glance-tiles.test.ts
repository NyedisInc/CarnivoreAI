import { describe, expect, test } from 'vitest';
import type { AccountUsage, LedgerSnapshot } from '../../opscenter/api';
import type { AccountSwitchState } from '../account-switch/switch-model';
import { ACCOUNT_OPTION, GLANCE_AMBER_AHEAD_POINTS, isAheadOfPace, providerGlanceTiles } from './glance-tiles';

const NOW = Date.parse('2026-09-30T15:00:00Z');
const HOUR = 3600_000;
const DAY = 24 * HOUR;
const at = (ms: number): string => new Date(NOW + ms).toISOString();

function account(id: string, provider: string, state: string, windows: AccountUsage['windows'], plan = 'max'): AccountUsage {
  return { id, name: id, short_name: null, provider, plan, identity: id, credential_state: state, fetched_at: null, next_poll_at: null, error: null, windows, color: null, managed: false } as AccountUsage;
}
const windows = (usedShort: number): AccountUsage['windows'] => [
  { kind: 'five_hour', label: '5h', used_pct: usedShort, window_seconds: 5 * 3600, resets_at: at(4 * HOUR) },
  { kind: 'seven_day', label: '7d', used_pct: 50, window_seconds: 7 * 86400, resets_at: at(3.5 * DAY) },
];
const snapshot = (accounts: AccountUsage[]): LedgerSnapshot => ({ accounts, total: { accounts: accounts.length, windows: [] }, loop: { alive: true, last_pass_at: null } });

describe('the amber threshold', () => {
  test('is 15 points ahead of the pacer, inclusive', () => {
    expect(GLANCE_AMBER_AHEAD_POINTS).toBe(15);
    expect(isAheadOfPace(35, 20)).toBe(true);
    expect(isAheadOfPace(34.9, 20)).toBe(false);
    expect(isAheadOfPace(90, null)).toBe(false);
  });

  test('turns a window amber from its own used and elapsed figures', () => {
    const [claude, codex] = providerGlanceTiles(snapshot([account('a', 'claude', 'ok', windows(30)), account('b', 'codex', 'ok', windows(10))]), NOW);
    expect(claude!.data.short).toMatchObject({ usedPct: 30, amber: false });
    expect(claude!.data.short!.pacerPct).toBeCloseTo(20, 6);
    expect(codex!.data.short).toMatchObject({ usedPct: 10, amber: false });
    const [ahead] = providerGlanceTiles(snapshot([account('a', 'claude', 'ok', windows(35))]), NOW);
    expect(ahead!.data.short!.amber).toBe(true);
    expect(ahead!.data.long!.amber).toBe(false);
  });
});

describe('providerGlanceTiles', () => {
  test('sorts the active account first and still honours a placement narrowed to one account', () => {
    const state = {
      auto_switch: false, threshold_percent: 90, last_switch: null, restarts_running_sessions: false,
      active: [{ provider: 'claude', account_id: 'b-claude', source: 'pointer', pointer: 'b-claude' }],
    } as AccountSwitchState;
    const accounts = snapshot([account('a-claude', 'claude', 'ok', windows(10)), account('b-claude', 'claude', 'ok', windows(10))]);
    expect(providerGlanceTiles(accounts, NOW, {}, state).map((tile) => tile.key)).toEqual(['b-claude', 'a-claude']);
    expect(providerGlanceTiles(accounts, NOW, { account: 'a-claude' }, state).map((tile) => tile.key)).toEqual(['a-claude']);
    expect(providerGlanceTiles(accounts, NOW, { account: 'all' }, state).map((tile) => tile.key)).toEqual(['b-claude', 'a-claude']);
  });

  test('is one tile per account the drawer lists, in the drawer order, each naming its account', () => {
    const tiles = providerGlanceTiles(
      snapshot([account('z-codex', 'codex', 'ok', windows(10)), account('b-claude', 'claude', 'expired', windows(70)), account('a-claude', 'claude', 'ok', windows(20))]),
      NOW,
    );
    expect(tiles.map((tile) => tile.key)).toEqual(['a-claude', 'b-claude', 'z-codex']);
    expect(tiles[0]!.data.title).toBe('claude max');
    expect(tiles[1]!.data).toMatchObject({ accountId: 'b-claude', credentialState: 'expired', short: null });
  });

  test('N entries give N tiles: two claude accounts are two tiles, not one per provider (Joe, 2026-10-02)', () => {
    const gmail = { ...account('auto-claude-default', 'claude', 'ok', windows(10)), name: 'Joe Gmail' } as AccountUsage;
    const imc = { ...account('joe-imc', 'claude', 'ok', windows(0)), name: 'Joe IMC', short_name: 'imc' } as AccountUsage;
    const two = providerGlanceTiles(snapshot([gmail, imc]), NOW);
    expect(two.map((tile) => tile.data.accountLabel)).toEqual(['Joe Gmail', 'imc']);
    expect(two[1]!.data.accountName).toBe('Joe IMC');
    const four = providerGlanceTiles(snapshot([gmail, imc, account('acct-3', 'claude', 'ok', windows(5)), account('c', 'codex', 'ok', windows(5))]), NOW);
    expect(four).toHaveLength(4);
    expect(new Set(four.map((tile) => tile.key)).size).toBe(4);
  });

  test('shows a login that is not ok as its state, with no figures', () => {
    const [tile] = providerGlanceTiles(snapshot([account('a', 'claude', 'expired', windows(70))]), NOW);
    expect(tile!.data).toMatchObject({ credentialState: 'expired', short: null, long: null });
  });

  test('never turns an absent window into zero', () => {
    const [tile] = providerGlanceTiles(snapshot([account('a', 'claude', 'ok', windows(30).slice(0, 1))]), NOW);
    expect(tile!.data.short).not.toBeNull();
    expect(tile!.data.long).toBeNull();
  });

  test('a chosen account narrows to it; one the ledger no longer lists falls back to every account (Joe, 2026-10-03)', () => {
    const snap = snapshot([account('a', 'claude', 'ok', windows(10)), account('b', 'claude', 'ok', windows(20))]);
    expect(providerGlanceTiles(snap, NOW, { [ACCOUNT_OPTION]: 'b' }).map((tile) => tile.key)).toEqual(['b']);
    expect(providerGlanceTiles(snap, NOW, { [ACCOUNT_OPTION]: 'deleted' }).map((tile) => tile.key)).toEqual(['a', 'b']);
  });

  test('has no tiles for nothing loaded or nothing configured (the icon shows)', () => {
    expect(providerGlanceTiles(null, NOW)).toEqual([]);
    expect(providerGlanceTiles(snapshot([]), NOW)).toEqual([]);
  });
});

describe('the bar colour step', () => {
  const stepsFor = (used: number, pacer = 0.5): number | undefined => {
    const w = [{ kind: 'seven_day', label: '7d', used_pct: used, window_seconds: 7 * 86400, resets_at: at(7 * DAY * (1 - pacer)) }] as AccountUsage['windows'];
    return providerGlanceTiles(snapshot([account('a', 'claude', 'ok', w)]), NOW)[0]!.data.long?.step;
  };
  test('follows the window ladder on used percent, so 89 is orange and 95 and 100 are red', () => {
    expect([3, 55, 70, 89, 95, 100].map((used) => stepsFor(used, 0.9))).toEqual([1, 2, 3, 4, 5, 5]);
  });
  test('ahead of the pacer lifts a green bar to amber and never lowers a hotter one', () => {
    expect(stepsFor(40, 0.1)).toBe(3);
    expect(stepsFor(95, 0.1)).toBe(5);
  });
});
