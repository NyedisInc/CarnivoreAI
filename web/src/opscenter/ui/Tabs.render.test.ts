/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Tabs, { type TabDef } from './Tabs.svelte';
import InsetHostFixture from './InsetHostFixture.svelte';

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

const TABS: TabDef[] = [
    { id: 'a', label: 'alpha' },
    { id: 'b', label: 'beta', disabled: true },
    { id: 'c', label: 'gamma', badge: 3, dot: true },
];

function show(active: string, picks: string[]): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(Tabs, {
        target,
        props: { tabs: TABS, active, onSelect: (id: string) => picks.push(id), label: 'demo', idBase: 'demo' },
    });
    flushSync();
    return target;
}

function key(target: HTMLElement, id: string, name: string): void {
    target
        .querySelector(`[data-tab="${id}"]`)
        ?.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true }));
}

describe('Tabs', () => {
    test('roles, selection and a roving tabindex', () => {
        const target = show('a', []);
        expect(target.querySelector('[role="tablist"]')?.getAttribute('aria-label')).toBe('demo');
        const tabs = [...target.querySelectorAll<HTMLElement>('[role="tab"]')];
        expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false']);
        expect(tabs.map((t) => t.tabIndex)).toEqual([0, -1, -1]);
        expect(tabs[0]?.getAttribute('aria-controls')).toBe('demo-panel-a');
        expect(target.querySelector('[data-tab="c"] .oc-ptab__badge')?.textContent).toBe('3');
        expect(target.querySelector('[data-tab="c"] .oc-ptab__dot')).not.toBeNull();
    });

    test('arrows wrap past the end and skip a disabled tab; Home and End jump', () => {
        const picks: string[] = [];
        const target = show('c', picks);
        key(target, 'c', 'ArrowRight');
        key(target, 'c', 'ArrowLeft');
        key(target, 'c', 'Home');
        key(target, 'c', 'End');
        expect(picks).toEqual(['a', 'a', 'a', 'c']);
    });
});

describe('Page inset', () => {
    test('no title bar, the actions ride in the bar row', () => {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(InsetHostFixture, { target });
        flushSync();
        expect(target.querySelector('.oc-titlebar')).toBeNull();
        expect(target.querySelector('.oc-page')?.getAttribute('aria-label')).toBe('hosts');
        expect(target.querySelector('.oc-page__bar [data-act]')).not.toBeNull();
        expect(target.querySelector('.oc-page__bar .oc-titlebar__count')?.textContent).toBe('3 items');
    });
});

describe('compact and collapse (TM Mark II round 4 point 2)', () => {
    const ICONS: TabDef[] = [{ id: 'a', label: 'action', icon: 'bolt' }, { id: 'b', label: 'discussion', icon: 'chat', badge: '2 new' }, { id: 'c', label: 'plain' }];

    test('compact is a class on the strip; collapse names every icon tab by its label and leaves the others alone', () => {
        mounted = mount(Tabs, { target: document.body, props: { tabs: ICONS, active: 'a', onSelect: () => {}, label: 'views', idBase: 'x', compact: true, collapse: true } });
        flushSync();
        const strip = document.querySelector('.oc-ptabs')!;
        expect(strip.classList.contains('oc-ptabs--compact')).toBe(true);
        expect(strip.classList.contains('oc-ptabs--collapse')).toBe(true);
        const tab = (id: string) => document.querySelector<HTMLElement>(`[data-tab="${id}"]`)!;
        expect(tab('a').getAttribute('aria-label')).toBe('action');
        expect(tab('a').getAttribute('title')).toBe('action');
        expect(tab('a').querySelector('.oc-ptab__icon svg')).not.toBeNull();
        expect(tab('b').querySelector('.oc-ptab__badge')?.textContent).toBe('2 new');
        expect(tab('c').hasAttribute('aria-label')).toBe(false);
    });

    test('without collapse no tab gets an aria-label or title of its own', () => {
        mounted = mount(Tabs, { target: document.body, props: { tabs: ICONS, active: 'a', onSelect: () => {}, label: 'views', idBase: 'y' } });
        flushSync();
        expect(document.querySelector('[data-tab="a"]')!.hasAttribute('aria-label')).toBe(false);
        expect(document.querySelector('.oc-ptabs--compact')).toBeNull();
    });
});
