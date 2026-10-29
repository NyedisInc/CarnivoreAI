/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import type { AccountUsage, LedgerSnapshot } from '../../opscenter/api/types';

const fakeLedger = vi.hoisted(() => ({
  status: 'ok' as const,
  data: null as LedgerSnapshot | null,
  fetchedAt: Date.now() as number | null,
  error: null as string | null,
}));
const bound = vi.hoisted(() => ({ id: '' }));
const usageBySession = vi.hoisted(() => ({} as Record<string, { state: string; account: { id: string } | null }>));

vi.mock('../../opscenter/api', () => ({
  ledger: fakeLedger,
  primarySessionId: () => bound.id,
}));
vi.mock('../../opscenter/api/session-usage.svelte', () => ({
  sessionUsage: (id: string) => ({ data: usageBySession[id] ?? null }),
  releaseSessionUsage: () => undefined,
}));

import DrawerLedger from './DrawerLedger.svelte';
import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';

function account(id: string, name: string): AccountUsage {
  return {
    id, name, short_name: null, provider: 'claude', plan: 'max', identity: id,
    credential_state: 'ok', fetched_at: null, next_poll_at: null, error: null,
    windows: [], color: null, managed: true,
  };
}

let host: HTMLElement | null = null;
let instance: unknown = null;

afterEach(() => {
  if (instance) unmount(instance as never);
  instance = null;
  host?.remove();
  host = null;
  bound.id = '';
  for (const k of Object.keys(usageBySession)) delete usageBySession[k];
  localStorage.clear();
});

function render(): HTMLElement {
  fakeLedger.data = {
    accounts: [account('gmail', 'the owner Gmail'), account('initech', 'the owner INITECH')],
    total: { accounts: 2, windows: [] },
    loop: { alive: true, last_pass_at: null },
  };
  host = document.createElement('div');
  document.body.appendChild(host);
  instance = mount(DrawerLedger, { target: host });
  flushSync();
  return host;
}

function marked(el: HTMLElement): string[] {
  return [...el.querySelectorAll<HTMLElement>('.ldp-account[data-active-account="1"]')].map(
    (row) => row.querySelector('.ldp-name')?.textContent?.trim() ?? '',
  );
}

function select(id: string): void {
  bound.id = id;
  globalThis.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: id } }));
  flushSync();
}

describe('DrawerLedger: the selected session highlights its own account', () => {
  test('no selection marks no row', () => {
    expect(marked(render())).toEqual([]);
  });

  test('the highlight follows the selection', () => {
    usageBySession.a = { state: 'ok', account: { id: 'initech' } };
    usageBySession.b = { state: 'ok', account: { id: 'gmail' } };
    const el = render();
    select('a');
    expect(marked(el)).toEqual(['the owner INITECH']);
    select('b');
    expect(marked(el)).toEqual(['the owner Gmail']);
  });

  test('an unread transcript still highlights the resolved account', () => {
    usageBySession.a = { state: 'unchecked', account: { id: 'initech' } };
    const el = render();
    select('a');
    expect(marked(el)).toEqual(['the owner INITECH']);
  });

  test('an unknown account marks nothing, and the marked row says why', () => {
    usageBySession.a = { state: 'ok', account: null };
    usageBySession.b = { state: 'ok', account: { id: 'initech' } };
    const el = render();
    select('a');
    expect(marked(el)).toEqual([]);
    select('b');
    const row = el.querySelector<HTMLElement>('.ldp-account[data-active-account="1"]');
    expect(row).not.toBeNull();
    expect(row?.hasAttribute('title')).toBe(false);
  });
});
