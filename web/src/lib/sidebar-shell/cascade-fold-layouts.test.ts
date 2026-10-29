/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import Heading from './Heading.svelte';
import type { HeadingPlan } from './plan';
import { cascadeKeysFor, liveCascadeWorld } from './cascade-keys';
import { isCollapsed, onSaved, save } from '../drawer/store';

vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [], companyOf: () => null, parentOf: () => null, projectParentOf: () => null }),
    watchCompanies: () => {},
}));
vi.mock('../../opscenter/api/projects.svelte', () => ({ projects: { data: [] } }));
vi.mock('./interaction-globals', () => ({
    announce: vi.fn(),
    announceFailure: vi.fn(),
    hg: () => ({}),
    repaintDrawerRows: () => {},
}));

function plan(key: string): HeadingPlan {
    return {
        toggle: 'group', key, bandKind: 'reserved', expanded: true, bodyId: `body-${key}`, title: key, label: key,
        iconHtml: '', ledHtml: '', pickedIconHtml: '', rollupHtml: '',
    };
}

let target: HTMLElement;
let handle: Record<string, unknown>;
let saves = 0;
// One listener for the file: onSaved has no unsubscribe, so registering per test would count twice.
onSaved(() => { saves += 1; });

beforeEach(() => {
    (window as unknown as Record<string, unknown>).SessionSidebarLayouts = {
        rows: () => [{ name: 'layout:u1' }, { name: 'layout:u2' }],
    };
    save([], [], []);
    target = document.createElement('div');
    document.body.appendChild(target);
    handle = mount(Heading, { target, props: { h: plan('layouts') } });
    flushSync();
    saves = 0;
});

afterEach(() => {
    unmount(handle);
    target.remove();
    delete (window as unknown as Record<string, unknown>).SessionSidebarLayouts;
});

function click(shiftKey: boolean, keyboard = false): void {
    const el = target.querySelector('[data-group-toggle="layouts"]') as HTMLElement;
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, shiftKey, detail: keyboard ? 0 : 1 }));
}

describe('LAYOUTS cascade', () => {
    it('lists every saved Layout as an inverted key under the LAYOUTS heading', () => {
        expect(cascadeKeysFor('layouts', liveCascadeWorld())).toEqual({ tree: [], inverted: ['layout:u1', 'layout:u2'] });
    });

    it('shift closes the band and every Layout row, then opens them all, one write each', () => {
        click(true);
        expect(isCollapsed('layouts')).toBe(true);
        expect(isCollapsed('layout:u1')).toBe(false);
        expect(saves).toBe(1);
        click(true);
        expect(isCollapsed('layouts')).toBe(false);
        expect(isCollapsed('layout:u1')).toBe(true);
        expect(isCollapsed('layout:u2')).toBe(true);
        expect(saves).toBe(2);
    });

    it('a keyboard click carrying Shift cascades; one without it toggles the band alone', () => {
        click(true, true);
        click(true, true);
        expect(isCollapsed('layout:u1') && isCollapsed('layout:u2')).toBe(true);
        save([], [], []);
        saves = 0;
        click(false, true);
        expect(isCollapsed('layouts')).toBe(true);
        expect(isCollapsed('layout:u1')).toBe(false);
        expect(saves).toBe(1);
    });
});
