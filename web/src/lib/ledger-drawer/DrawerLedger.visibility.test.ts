/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import type { LedgerSnapshot } from '../../opscenter/api/types';

const fakeLedger = vi.hoisted(() => ({
  status: 'loading' as 'loading' | 'ok' | 'error' | 'unavailable' | 'signed-out',
  data: null as LedgerSnapshot | null,
  fetchedAt: null as number | null,
  error: null as string | null,
}));

vi.mock('../../opscenter/api', () => ({
  ledger: fakeLedger,
  primarySessionId: () => '',
}));

import DrawerLedger from './DrawerLedger.svelte';

const NONE: LedgerSnapshot = {
  accounts: [],
  total: { accounts: 0, windows: [] },
  loop: { alive: true, last_pass_at: null },
};

const ONE: LedgerSnapshot = {
  accounts: [
    {
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
      managed: false,
    },
  ],
  total: { accounts: 1, windows: [] },
  loop: { alive: true, last_pass_at: null },
};

let host: HTMLElement | null = null;
let instance: unknown = null;

afterEach(() => {
  if (instance) unmount(instance as never);
  instance = null;
  host?.remove();
  host = null;
  fakeLedger.status = 'loading';
  fakeLedger.data = null;
  fakeLedger.fetchedAt = null;
  fakeLedger.error = null;
});

function render(): HTMLElement {
  host = document.createElement('div');
  document.body.appendChild(host);
  instance = mount(DrawerLedger, { target: host });
  return host;
}

describe('DrawerLedger: notice when empty, panel when not', () => {
  test('a loaded ledger with zero accounts shows a one-line notice with an add link, not the panel', () => {
    fakeLedger.status = 'ok';
    fakeLedger.data = NONE;
    const el = render();
    expect(el.querySelector('.ldp')).toBeNull();
    const line = el.querySelector('.ldp-empty');
    expect(line).not.toBeNull();
    expect(line!.textContent).toContain('no accounts yet.');
    const link = line!.querySelector<HTMLAnchorElement>('a.ldp-empty-link');
    expect(link?.textContent).toBe('add one');
    expect(link?.getAttribute('href')).toBe('#ledger');
  });

  test('a loaded ledger with one account renders the panel', () => {
    fakeLedger.status = 'ok';
    fakeLedger.data = ONE;
    const el = render();
    expect(el.querySelector('.ldp')).not.toBeNull();
    expect(el.textContent).toContain('main');
  });

  test('still loading (no snapshot yet) keeps the panel, not the empty gate', () => {
    fakeLedger.status = 'loading';
    fakeLedger.data = null;
    const el = render();
    expect(el.querySelector('.ldp')).not.toBeNull();
  });

  test('a read error on an install that has accounts keeps the panel visible', () => {
    fakeLedger.status = 'error';
    fakeLedger.data = null;
    fakeLedger.error = 'boom';
    const el = render();
    expect(el.querySelector('.ldp')).not.toBeNull();
  });
});

describe('DrawerLedger: the fold button is a four step control', () => {
  test('each press moves to the next view, the label names it, and no step dots sit beside the chevron', async () => {
    fakeLedger.status = 'ok';
    fakeLedger.data = ONE;
    localStorage.clear();
    const el = render();
    const button = el.querySelector<HTMLButtonElement>('[data-ldp-toggle]')!;
    const seen: Array<[string | null, string]> = [];
    for (let press = 0; press < 5; press += 1) {
      seen.push([button.getAttribute('data-fold'), button.getAttribute('aria-label') ?? '']);
      button.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    expect(el.querySelectorAll('.ldp-step, .ldp-steps')).toHaveLength(0);
    expect(button.querySelectorAll('svg')).toHaveLength(1);
    expect(seen.map(([fold]) => fold)).toEqual(['compact', 'expanded', 'glance', 'hidden', 'compact']);
    expect(seen[0]![1]).toContain('view 3 of 4');
    expect(seen[1]![1]).toContain('view 4 of 4');
    expect(seen[2]![1]).toContain('view 1 of 4');
  });
});
