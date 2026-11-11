/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalFoot from './TerminalFoot.svelte';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessionUsage: vi.fn((id: string) => ({
      data: {
        state: 'ok', family: 'claude', model: 'claude-opus-4', model_display_name: 'Opus 4',
        model_cost_tier: 3, effort: null, input_tokens: 1, output_tokens: 1,
        cache_read_input_tokens: null, cache_creation_input_tokens: null, total_tokens: 2,
        cost_estimate_usd: 0, context_used_tokens: 1000, context_window_tokens: 200000,
        context_remaining_pct: 99, as_of: '2026-10-02T00:00:00Z', detail: null,
        account: id.startsWith('remote:peer-aa') ? { id: 'far-1', name: 'Nyedis', short_name: null, provider: 'claude', plan: null, identity: null, credential_state: 'ok', fetched_at: null, windows: [] } : null,
      },
      status: 'ok',
    })),
    releaseSessionUsage: vi.fn(),
    sessions: { data: [
      { session: { id: 'ses_1' }, agent_family: 'claude', account_id: 'acct-1' },
      { session: { id: 'remote:peer-aa:carnivore_x' }, agent_family: 'claude', account_id: null, host_key: 'peer-aa', host_label: 'Cerberus', host_state: 'up' },
      { session: { id: 'remote:peer-bb:carnivore_y' }, agent_family: 'claude', account_id: null, host_key: 'peer-bb', host_label: null, host_state: 'up' },
    ] },
  };
});
vi.mock('../../api/ledger.svelte', () => ({
  ledger: { data: { accounts: [{ id: 'acct-1', name: 'Claude Code - Acme', short_name: 'Nyedis' }] } },
}));

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

test('the account tag is a descendant of the bar element, not a sibling past its edge', () => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width: 900 } }));
  flushSync();
  const tag = target.querySelector('.oc-tf-acct');
  expect(tag?.textContent).toContain('Nyedis');
  const bar = tag?.closest('[data-foot-bar]');
  expect(bar).not.toBeNull();
  expect(bar?.querySelector('button.oc-tf')).not.toBeNull();
});

test('a session on a paired computer shows the account that computer named, with no mismatch warning', () => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'remote:peer-aa:carnivore_x', width: 900 } }));
  flushSync();
  const tag = target.querySelector('.oc-tf-acct');
  expect(tag?.textContent).toContain('Nyedis');
  expect(tag?.querySelector('.oc-tf-acct-warn')).toBeNull();
});

test('a far session shows the linked mark and the computer name beside the account; local shows none', () => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'remote:peer-aa:carnivore_x', width: 900 } }));
  flushSync();
  const host = target.querySelector('.oc-tf-host');
  expect(host?.textContent).toContain('Cerberus');
  expect(host?.querySelector('svg')).not.toBeNull();
  expect(host?.getAttribute('aria-label')).toBe('running on Cerberus');
  expect(host?.nextElementSibling?.classList.contains('oc-tf-acct')).toBe(true);
  const local = document.createElement('div');
  document.body.append(local);
  mounted.push(mount(TerminalFoot, { target: local, props: { sessionId: 'ses_1', width: 900 } }));
  flushSync();
  expect(local.querySelector('.oc-tf-host')).toBeNull();
});

test('the host tag still shows with no account, falling back to host_key', () => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'remote:peer-bb:carnivore_y', width: 900 } }));
  flushSync();
  expect(target.querySelector('.oc-tf-acct')).toBeNull();
  expect(target.querySelector('.oc-tf-host')?.textContent).toContain('peer-bb');
});
