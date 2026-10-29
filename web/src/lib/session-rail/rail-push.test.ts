/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { CELL_WIDTH_FALLBACK_PX, TERMINAL_MIN_COLUMNS } from './bar-limits';
import { flushSync } from 'svelte';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD, RAIL_SPECS } from './rail-model';
import { RAIL_PUSH_DEBOUNCE_MS } from './rail-size';
import { BOTTOM_FIELD, follow, keyIn, mountRails, ptr, unmountRails } from './rail-test-harness';

const side = (): HTMLElement => document.getElementById(RAIL_SPECS.side.id)!;
const bottom = (): HTMLElement => document.getElementById(RAIL_SPECS.bottom.id)!;
const settle = (): void => {
  vi.advanceTimersByTime(RAIL_PUSH_DEBOUNCE_MS + 10);
  flushSync();
};

beforeEach(() => {
  vi.useFakeTimers();
  mountRails();
});
afterEach(() => {
  unmountRails();
  vi.useRealTimers();
});

describe('the side slide-out pushes the grid', () => {
  test('opening shrinks the grid by the panel width, closing gives it back', () => {
    follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }] });
    expect(side().style.marginLeft).toBe('');
    keyIn('side', 'core.changes').click();
    flushSync();
    const width = document.querySelector<HTMLElement>('[data-rail-slideout]')!.style.width;
    expect(width).toBe('380px');
    expect(side().style.marginLeft).toBe(width);
    expect(side().dataset['railPush']).toBe('380');
    keyIn('side', 'core.changes').click();
    flushSync();
    expect(side().style.marginLeft).toBe('');
  });

  test('a drag changes the push once it settles, not on every pixel', () => {
    follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }] });
    keyIn('side', 'core.changes').click();
    flushSync();
    const grip = document.querySelector<HTMLElement>('[data-rail-grip="side"]')!;
    grip.dispatchEvent(ptr('pointerdown', 900, 200));
    grip.dispatchEvent(ptr('pointermove', 800, 200));
    flushSync();
    expect(document.querySelector<HTMLElement>('[data-rail-slideout]')!.style.width).toBe('480px');
    expect(side().style.marginLeft).toBe('380px');
    grip.dispatchEvent(ptr('pointermove', 700, 200));
    flushSync();
    expect(side().style.marginLeft).toBe('380px');
    settle();
    expect(side().style.marginLeft).toBe(`${Math.floor(window.innerWidth - TERMINAL_MIN_COLUMNS * CELL_WIDTH_FALLBACK_PX)}px`);
    grip.dispatchEvent(ptr('pointerup', 700, 200));
  });

  test('the bottom rail pushes the grid up by its height, and gives it back on close', () => {
    follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.notes' }] });
    keyIn('bottom', 'core.notes').click();
    flushSync();
    const height = document.querySelector<HTMLElement>('[data-rail-slideout="core.notes"]')!.style.height;
    expect(height).toBe('320px');
    expect(bottom().style.marginTop).toBe(height);
    expect(bottom().style.marginLeft).toBe('');
    keyIn('bottom', 'core.notes').click();
    flushSync();
    expect(bottom().style.marginTop).toBe('');
  });

  test('a bottom drag changes the push once it settles', () => {
    follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.notes' }] });
    keyIn('bottom', 'core.notes').click();
    flushSync();
    const grip = document.querySelector<HTMLElement>('[data-rail-grip="bottom"]')!;
    grip.dispatchEvent(ptr('pointerdown', 400, 500));
    grip.dispatchEvent(ptr('pointermove', 400, 400));
    flushSync();
    expect(bottom().style.marginTop).toBe('320px');
    settle();
    expect(bottom().style.marginTop).toBe('420px');
    grip.dispatchEvent(ptr('pointerup', 400, 400));
  });

  test('the grid css names the push and the margin is the only thing that moves the column', () => {
    const css = readFileSync(join(process.cwd(), '..', 'client/css/terminal-grid.css'), 'utf8');
    expect(css).toMatch(/slide-out PUSHES the grid/);
    expect(css).toMatch(/grid-template-columns: minmax\(0, 1fr\) auto;/);
  });
});
