/** @vitest-environment jsdom */
import { afterEach, beforeAll, describe, expect, test, vi } from 'vitest';
import { installSharedTooltip, SHOW_DELAY_MS } from './tooltip';
import { revealCutOffText } from './cut-off-reveal';

const FULL = 'a very long session name that the drawer will certainly truncate';

function row(scroll: number, client: number, cls = 'session-sidebar-row-name'): HTMLElement {
  const wrap = document.createElement('div');
  const el = document.createElement('span');
  el.className = cls;
  el.textContent = FULL;
  Object.defineProperty(el, 'scrollWidth', { value: scroll, configurable: true });
  Object.defineProperty(el, 'clientWidth', { value: client, configurable: true });
  wrap.appendChild(el);
  document.body.appendChild(wrap);
  return el;
}
const over = (el: Element): void => void el.dispatchEvent(new MouseEvent('pointerover', { bubbles: true }));
const shown = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('.cc-tooltip')].filter((e) => !e.hidden);

beforeAll(() => {
  installSharedTooltip();
  const real = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((el: Element) => {
    const cs = real(el);
    if (!el.classList.contains('session-sidebar-row-name') && !el.classList.contains('rail-key-label')) return cs;
    return new Proxy(cs, {
      get: (t, k) => (k === 'textOverflow' ? 'ellipsis' : k === 'getPropertyValue' ? (p: string) => t.getPropertyValue(p) : Reflect.get(t, k)),
    });
  });
});
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
});

describe('cut-off text reveal', () => {
  test('a cut-off sidebar row name reveals its full words after the shared delay', () => {
    vi.useFakeTimers();
    const el = row(400, 150);
    over(el);
    expect(el.getAttribute('data-tooltip')).toBe(FULL);
    vi.advanceTimersByTime(SHOW_DELAY_MS + 10);
    expect(shown()[0]?.textContent).toBe(FULL);
  });

  test('a row name that fits reveals nothing', () => {
    vi.useFakeTimers();
    const el = row(150, 150);
    over(el);
    vi.advanceTimersByTime(SHOW_DELAY_MS + 10);
    expect(shown()).toHaveLength(0);
    expect(el.hasAttribute('data-tooltip')).toBe(false);
  });

  test('a rail key label is revealed when cut off, and withdrawn once it fits', () => {
    const el = row(300, 100, 'rail-key-label');
    revealCutOffText(el);
    expect(el.getAttribute('data-tooltip')).toBe(FULL);
    Object.defineProperty(el, 'scrollWidth', { value: 100 });
    revealCutOffText(el);
    expect(el.hasAttribute('data-tooltip')).toBe(false);
  });

  test('hovering a child inside the cut-off element reveals the parent text', () => {
    const el = row(400, 150);
    const child = document.createElement('b');
    el.appendChild(child);
    revealCutOffText(child);
    expect(el.getAttribute('data-tooltip')).toContain(FULL);
  });

  test('an authored title or data-tooltip is left alone', () => {
    const el = row(400, 150);
    el.setAttribute('data-tooltip', 'authored');
    revealCutOffText(el);
    expect(el.getAttribute('data-tooltip')).toBe('authored');
  });

  test('text with no ellipsis style is never touched', () => {
    const el = row(400, 150, 'plain');
    revealCutOffText(el);
    expect(el.hasAttribute('data-tooltip')).toBe(false);
  });
});
