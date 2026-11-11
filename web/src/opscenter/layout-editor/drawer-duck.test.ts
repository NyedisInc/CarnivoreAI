/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { acquireDragHold } from '../../lib/motion-grid/drag-hold';
import { beginPress } from './drawer-drag';

const ptr = (type: string, x: number, y: number): PointerEvent =>
  Object.assign(new Event(type, { bubbles: true }), { pointerId: 1, clientX: x, clientY: y, button: 0 }) as unknown as PointerEvent;

describe('drawer duck class across the surface handoff', () => {
  test('a surface that takes its hold in a microtask (the dashboard) never sees the class drop', async () => {
    const card = document.createElement('div');
    document.body.append(card);
    let surfaceRelease: (() => void) | null = null;
    const records: MutationRecord[] = [];
    const observer = new MutationObserver((batch) => records.push(...batch));
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'], attributeOldValue: true });
    beginPress(card, ptr('pointerdown', 0, 0), {
      onMove: () => {
        void Promise.resolve().then(() => (surfaceRelease = acquireDragHold(document)));
        return 'handoff';
      },
      onDrop: () => {},
      onEnd: () => {},
    });
    window.dispatchEvent(ptr('pointermove', 40, 40));
    await Promise.resolve();
    await Promise.resolve();
    expect(document.body.classList.contains('grid-dragging')).toBe(true);
    await new Promise((r) => setTimeout(r, 5));
    expect(document.body.classList.contains('grid-dragging')).toBe(true);
    records.push(...observer.takeRecords());
    observer.disconnect();
    const states = records.map((r) => (r.oldValue ?? '').split(/\s+/).includes('grid-dragging'));
    states.push(true);
    expect(states.slice(states.indexOf(true))).not.toContain(false);
    surfaceRelease!();
    expect(document.body.classList.contains('grid-dragging')).toBe(false);
  });

  test('the class stays on from lift, through the handoff, until the surface releases', async () => {
    const card = document.createElement('div');
    document.body.append(card);
    const seen: boolean[] = [];
    let surfaceRelease: (() => void) | null = null;
    beginPress(card, ptr('pointerdown', 0, 0), {
      onMove: () => {
        surfaceRelease = acquireDragHold(document);
        seen.push(document.body.classList.contains('grid-dragging'));
        return 'handoff';
      },
      onDrop: () => {},
      onEnd: () => seen.push(document.body.classList.contains('grid-dragging')),
    });
    window.dispatchEvent(ptr('pointermove', 40, 40));
    expect(seen).toEqual([true, true]);
    expect(document.body.classList.contains('grid-dragging')).toBe(true);
    await new Promise((r) => setTimeout(r, 5));
    surfaceRelease!();
    expect(document.body.classList.contains('grid-dragging')).toBe(false);
  });
});
