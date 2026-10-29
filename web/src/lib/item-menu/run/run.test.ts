/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const sleeper = vi.hoisted(() => ({
    runKillAsleep: vi.fn(async () => 'killed'), runSleep: vi.fn(), runReopen: vi.fn(), runArchive: vi.fn(), runWake: vi.fn(),
}));
vi.mock('../../drawer/row-menu-sleep', () => sleeper);
const restartMock = vi.hoisted(() => ({ runRestart: vi.fn(async () => {}) }));
vi.mock('../../drawer/restart-click', () => restartMock);
import { setDrawerEnv } from '../../drawer/env';
import type { RowMenuCtx } from '../row-context';
import { run } from './index';
import { navToken, recordFor } from './run-env';

const ctx = (over: Record<string, unknown> = {}): RowMenuCtx => ({ name: 'cloude_a', label: 'a', hostKey: 'local', projectId: null, ...over }) as unknown as RowMenuCtx;

let said: string[];
let overrides: Array<[string, boolean]>;

function page(extra: Record<string, unknown> = {}): void {
    setDrawerEnv({
        CloudeI18n: { t: (k: string, p?: Record<string, string>) => (p ? `${k} ${JSON.stringify(p)}` : k) },
        Launchpad: { showError: (t: string) => said.push(t) },
        CloudeWeb: { rowMenu: { setMuteOverride: (n: string, m: boolean) => overrides.push([n, m]), shiftHeld: () => false } },
        ...extra,
    });
}

beforeEach(() => {
    said = [];
    overrides = [];
    const g = globalThis as { CSS?: { escape?(v: string): string } };
    if (!g.CSS || typeof g.CSS.escape !== 'function') g.CSS = { ...(g.CSS || {}), escape: (v: string) => String(v) };
});
afterEach(() => { setDrawerEnv(null); document.body.replaceChildren(); vi.restoreAllMocks(); });

describe('recordFor', () => {
    it('newest epoch wins, an archived row never does, a row with no epoch loses to one that has one', async () => {
        page({ API: { listSessionRecords: async () => [
            { tmux_name: 'cloude_a', session_uuid: 'old', tmux_created_epoch: 5 },
            { tmux_name: 'cloude_a', session_uuid: 'new', tmux_created_epoch: 9 },
            { tmux_name: 'cloude_a', session_uuid: 'arch', tmux_created_epoch: 99, archived_at: 'x' },
            { tmux_name: 'cloude_a', session_uuid: 'none' },
        ] } });
        expect((await recordFor('cloude_a'))?.session_uuid).toBe('new');
    });
    it('is null when the listing cannot be read', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        page({ API: { listSessionRecords: async () => { throw new Error('down'); } } });
        expect(await recordFor('cloude_a')).toBeNull();
    });
});

describe('mute', () => {
    const records = async () => [{ tmux_name: 'cloude_a', session_uuid: 'u1' }];
    it('flips at once, then takes the server answer', async () => {
        const call = vi.fn(async () => ({ muted: false }));
        page({ API: { listSessionRecords: records, call } });
        await run('mute', ctx({ muted: false }));
        expect(call).toHaveBeenCalledWith('/sessions/records/u1/notifications', { method: 'PATCH', body: { muted: true } });
        expect(overrides).toEqual([['cloude_a', true], ['cloude_a', false]]);
    });
    it('puts the override back and says so when the write fails', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        page({ API: { listSessionRecords: records, call: async () => { throw new Error('nope'); } } });
        await run('mute', ctx({ muted: false }));
        expect(overrides).toEqual([['cloude_a', true], ['cloude_a', false]]);
        expect(said[0]).toContain('session.menu.run.mute_failed')
        expect(said[0]).toContain('"message":"nope"');
    });
    it('rolls back without a write when no stored record names the session', async () => {
        const call = vi.fn();
        page({ API: { listSessionRecords: async () => [], call } });
        await run('mute', ctx({ muted: true }));
        expect(call).not.toHaveBeenCalled();
        expect(overrides).toEqual([['cloude_a', false], ['cloude_a', true]]);
    });
});

