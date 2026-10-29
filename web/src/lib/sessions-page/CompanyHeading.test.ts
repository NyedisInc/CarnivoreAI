/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import GroupSection from './GroupSection.svelte';
import type { LensGroup } from './lenses';
import { t, setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

setLocale('en');
installPopoverPolyfill();

const head: LensGroup = { key: 'company:7', label: 'acme', bits: ['2 projects'], measure: '', rows: [], count: 2, live: 1, project: null, provider: null };
let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

test('right click opens the company menu, a pick names the company, the heading folds', async () => {
    const onCompanyAction = vi.fn();
    const onFold = vi.fn();
    const company = { id: 7, name: 'acme', project_count: 2 };
    handle = mount(GroupSection, { target: document.body, props: { group: head, company, onCompanyAction, folded: false, t, onFold } });
    flushSync();
    const bar = document.querySelector<HTMLElement>('.sp-sec-head')!;
    expect(document.querySelector('.sp-sec')?.hasAttribute('data-company')).toBe(true);
    expect(document.querySelector('.sp-pchip')).toBeNull();
    bar.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 5, clientY: 5 }));
    await vi.waitFor(() => expect(document.querySelector('[role="menu"]')).not.toBeNull());
    const ids = [...document.querySelectorAll('[data-node]')].map((n) => n.getAttribute('data-node'));
    expect(ids).toEqual(expect.arrayContaining(['rename-company', 'migrate-company', 'set-image', 'regenerate-art', 'delete-company']));
    expect(ids).not.toContain('delete-project');
    document.querySelector<HTMLElement>('[data-node="rename-company"]')!.click();
    expect(onCompanyAction).toHaveBeenCalledWith('rename-company', company);
    document.querySelector<HTMLButtonElement>('[data-fold]')!.click();
    expect(onFold).toHaveBeenCalledWith('company:7');
});
