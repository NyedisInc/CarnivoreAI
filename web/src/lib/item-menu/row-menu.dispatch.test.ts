/** @vitest-environment jsdom */
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import * as Clicks from '../drawer/clicks';
import * as Rename from '../drawer/rename';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const registry = vi.hoisted(() => ({ ran: [] as Array<[string, string, boolean]> }));
vi.mock('../plugins/session-card-actions', () => ({
    sessionCardMenuItems: () => [],
    runSessionCardAction: vi.fn(async (id: string, row: { name: string; unread: boolean }) => {
        registry.ran.push([id, row.name, row.unread]);
        return false;
    }),
}));

const restart = vi.hoisted(() => ({ override: null as null | ((...a: unknown[]) => unknown) }));
vi.mock('../drawer/restart-click', async (orig) => {
    const real = await orig<typeof import('../drawer/restart-click')>();
    return { ...real, runRestart: (...a: Parameters<typeof real.runRestart>) => (restart.override ? restart.override(...a) : real.runRestart(...a)) };
});

const picker = vi.hoisted(() => ({ opened: [] as Array<[boolean, string]> }));
vi.mock('../drawer/group-actions', () => ({
    openPickerFor: (anchor: unknown, name: string) => { picker.opened.push([!!anchor, name]); },
}));

const pinning = vi.hoisted(() => ({ toggled: [] as string[] }));
vi.mock('../sidebar-shell/row-reorder', () => ({
    togglePinRow: (name: string) => { pinning.toggled.push(name); return true; },
}));

import { contextFromRow, triggerHtml } from './row-context';
import { bench, loadRunTable, win } from './row-test-env';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

const loaded = new Set<string>();
function loadScripts(files: string[], fresh = false): void {
    const log = console.log;
    console.log = () => {};
    try {
        for (const f of files) {
            if (loaded.has(f) && !fresh) continue;
            loaded.add(f);
            new Function(fs.readFileSync(path.join(repoRoot, 'client', 'js', f), 'utf8'))();
        }
    } finally {
        console.log = log;
    }
}

function freshRename(): void {
    document.body.replaceChildren();
    Rename.afterRender();
}

function drawRow(shown = true): { rowEl: HTMLElement; nameEl: HTMLElement } {
    const rowEl = document.createElement('div');
    rowEl.className = 'session-sidebar-row';
    rowEl.setAttribute('data-name', 'cloude_api');
    rowEl.setAttribute('data-session-id', 'ses_1');
    rowEl.setAttribute('data-rename-state', 'renameable');
    rowEl.innerHTML = '<span data-row-name>api</span><button data-row-menu="cloude_api"></button>';
    (rowEl as unknown as { getClientRects: () => unknown[] }).getClientRects = () => (shown ? [{}] : []);
    document.body.appendChild(rowEl);
    return { rowEl, nameEl: rowEl.querySelector('[data-row-name]') as HTMLElement };
}

const ctx = () => ({ name: 'cloude_api', label: 'api', surface: 'sidebar', sessionId: 'ses_1' });

let calls: unknown[][];

beforeEach(() => {
    calls = [];
    picker.opened = [];
    registry.ran = [];
    restart.override = (ctrl: unknown, name: unknown, el: unknown) => { calls.push(['runRestart', ctrl, name, !!el]); };
    bench({
        SessionLabel: { LABEL_MAX_CHARS: 200 },
        SessionSidebar: { id: 'the-controller' },
        CloudeWeb: {
            launchpad: { createConsoleSession: (options: unknown) => { calls.push(['createConsoleSession', options]); return Promise.resolve(); } },
            addToMenu: {
                openForSession: (anchor: unknown, name: string, uuid: string) => { calls.push(['openForSession', !!anchor, name, uuid]); },
                openForLayout: (anchor: unknown, uuid: string) => { calls.push(['openForLayout', !!anchor, uuid]); },
            },
        },
        API: { getProjects: () => Promise.resolve(win.API._projects || []), listSessionRecords: () => Promise.resolve(win.API._records || []), _projects: [], _records: [] },
    });
    vi.spyOn(console, 'warn').mockImplementation((...args: unknown[]) => { calls.push(['warn', ...args]); });
    delete win.SessionSidebarLayouts;
    loadRunTable();
    freshRename();
});

afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
});

