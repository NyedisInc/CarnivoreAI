/** @vitest-environment jsdom */
import * as BrowserRows from '../drawer/browser-rows';
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { isBrowser, isFileRow } from '../drawer/bucketing';
import { isBandOrderKey, isFoldKey } from '../drawer/store-keys';
import * as Store from '../drawer/store';
import { setQuery } from '../drawer/search';
import { buildRowPlan, type BrowserRowPlan } from '../sidebar-shell/row-plan';
import { buildListPlan, type PaintInput } from '../sidebar-shell/plan';
import type { LegacyDrawer, SidebarRow } from '../sidebar-shell/legacy';
import BrowserRow from '../sidebar-shell/BrowserRow.svelte';
import { fileDrawerRows } from './rows';
import { workdirRelative } from './paths';
import { OPEN_FILES_TOPIC, type OpenFileInfo } from './api.svelte';
import { ROW_ITEMS } from '../item-menu/menus/row-items';

vi.mock('../sidebar-shell/pack-source.svelte', () => ({ packSource: () => [], watchPack: () => {} }));

type G = Record<string, any>; // the legacy drawer globals are untyped by nature

const FILE: OpenFileInfo = {
    id: 'a1b2c3d4e5f60718', kind: 'file', root: 'workdir', path: 'src/app/main.py', session_uuid: 'u-1',
    title: 'main.py', opened_at: 7, seq: 1,
};
const DIFF: OpenFileInfo = { ...FILE, id: 'b1b2c3d4e5f60718', kind: 'diff', path: 'README.md', title: 'README.md' };

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

describe('the files list rows', () => {
    test('an open file is a browser-kind browser:<id> row with its path and dirty state', () => {
        const [row, diff] = fileDrawerRows([FILE, DIFF], (id) => id === FILE.id || id === DIFF.id);
        expect(row).toMatchObject({ name: `browser:${FILE.id}`, kind: 'browser', file: true, browser_id: FILE.id, label: 'main.py',
            path: 'src/app/main.py', dirty: true, status: 'dirty', created_at_epoch: 7 });
        expect(diff).toMatchObject({ file_kind: 'diff', dirty: false, status: 'file' });
    });

    test('a file row files under FILES, never under BROWSERS; a page and a browser stay browsers', () => {
        const [row] = fileDrawerRows([FILE], () => false);
        expect(isFileRow(row!)).toBe(true);
        expect(isBrowser(row!)).toBe(false);
        expect(isBrowser({ name: 'browser:0123456789abcdef', kind: 'browser', page: true })).toBe(true);
        expect(isFileRow({ name: 'browser:0123456789abcdef', kind: 'browser' })).toBe(false);
    });

    test('the files band folds and keeps its own order', () => {
        expect(isFoldKey('files')).toBe(true);
        expect(isBandOrderKey('files')).toBe(true);
    });

    test('the FILES band is drawn right after BROWSERS and moves with it', () => {
        localStorage.clear();
        Store.load();
        setQuery('');
        const L: LegacyDrawer = {
            projectHeader: { ledHtml: () => '', iconHtml: (n) => (n ? `<i ${n}>` : ''), iconForBand: () => null },
        };
        const rows: SidebarRow[] = [
            { name: 't', agent_family: 'shell', project_id: null },
            { name: 'browser:0123456789abcdef', kind: 'browser', project_id: null },
            ...(fileDrawerRows([FILE], () => false) as unknown as SidebarRow[]),
        ];
        const input = (sections?: string[]): PaintInput => ({
            rows, density: 'compact', listing: { ok: true }, missing: [], opts: {},
            arrangement: sections ? { ...Store.current(), sections } : null,
        });
        const keys = buildListPlan(L, input())!.parts.map((p) => p.key);
        expect(keys.slice(-3)).toEqual(['terminals', 'browsers', 'files']);
        const moved = buildListPlan(L, input(['browsers', 'terminals']))!.parts.map((p) => p.key);
        expect(moved.slice(0, 2)).toEqual(['browsers', 'files']);
    });
});

