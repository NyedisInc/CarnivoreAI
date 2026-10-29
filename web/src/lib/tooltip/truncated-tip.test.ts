/** @vitest-environment jsdom */
import { afterEach, beforeAll, describe, expect, test, vi } from 'vitest';
import { installSharedTooltip, SHOW_DELAY_MS } from './tooltip';
import { truncatedTip } from './truncated-tip';

function span(scroll: number, client: number): HTMLElement {
  const el = document.createElement('span');
  el.textContent = 'a long item text';
  Object.defineProperty(el, 'scrollWidth', { value: scroll });
  Object.defineProperty(el, 'clientWidth', { value: client });
  document.body.appendChild(el);
  truncatedTip(el, 'the complete item text');
  return el;
}

function over(el: Element): void {
  el.dispatchEvent(new MouseEvent('pointerover', { bubbles: true }));
}

const shown = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('.cc-tooltip')].filter((e) => !e.hidden);

beforeAll(() => installSharedTooltip());
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
});

describe('truncatedTip', () => {
  test('a clipped line shows the complete text after the shared delay', () => {
    vi.useFakeTimers();
    const el = span(300, 200);
    over(el);
    expect(shown()).toHaveLength(0);
    vi.advanceTimersByTime(SHOW_DELAY_MS + 10);
    expect(shown()[0]?.textContent).toBe('the complete item text');
  });

  test('a line that fits shows nothing', () => {
    vi.useFakeTimers();
    const el = span(200, 200);
    over(el);
    vi.advanceTimersByTime(SHOW_DELAY_MS + 10);
    expect(shown()).toHaveLength(0);
    expect(el.hasAttribute('data-tooltip')).toBe(false);
  });
});

function titleSpan(box: { sw: number; cw: number; sh: number; ch: number }, overflowY = 'hidden'): HTMLElement {
  const full = 'a deliberately long task title that the row cannot fit';
  const el = document.createElement('span');
  el.textContent = full;
  el.style.overflowY = overflowY;
  Object.defineProperty(el, 'scrollWidth', { value: box.sw });
  Object.defineProperty(el, 'clientWidth', { value: box.cw });
  Object.defineProperty(el, 'scrollHeight', { value: box.sh });
  Object.defineProperty(el, 'clientHeight', { value: box.ch });
  document.body.appendChild(el);
  truncatedTip(el, full);
  return el;
}

describe('a cut-off title whose visible text is the full text', () => {
  test('a one-line ellipsis (sidebar, compact) shows the full text', () => {
    vi.useFakeTimers();
    const el = titleSpan({ sw: 600, cw: 240, sh: 15, ch: 15 });
    over(el);
    vi.advanceTimersByTime(SHOW_DELAY_MS + 10);
    expect(el.hasAttribute('data-tooltip'), 'the action measured it clipped').toBe(true);
    expect(shown()[0]?.textContent).toBe(el.textContent);
  });

  test('a two-line clamp (pop-out, normal) shows the full text', () => {
    vi.useFakeTimers();
    const el = titleSpan({ sw: 240, cw: 240, sh: 60, ch: 30 });
    over(el);
    vi.advanceTimersByTime(SHOW_DELAY_MS + 10);
    expect(el.hasAttribute('data-tooltip'), 'the action measured it clipped').toBe(true);
    expect(shown()[0]?.textContent).toBe(el.textContent);
  });

  test('text that spills below an unclipped box is on screen, so a tip repeating it stays gone', () => {
    vi.useFakeTimers();
    const el = titleSpan({ sw: 240, cw: 240, sh: 60, ch: 30 }, 'visible');
    over(el);
    vi.advanceTimersByTime(SHOW_DELAY_MS + 10);
    expect(el.hasAttribute('data-tooltip'), 'the population: a carrier exists').toBe(true);
    expect(shown()).toHaveLength(0);
  });
});

describe('an inline node cut by its parent', () => {
  test('a text span with no box of its own is clipped when the clipping parent is', async () => {
    const { isClipped } = await import('./truncated-tip');
    const parent = document.createElement('div');
    parent.style.overflowX = 'hidden';
    Object.defineProperty(parent, 'scrollWidth', { value: 300, configurable: true });
    Object.defineProperty(parent, 'clientWidth', { value: 120 });
    const inner = document.createElement('span');
    parent.appendChild(inner);
    document.body.appendChild(parent);
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, 'getComputedStyle').mockImplementation((el: Element) => (el === parent ? ({ overflowX: 'hidden' } as CSSStyleDeclaration) : real(el)));
    expect(isClipped(inner)).toBe(true);
    Object.defineProperty(parent, 'scrollWidth', { value: 100, configurable: true });
    expect(isClipped(inner)).toBe(false);
  });
});
