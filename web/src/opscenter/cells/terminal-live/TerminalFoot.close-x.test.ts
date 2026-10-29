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

function setup(width = 1440): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width } }));
  flushSync();
  return target;
}

const bar = (target: HTMLElement) => target.querySelector<HTMLButtonElement>('button.oc-tf')!;
const grown = (target: HTMLElement) => target.querySelector<HTMLElement>('.oc-tf-grown')!;
const closeX = (target: HTMLElement) => target.querySelector<HTMLButtonElement>('.oc-tf-close button');

test('collapsed: the X is not in the document at all', () => {
  const target = setup();
  expect(grown(target).hidden).toBe(true);
  expect(closeX(target)).toBeNull();
});

test('grown: the X is visible, keyboard-reachable, and named by i18n', () => {
  const target = setup();
  bar(target).click();
  flushSync();
  const x = closeX(target);
  expect(x).not.toBeNull();
  expect(x!.getAttribute('type')).toBe('button');
  expect(x!.getAttribute('aria-label')).toBeTruthy();
});

test('a click on the X collapses the bar, same as the toggle', () => {
  const target = setup();
  bar(target).click();
  flushSync();
  expect(grown(target).hidden).toBe(false);
  closeX(target)!.click();
  flushSync();
  expect(grown(target).hidden).toBe(true);
  expect(bar(target).getAttribute('aria-expanded')).toBe('false');
});

test('NO RESIZE VOTE: the X collapsing never asks the fit pipeline to run, or fires a window resize', () => {
  const target = setup();
  bar(target).click();
  flushSync();
  const resized = vi.fn();
  window.addEventListener('resize', resized);
  closeX(target)!.click();
  flushSync();
  window.removeEventListener('resize', resized);
  expect(requestFit).not.toHaveBeenCalled();
  expect(resized).not.toHaveBeenCalled();
});
