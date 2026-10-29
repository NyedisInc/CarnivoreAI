/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Tabs, { type TabDef } from './Tabs.svelte';
import { revealSideways } from './scroll-fade';

let mounted: Record<string, unknown> | null = null;
const intoView = vi.fn();

beforeEach(() => {
    intoView.mockClear();
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, writable: true, value: intoView });
});

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});

function rect(left: number, width: number): DOMRect {
    return { left, right: left + width, top: 0, bottom: 20, width, height: 20, x: left, y: 0, toJSON: () => ({}) } as DOMRect;
}

const tabsOf = (n: number): TabDef[] => Array.from({ length: n }, (_, i) => ({ id: `t${i}`, label: `tab ${i}` }));

describe('Tabs reveal', () => {
    test('a strip inside a scrolled list reveals its tab sideways and leaves the list where it is, on mount and on every re-render', () => {
        const list = document.createElement('div');
        list.style.overflowY = 'auto';
        document.body.append(list);
        list.scrollTop = 0;
        const props = $state({ tabs: tabsOf(3), active: 't2' });
        mounted = mount(Tabs, {
            target: list,
            props: { get tabs() { return props.tabs; }, get active() { return props.active; }, onSelect: () => {}, label: 'task', idBase: 'row' },
        });
        const strip = list.querySelector<HTMLElement>('[role="tablist"]') as HTMLElement;
        strip.getBoundingClientRect = () => rect(0, 100);
        for (const [i, tab] of [...strip.querySelectorAll<HTMLElement>('[role="tab"]')].entries()) tab.getBoundingClientRect = () => rect(i * 80 - strip.scrollLeft, 80);
        flushSync();
        props.tabs = tabsOf(3);
        flushSync();
        props.active = 't0';
        flushSync();
        expect(intoView).not.toHaveBeenCalled();
        expect(list.scrollTop).toBe(0);
    });

    test('revealSideways scrolls the strip to the nearest edge only', () => {
        const strip = document.createElement('div');
        const tab = document.createElement('button');
        strip.append(tab);
        strip.getBoundingClientRect = () => rect(0, 100);
        tab.getBoundingClientRect = () => rect(150 - strip.scrollLeft, 40);
        revealSideways(strip, tab);
        expect(strip.scrollLeft).toBe(90);
        tab.getBoundingClientRect = () => rect(20 - strip.scrollLeft, 40);
        revealSideways(strip, tab);
        expect(strip.scrollLeft).toBe(20);
        revealSideways(strip, tab);
        expect(strip.scrollLeft).toBe(20);
        revealSideways(strip, null);
        expect(strip.scrollLeft).toBe(20);
    });
});
