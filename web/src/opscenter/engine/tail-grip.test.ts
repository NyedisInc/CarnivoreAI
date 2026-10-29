/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import Gutter from './Gutter.svelte';
import { homeLayout } from './layout.svelte';

describe('tail grip', () => {
  test('grows the last px row and stops shrinking at the fit', () => {
    const rows = homeLayout.state.layout.rows;
    const last = rows[rows.length - 1]!;
    expect(last.kind).toBe('px');
    const start = last.size;
    const target = document.createElement('div');
    document.body.append(target);
    const app = mount(Gutter, { target, props: { axis: 'y', row: last, gutter: 12, tail: start - 20, store: homeLayout } });
    const grip = target.querySelector('[role="separator"]')!;
    grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    flushSync();
    expect(homeLayout.state.layout.rows.at(-1)!.size).toBeGreaterThan(start);
    grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    flushSync();
    expect(homeLayout.state.layout.rows.at(-1)!.size).toBe(start - 20);
    unmount(app);
  });
});
