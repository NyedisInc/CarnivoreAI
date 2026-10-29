/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import StatTile from './StatTile.svelte';

let mounted: Record<string, unknown>[] = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

function tile(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(StatTile, { target, props: { label: 'needs you', figure: '0', ...props } }) as Record<string, unknown>);
    flushSync();
    return target;
}

test('onsub makes the sub line a button that calls it, carrying subAttrs', () => {
    expect(tile({ sub: 'all clear' }).querySelector('button')).toBeNull();
    const onsub = vi.fn();
    const root = tile({ sub: 'all clear', onsub, subAttrs: { 'data-go': 'needs' } });
    const button = root.querySelector<HTMLButtonElement>('button.oc-stat-tile__sub')!;
    expect(button.getAttribute('data-go')).toBe('needs');
    button.click();
    expect(onsub).toHaveBeenCalledTimes(1);
});
