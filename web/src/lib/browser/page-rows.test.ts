/** @vitest-environment jsdom */
import * as BrowserRows from '../drawer/browser-rows';
import fs from 'node:fs';
import path from 'node:path';
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import SidebarRow from '../sidebar-shell/SidebarRow.svelte';
import { rowHost } from '../sidebar-shell/row-host';
import { buildRowPlan } from '../sidebar-shell/row-plan';
import { ROW_ITEMS } from '../item-menu/menus/row-items';
import { contextFromTrigger, triggerHtml } from '../item-menu/row-context';

type G = Record<string, any>; // the legacy drawer globals are untyped by nature

const PAGE = { id: 'fedcba9876543210', key: 'app:/static/popout.html?tab=flow', frame: 'app', title: 'flow', opened_at: 5, src: '/static/popout.html?tab=flow' };
const BROWSER = { id: '0123456789abcdef', label: 'docs', url: 'https://example.com/a', state: 'live', viewers: 0, created_at: '2026-10-11T10:00:00Z', updated_at: '' };

/** Run a legacy script once, as its <script> tag does. */
function load(file: string): void {
    const log = console.log;
    console.log = () => {};
    try {
        new Function(fs.readFileSync(path.resolve(__dirname, '../../../../client/js', file), 'utf8'))();
    } finally {
        console.log = log;
    }
}

function drawn(r: G, band: string): string {
    const target = document.body.appendChild(document.createElement('div'));
    const app = mount(SidebarRow, { target, props: { r: buildRowPlan(r as never, 'compact', band, undefined, rowHost()) } });
    flushSync();
    const html = target.innerHTML;
    unmount(app);
    target.remove();
    return html;
}

describe('page rows in the browser list', () => {
    let calls: string[];
    const g = globalThis as G;

    beforeEach(() => {
        calls = [];
        g.CloudeWeb = {
            browsers: {
                list: () => [BROWSER],
                pages: () => [PAGE],
                open: (id: string) => { calls.push(`open ${id}`); return true; },
                close: async (id: string) => { calls.push(`close ${id}`); },
                popOut: async (id: string) => { calls.push(`popOut ${id}`); return true; },
            },
        };
        g.App = { showConfirmModal: vi.fn(async () => { calls.push('confirm'); return true; }) };
        load('i18n/tr.js');
    });

    afterEach(() => {
        delete g.CloudeWeb;
        delete g.App;
    });

    test('a page is a browser-kind row named browser:<id>, after the remote browsers, with no host subtitle', () => {
        const rows = BrowserRows.rows() as G[];
        expect(rows.map((r) => r.name)).toEqual([`browser:${BROWSER.id}`, `browser:${PAGE.id}`]);
        const page = rows[1]!;
        expect(page).toMatchObject({ kind: 'browser', browser_id: PAGE.id, page: true, label: 'flow', status: 'page', created_at_epoch: 5 });
        expect(rows[0]!.page).toBeUndefined();
    });

    test('a page row draws the document mark and cannot be renamed; a browser row keeps the globe', () => {
        const [browser, page] = BrowserRows.rows() as G[];
        const pageHtml = drawn(page!, 'browsers');
        expect(pageHtml).toContain('data-browser-state="page"');
        expect(pageHtml).toContain('M5 3h9l5 5v13H5Z');
        expect(pageHtml).not.toContain('<circle');
        expect(pageHtml).toContain('data-rename-state="unavailable"');
        expect(pageHtml).toContain('data-row-menu-page="1"');
        expect(pageHtml).toContain('data-row-menu-renameable="0"');
        const browserHtml = drawn(browser!, 'browsers');
        expect(browserHtml).toContain('<circle');
        expect(browserHtml).toContain('data-rename-state="renameable"');
    });

    test('a click on a page row opens it through the bridge, like a browser row', () => {
        expect(BrowserRows.activate(null, `browser:${PAGE.id}`)).toBe(true);
        expect(calls).toEqual([`open ${PAGE.id}`]);
    });

    test('pop out reaches the bridge for a page row and for a remote browser row', async () => {
        await BrowserRows.runMenuItem('popout', { name: `browser:${PAGE.id}`, isPage: true });
        await BrowserRows.runMenuItem('popout', { name: `browser:${BROWSER.id}` });
        expect(calls).toEqual([`popOut ${PAGE.id}`, `popOut ${BROWSER.id}`]);
    });

    test('closing a page row has no profile-wipe confirm; closing a browser keeps it', async () => {
        await BrowserRows.runMenuItem('close', { name: `browser:${PAGE.id}`, isPage: true, label: 'flow' });
        expect(calls).toEqual([`close ${PAGE.id}`]);
        calls.length = 0;
        await BrowserRows.runMenuItem('close', { name: `browser:${BROWSER.id}`, label: 'docs' });
        expect(calls).toEqual(['confirm', `close ${BROWSER.id}`]);
    });

    test('the row menu offers pop out on browser rows only, and names a page close "close page"', () => {
        const items = ROW_ITEMS as unknown as G[];
        const pop = items.find((i) => i.id === 'popout')!;
        expect(pop.available({ kind: 'browser' })).toBe(true);
        expect(pop.available({ kind: 'session' })).toBe(false);
        expect(pop.available({ kind: 'layout' })).toBe(false);
        const close = items.find((i) => i.id === 'close')!;
        expect(close.label({ kind: 'browser', isPage: true })).toBe('browser.menu.close_page');
        expect(close.label({ kind: 'browser' })).toBe('browser.menu.close');
    });

    test('the page flag survives the kebab trigger round trip, and only a page row carries it', () => {
        const menu = { triggerHtml, contextFromTrigger: (el: { getAttribute(n: string): string | null }) => contextFromTrigger(el as unknown as Element)! };
        const base = { name: 'browser:fedcba9876543210', label: 'flow', kind: 'browser', surface: 'sidebar', owned: true, status: 'unknown' };
        const html = (ctx: G) => menu.triggerHtml({ ...base, ...ctx } as never);
        const trigger = (markup: string) => {
            const open = markup.match(/<button[^>]*data-row-menu[^>]*>/)![0];
            return { getAttribute: (n: string) => open.match(new RegExp(`${n}="([^"]*)"`))?.[1] ?? null };
        };
        expect(html({ isPage: true })).toContain('data-row-menu-page="1"');
        expect(menu.contextFromTrigger(trigger(html({ isPage: true }))).isPage).toBe(true);
        expect(html({})).not.toContain('data-row-menu-page');
        expect(menu.contextFromTrigger(trigger(html({}))).isPage).toBe(false);
    });
});
