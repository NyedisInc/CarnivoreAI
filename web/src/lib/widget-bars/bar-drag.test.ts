/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { BarDrag, dragLook, snapBar } from './bar-drag.svelte';
import { widgetBars, type BarSettings } from './bar-settings.svelte';
import { barLead } from './bar-lead.svelte';
import { BAR_SIZES } from './bar-size';
import type { RailEdge } from '../session-rail/rail-model';

const g = globalThis as Record<string, unknown>;
let writes: unknown[];
let shared: Record<string, unknown>;

beforeEach(() => {
  writes = [];
  shared = {};
  g.PreferenceBridge = {
    read: (field: string) => shared[field] ?? null,
    write: async (field: string, value: unknown) => {
      writes.push(value);
      shared[field] = value;
      return { status: 'committed' };
    },
    follow: () => () => {},
  };
  widgetBars.reload();
  barLead.edge = null;
});
afterEach(() => {
  delete g.PreferenceBridge;
});

function drag(edge: RailEdge, from: number, steps: number[], release = true): BarDrag {
  const d = new BarDrag(edge, () => widgetBars.view[edge]);
  d.begin(500, from);
  for (const step of steps) d.move(500 - (step - from));
  if (release) d.end();
  return d;
}

const EDGES: RailEdge[] = ['side', 'bottom'];

describe.each(EDGES)('%s bar', (edge) => {
  const e = (s: 'compact' | 'cozy' | 'detailed'): number => BAR_SIZES[s][edge].bar;

  test('snap: each midpoint boundary and the close threshold', () => {
    const [c, z, d] = [e('compact'), e('cozy'), e('detailed')];
    expect(snapBar(edge, c / 2 - 1)).toBe('closed');
    expect(snapBar(edge, c / 2)).toBe('compact');
    expect(snapBar(edge, (c + z) / 2 - 1)).toBe('compact');
    expect(snapBar(edge, (c + z) / 2)).toBe('cozy');
    expect(snapBar(edge, (z + d) / 2 - 1)).toBe('cozy');
    expect(snapBar(edge, (z + d) / 2)).toBe('detailed');
    expect(snapBar(edge, d + 200)).toBe('detailed');
  });

  test.each(['compact', 'detailed'] as const)('released at %s writes size and pinned once', async (size) => {
    drag(edge, e('cozy'), [e('compact') - 4, e(size)]);
    await Promise.resolve();
    expect(writes).toEqual([{ v: 1, [edge]: { size, mode: 'pinned' } }]);
  });

  test('released at cozy, the pinned cozy default (#2511), writes nothing', async () => {
    drag(edge, e('cozy'), [e('detailed'), e('cozy')]);
    await Promise.resolve();
    expect(writes).toEqual([]);
  });

  test('released closed writes autohide once and keeps the size', async () => {
    await widgetBars.set(edge, { size: 'detailed', mode: 'pinned' });
    writes = [];
    drag(edge, e('detailed'), [e('cozy'), 0]);
    await Promise.resolve();
    expect(writes).toEqual([{ v: 1, [edge]: { size: 'detailed', mode: 'autohide' } }]);
  });

  test('released where it started writes nothing, so does a press with no movement', async () => {
    await widgetBars.set(edge, { size: 'compact', mode: 'pinned' });
    writes = [];
    drag(edge, e('compact'), [e('detailed'), e('compact')]);
    drag(edge, e('compact'), []);
    drag(edge, e('compact'), [e('compact') + 2]);
    await Promise.resolve();
    expect(writes).toEqual([]);
  });

  test('nothing is written while dragging, the preview follows, Escape restores and writes nothing', async () => {
    const d = drag(edge, e('cozy'), [e('detailed')], false);
    expect(d.preview).toBe('detailed');
    expect(writes).toEqual([]);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(d.preview).toBeNull();
    window.dispatchEvent(new Event('pointerup'));
    await Promise.resolve();
    expect(writes).toEqual([]);
    expect(d.consumeClick()).toBe(true);
  });

  test('a handle drag out of auto-hide pins at the snapped size; a plain press does not swallow the click', async () => {
    const press = new BarDrag(edge, () => widgetBars.view[edge]);
    press.begin(500, 0);
    window.dispatchEvent(new Event('pointerup'));
    expect(press.consumeClick()).toBe(false);
    const d = drag(edge, 0, [e('compact'), e('detailed')]);
    await Promise.resolve();
    expect(writes).toEqual([{ v: 1, [edge]: { size: 'detailed', mode: 'pinned' } }]);
    expect(d.consumeClick()).toBe(true);
    expect(barLead.edge).toBe(edge);
  });

  test('a handle drag released closed from the pinned default writes autohide once', async () => {
    drag(edge, 0, [e('detailed'), 2]);
    await Promise.resolve();
    expect(writes).toEqual([{ v: 1, [edge]: { mode: 'autohide' } }]);
  });

  test('arrow keys step one size per write, Home is cozy, End is detailed', async () => {
    const grow = edge === 'side' ? 'ArrowLeft' : 'ArrowUp';
    const shrink = edge === 'side' ? 'ArrowRight' : 'ArrowDown';
    await widgetBars.set(edge, { mode: 'autohide' });
    const d = new BarDrag(edge, () => widgetBars.view[edge]);
    const tick = async (): Promise<BarSettings> => { await Promise.resolve(); return widgetBars.view[edge]; };
    expect(d.key(grow)).toBe(true);
    expect(await tick()).toMatchObject({ size: 'compact', mode: 'pinned' });
    d.key(grow);
    expect(await tick()).toMatchObject({ size: 'cozy', mode: 'pinned' });
    d.key(grow);
    d.key(grow);
    expect(await tick()).toMatchObject({ size: 'detailed', mode: 'pinned' });
    d.key('Home');
    expect(await tick()).toMatchObject({ size: 'cozy' });
    d.key(shrink);
    expect(await tick()).toMatchObject({ size: 'compact', mode: 'pinned' });
    d.key(shrink);
    expect(await tick()).toMatchObject({ size: 'compact', mode: 'autohide' });
    d.key(shrink);
    d.key('End');
    expect(await tick()).toMatchObject({ size: 'detailed', mode: 'pinned' });
    expect(d.key('x')).toBe(false);
    expect(writes).toHaveLength(8);
  });
});

test('the preview wins over the state table except edit, absent and held', () => {
  expect(dragLook('handle', 'cozy')).toBe('pinned');
  expect(dragLook('peek', 'closed')).toBe('handle');
  expect(dragLook('held', 'closed')).toBe('held');
  expect(dragLook('edit', 'cozy')).toBe('edit');
  expect(dragLook('peek', null)).toBe('peek');
});