describe('rename: one implementation, two doors', () => {
    test('double-click rename stays retired (2026-09-20 owner decision)', () => {
        expect((Rename as Record<string, unknown>).onDblClick).toBeUndefined();
        expect((Rename as Record<string, unknown>).deferActivation).toBeUndefined();
    });

    test('F2 and the menu reach the row\'s own editor, not a copy of it', () => {
        const a = drawRow();
        expect(Rename.onRowKeydown(new KeyboardEvent('keydown', { key: 'F2' }), a.rowEl)).toBe(true);
        expect(Rename.isEditing()).toBe(true);
        freshRename();
        document.body.replaceChildren();
        const b = drawRow();
        void win.SessionRowMenuActions.run('rename', ctx());
        expect(Rename.isEditing()).toBe(true);
        expect(b.rowEl.getAttribute('data-editing')).toBe('1');
    });

    test('with no laid-out drawer row it prompts and saves through the rename route', async () => {
        drawRow(false);
        const saved: unknown[] = [];
        const shown: unknown[] = [];
        win.Launchpad = { showError: (m: unknown) => shown.push(m) };
        win.SessionLabel = { LABEL_MAX_CHARS: 200, validate: (v: string) => ({ ok: true, value: v }) };
        win.TextPromptModal = { open: async (o: { defaultValue: string }) => `${o.defaultValue}2` };
        win.API.renameSession = async (id: string, v: string) => { saved.push([id, v]); };
        await win.SessionRowMenuActions.run('rename', { ...ctx(), label: null });
        expect(saved).toEqual([['ses_1', 'api2']]);
        expect(shown).toEqual([]);
        delete win.Launchpad;
    });

    test('both doors refuse a row that cannot be renamed, identically', () => {
        for (const drive of ['f2', 'menu']) {
            freshRename();
            document.body.replaceChildren();
            const { rowEl } = drawRow();
            rowEl.setAttribute('data-rename-state', 'adopting');
            if (drive === 'f2') Rename.onRowKeydown(new KeyboardEvent('keydown', { key: 'F2' }), rowEl);
            else void win.SessionRowMenuActions.run('rename', ctx());
            expect(Rename.isEditing(), drive).toBe(false);
            expect(rowEl.getAttribute('data-rename-refused'), drive).toBe('1');
        }
    });
});

describe('restart and update restart', () => {
    const recordRestart = (): void => {
        restart.override = (...args: unknown[]) => { calls.push(['runRestart', args[0], args[1], !!args[2], args[4], args[5], args[6]]); };
    };

    test('restart goes to the picker through the row\'s own handler, never armed', () => {
        drawRow();
        void win.SessionRowMenuActions.run('restart', ctx());
        expect(calls[0]).toEqual(['runRestart', { id: 'the-controller' }, 'cloude_api', true]);
        calls.length = 0;
        recordRestart();
        void win.SessionRowMenuActions.run('restart', ctx(), { armedByGesture: true });
        expect(calls[0]).toEqual(['runRestart', { id: 'the-controller' }, 'cloude_api', true, false, false, false]);
    });

    test('update restart is unarmed unless the shift-click armed it, and names busy work', () => {
        drawRow();
        recordRestart();
        void win.SessionRowMenuActions.run('update-restart', ctx());
        void win.SessionRowMenuActions.run('update-restart', ctx(), { armedByGesture: true });
        void win.SessionRowMenuActions.run('update-restart', { ...ctx(), updateBusy: true });
        expect(calls.map((c) => [c[5], c[6]])).toEqual([[false, false], [true, false], [false, true]]);
    });

    test('the restart flow reads the status the kebab actually stamped, the measured one for each', async () => {
        loadScripts(['session-status-ui.js', 'session-row-actions-confirm.js', 'session-row-actions.js']);
        restart.override = null;
        for (const status of ['working', 'idle', 'question', 'notice']) {
            document.body.replaceChildren();
            const holder = document.createElement('div');
            holder.className = 'session-sidebar-row';
            holder.setAttribute('data-name', 'cloude_api');
            holder.innerHTML = triggerHtml(contextFromRow({ name: 'cloude_api', label: 'api', status, created_by_cloude: true }, { surface: 'sidebar', renameable: true }));
            document.body.appendChild(holder);
            const seen: unknown[] = [];
            win.SessionRestartPicker = { open: (_n: string, _l: string, st: unknown) => { seen.push(st); return Promise.resolve(null); }, lastError: () => null };
            await Clicks.runRestart(win.SessionSidebar, 'cloude_api', null);
            expect(seen, `status ${status} must reach the picker`).toEqual([status]);
        }
    });
});

