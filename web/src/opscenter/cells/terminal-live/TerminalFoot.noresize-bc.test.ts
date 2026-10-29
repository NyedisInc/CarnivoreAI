/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TerminalFoot from './TerminalFoot.svelte';
import type { SessionTokenUsage } from '../../api/types';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessionUsage: vi.fn(() => ({ data: USAGE, status: 'ok' })),
    releaseSessionUsage: vi.fn(),
  };
});

const USAGE = {
  state: 'ok', family: 'claude', model: 'claude-opus-4', model_display_name: 'Opus 4', model_cost_tier: 3,
  effort: 'high', input_tokens: 12000, output_tokens: 3400, cache_read_input_tokens: null,
  cache_creation_input_tokens: null, total_tokens: 15400, cost_estimate_usd: 1.2345,
  context_used_tokens: 447000, context_window_tokens: 1000000, context_remaining_pct: 55.3,
  as_of: '2026-09-24T00:00:00Z', detail: null, account: null,
} as unknown as SessionTokenUsage;

const requestFit = vi.fn();
const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  (globalThis as { TerminalLayout?: unknown }).TerminalLayout = { requestFit };
});

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete (globalThis as { TerminalLayout?: unknown }).TerminalLayout;
  requestFit.mockReset();
  try { localStorage.clear(); } catch {  }
});

function setup(width: number, collapsedOption: 'b' | 'c', openOption: 'b' | 'c'): { target: HTMLElement } {
  const area = document.createElement('div');
  area.setAttribute('data-foot-area', '');
  Object.defineProperty(area, 'clientHeight', { configurable: true, get: () => 800 });
  const pane = document.createElement('div');
  pane.className = 'oc-tl-pane';
  const target = document.createElement('div');
  area.append(pane, target);
  document.body.append(area);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width, collapsedOption, openOption } }));
  flushSync();
  return { target };
}

const bar = (target: HTMLElement) => target.querySelector<HTMLButtonElement>('button.oc-tf')!;
const grown = (target: HTMLElement) => target.querySelector<HTMLElement>('.oc-tf-grown')!;

for (const collapsedOption of ['b', 'c'] as const) {
  for (const openOption of ['b', 'c'] as const) {
    test(`option ${collapsedOption}/${openOption}: expanding and collapsing never asks the fit pipeline to run`, () => {
      const { target } = setup(1440, collapsedOption, openOption);
      const resized = vi.fn();
      window.addEventListener('resize', resized);
      bar(target).click();
      flushSync();
      expect(grown(target).hidden).toBe(false);
      bar(target).click();
      flushSync();
      window.removeEventListener('resize', resized);
      expect(requestFit).not.toHaveBeenCalled();
      expect(resized).not.toHaveBeenCalled();
    });

    test(`option ${collapsedOption}/${openOption}: the grown bar is always full width, never stopping short of the work segments`, () => {
      const { target } = setup(1440, collapsedOption, openOption);
      bar(target).click();
      flushSync();
      expect(grown(target).style.right).toBe('0px');
    });
  }
}