describe('folders refuse with a reason', () => {
    it('new in folder: no record, and a record with no folder', async () => {
        const selectProject = vi.fn();
        page({ Launchpad: { showError: (t: string) => said.push(t), selectProject }, API: { listSessionRecords: async () => [] } });
        await run('new-in-folder', ctx());
        expect(said[0]).toContain('session.menu.run.folder_unknown_start');
        page({ Launchpad: { showError: (t: string) => said.push(t), selectProject }, API: { listSessionRecords: async () => [{ tmux_name: 'cloude_a' }] } });
        await run('new-in-folder', ctx());
        expect(said[1]).toContain('session.menu.run.no_folder');
        expect(selectProject).not.toHaveBeenCalled();
    });
    it('new in folder starts where the record lives', async () => {
        const selectProject = vi.fn();
        page({ Launchpad: { selectProject }, API: { listSessionRecords: async () => [{ tmux_name: 'cloude_a', working_dir: '/w', title: 'T' }] } });
        await run('new-in-folder', ctx());
        expect(selectProject).toHaveBeenCalledWith({ name: 'T', path: '/w', launch_from: { kind: 'session', name: 'T', pinned: false } });
    });
    it('show path: the session record wins over the project', async () => {
        const showPath = vi.fn(async () => {});
        page({ CloudeWeb: { showPath }, API: {
            listSessionRecords: async () => [{ tmux_name: 'cloude_a', working_dir: '/rec' }],
            getProjects: async () => [{ id: 7, path: '/proj' }],
        } });
        await run('show-path', ctx({ projectId: 7 }));
        expect(showPath).toHaveBeenCalledWith('/rec', 'a');
    });
    it('new terminal: the project path wins over the record', async () => {
        const createConsoleSession = vi.fn(async () => {});
        page({ CloudeWeb: { launchpad: { createConsoleSession } }, API: {
            listSessionRecords: async () => [{ tmux_name: 'cloude_a', working_dir: '/rec' }],
            getProjects: async () => [{ id: 7, path: '/proj' }],
        } });
        await run('new-terminal-here', ctx({ projectId: 7 }));
        expect(createConsoleSession).toHaveBeenCalledWith({ workingDir: '/proj' });
    });
});

describe('the order the table tries things in', () => {
    it('an unknown id goes to the plugin bridge last, and answers false without one', async () => {
        const runPlugin = vi.fn(async (_id: string, _ctx: RowMenuCtx) => true);
        page({ CloudeWeb: { rowMenu: { setMuteOverride() {}, shiftHeld: () => false, runPlugin } } });
        expect(await run('mark-unread', ctx())).toBe(true);
        expect(runPlugin).toHaveBeenCalledWith('mark-unread', expect.objectContaining({ name: 'cloude_a' }));
        page({});
        expect(await run('mark-unread', ctx())).toBe(false);
    });
    it('close on an asleep row kills the record, never the pane', async () => {
        expect(await run('close', ctx({ asleep: true }))).toBe('killed');
        expect(sleeper.runKillAsleep).toHaveBeenCalled();
        expect(await run('archive', ctx())).toBeUndefined();
        expect(sleeper.runArchive).toHaveBeenCalled();
    });
    it('close hands the click ladder a detached button carrying the captured identity', async () => {
        const confirm = vi.fn(async () => false);
        page({
            SessionRowActions: { ATTR_ACTION: 'data-a', ATTR_NAME: 'data-n', ACTION_CLOSE: 'close', confirm },
            SessionSidebar: { listEl: null },
        });
        await run('close', ctx());
        expect(confirm).toHaveBeenCalledWith('close', 'cloude_a');
    });
    it('restart now runs plain while shift is up', async () => {
        const runRestart = restartMock.runRestart;
        runRestart.mockClear();
        const row = document.createElement('div');
        row.className = 'session-sidebar-row';
        row.setAttribute('data-name', 'cloude_a');
        document.body.appendChild(row);
        page({ SessionSidebar: { id: 'c' } });
        await run('restart-now', ctx());
        expect(runRestart.mock.calls[0]?.slice(3)).toEqual(['local', false, false, false, false]);
        page({
            SessionSidebar: { id: 'c' },
            CloudeWeb: { rowMenu: { setMuteOverride() {}, shiftHeld: () => true } },
        });
        await run('restart-now', ctx());
        expect(runRestart.mock.calls[1]?.slice(3)).toEqual(['local', false, false, false, true]);
    });
    it('a restart without its row on screen says so and starts nothing', async () => {
        const runRestart = restartMock.runRestart;
        runRestart.mockClear();
        page();
        await run('restart', ctx());
        expect(runRestart).not.toHaveBeenCalled();
        expect(said[0]).toContain('session.menu.run.restart_row_gone');
    });
});

describe('item ids that are Object.prototype members', () => {
    it.each(['constructor', 'toString', 'hasOwnProperty', '__proto__'])('%s goes to the plugin bridge, never a prototype member', async (id) => {
        const runPlugin = vi.fn(async (_id: string, _ctx: RowMenuCtx) => true);
        page({ CloudeWeb: { rowMenu: { setMuteOverride: () => undefined, shiftHeld: () => false, runPlugin } } });
        await run(id, ctx());
        expect(runPlugin).toHaveBeenCalledTimes(1);
        expect(runPlugin.mock.calls[0]![0]).toBe(id);
    });
});

describe('navToken', () => {
    it('moves on every navigation the app announces', () => {
        const before = navToken();
        window.dispatchEvent(new Event('popstate'));
        window.dispatchEvent(new Event('hashchange'));
        expect(navToken()).toBe(before + 2);
    });
});
