
import type { AccountUsage, LedgerSnapshot, LedgerTotalWindow, UsageWindow } from '../api/types';

export interface DemoAccount extends AccountUsage {
  demo: true;
}

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

function at(nowMs: number, seconds: number): string {
  return new Date(nowMs + seconds * 1000).toISOString();
}

function window(
  kind: string,
  label: string,
  usedPct: number,
  windowSeconds: number,
  resetsAt: string,
): UsageWindow {
  return { kind, label, used_pct: usedPct, window_seconds: windowSeconds, resets_at: resetsAt };
}

export function demoAccounts(nowMs: number): DemoAccount[] {
  return [
    {
      demo: true,
      id: 'demo-claude-work',
      name: 'work max',
      short_name: null,
      provider: 'claude',
      plan: 'max',
      identity: 'ops@example.com',
      credential_state: 'ok',
      fetched_at: at(nowMs, -47),
      next_poll_at: at(nowMs, 133),
      error: null,
      windows: [
        window('five_hour', '5h', 62.4, 5 * HOUR, at(nowMs, 2 * HOUR + 14 * MINUTE)),
        window('seven_day', '7d', 18.2, 7 * DAY, at(nowMs, 4 * DAY + 5 * HOUR)),
      ],
      color: null,
      managed: true,
    },
    {
      demo: true,
      id: 'demo-claude-research',
      name: 'research max',
      short_name: null,
      provider: 'claude',
      plan: 'max',
      identity: 'research@example.com',
      credential_state: 'rate_limited',
      fetched_at: at(nowMs, -52),
      next_poll_at: at(nowMs, 128),
      error: null,
      windows: [
        window('five_hour', '5h', 96.1, 5 * HOUR, at(nowMs, 38 * MINUTE)),
        window('seven_day', '7d', 71.5, 7 * DAY, at(nowMs, 2 * DAY + 11 * HOUR)),
      ],
      color: null,
      managed: false,
    },
    {
      demo: true,
      id: 'demo-codex-main',
      name: 'codex main',
      short_name: null,
      provider: 'codex',
      plan: 'plus',
      identity: 'build@example.com',
      credential_state: 'ok',
      fetched_at: at(nowMs, -41),
      next_poll_at: at(nowMs, 19),
      error: null,
      windows: [
        window('primary', '5h', 41, 5 * HOUR, at(nowMs, HOUR + 2 * MINUTE)),
        window('secondary', 'weekly', 83.7, 7 * DAY, at(nowMs, 5 * DAY + 18 * HOUR)),
      ],
      color: null,
      managed: false,
    },
  ];
}

function demoTotalWindows(accounts: readonly AccountUsage[]): LedgerTotalWindow[] {
  const order: string[] = [];
  const bucket = new Map<string, { label: string; sum: number; count: number; resets: string | null }>();
  for (const account of accounts) {
    for (const reported of account.windows) {
      let held = bucket.get(reported.kind);
      if (!held) {
        held = { label: reported.label, sum: 0, count: 0, resets: null };
        bucket.set(reported.kind, held);
        order.push(reported.kind);
      }
      held.sum += reported.used_pct;
      held.count += 1;
      if (reported.resets_at !== null) {
        if (held.resets === null || Date.parse(reported.resets_at) < Date.parse(held.resets)) {
          held.resets = reported.resets_at;
        }
      }
    }
  }
  return order.map((kind) => {
    const held = bucket.get(kind);
    if (!held) return { kind, label: kind, used_pct: 0, resets_at: null, accounts: 0 };
    return {
      kind,
      label: held.label,
      used_pct: held.sum / held.count,
      resets_at: held.resets,
      accounts: held.count,
    };
  });
}

export function demoLedgerSnapshot(nowMs: number = Date.now()): LedgerSnapshot {
  const accounts = demoAccounts(nowMs);
  return {
    accounts,
    total: { accounts: accounts.length, windows: demoTotalWindows(accounts) },
    loop: { alive: true, last_pass_at: at(nowMs, -9) },
  };
}
