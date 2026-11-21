/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalFoot from './TerminalFoot.svelte';

const delegated = { jobs: 1, input_tokens: 200000, output_tokens: 99000, cache_read_tokens: 0, cache_write_tokens: 0, cost_usd: 0.3, accounts: [] };
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessionUsage: vi.fn((id: string) => ({
      data: {
        state: 'ok', family: 'claude', model: 'claude-opus-4', model_display_name: 'Opus 4', model_cost_tier: 3, effort: null,
        input_tokens: 1, output_tokens: 1, cache_read_input_tokens: null, cache_creation_input_tokens: null, total_tokens: 2,
        cost_estimate_usd: 0, context_used_tokens: 1000, context_window_tokens: 200000, context_remaining_pct: 99,
        as_of: '2026-11-19T00:00:00Z', detail: null, account: null,
        delegated: id === 'ses_1' ? delegated : id === 'ses_3' ? { ...delegated, jobs: 0, running: 1, running_on: ['tower'] } : undefined,
      },
      status: 'ok',
    })),
    releaseSessionUsage: vi.fn(),
    sessions: { data: [{ session: { id: 'ses_1' }, agent_family: 'claude', account_id: null }, { session: { id: 'ses_2' }, agent_family: 'claude', account_id: null }, { session: { id: 'ses_3' }, agent_family: 'claude', account_id: null }] },
  };
});
vi.mock('../../api/ledger.svelte', () => ({ ledger: { data: { accounts: [] } } }));
vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

function foot(id: string): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: id, width: 900 } }));
  flushSync();
  return target;
}

test('delegated work draws the wolf icon alone, the numbers in its hover', () => {
  const tag = foot('ses_1').querySelector('[data-foot-delegated]');
  expect(tag?.querySelector('svg')).not.toBeNull();
  expect(tag?.textContent?.trim()).toBe('');
  expect(tag?.getAttribute('title')).toContain('+ 1 job: 299k tokens, $0.30');
});

test('work running on another computer turns the icon green with no usage yet; finished work keeps the default', () => {
  const live = foot('ses_3').querySelector('[data-foot-delegated]');
  expect((live as HTMLElement).style.color).toBe('var(--oc-green)');
  expect(live?.getAttribute('title')).toContain('running now on tower');
  expect((foot('ses_1').querySelector('[data-foot-delegated]') as HTMLElement).style.color).toBe('');
});

test('no delegated work draws nothing', () => {
  expect(foot('ses_2').querySelector('[data-foot-delegated]')).toBeNull();
});
