/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import PlaceMenu from './PlaceMenu.svelte';

let handle: Record<string, unknown> | null = null;

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

describe('PlaceMenu disabled rows', () => {
    test('the reason is the tooltip, the arrow lands on the row, a click is a no-op', async () => {
        const live = vi.fn();
        const dead = vi.fn();
        const onClose = vi.fn();
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        handle = mount(PlaceMenu, {
            target: document.body,
            props: {
                anchor, label: 'add', onClose,
                entries: [
                    { id: 'a', label: 'alpha', run: live },
                    { id: 'b', label: 'beta', sub: 'already in this place', disabled: true, run: dead },
                ],
            },
        });
        flushSync();
        await tick();
        const rows = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')];
        const off = rows[1]!;
        expect(off.getAttribute('aria-disabled')).toBe('true');
        expect(off.getAttribute('data-tooltip')).toBe('already in this place');
        expect(document.querySelector('.session-row-menu__reason')).toBeNull();
        rows[0]!.focus();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
        expect(document.activeElement).toBe(off);
        off.click();
        expect(dead).not.toHaveBeenCalled();
        expect(onClose).not.toHaveBeenCalled();
        rows[0]!.click();
        expect(live).toHaveBeenCalledTimes(1);
    });
});
