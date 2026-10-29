/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import type { LedgerSnapshot } from '../../api/types';

const fakeLedger = vi.hoisted(() => ({
  status: 'ok' as const,
  data: null as LedgerSnapshot | null,
  fetchedAt: Date.now() as number | null,
  error: null as string | null,
}));

vi.mock('../../api', () => ({ ledger: fakeLedger, primarySessionId: () => '' }));

import DrawerLedger from '../../../lib/ledger-drawer/DrawerLedger.svelte';
import Cell from './Cell.svelte';

const account = (id: string, name: string, short: string | null) => ({
  id,
  name,
  short_name: short,
  provider: 'claude',
  plan: 'max',
  identity: null,
  credential_state: 'ok',
  fetched_at: null,
  next_poll_at: null,
  error: null,
  windows: [],
  color: null,
  managed: true,
});

fakeLedger.data = {
  accounts: [account('a', 'Claude - acme', 'acme'), account('b', 'Plain Name', null)],
  total: { accounts: 2, windows: [] },
  loop: { alive: true, last_pass_at: null },
} as unknown as LedgerSnapshot;

const mounted: Array<{ inst: unknown; host: HTMLElement }> = [];
function render(component: unknown, props: Record<string, unknown> = {}): HTMLElement {
  const host = document.createElement('div');
  document.body.append(host);
  const inst = mount(component as never, { target: host, props });
  mounted.push({ inst, host });
  return host;
}
afterEach(() => {
  for (const m of mounted.splice(0)) {
    unmount(m.inst as never);
    m.host.remove();
  }
});

describe('home ledger cell renders the drawer widget', () => {
  test('same rows, names, switch buttons and auto-switch icon', () => {
    const drawer = render(DrawerLedger);
    const cell = render(Cell, {
      width: 400,
      height: 300,
      meta: {},
      limit: null,
      phone: false,
    });
    const names = (h: HTMLElement) => [...h.querySelectorAll('.ldp-name')].map((n) => n.textContent?.trim());
    expect(names(cell)).toEqual(['acme', 'Plain Name']);
    expect(names(cell)).toEqual(names(drawer));
    const count = (h: HTMLElement, sel: string) => h.querySelectorAll(sel).length;
    expect(count(cell, '.ldp-account')).toBe(count(drawer, '.ldp-account'));
    expect(count(cell, '.ldp-account')).toBe(2);
    expect(count(cell, '.ldp-auto')).toBe(1);
    expect(count(cell, '.ldp-open-count')).toBe(2);
    expect(cell.querySelector('.ldp')?.getAttribute('data-embedded')).toBe('1');
  });
});
