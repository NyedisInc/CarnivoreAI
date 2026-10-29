/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import GroupSection from './GroupSection.svelte';
import { t } from '../i18n/index.svelte';
import type { LensGroup } from './lenses';
import { closeItemMenu } from '../item-menu/open.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

const colorOf = vi.hoisted(() => ({ value: '#2e7d4f' as string | null }));
vi.mock('../project-colors/store.svelte', () => ({ projectColorOf: () => colorOf.value }));

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

function mountGroup(project: boolean): HTMLElement {
    const group = { key: 'p:1', label: 'Shopify', bits: [], measure: '', rows: [], count: 0, live: 0, project: project ? { id: 1, name: 'Shopify' } : null, provider: null } as unknown as LensGroup;
    handle = mount(GroupSection, { target: document.body, props: { group, folded: false, t, onFold: vi.fn(), children: createRawSnippet(() => ({ render: () => '<i></i>' })) } });
    flushSync();
    return document.querySelector<HTMLElement>('section.sp-sec')!;
}

test('a colored project stamps its color on the section', () => {
    const sec = mountGroup(true);
    expect(sec.hasAttribute('data-block')).toBe(true);
    expect(sec.style.getPropertyValue('--sp-block')).toBe('#2e7d4f');
});

test('a project with no color stamps nothing', () => {
    colorOf.value = null;
    const sec = mountGroup(true);
    expect(sec.hasAttribute('data-block')).toBe(false);
    expect(sec.style.getPropertyValue('--sp-block')).toBe('');
    colorOf.value = '#2e7d4f';
});

test('a group that is not a project stamps nothing', () => {
    expect(mountGroup(false).hasAttribute('data-block')).toBe(false);
});

function mountMenu(rows: unknown[]): HTMLElement {
    const group = { key: 'p:1', label: 'Shopify', bits: [], measure: '', rows, count: rows.length, live: 0, project: { id: 1, name: 'Shopify' }, provider: null } as unknown as LensGroup;
    handle = mount(GroupSection, { target: document.body, props: { group, folded: false, t, onFold: vi.fn(), onProjectAction: vi.fn(), children: createRawSnippet(() => ({ render: () => '<i></i>' })) } });
    flushSync();
    return document.querySelector<HTMLElement>('section.sp-sec')!;
}

function rightClick(sec: HTMLElement): MouseEvent {
    const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 30, clientY: 30 });
    sec.querySelector('.sp-sec-head')!.dispatchEvent(event);
    flushSync();
    return event;
}

test('a local project heading draws no menu button; its right click opens the one item menu, and a paired computer\'s has none', () => {
    const local = mountMenu([{ computer: null }]);
    expect(local.querySelector('.sp-sec-head > :not([data-fold])'), 'a heading draws no menu button').toBeNull();
    expect(local.querySelector('[aria-haspopup]'), 'no kebab').toBeNull();
    expect(rightClick(local).defaultPrevented, 'the page claimed the right click').toBe(true);
    expect(document.querySelector('[role="menu"] [data-node="rename-project"]'), 'the one menu opened with the project actions').not.toBeNull();
    closeItemMenu();
    unmount(handle!);
    document.body.innerHTML = '';
    const paired = mountMenu([{ computer: 'studio' }]);
    expect(rightClick(paired).defaultPrevented, 'a paired computer\'s project keeps the native menu').toBe(false);
    expect(document.querySelector('[role="menu"]')).toBeNull();
});
