/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import Heading from './Heading.svelte';
import type { HeadingPlan } from './plan';
import { CASCADE_PATH, CHEVRON_PATH } from './cascade-hint';
import { isCollapsed, onSaved, save } from '../drawer/store';

vi.mock('./company-source.svelte', () => ({
    companySource: () => ({
        companies: [{ id: 1, name: 'acme' }, { id: 2, name: 'inner' }],
        companyOf: (p: string) => ({ '10': 1, '11': 2 } as Record<string, number>)[p] ?? null,
        parentOf: (c: number) => (c === 2 ? 1 : null),
        projectParentOf: (p: string) => (p === '11' ? '10' : null),
    }),
    watchCompanies: () => {},
}));
vi.mock('../../opscenter/api/projects.svelte', () => ({
    projects: { data: [{ id: 10, company_id: 1 }, { id: 11, company_id: 2, parent_project_id: 10 }] },
}));
vi.mock('./interaction-globals', () => ({
    announce: vi.fn(),
    announceFailure: vi.fn(),
    hg: () => ({}),
    repaintDrawerRows: () => {},
}));

function plan(key: string): HeadingPlan {
    return {
        toggle: 'group', key, bandKind: 'company', expanded: true, bodyId: `body-${key}`, title: key, label: key,
        iconHtml: '', ledHtml: '', pickedIconHtml: '', rollupHtml: '',
    };
}

let target: HTMLElement;
let handle: Record<string, unknown>;
let saves = 0;
// One listener for the file: onSaved has no unsubscribe, so registering per test would count twice.
onSaved(() => { saves += 1; });

beforeEach(() => {
    save([], [], []);
    saves = 0;
    target = document.createElement('div');
    document.body.appendChild(target);
    handle = mount(Heading, { target, props: { h: plan('c:1') } });
    flushSync();
    saves = 0;
});

afterEach(() => {
    unmount(handle);
    target.remove();
});

function toggle(): HTMLElement {
    return target.querySelector('[data-group-toggle="c:1"]') as HTMLElement;
}

function click(shiftKey: boolean): void {
    toggle().dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, shiftKey }));
}

describe('shift+click cascade fold', () => {
    it('closes everything under a company, then opens it all, in one write each', () => {
        click(true);
        for (const k of ['c:1', 'c:2', 'p:10', 'p:11']) expect(isCollapsed(k)).toBe(true);
        expect(saves).toBe(1);
        click(true);
        for (const k of ['c:1', 'c:2', 'p:10', 'p:11']) expect(isCollapsed(k)).toBe(false);
        expect(isCollapsed('p:10:agents')).toBe(true);
        expect(saves).toBe(2);
    });

    it('a plain click toggles only the one heading', () => {
        click(false);
        expect(isCollapsed('c:1')).toBe(true);
        for (const k of ['c:2', 'p:10', 'p:11']) expect(isCollapsed(k)).toBe(false);
        expect(saves).toBe(1);
    });

    it('swaps the chevron for the double chevron only while shift is held over the heading', () => {
        const row = target.querySelector('.session-sidebar-group__headerrow') as HTMLElement;
        const d = (): string | null => row.querySelector('.session-sidebar-group__chevron path')!.getAttribute('d');
        expect(d()).toBe(CHEVRON_PATH);
        window.dispatchEvent(new KeyboardEvent('keydown', { shiftKey: true }));
        expect(d()).toBe(CHEVRON_PATH);
        row.dispatchEvent(new MouseEvent('pointerenter', { shiftKey: true }));
        expect(d()).toBe(CASCADE_PATH);
        expect(row.getAttribute('data-cascade')).toBe('1');
        window.dispatchEvent(new KeyboardEvent('keyup', { shiftKey: false }));
        expect(d()).toBe(CHEVRON_PATH);
        row.dispatchEvent(new MouseEvent('pointerleave'));
    });
});