describe('pin and unpin on a session row (#2674)', () => {
    test('the pin item runs the drawer\'s one pin path for the row\'s name, and never the plugin registry', async () => {
        pinning.toggled.length = 0;
        await win.SessionRowMenuActions.run('pin', ctx());
        expect(pinning.toggled).toEqual(['cloude_api']);
        expect(registry.ran).toEqual([]);
    });
});

describe('plugin items reach the registry and nothing else', () => {
    test('mark unread carries the frozen flag to the registry', async () => {
        await win.SessionRowMenuActions.run('mark-unread', { ...ctx(), unread: true });
        await win.SessionRowMenuActions.run('mark-unread', { ...ctx(), unread: false });
        expect(registry.ran).toEqual([['mark-unread', 'cloude_api', true], ['mark-unread', 'cloude_api', false]]);
    });

    test('without the bridge the native table is not a second path to a plugin item', async () => {
        win.CloudeWeb = {};
        await win.SessionRowMenuActions.run('mark-unread', { ...ctx(), unread: true });
        expect(registry.ran).toEqual([]);
        expect(calls).toEqual([]);
    });

    test('an id nothing claims reaches the registry, which answers false, and nothing else', async () => {
        expect(await win.SessionRowMenuActions.run('no-such-item', ctx())).toBe(false);
        expect(registry.ran).toEqual([['no-such-item', 'cloude_api', false]]);
        expect(calls).toEqual([]);
    });
});

describe('filing and add to', () => {
    test('move to group opens the group module\'s own picker on the row\'s kebab', () => {
        drawRow();
        void win.SessionRowMenuActions.run('move-to-group', ctx());
        expect(picker.opened).toEqual([[true, 'cloude_api']]);
    });

    test('add to opens the session branch with the tmux name and uuid; on a Layout row, the Layout branch', () => {
        drawRow();
        void win.SessionRowMenuActions.run('add-to', { ...ctx(), sessionUuid: 'u-1' });
        void win.SessionRowMenuActions.run('add-to', { ...ctx(), kind: 'layout', layoutUuid: 'lay-1' });
        expect(calls).toEqual([['openForSession', true, 'cloude_api', 'u-1'], ['openForLayout', true, 'lay-1']]);
    });

    test('a missing collaborator does nothing and throws nothing', () => {
        drawRow();
        win.CloudeWeb = {};
        restart.override = null;
        const quiet = vi.spyOn(console, 'error').mockImplementation(() => {});
        void win.SessionRowMenuActions.run('add-to', ctx());
        void win.SessionRowMenuActions.run('restart', ctx());
        expect(calls).toEqual([]);
        quiet.mockRestore();
    });
});

describe('new terminal here', () => {
    test('opens at the row\'s project path, else the stored record\'s folder', async () => {
        win.API._projects = [{ id: 9, path: '/Users/me/code/other' }, { id: 7, path: '/Users/me/code/api' }];
        win.API._records = [{ tmux_name: 'cloude_api', working_dir: '/should/not/be/used' }];
        await win.SessionRowMenuActions.run('new-terminal-here', { ...ctx(), projectId: 7 });
        win.API._projects = [{ id: 9, path: '/Users/me/code/other' }];
        win.API._records = [{ tmux_name: 'cloude_api', working_dir: '/Users/me/code/api', tmux_created_epoch: 1 }];
        await win.SessionRowMenuActions.run('new-terminal-here', { ...ctx(), projectId: null });
        expect(calls.map((c) => [c[0], (c[1] as { workingDir: string }).workingDir])).toEqual([
            ['createConsoleSession', '/Users/me/code/api'], ['createConsoleSession', '/Users/me/code/api'],
        ]);
    });

    test('NEGATIVE CONTROL: no folder anywhere refuses by name; a missing launcher refuses too', async () => {
        win.CloudeI18n = { t: (k: string, p?: Record<string, string>) => String((enCatalog as Record<string, string>)[k] ?? k).replace(/\{(\w+)\}/g, (_m, n: string) => p?.[n] ?? '') };
        await win.SessionRowMenuActions.run('new-terminal-here', ctx());
        expect(calls).toHaveLength(1);
        expect(calls[0]![0]).toBe('warn');
        expect(String(calls[0]![2])).toMatch(/cannot determine the folder for "api"/);
        calls.length = 0;
        win.CloudeWeb = {};
        await win.SessionRowMenuActions.run('new-terminal-here', ctx());
        expect(calls).toHaveLength(1);
        expect(String(calls[0]![2])).toMatch(/the launcher did not load/);
    });
});
