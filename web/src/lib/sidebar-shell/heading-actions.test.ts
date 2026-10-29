/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const sleepHook = vi.hoisted(() => ({ release: (_name: string): void => {} }));
vi.mock('../drawer/row-menu-sleep', async (orig) => ({
    ...(await orig<typeof import('../drawer/row-menu-sleep')>()), releaseThisTab: (o: { name: string }) => sleepHook.release(o.name),
}));
import * as GroupStore from '../drawer/group-store';
import { deleteGroup } from './heading-group-actions';
import { removeProject, sleepGroup, sleepProject } from './heading-project-actions';

type Win = Record<string, any>;
const win = globalThis as unknown as Win;

const row = (o: Record<string, unknown>) => ({ kind: 'agent', asleep: false, session_id: null, ...o });
const ROWS = () => [
    row({ name: 'c_a', session_uuid: 'ua', session_id: 'ses_a', project_id: 3, project_name: 'Api' }),
    row({ name: 'c_b', session_uuid: 'ub', project_id: 3, project_name: 'Api' }),
    row({ name: 'c_z', session_uuid: 'uz', project_id: 3, project_name: 'Api', asleep: true }),
    row({ name: 'c_web', session_uuid: 'uw', project_id: 3, project_name: 'Api', kind: 'browser' }),
    row({ name: 'c_other', session_uuid: 'uo', session_id: 'ses_o', project_id: 4, project_name: 'Web' }),
];

let calls: unknown[][];
let spoken: string[];
let reported: string[];
let modal: unknown[][];
let confirmAnswer: boolean;

function standUp(o: { failClose?: string; sleepRefuse?: string; deleteFails?: boolean } = {}): void {
    win.SessionSidebar = { _rows: ROWS(), repaint: () => calls.push(['repaint']), _fetchAndRender: async () => { calls.push(['refresh']); } };
    win.WriteFailureNotice = { report: (text: string) => reported.push(text) };
    sleepHook.release = (name) => { calls.push(['release', name]); };
    win.App = { showConfirmModal: async (...args: unknown[]) => { modal.push(args); return confirmAnswer; } };
    const reject = (name: string) => { if (o.failClose === name) throw new Error('tmux said no'); };
    win.API = {
        destroySession: async (id: string) => { calls.push(['destroySession', id]); reject(id === 'ses_a' ? 'c_a' : id); },
        destroyExternalSession: async (name: string) => { calls.push(['destroyExternal', name]); reject(name); },
        deleteSessionRecord: async (uuid: string) => { calls.push(['deleteRecord', uuid]); },
        archiveProject: async (name: string) => { calls.push(['archive', name]); return {}; },
        sleepSession: async (uuid: string) => {
            calls.push(['sleep', uuid]);
            return o.sleepRefuse === uuid ? { status: 'refused', detail: 'no conversation id' } : { status: 'asleep' };
        },
        deleteSessionGroup: async (uuid: string) => {
            calls.push(['delete', uuid]);
            if (o.deleteFails) throw new Error('503 datastore unavailable');
            return { status: 'ok', groups: [], freed: 2 };
        },
        listSessionGroups: async () => ({ status: 'ok', groups: [] }),
    };
}

const writes = () => calls.filter((c) => c[0] !== 'refresh' && c[0] !== 'release' && c[0] !== 'repaint');

beforeEach(() => {
    calls = [];
    spoken = [];
    reported = [];
    modal = [];
    confirmAnswer = true;
    document.body.innerHTML = '<div id="session-sidebar-live"></div>';
    GroupStore.apply({
        status: 'ok',
        groups: [{ group_uuid: 'g1', name: 'Argent', position: 0, members: ['c_a', 'c_other'], member_session_uuids: [], colour: null, gradient: null, animation: 'none', icon: null }],
    });
});

afterEach(() => {
    GroupStore.reset();
    for (const key of ['SessionSidebar', 'WriteFailureNotice', 'App', 'API']) delete win[key];
    vi.restoreAllMocks();
});

const live = () => document.getElementById('session-sidebar-live')!.textContent ?? '';

describe('removing a group', () => {
    it('asks the app\'s own modal, naming the real group and the real destination, danger variant', async () => {
        standUp();
        const confirm = vi.spyOn(win, 'confirm' as never).mockImplementation((() => { throw new Error('window.confirm must never be called'); }) as never);
        await deleteGroup('g1');
        expect(confirm).not.toHaveBeenCalled();
        expect(modal).toHaveLength(1);
        const [title, message, detail, ok, cancel, variant] = modal[0] as string[];
        expect([title, message, ok, cancel, variant]).toEqual(['remove group', 'remove the group "Argent"?', 'remove', 'cancel', 'danger']);
        expect(detail).toMatch(/own project/);
        expect(detail).toMatch(/rogue agents/);
        expect(detail).not.toMatch(/\bother\b/);
    });

    it('CANCEL keeps the group: no delete, no announcement', async () => {
        standUp();
        confirmAnswer = false;
        expect(await deleteGroup('g1')).toBe(false);
        expect(writes()).toEqual([]);
        expect(live()).toBe('');
    });

    it('CONFIRM sends one delete, applies the answer and announces where the agents went', async () => {
        standUp();
        expect(await deleteGroup('g1')).toBe(true);
        expect(writes()).toEqual([['delete', 'g1']]);
        expect(GroupStore.current().groups).toEqual([]);
        expect(live()).toMatch(/project or rogue agents/);
        expect(live()).not.toMatch(/\bother\b/);
    });

    it('a refused delete says so on both surfaces, not success', async () => {
        standUp({ deleteFails: true });
        expect(await deleteGroup('g1')).toBe(false);
        expect(live()).toMatch(/could not remove/);
        expect(reported).toHaveLength(1);
    });
});

describe('project and group bulk actions', () => {
    it('cancelling a project remove sends nothing', async () => {
        standUp();
        confirmAnswer = false;
        expect(await removeProject('p:3')).toBe(false);
        expect(modal).toHaveLength(1);
        expect(modal[0]![5]).toBe('danger');
        expect(writes()).toEqual([]);
    });

    it('a confirmed remove closes every session by its own route, then archives', async () => {
        standUp();
        expect(await removeProject('p:3')).toBe(true);
        expect(writes()).toEqual([['destroySession', 'ses_a'], ['destroyExternal', 'c_b'], ['deleteRecord', 'uz'], ['archive', 'Api']]);
        expect(reported).toEqual([]);
    });

    it('one failed close keeps the project and says which session', async () => {
        standUp({ failClose: 'c_b' });
        expect(await removeProject('p:3')).toBe(false);
        expect(calls.some((c) => c[0] === 'archive')).toBe(false);
        expect(reported).toHaveLength(1);
        expect(reported[0]).toContain('c_b: tmux said no');
    });

    it('sleep on a project sleeps awake non-browser rows only', async () => {
        standUp();
        expect(await sleepProject('p:3')).toEqual({ slept: 2, failed: 0 });
        expect(writes()).toEqual([['sleep', 'ua'], ['sleep', 'ub']]);
        expect(reported).toEqual([]);
    });

    it('sleep on a group sleeps its members and reports a refusal', async () => {
        standUp({ sleepRefuse: 'uo' });
        expect(await sleepGroup('g1')).toEqual({ slept: 1, failed: 1 });
        expect(writes()).toEqual([['sleep', 'ua'], ['sleep', 'uo']]);
        expect(reported).toHaveLength(1);
        expect(reported[0]).toContain('no conversation id');
    });
});
