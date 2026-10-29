/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { BAR_GRAB_MIN_PX as OUT_MIN_PX, CELL_WIDTH_FALLBACK_PX, TERMINAL_MIN_COLUMNS } from './bar-limits';
import { OUT_DEFAULT_PX, OUT_STEP_PX, clampOut, readOutSize, sizeKey, writeOutSize, type SizeStorage } from './rail-size';
import { railOutSizes } from './rail-out-size.svelte';
import RailResizeHandle from './RailResizeHandle.svelte';

function memory(broken = false): SizeStorage & { map: Map<string, string> } {
  const map = new Map<string, string>();
  const fail = (): never => {
    throw new Error('blocked');
  };
  return {
    map,
    getItem: (key) => (broken ? fail() : (map.get(key) ?? null)),
    setItem: (key, value) => (broken ? fail() : void map.set(key, value)),
  };
}

const wide = (room: number) => Math.floor(room - TERMINAL_MIN_COLUMNS * CELL_WIDTH_FALLBACK_PX);

describe('the clamp', () => {
  test('keeps a size between the grab minimum and what leaves the terminal 60 columns', () => {
    expect(clampOut(1, 1000)).toBe(OUT_MIN_PX);
    expect(clampOut(600, 1000)).toBe(wide(1000) < 600 ? wide(1000) : 600);
    expect(clampOut(5000, 1600)).toBe(wide(1600));
  });

  test('a window too small for 60 columns still leaves the grab minimum', () => {
    expect(clampOut(500, 300)).toBe(OUT_MIN_PX);
  });

  test('a remembered size beyond the new limits is clamped on read', () => {
    expect(clampOut(readOutSize('side', { getItem: () => '99999', setItem: () => {} })!, 1200)).toBe(wide(1200));
  });

  test('the bottom floor is the strip height and the side floor stays 44', () => {
    expect(clampOut(1, 1000, 'bottom')).toBe(36);
    expect(clampOut(1, 1000, 'bottom', 'compact')).toBe(20);
    expect(clampOut(1, 1000, 'bottom', 'detailed')).toBe(44);
    expect(clampOut(1, 1000, 'side')).toBe(44);
    expect(railOutSizes.set('bottom', 1, 800)).toBe(36);
    expect(railOutSizes.set('side', 1, 1400)).toBe(44);
    expect(clampOut(readOutSize('bottom', { getItem: () => '20', setItem: () => {} })!, 800, 'bottom')).toBe(36);
  });

  test('rounds to whole pixels', () => {
    expect(clampOut(400.6, 1000)).toBe(401);
  });
});

describe('the per-device memory', () => {
  test('side and bottom are kept apart under their own keys', () => {
    const store = memory();
    writeOutSize('side', 500, store);
    writeOutSize('bottom', 300, store);
    expect(sizeKey('side')).not.toBe(sizeKey('bottom'));
    expect(readOutSize('side', store)).toBe(500);
    expect(readOutSize('bottom', store)).toBe(300);
  });

  test('nothing stored, a junk value and a zero all read as nothing', () => {
    const store = memory();
    expect(readOutSize('side', store)).toBeNull();
    store.map.set(sizeKey('side'), 'wide');
    expect(readOutSize('side', store)).toBeNull();
    store.map.set(sizeKey('side'), '0');
    expect(readOutSize('side', store)).toBeNull();
  });

  test('a storage that throws never throws out of a read or a write', () => {
    const store = memory(true);
    expect(() => writeOutSize('side', 400, store)).not.toThrow();
    expect(readOutSize('side', store)).toBeNull();
    expect(readOutSize('side', null)).toBeNull();
  });
});

