/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { autogrow, fitHeight } from './autogrow';

const LINE = 16;
const PAD = 4;
const WIDTH_CHARS = 20;

function box(maxHeight: string): HTMLTextAreaElement {
  const el = document.createElement('textarea');
  el.style.cssText = `box-sizing: border-box; padding: 2px 0; border: 0; min-height: 20px; max-height: ${maxHeight}; height: 20px;`;
  Object.defineProperty(el, 'scrollHeight', {
    get: () => el.value.split('\n').reduce((n, line) => n + Math.max(1, Math.ceil(line.length / WIDTH_CHARS)), 0) * LINE + PAD,
  });
  document.body.appendChild(el);
  return el;
}

afterEach(() => { document.body.innerHTML = ''; });

describe('autogrow', () => {
  test('one soft-wrapped long line grows the box without a newline, and the cap stops it at three rows', () => {
    const el = box(`${3 * LINE + PAD}px`);
    expect(fitHeight(el)).toBe(20);
    el.value = 'x'.repeat(WIDTH_CHARS + 5);
    expect(fitHeight(el)).toBe(2 * LINE + PAD);
    el.value = 'x'.repeat(WIDTH_CHARS * 2 + 5);
    expect(fitHeight(el)).toBe(3 * LINE + PAD);
    el.value = 'x'.repeat(WIDTH_CHARS * 9);
    expect(fitHeight(el)).toBe(3 * LINE + PAD);
    expect(el.style.height).toBe(`${3 * LINE + PAD}px`);
  });

  test('the box refits when the text changes and shrinks back when it is cleared', () => {
    const el = box(`${3 * LINE + PAD}px`);
    const stop = autogrow(el);
    el.value = 'x'.repeat(WIDTH_CHARS * 2);
    fitHeight(el);
    expect(el.style.height).toBe(`${2 * LINE + PAD}px`);
    el.value = '';
    fitHeight(el);
    expect(el.style.height).toBe('20px');
    stop();
  });
});

describe('an empty box (issue #1710 round 6 point J)', () => {
  test('stays one line however far its placeholder wraps, and shows no scrollbar', () => {
    const el = document.createElement('textarea');
    el.style.cssText = 'box-sizing: border-box; padding: 2px 0; border: 0; min-height: 20px; max-height: 60px; height: 20px;';
    el.placeholder = 'a long hint that wraps over several lines in a narrow box';
    Object.defineProperty(el, 'scrollHeight', { value: 4 * LINE + PAD });
    document.body.appendChild(el);
    expect(fitHeight(el)).toBe(20);
    expect(el.style.overflowY).toBe('hidden');
  });
});
