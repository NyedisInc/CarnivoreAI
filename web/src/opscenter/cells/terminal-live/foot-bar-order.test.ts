/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TerminalFoot from './TerminalFoot.svelte';
import { asFootBarOrder, moveInOrder } from './foot-bar-order';
import type { SessionTokenUsage } from '../../api/types';

let currentPayload: SessionTokenUsage | null = null;
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessionUsage: vi.fn(() => ({ data: currentPayload, status: 'ok' })),
    releaseSessionUsage: vi.fn(),
  };
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  currentPayload = null;
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
});

test('absent and partial values read as a complete order', () => {
  expect(asFootBarOrder(undefined)).toEqual(['context', 'window_5h', 'window_7d']);
  expect(asFootBarOrder(['window_7d', 'bogus', 'window_7d'])).toEqual(['window_7d', 'context', 'window_5h']);
});

test('moveInOrder swaps one step and is a no-op at the ends', () => {
  const built = ['context', 'window_5h', 'window_7d'] as const;
  expect(moveInOrder(built, 'window_5h', 'up')).toEqual(['window_5h', 'context', 'window_7d']);
  expect(moveInOrder(built, 'context', 'up')).toEqual([...built]);
  expect(moveInOrder(built, 'window_7d', 'down')).toEqual([...built]);
});

function meterLabels(order: string[] | null): string[] {
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: (field: string) => (field === 'foot_bar_order' ? order : null),
    write: async () => ({ status: 'committed' }),
    follow: () => () => {},
  };
  currentPayload = {
    state: 'ok', family: 'claude', model: 'claude-opus-4', model_display_name: 'Opus 4', model_cost_tier: 3,
    effort: null, input_tokens: 1000, output_tokens: 500, cache_read_input_tokens: null,
    cache_creation_input_tokens: null, total_tokens: 1500, cost_estimate_usd: 0.5, context_used_tokens: 1000,
    context_window_tokens: 200000, context_remaining_pct: 99.5, as_of: '2026-09-24T00:00:00Z', detail: null,
    account: {
      id: 'acct-1', name: 'Claude Code', short_name: null, provider: 'claude', plan: null, identity: null,
      credential_state: 'ok', fetched_at: null, next_poll_at: null, error: null, color: null, managed: false,
      windows: [
        { kind: 'five_hour', label: '5h', used_pct: 26, resets_at: '2026-09-27T12:00:00Z' } as never,
        { kind: 'seven_day', label: '7d', used_pct: 29, resets_at: '2026-10-01T00:00:00Z' } as never,
      ],
    },
  } as SessionTokenUsage;
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width: 1400 } }));
  flushSync();
  return [...target.querySelectorAll('button.oc-tf .oc-tf-meters .oc-tf-label')].map((el) => el.getAttribute('title') || el.textContent || '');
}

test('the live collapsed bar draws its meters in the saved order', () => {
  const built = meterLabels(null);
  expect(built).toHaveLength(3);
  const flipped = meterLabels(['window_7d', 'window_5h', 'context']);
  expect(flipped).toEqual([...built].reverse());
});
