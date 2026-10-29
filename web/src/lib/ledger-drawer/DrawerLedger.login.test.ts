/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import type { AccountUsage, LedgerSnapshot } from '../../opscenter/api/types';

const fakeLedger = vi.hoisted(() => ({
  status: 'ok' as 'loading' | 'ok' | 'error' | 'unavailable' | 'signed-out',
  data: null as LedgerSnapshot | null,
  fetchedAt: null as number | null,
  error: null as string | null,
}));

vi.mock('../../opscenter/api', () => ({
  ledger: fakeLedger,
  primarySessionId: () => '',
}));

import DrawerLedger from './DrawerLedger.svelte';

const DAY_MS = 86400 * 1000;

function account(overrides: Partial<AccountUsage>): AccountUsage {
  return {
    id: 'main',
    name: 'main',
    short_name: null,
    provider: 'claude',
    plan: 'max 20x',
    identity: 'alex',
    credential_state: 'ok',
    fetched_at: null,
    next_poll_at: null,
    error: null,
    windows: [],
    color: null,
    managed: true,
    ...overrides,
  };
}

function snapshot(row: AccountUsage): LedgerSnapshot {
  return {
    accounts: [row],
    total: { accounts: 1, windows: [] },
    loop: { alive: true, last_pass_at: null },
  };
}

let host: HTMLElement | null = null;
let instance: unknown = null;

afterEach(() => {
  if (instance) unmount(instance as never);
  instance = null;
  host?.remove();
  host = null;
  fakeLedger.data = null;
  localStorage.clear();
});

function render(row: AccountUsage): HTMLElement {
  fakeLedger.data = snapshot(row);
  host = document.createElement('div');
  document.body.appendChild(host);
  instance = mount(DrawerLedger, { target: host });
  return host;
}

async function expand(el: HTMLElement): Promise<void> {
  el.querySelector<HTMLButtonElement>('[data-ldp-toggle]')?.click();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('DrawerLedger: the login countdown is gone from the panel', () => {
  test('a deadline the server sent renders no countdown line, collapsed or expanded', async () => {
    const at = new Date(Date.now() + 12.5 * DAY_MS).toISOString();
    const el = render(account({ login_expires_at: at }));
    expect(el.querySelector('.ldp-login')).toBeNull();
    await expand(el);
    expect(el.querySelector('.ldp-login')).toBeNull();
    expect(el.textContent).not.toContain('login expires');
  });
});

describe('DrawerLedger: provider and plan sit beside the name when expanded', () => {
  test('collapsed shows no plan text', () => {
    const el = render(account({}));
    expect(el.querySelector('.ldp-plan')).toBeNull();
  });

  test('expanded puts "claude" and "max 20x", middle-dot separated, right after the name', async () => {
    const el = render(account({}));
    await expand(el);
    const row = el.querySelector('.ldp-id');
    const plan = row?.querySelector('.ldp-plan');
    expect(plan).not.toBeNull();
    expect(plan?.querySelector('.ldp-dot')).not.toBeNull();
    expect(plan?.textContent?.trim()).toBe('claudemax 20x');
    expect(plan?.parentElement).toBe(row);
    expect(row?.querySelector('.ldp-name + .ldp-plan')).toBe(plan);
  });
});

describe('DrawerLedger: re-add after a refresh that is never retried', () => {
  test('a failed poke on a still-ok token offers re-add', () => {
    const el = render(account({ poke: { state: 'failed', error: 'poke_no_refresh' } }));
    expect(el.querySelector('.ldp-readd')).not.toBeNull();
  });

  test('an unknown poke offers re-add too', () => {
    const el = render(account({ poke: { state: 'unknown', error: 'poke_timed_out' } }));
    expect(el.querySelector('.ldp-readd')).not.toBeNull();
  });

  test('a healthy row with a successful poke does not', () => {
    const el = render(account({ poke: { state: 'idle', error: null } }));
    expect(el.querySelector('.ldp-readd')).toBeNull();
  });
});
