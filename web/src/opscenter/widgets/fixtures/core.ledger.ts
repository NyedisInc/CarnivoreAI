import { ago, DAY, HOUR, MIN } from './clock';
import type { WidgetFixtures } from './types';

const inFuture = (seconds: number): string => ago(-seconds);

function account(id: string, name: string, provider: string, plan: string, state: string, windows: [string, string, number, number, number][]): unknown {
  return {
    id,
    name,
    short_name: null,
    provider,
    plan,
    identity: name,
    credential_state: state,
    fetched_at: ago(40),
    next_poll_at: inFuture(5 * MIN),
    error: null,
    windows: windows.map(([kind, label, used, seconds, resets]) => ({
      kind,
      label,
      used_pct: used,
      window_seconds: seconds,
      resets_at: inFuture(resets),
    })),
    color: null,
    managed: true,
    setup_complete: true,
  };
}

export const ledgerFixtures: WidgetFixtures = {
  data: {
    'GET /provider-ledger': {
      accounts: [
        account('acct-studio', 'studio', 'claude', 'max 20x', 'ok', [
          ['five_hour', '5h', 38.2, 5 * HOUR, 2 * HOUR + 10 * MIN],
          ['seven_day', '7d', 61.5, 7 * DAY, 3 * DAY],
          ['seven_day_opus', '7d opus', 74.9, 7 * DAY, 3 * DAY],
        ]),
        account('acct-home', 'home', 'claude', 'max 5x', 'ok', [
          ['five_hour', '5h', 12.4, 5 * HOUR, 3 * HOUR],
          ['seven_day', '7d', 33.0, 7 * DAY, 4 * DAY],
        ]),
        account('acct-lab', 'lab', 'codex', 'plus', 'ok', [
          ['primary', '5h', 52.0, 5 * HOUR, 4 * HOUR],
          ['secondary', '7d', 29.8, 7 * DAY, 5 * DAY],
        ]),
      ],
      total: {
        accounts: 3,
        windows: [
          { kind: 'five_hour', label: '5h', used_pct: 45.1, resets_at: inFuture(2 * HOUR + 10 * MIN), accounts: 3 },
          { kind: 'seven_day', label: '7d', used_pct: 45.7, resets_at: inFuture(3 * DAY), accounts: 3 },
        ],
      },
      loop: { alive: true, last_pass_at: ago(40) },
    },
  },
  empty: {
    'GET /provider-ledger': { accounts: [], total: { accounts: 0, windows: [] }, loop: { alive: true, last_pass_at: ago(40) } },
  },
};