describe('the live size and the handle', () => {
  let host: HTMLElement;
  let instance: Record<string, unknown>;

  beforeEach(() => {
    localStorage.clear();
    railOutSizes.reload();
    host = document.createElement('div');
    document.body.appendChild(host);
  });

  afterEach(() => {
    void unmount(instance);
    host.remove();
  });

  test('a set size is clamped to the window and remembered per edge on this device', () => {
    expect(railOutSizes.raw('side')).toBe(OUT_DEFAULT_PX.side);
    expect(railOutSizes.set('side', 5000, 1000)).toBe(wide(1000));
    railOutSizes.remember('side');
    expect(localStorage.getItem(sizeKey('side'))).toBe(String(wide(1000)));
    expect(localStorage.getItem(sizeKey('bottom'))).toBeNull();
    railOutSizes.reload();
    expect(railOutSizes.raw('side')).toBe(wide(1000));
    expect(railOutSizes.raw('bottom')).toBe(OUT_DEFAULT_PX.bottom);
  });

  test('the arrow keys that move the edge change the size a step, within the clamp, and remember it', () => {
    (window as { innerWidth: number }).innerWidth = 1400;
    instance = mount(RailResizeHandle, { target: host, props: { edge: 'side', label: 'resize' } }) as Record<string, unknown>;
    flushSync();
    const grip = host.querySelector<HTMLElement>('[data-rail-grip="side"]')!;
    expect(grip.getAttribute('role')).toBe('separator');
    expect(grip.tabIndex).toBe(0);
    expect(grip.getAttribute('aria-valuemin')).toBe(String(OUT_MIN_PX));
    expect(grip.getAttribute('aria-valuemax')).toBe(String(wide(1400)));
    expect(grip.getAttribute('aria-valuenow')).toBe(String(OUT_DEFAULT_PX.side));

    grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    flushSync();
    expect(grip.getAttribute('aria-valuenow')).toBe(String(OUT_DEFAULT_PX.side + OUT_STEP_PX));
    expect(localStorage.getItem(sizeKey('side'))).toBe(String(OUT_DEFAULT_PX.side + OUT_STEP_PX));

    for (let i = 0; i < 40; i++) grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    flushSync();
    expect(grip.getAttribute('aria-valuenow')).toBe(String(OUT_MIN_PX));

    grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    flushSync();
    expect(grip.getAttribute('aria-valuenow')).toBe(String(wide(1400)));

    grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    flushSync();
    expect(grip.getAttribute('aria-valuenow')).toBe(String(OUT_DEFAULT_PX.side));
  });

  test('the bottom handle grows upward and a drag past the maximum stops where the terminal keeps its rows', () => {
    (window as { innerHeight: number }).innerHeight = 800;
    instance = mount(RailResizeHandle, { target: host, props: { edge: 'bottom', label: 'resize' } }) as Record<string, unknown>;
    flushSync();
    const grip = host.querySelector<HTMLElement>('[data-rail-grip="bottom"]')!;
    expect(grip.getAttribute('aria-orientation')).toBe('horizontal');
    expect(grip.getAttribute('aria-valuemin')).toBe('36');
    grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    flushSync();
    expect(grip.getAttribute('aria-valuenow')).toBe(String(OUT_DEFAULT_PX.bottom + OUT_STEP_PX));
    for (let i = 0; i < 40; i++) grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    flushSync();
    expect(grip.getAttribute('aria-valuenow')).toBe('36');
    grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    flushSync();

    const move = (type: string, y: number): PointerEvent => {
      const event = new MouseEvent(type, { clientY: y, bubbles: true, button: 0 }) as PointerEvent;
      Object.defineProperty(event, 'pointerId', { value: 1 });
      return event;
    };
    grip.dispatchEvent(move('pointerdown', 500));
    grip.dispatchEvent(move('pointermove', -2000));
    flushSync();
    expect(grip.getAttribute('aria-valuenow')).toBe(String(800 - 5 * 17));
    grip.dispatchEvent(move('pointerup', -2000));
    expect(localStorage.getItem(sizeKey('bottom'))).toBe(String(800 - 5 * 17));
  });
});
