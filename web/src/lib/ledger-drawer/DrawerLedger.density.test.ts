/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import type { AccountUsage, LedgerSnapshot } from '../../opscenter/api/types';

const fakeLedger = vi.hoisted(() => ({
  status: 'ok' as 'ok',
  data: null as LedgerSnapshot | null,
  fetchedAt: Date.now() as number | null,
  error: null as string | null,
}));

vi.mock('../../opscenter/api', () => ({ ledger: fakeLedger, primarySessionId: () => '' }));

import DrawerLedger from './DrawerLedger.svelte';

const win = (kind: string, label: string, used_pct: number) => ({
  kind, label, used_pct, resets_at: new Date(Date.now() + 3_600_000).toISOString(), window_seconds: null,
});

const account = (id: string, name: string): AccountUsage => ({
  id, name, short_name: name, provider: 'claude', plan: 'max', identity: null, credential_state: 'ok',
  fetched_at: null, next_poll_at: null, error: null, color: null, managed: true,
  windows: [win('five_hour', '5h', 10), win('seven_day', '7d', 40)],
} as unknown as AccountUsage);

const SNAPSHOT = {
  accounts: [account('a', 'alpha'), account('b', 'bravo')],
  total: {
    accounts: 3,
    windows: [
      { provider: 'claude', kind: 'five_hour', label: '5h', used_pct: 4, resets_at: null, accounts: 2 },
      { provider: 'claude', kind: 'seven_day', label: '7d', used_pct: 48, resets_at: null, accounts: 2 },
      { provider: 'codex', kind: 'primary', window_seconds: 604800, label: '7d', used_pct: 11, resets_at: null, accounts: 1 },
      { provider: 'antigravity', kind: 'gemini-5h', window_seconds: 18000, label: '5h', used_pct: 22, resets_at: null, accounts: 1 },
      { provider: 'antigravity', kind: 'gemini-weekly', window_seconds: 604800, label: '7d', used_pct: 50, resets_at: null, accounts: 1 },
    ],
  },
  loop: { alive: true, last_pass_at: null },
} as unknown as LedgerSnapshot;

let host: HTMLElement | null = null;
let instance: unknown = null;

afterEach(() => {
  if (instance) unmount(instance as never);
  instance = null;
  host?.remove();
  host = null;
  localStorage.clear();
});

function render(): HTMLElement {
  fakeLedger.data = SNAPSHOT;
  localStorage.clear();
  host = document.createElement('div');
  document.body.appendChild(host);
  instance = mount(DrawerLedger, { target: host });
  return host;
}

const foldOf = (el: HTMLElement): string | null => el.querySelector('.ldp')!.getAttribute('data-fold');

describe('DrawerLedger density', () => {
  test('empty header space steps compact, expanded, glance, total only and wraps; the smallest view is the total line alone', () => {
    const el = render();
    const title = el.querySelector<HTMLElement>('.ldp-head')!;
    const seen: Array<string | null> = [foldOf(el)];
    expect(el.querySelectorAll('.ldp-account')).toHaveLength(2);

    title.click();
    flushSync();
    seen.push(foldOf(el));

    title.click();
    flushSync();
    seen.push(foldOf(el));
    expect(el.querySelectorAll('[data-ledger-glance] .pgl')).toHaveLength(2);
    expect(el.querySelector('.ldp-total')).toBeNull();
    title.click();
    flushSync();
    seen.push(foldOf(el));
    expect(el.querySelectorAll('.ldp-account')).toHaveLength(0);
    expect(el.querySelector('.ldp-accounts-count')?.textContent).toBe('3 accounts');
    expect(el.querySelector('.ldp-total .ldp-mini--stacked')).not.toBeNull();
    const meters = [...el.querySelectorAll('.ldp-total .ldp-mini .ldp-meter')];
    expect(meters.map((m) => m.textContent?.replace(/\s+/g, ' ').trim())).toEqual(['7d 48%', '7d 11%', '7d 50%']);
    expect(el.querySelectorAll('.ldp-total .ldp-mini .ldp-meter .oc-gauge').length).toBe(3);
    expect(el.querySelectorAll('.ldp-total .ldp-meter .ldp-provider-mark[role="img"]').length).toBe(3);
    expect(el.querySelector('.ldp-window, table')).toBeNull();

    title.click();
    flushSync();
    seen.push(foldOf(el));
    expect(seen).toEqual(['compact', 'expanded', 'glance', 'hidden', 'compact']);
  });

  test('a click on the empty header space steps; a click on the auto-switch control or the caret does the right one thing', () => {
    const el = render();
    el.querySelector<HTMLElement>('.ldp-head')!.click();
    flushSync();
    expect(foldOf(el)).toBe('expanded');
    const other = el.querySelector<HTMLButtonElement>('.ldp-head button:not([data-ldp-toggle])');
    expect(other).not.toBeNull();
    other!.click();
    flushSync();
    expect(foldOf(el)).toBe('expanded');
    el.querySelector<HTMLButtonElement>('[data-ldp-toggle]')!.click();
    flushSync();
    expect(foldOf(el)).toBe('glance');
  });
});
