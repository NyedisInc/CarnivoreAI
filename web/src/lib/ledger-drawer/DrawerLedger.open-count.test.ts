/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import type { LedgerSnapshot } from '../../opscenter/api/types';
import type { ProviderSession } from '../ledger/ledger-sessions';

const fakeLedger = vi.hoisted(() => ({
  status: 'ok' as const,
  data: null as LedgerSnapshot | null,
  fetchedAt: Date.now() as number | null,
  error: null as string | null,
}));

vi.mock('../../opscenter/api', () => ({ ledger: fakeLedger, primarySessionId: () => '' }));

import DrawerLedger from './DrawerLedger.svelte';

const account = (id: string, name: string) => ({
  id,
  name,
  short_name: name,
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
  accounts: [account('a', 'Alpha'), account('b', 'Beta')],
  total: { accounts: 2, windows: [] },
  loop: { alive: true, last_pass_at: null },
} as unknown as LedgerSnapshot;

const row = (id: string, account_id: string | null) =>
  ({ session: { id }, tmux_session: id, label: null, account_id }) as unknown as ProviderSession;

let inst: Record<string, unknown> | null = null;
afterEach(() => {
  if (inst) unmount(inst as never);
  inst = null;
  document.body.innerHTML = '';
});

describe('providers widget open-session count', () => {
  test('counts per account id, zero for none, and unknown sessions count nowhere', () => {
    const host = document.createElement('div');
    document.body.append(host);
    inst = mount(DrawerLedger as never, {
      target: host,
      props: { sessionRows: [row('1', 'a'), row('2', 'a'), row('3', null), row('4', 'ghost')] },
    }) as never;
    const counts = [...host.querySelectorAll('.ldp-account')].map((li) => ({
      name: li.querySelector('.ldp-name')?.textContent?.trim(),
      count: li.querySelector('.ldp-open-count')?.textContent?.trim(),
      tip: li.querySelector('.ldp-open-count')?.getAttribute('data-tooltip'),
      title: li.querySelector('.ldp-open-count')?.getAttribute('title'),
      icon: li.querySelector('.ldp-open-count svg') !== null,
    }));
    expect(counts).toEqual([
      { name: 'Alpha', count: '2', tip: '2 open sessions', title: null, icon: true },
      { name: 'Beta', count: '0', tip: '0 open sessions', title: null, icon: true },
    ]);
  });
});
