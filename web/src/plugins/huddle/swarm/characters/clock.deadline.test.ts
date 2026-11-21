/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { EXPRESSIONS } from './expressions';
import { createClock, TICK_MS, watchVisibility, packClock } from './clock';
import { windowCalm, calmReasons, watchWindowCalm } from '../../../../lib/motion/window-calm';

function square(): HTMLElement {
  const el = document.createElement('div');
  el.className = 'pk-sq';
  document.body.append(el);
  return el;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(1_000_000);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.innerHTML = '';
  document.documentElement.removeAttribute('data-calm');
});

const realSet = globalThis.setTimeout;

describe('the deadline-driven clock', () => {
  test('never uses setInterval; one idle character fires few timers, off-edge wakes sit on the 250 ms grid', () => {
    const setInt = vi.spyOn(globalThis, 'setInterval');
    const targets: number[] = [];
    const spy = vi.spyOn(globalThis, 'setTimeout').mockImplementation(((fn: () => void, ms?: number) => {
      if ((ms ?? 0) >= TICK_MS) targets.push(Date.now() + (ms ?? 0));
      return realSet(fn, ms);
    }) as never);
    const clock = createClock(
      () => 0.5,
      () => true,
    );
    clock.register(square(), () => 'idle');
    const base = spy.mock.calls.length;
    vi.advanceTimersByTime(60_000);
    const fired = spy.mock.calls.length - base + 1;
    expect(setInt).not.toHaveBeenCalled();
    expect(fired).toBeLessThanOrEqual(90);
    const longOnes = spy.mock.calls.map(([, ms]) => Number(ms)).filter((ms) => ms >= TICK_MS);
    expect(longOnes.length).toBeGreaterThan(0);
    expect(targets.every((t) => t % TICK_MS === 0)).toBe(true);
    expect(longOnes.every((ms) => ms <= 2000)).toBe(true);
  });

  test('a blink closes within 110 ms of opening', () => {
    const el = square();
    const clock = createClock(
      () => 0.1,
      () => true,
    );
    clock.register(el, () => 'idle');
    let closedAt = -1;
    let openAt = -1;
    for (let t = 0; t < 8000 && closedAt < 0; t++) {
      vi.advanceTimersByTime(1);
      const open = el.style.getPropertyValue('--bl') === '0.1';
      if (open && openAt < 0) openAt = t;
      if (!open && openAt >= 0) closedAt = t;
    }
    expect(openAt).toBeGreaterThanOrEqual(0);
    expect(closedAt - openAt).toBeLessThanOrEqual(112);
    expect(closedAt - openAt).toBeGreaterThanOrEqual(108);
  });

  test('zero timers when empty, all still, or paused; exactly one after register, reset, play and resume', () => {
    const clock = createClock(
      () => 0.5,
      () => true,
    );
    expect(vi.getTimerCount()).toBe(0);
    const still = square();
    still.setAttribute('data-still', '');
    const off = clock.register(still, () => 'idle');
    expect(vi.getTimerCount()).toBe(0);
    off();
    const el = square();
    const unregister = clock.register(el, () => 'idle');
    expect(vi.getTimerCount()).toBe(1);
    clock.reset(el);
    expect(vi.getTimerCount()).toBe(1);
    clock.play(el, EXPRESSIONS[0]!);
    expect(vi.getTimerCount()).toBe(1);
    clock.setPaused(true);
    expect(vi.getTimerCount()).toBe(0);
    clock.setPaused(false);
    expect(vi.getTimerCount()).toBe(1);
    unregister();
    expect(vi.getTimerCount()).toBe(0);
  });

  test('a calm window pauses the shared clock and clearing calm resumes it synchronously', () => {
    const unwatch = watchWindowCalm(() => {});
    const el = square();
    const off = packClock.register(el, () => 'idle');
    watchVisibility();
    expect(vi.getTimerCount()).toBe(1);
    document.documentElement.setAttribute('data-calm', 'blur');
    document.dispatchEvent(
      new CustomEvent('carnivore:calm', {
        detail: { calm: true, reasons: ['blur'] },
      }),
    );
    expect(windowCalm()).toBe(true);
    expect(calmReasons()).toEqual(['blur']);
    expect(vi.getTimerCount()).toBe(0);
    document.documentElement.removeAttribute('data-calm');
    document.dispatchEvent(
      new CustomEvent('carnivore:calm', {
        detail: { calm: false, reasons: [] },
      }),
    );
    expect(vi.getTimerCount()).toBe(1);
    off();
    unwatch();
  });

  test('re-arming mid-sleep keeps the deadline: a steady stream of re-arms cannot stall the clock', () => {
    const el = square();
    const clock = createClock(
      () => 0.5,
      () => true,
    );
    const base = Date.now();
    clock.register(el, () => 'idle');
    let opened = -1;
    for (let t = 1; t <= 4000 && opened < 0; t++) {
      vi.advanceTimersByTime(1);
      if (t % 100 === 0) clock.setPaused(false);
      if (el.style.getPropertyValue('--bl') === '0.1') opened = Date.now() - base;
    }
    expect(opened).toBeGreaterThanOrEqual(2400);
    expect(opened).toBeLessThanOrEqual(2400 + TICK_MS);
  });

  test('pausing during a blink leaves the eyes open and the hop finished', () => {
    const el = square();
    const clock = createClock(
      () => 0.1,
      () => true,
    );
    clock.register(el, () => 'idle');
    let guard = 0;
    while (el.style.getPropertyValue('--bl') !== '0.1' && guard++ < 8000) vi.advanceTimersByTime(1);
    expect(el.style.getPropertyValue('--bl')).toBe('0.1');
    clock.setPaused(true);
    expect(el.style.getPropertyValue('--bl')).toBe('');
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(5000);
    expect(el.style.getPropertyValue('--bl')).toBe('');
    clock.setPaused(false);
    expect(vi.getTimerCount()).toBe(1);
  });

  test('the grid is 250 ms', () => {
    expect(TICK_MS).toBe(250);
  });
});
