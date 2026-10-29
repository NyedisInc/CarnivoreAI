/** @vitest-environment jsdom */
/* the bottom bar */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TerminalFoot from './TerminalFoot.svelte';
import type { SessionTokenUsage } from '../../api/types';
import { GROW_CAP_PX, SPLIT_MIN_WIDTH } from './foot-expand';

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
  try { localStorage.clear(); } catch { /* jsdom always has storage */ }
});

function setup(width: number, areaHeight = 800): { area: HTMLElement; pane: HTMLElement; target: HTMLElement } {
  const area = document.createElement('div');
  area.setAttribute('data-foot-area', '');
  Object.defineProperty(area, 'clientHeight', { configurable: true, get: () => areaHeight });
  const pane = document.createElement('div');
  pane.className = 'oc-tl-pane';
  const target = document.createElement('div');
  area.append(pane, target);
  document.body.append(area);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width } }));
  flushSync();
  return { area, pane, target };
}

const bar = (target: HTMLElement) => target.querySelector<HTMLButtonElement>('button.oc-tf')!;
const grown = (target: HTMLElement) => target.querySelector<HTMLElement>('.oc-tf-grown')!;
const inFlow = (target: HTMLElement) => [...target.querySelector('.oc-tf-slot')!.children]
  .filter((el) => !el.classList.contains('oc-tf-grown') && !el.classList.contains('oc-tf-measure'));

test('NO RESIZE VOTE: expanding and collapsing never asks the fit pipeline to run', () => {
  const { target } = setup(1440);
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

test('NO RESIZE VOTE: the in-flow bar is the same nodes collapsed and grown; only the overlay appears', () => {
  const { target, area, pane } = setup(1440);
  const before = inFlow(target);
  bar(target).click();
  flushSync();
  expect(inFlow(target)).toEqual(before);
  expect([...area.children]).toEqual([pane, target]);
  expect(target.querySelector('.oc-tf-slot')!.contains(grown(target))).toBe(true);
});

test('NO RESIZE VOTE: opening on a section from a segment never scrolls anything outside the bar', () => {
  const spy = vi.fn();
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = spy;
  try {
    const { target } = setup(1440);
    bar(target).click();
    flushSync();
    expect(spy).not.toHaveBeenCalled();
    expect(requestFit).not.toHaveBeenCalled();
  } finally {
    Element.prototype.scrollIntoView = original;
  }
});

test('HEIGHT: the grown bar is capped at half the terminal area, and never past its ceiling', () => {
  const small = setup(1440, 600).target;
  bar(small).click();
  flushSync();
  expect(grown(small).style.maxHeight).toBe('300px');

  const tall = setup(1440, 2000).target;
  bar(tall).click();
  flushSync();
  expect(grown(tall).style.maxHeight).toBe(`${GROW_CAP_PX}px`);
});

test('WIDTHS: columns only with room; stacked (accordion) below that; ALWAYS full width', () => {
  const layouts: Record<number, { stacked: string | null; right: string; bottom: string }> = {};
  for (const width of [1440, 1024, 800, 600, 390]) {
    const { target } = setup(width);
    bar(target).click();
    flushSync();
    const el = grown(target);
    layouts[width] = { stacked: el.getAttribute('data-stacked'), right: el.style.right, bottom: el.style.bottom };
  }
  expect(SPLIT_MIN_WIDTH).toBeLessThanOrEqual(800);
  for (const width of [1440, 1024, 800]) {
    expect(layouts[width]?.stacked).toBe('false');
    expect(layouts[width]?.right).toBe('0px');
    expect(layouts[width]?.bottom).toBe('');
  }
  // underneath.
  for (const width of [600, 390]) {
    expect(layouts[width]?.stacked).toBe('true');
    expect(layouts[width]?.right).toBe('0px');
    expect(layouts[width]?.bottom).toBe('100%');
  }
});

test('FULL WIDTH (issue #1053, Joe, 2026-09-28): the grown bar always covers the work segments, never stopping short of them', () => {
  const { target } = setup(1440);
  bar(target).click();
  flushSync();
  expect(grown(target).style.right).toBe('0px');
});
