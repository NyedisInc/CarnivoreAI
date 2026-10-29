/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalFoot from './TerminalFoot.svelte';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessionUsage: vi.fn(() => ({
      data: {
        state: 'ok', family: 'claude', model: 'claude-opus-4', model_display_name: 'Opus 4',
        model_cost_tier: 3, effort: null, input_tokens: 1, output_tokens: 1,
        cache_read_input_tokens: null, cache_creation_input_tokens: null, total_tokens: 2,
        cost_estimate_usd: 0, context_used_tokens: 1000, context_window_tokens: 200000,
        context_remaining_pct: 99, as_of: '2026-10-02T00:00:00Z', detail: null, account: null,
      },
      status: 'ok',
    })),
    releaseSessionUsage: vi.fn(),
    sessions: { data: [{ session: { id: 'ses_1' }, agent_family: 'claude', account_id: 'acct-1' }] },
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
