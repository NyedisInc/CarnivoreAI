import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import type { AccountUsage } from '../../opscenter/api/types';
import { recommend } from './recommend';

const FIXTURE = fileURLToPath(new URL('../../../../tests/fixtures/account_switch_star_parity.json', import.meta.url));

type FixtureWindow = [string, number, number, number];
interface ParityCase {
  name: string;
  accounts: { id: string; windows: FixtureWindow[] }[];
  order: string[];
}
const fixture = JSON.parse(readFileSync(FIXTURE, 'utf8')) as { now: string; cases: ParityCase[] };
const NOW = Date.parse(fixture.now);

function account(id: string, windows: FixtureWindow[]): AccountUsage {
  return {
    id,
    name: id,
    short_name: null,
    provider: 'claude',
    plan: null,
    identity: null,
    credential_state: 'ok',
    fetched_at: null,
    next_poll_at: null,
    error: null,
    windows: windows.map(([kind, used, seconds, hours]) => ({
      kind,
      label: kind,
      used_pct: used,
      window_seconds: seconds,
      resets_at: new Date(NOW + hours * 3_600_000).toISOString(),
    })),
    color: null,
    managed: false,
  };
}

function starOrder(accounts: AccountUsage[]): string[] {
  const left = [...accounts];
  const out: string[] = [];
  for (;;) {
    const pick = recommend(left, NOW)[0]?.pick;
    if (!pick) return out;
    out.push(pick.account.id);
    left.splice(left.indexOf(pick.account), 1);
  }
}

describe('star and switcher parity', () => {
  test('the fixture has cases', () => {
    expect(fixture.cases.length).toBeGreaterThan(0);
  });
  for (const c of fixture.cases) {
    test(c.name, () => {
      expect(starOrder(c.accounts.map((a) => account(a.id, a.windows)))).toEqual(c.order);
    });
  }
});