describe('a file row as drawn', () => {
    const host = { menu: { contextFromRow: () => ({}) as never, triggerSpec: (ctx: G) => ({ attrs: { 'data-ctx-file': String(ctx.isFile), 'data-ctx-renameable': String(ctx.renameable) }, svg: '' }) } };

    function plan(dirty: boolean): BrowserRowPlan {
        const [row] = fileDrawerRows([FILE], () => dirty);
        return buildRowPlan(row as unknown as SidebarRow, 'compact', 'files', null, host as never) as BrowserRowPlan;
    }

    test('the plan: a file mark, the path tooltip, the dirty dot, no pop out, "close file", no rename', () => {
        const p = plan(true);
        expect(p.type).toBe('browser');
        expect(p.globe).toMatchObject({ file: true, page: false });
        expect(p.globe.attrs['data-browser-state']).toBe('file');
        expect(p.globe.attrs.title).toBe('file, shown in the main view: src/app/main.py');
        expect(p.name.attrs.title).toBeUndefined();
        expect(p.dirty).not.toBeNull();
        expect(p.popOut).toBeNull();
        expect(p.closeKey.title).toBe('close file');
        expect(p.attrs['data-rename-state']).toBe('unavailable');
        expect(p.menu?.attrs['data-ctx-file']).toBe('true');
        expect(p.menu?.attrs['data-ctx-renameable']).toBe('false');
        expect(plan(false).dirty).toBeNull();
    });

    test('the Svelte row draws the file mark and the dot, and no pop out key', () => {
        const target = document.createElement('div');
        document.body.appendChild(target);
        const shown = mount(BrowserRow, { target, props: { p: plan(true) } });
        flushSync();
        expect(target.querySelector('[data-browser-state="file"] path')?.getAttribute('d')).toContain('M10 12l-2 2.5');
        expect(target.querySelector('.session-sidebar-row-dirty')).not.toBeNull();
        expect(target.querySelector('[data-browser-row-action="popout"]')).toBeNull();
        expect(target.querySelector('[data-browser-state="file"]')?.getAttribute('title')).toContain('src/app/main.py');
        void unmount(shown);
        target.remove();
    });
});

describe('the legacy browsers module with a file row', () => {
    let calls: string[];
    const g = globalThis as G;

    beforeEach(() => {
        calls = [];
        g.CloudeWeb = {
            browsers: {
                list: () => [], pages: () => [],
                open: (id: string) => { calls.push(`open ${id}`); return true; },
                close: async (id: string) => { calls.push(`close ${id}`); },
                popOut: async (id: string) => { calls.push(`popOut ${id}`); return true; },
            },
        };
        g.CloudeWeb.rowMenu = {
            contextFromTrigger: () => ({ name: `browser:${FILE.id}`, label: 'main.py', isPage: false, isFile: true }),
        };
        g.App = { showConfirmModal: vi.fn(async () => { calls.push('profile confirm'); return true; }) };
        g.CloudeI18n = { t: (k: string, p?: { path?: string }) => (p?.path ? `${k}:${p.path}` : k) };
    });

    afterEach(() => {
        delete g.CloudeI18n;
    });

    test('the Shift red x closes the row through the bridge, with no proxy browser confirm', async () => {
        const rowEl = document.createElement('div');
        rowEl.className = 'session-sidebar-row';
        rowEl.setAttribute('data-name', `browser:${FILE.id}`);
        rowEl.innerHTML = '<i data-row-menu></i><button data-browser-row-action="close"></button>';
        document.body.appendChild(rowEl);
        await BrowserRows.onKeyClick(rowEl.querySelector('[data-browser-row-action="close"]')!);
        expect(calls).toEqual([`close ${FILE.id}`]);
        rowEl.remove();
    });

    test('a click on a file row opens the center screen through the same activation', () => {
        expect(BrowserRows.activate(null, `browser:${FILE.id}`)).toBe(true);
        expect(calls).toEqual([`open ${FILE.id}`]);
    });
});

describe('the row menu for a file', () => {
    test('no pop out, and close is named "close file"', () => {
        const g = globalThis as G;
        g.CloudeI18n = { t: (k: string) => k };
        const list = ROW_ITEMS as unknown as G[];
        const popout = list.find((i) => i.id === 'popout');
        const kill = list.find((i) => i.id === 'close');
        expect(popout?.available({ kind: 'browser', isFile: true })).toBe(false);
        expect(popout?.available({ kind: 'browser', isPage: true })).toBe(true);
        expect(kill?.label({ kind: 'browser', isFile: true })).toBe('files.menu.close');
        delete g.CloudeI18n;
    });
});

describe('the push topic', () => {
    test('the list re-reads on the topic its one server writer names (PUSH, NOT PULL)', () => {
        const topics = fs.readFileSync(path.resolve(__dirname, '../../../../src/core/resource_push/topics.py'), 'utf8');
        expect(topics).toMatch(new RegExp(`^OPEN_FILES = "${OPEN_FILES_TOPIC}"$`, 'm'));
    });
});

describe('workdirRelative', () => {
    test('a changed file is named from the session folder, and refused outside it', () => {
        expect(workdirRelative('src/a.py', '/r', '/r')).toBe('src/a.py');
        expect(workdirRelative('app/src/a.py', '/r', '/r/app')).toBe('src/a.py');
        expect(workdirRelative('lib/b.py', '/r', '/r/app')).toBeNull();
        expect(workdirRelative('app', '/r', '/r/app')).toBeNull();
        expect(workdirRelative('a.py', null, '/r')).toBeNull();
        expect(workdirRelative('/etc/passwd', '/r', '/r')).toBeNull();
    });
});
