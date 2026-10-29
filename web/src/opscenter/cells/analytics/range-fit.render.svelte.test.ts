/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { chooseRangeStage, fitRange, type RangeStage } from './range-fit';

afterEach(() => { document.body.innerHTML = ''; });

function strip(room: number, titleText = 'tokens by hour'): { name: HTMLElement; range: HTMLElement } {
  document.body.innerHTML = `<header class="oc-frame-title"><h2 class="oc-frame-name">${titleText}</h2><span class="analytics-range">24 hours</span></header>`;
  const name = document.querySelector<HTMLElement>('.oc-frame-name')!;
  const range = document.querySelector<HTMLElement>('.analytics-range')!;
  const used: Record<RangeStage, number> = { full: 'as of 12:00 24 hours'.length, short: '24h'.length, none: 0 };
  Object.defineProperty(name, 'clientWidth', { configurable: true, get: () => Math.max(1, room - used[range.dataset.fit as RangeStage]) });
  Object.defineProperty(name, 'scrollWidth', { configurable: true, get: () => titleText.length });
  return { name, range };
}

describe('the range label yields to the title', () => {
  test('chooseRangeStage takes the widest stage that leaves the title whole', () => {
    expect(chooseRangeStage(() => false)).toBe('full');
    expect(chooseRangeStage((stage) => stage === 'full')).toBe('short');
    expect(chooseRangeStage((stage) => stage !== 'none')).toBe('none');
  });
  test('a wide strip keeps the full range', () => {
    const { range } = strip(60);
    fitRange(range, '24 hours');
    expect(range.dataset.fit).toBe('full');
  });
  test('a narrower strip shortens the range before it cuts the title', () => {
    const { name, range } = strip('tokens by hour'.length + 3 + 1);
    fitRange(range, '24 hours');
    expect(range.dataset.fit).toBe('short');
    expect(name.scrollWidth <= name.clientWidth).toBe(true);
    expect(name.hasAttribute('title')).toBe(false);
  });
  test('a strip with room for the title alone drops the range, shows the title whole and keeps the range in its title attribute', () => {
    const { name, range } = strip('tokens by hour'.length);
    fitRange(range, '24 hours');
    expect(range.dataset.fit).toBe('none');
    expect(name.scrollWidth <= name.clientWidth).toBe(true);
    expect(name.getAttribute('title')).toBe('tokens by hour, 24 hours');
  });
  test('widening again brings the range back and clears the hint', () => {
    const { name, range } = strip('tokens by hour'.length);
    const handle = fitRange(range, '24 hours');
    expect(range.dataset.fit).toBe('none');
    Object.defineProperty(name, 'clientWidth', { configurable: true, get: () => 80 });
    handle.update('24 hours');
    expect(range.dataset.fit).toBe('full');
    expect(name.hasAttribute('title')).toBe(false);
  });
});
