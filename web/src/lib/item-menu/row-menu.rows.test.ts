/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, beforeEach, describe, expect, test } from 'vitest';
import '../plugins/builtin';
import { sessionCardMenuItems } from '../plugins/session-card-actions';
import { contextFromRow, contextFromTrigger, triggerHtml, type RowContextOptions } from './row-context';
import { bench, ctxOf, idsOf, itemsOf, loadRunTable, triggerFrom, win } from './row-test-env';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

function run(...files: string[]): void {
    const log = console.log;
    console.log = () => {};
    try {
        for (const f of files) new Function(fs.readFileSync(path.join(repoRoot, 'client', 'js', f), 'utf8'))();
    } finally {
        console.log = log;
    }
}

function groupStore(groups: Array<{ group_uuid: string; name: string }>) {
    return {
        groupUuidOf: (key: string) => (typeof key === 'string' && key.startsWith('g:') ? key.slice(2) || null : null),
        groupByUuid: (uuid: string) => groups.find((g) => g.group_uuid === uuid) || null,
    };
}

let rowActions: Record<string, unknown>;
let markUnread = true;

beforeAll(() => {
    run('session-key.js', 'session-status-ui.js', 'session-row-actions-confirm.js', 'session-row-actions.js');
    rowActions = win.SessionRowActions;
});

beforeEach(() => {
    markUnread = true;
    bench({
        SessionLabel: { LABEL_MAX_CHARS: 200 },
        SessionRowActions: rowActions,
        UIFlags: { showMarkUnreadControl: () => markUnread },
        SessionSidebarGroupActions: { openPickerFor() {} },
        SessionSidebarGroupStore: groupStore([{ group_uuid: 'u-orchard', name: 'Orchard' }]),
        CloudeWeb: { sessionCardMenuItems },
    });
    win.CloudeI18n = { t: (key: string) => ({ 'sidebar.group.remove_from.label': 'remove from group' } as Record<string, string>)[key] ?? key };
});

const liveRow = (over: Record<string, unknown> = {}) => ({ name: 'cloude_api', label: 'api', status: 'idle', created_by_cloude: true, session_id: 'ses_1', ...over });
const ctxFor = (row: Record<string, unknown>, opts: RowContextOptions = {}) => contextFromRow(row, { surface: 'sidebar', renameable: true, ...opts });
const idsFor = (row: Record<string, unknown>, opts: RowContextOptions = {}) => idsOf(ctxFor(row, opts));

describe('a live row (test_session_row_menu_superset)', () => {
    test('offers every item in the ruled order, a spacer between every group and only there', () => {
        expect(idsFor(liveRow())).toEqual([
            'new-in-folder', 'new-terminal-here', 'fork',
            'rename', 'mark-unread', 'pin', 'share-read-only', 'add-to',
            'show-path',
            'mute',
            'restart', 'sleep', 'send-to', 'move-to-folder',
            'close',
        ]);
        const items = itemsOf(ctxFor(liveRow()));
        expect(items.filter((i) => i.separatorBefore).map((i) => i.id)).toEqual(['rename', 'show-path', 'mute', 'restart', 'close']);
        expect(items[0]!.separatorBefore).toBe(false);
        const asleep = itemsOf(ctxFor(liveRow({ status: 'asleep', asleep: true, session_id: null, session_uuid: 'u-1' })));
        expect(asleep.at(-1)!.id).toBe('close');
        expect(asleep.at(-1)!.separatorBefore).toBe(true);
        expect(asleep.slice(-3).map((i) => i.id)).toEqual(['wake', 'send-to', 'close']);
    });

    test('sleep and move to folder need the stored key, and say so without it', () => {
        const sleep = itemsOf(ctxFor(liveRow())).find((i) => i.id === 'sleep')!;
        expect(sleep.enabled).toBe(false);
        expect(sleep.reason.length).toBeGreaterThan(0);
        expect(itemsOf(ctxFor(liveRow({ session_uuid: 'u-1' }))).find((i) => i.id === 'sleep')!.enabled).toBe(true);
        const move = itemsOf(ctxFor(liveRow({ session_uuid: 'u-1' }))).find((i) => i.id === 'move-to-folder')!;
        expect(move.label).toBe('session.menu.move_folder');
        expect(move.enabled).toBe(true);
        expect(itemsOf(ctxFor(liveRow())).find((i) => i.id === 'move-to-folder')!.enabled).toBe(false);
        expect(idsFor(liveRow({ status: 'asleep', asleep: true, session_id: null, session_uuid: 'u-1' }))).not.toContain('move-to-folder');
        expect(idsFor(liveRow({ host_key: 'peer-1', session_uuid: 'u-1' }))).not.toContain('move-to-folder');
    });

    test('an asleep row offers wake in sleep\'s place and nothing that needs tmux', () => {
        const ids = idsFor(liveRow({ status: 'asleep', asleep: true, session_id: null, session_uuid: 'u-1' }));
        for (const kept of ['wake', 'close', 'rename', 'fork', 'send-to']) expect(ids, kept).toContain(kept);
        for (const gone of ['sleep', 'restart', 'mark-unread', 'share-read-only']) expect(ids, gone).not.toContain(gone);
        expect(idsFor(liveRow({ status: 'asleep', asleep: true, archived: true, session_id: null, session_uuid: 'u-1' }))).not.toContain('rename');
        expect(idsFor(liveRow({ session_uuid: 'u-1' }))).not.toContain('wake');
    });

    test('decision 3: every measured-live status offers restart; an undetermined row only when we created it', () => {
        for (const status of ['working', 'working_subagent', 'question', 'notice', 'finished_unread', 'idle', 'running']) expect(idsFor(liveRow({ status })), status).toContain('restart');
        for (const status of ['unknown', undefined, null, '']) {
            for (const created of [false, null, undefined]) expect(idsFor(liveRow({ status, created_by_cloude: created })), `${String(status)} ${String(created)}`).not.toContain('restart');
            const owned = idsFor(liveRow({ status, created_by_cloude: true }));
            expect(owned).toContain('restart');
            expect(owned).toContain('close');
        }
    });

    test('restart availability is derived from actionsFor, and decision 4: a dead row draws no menu', () => {
        const ra = rowActions as { actionsFor(s: string, o?: { owned: boolean }): string[]; offersMenu(s: string): boolean; ACTION_RESTART: string; ACTION_REMOVE: string };
        for (const status of ['working', 'idle', 'unknown', 'dead', 'question']) {
            if (!ra.offersMenu(status)) continue;
            expect(idsFor(liveRow({ status })).includes('restart'), status).toBe(ra.actionsFor(status, { owned: true }).includes(ra.ACTION_RESTART));
        }
        expect(ra.offersMenu('dead')).toBe(false);
        expect([...ra.actionsFor('dead')]).toEqual([ra.ACTION_RESTART, ra.ACTION_REMOVE]);
    });

    test('mark unread follows its flag; an unread row offers mark read in its place (issue 2071)', () => {
        markUnread = false;
        const off = idsFor(liveRow());
        expect(off).not.toContain('mark-unread');
        expect(off).toContain('close');
        expect(off).toContain('restart');
        markUnread = true;
        const idsOfUnread = (unread: boolean) => itemsOf(ctxFor(liveRow({ unread }))).map((i) => i.id);
        expect(idsOfUnread(false)).toContain('mark-unread');
        expect(idsOfUnread(false)).not.toContain('mark-read');
        expect(idsOfUnread(true)).toContain('mark-read');
        expect(idsOfUnread(true)).not.toContain('mark-unread');
    });

    test('add to only on the sidebar with the group module; a browser or Layout files itself, a Layout also adds members', () => {
        expect(idsFor(liveRow())).toContain('add-to');
        expect(idsFor(liveRow(), { surface: 'launchpad' })).not.toContain('add-to');
        delete win.SessionSidebarGroupActions;
        expect(idsFor(liveRow())).not.toContain('add-to');
        win.SessionSidebarGroupActions = { openPickerFor() {} };
        const base = ctxFor(liveRow());
        expect(idsOf(base)).not.toContain('move-to-group');
        const browser = idsOf({ ...base, kind: 'browser' });
        expect(browser).toContain('move-to-group');
        expect(browser).not.toContain('add-to');
        const layout = idsOf({ ...base, kind: 'layout' });
        expect(layout).toContain('move-to-group');
        expect(layout).toContain('add-members');
        expect(layout).not.toContain('add-to');
    });

    test('mute states the result; fork and rename are refused with a reason', () => {
        const mute = (muted: boolean) => itemsOf(ctxFor(liveRow({ notifications_muted: muted }))).find((i) => i.id === 'mute')!.label;
        expect(mute(false)).toMatch(/^mute/);
        expect(mute(true)).toMatch(/^unmute/);
        const fork = itemsOf(ctxFor(liveRow({ created_by_cloude: false }))).find((i) => i.id === 'fork')!;
        expect(fork.enabled).toBe(false);
        expect(fork.reason).toMatch(/cannot fork/);
        const rename = itemsOf(contextFromRow(liveRow(), { surface: 'sidebar', renameable: false, renameReason: 'open it first' })).find((i) => i.id === 'rename')!;
        expect(rename.enabled).toBe(false);
        expect(rename.reason).toBe('open it first');
    });

    test('the context round-trips through the trigger unchanged: the same menu, the key, a Layout uuid, the project id', () => {
        const ctx = ctxFor(liveRow({ unread: true }));
        const back = contextFromTrigger(triggerFrom(triggerHtml(ctx)))!;
        for (const field of ['name', 'status', 'unread', 'restartable', 'pluginItems', 'groupable', 'renameable', 'muted'] as const) expect(back[field], field).toBe(ctx[field]);
        expect(idsOf(back)).toEqual(idsOf(ctx));
        const asleep = contextFromTrigger(triggerFrom(triggerHtml(contextFromRow(liveRow({ asleep: true, session_uuid: 'u-9' }), { surface: 'sidebar' }))))!;
        expect(asleep.sessionUuid).toBe('u-9');
        expect(asleep.asleep).toBe(true);
        const layout = contextFromTrigger(triggerFrom(triggerHtml({ ...ctx, kind: 'layout', layoutUuid: 'lay-42' })))!;
        expect(layout.kind).toBe('layout');
        expect(layout.layoutUuid).toBe('lay-42');
        expect(contextFromTrigger(triggerFrom(triggerHtml(ctxFor(liveRow({ project_id: 7 })))))!.projectId).toBe(7);
        expect(contextFromTrigger(triggerFrom(triggerHtml(ctxFor(liveRow()))))!.projectId).toBeNull();
    });

    test('every drawn letter is distinct', () => {
        const drawn = itemsOf(ctxFor(liveRow(), { band: 'g:u-orchard' })).map((i) => i.shortcut).filter(Boolean);
        expect(new Set(drawn).size).toBe(drawn.length);
    });
});

describe('a remote row (test_session_row_menu_host_gate)', () => {
    const LOCAL = { name: 'cloude_api', status: 'working', created_by_cloude: true };
    const REMOTE = { ...LOCAL, host_key: 'hosta' };

    test('both are restartable; the host rides the context and the trigger; fork and sleep are local only', () => {
        expect(ctxFor(LOCAL).restartable).toBe(true);
        expect(ctxFor(LOCAL).hostKey).toBe('local');
        expect(ctxFor({ ...LOCAL, host_key: 'local' }).restartable).toBe(true);
        const remote = ctxFor(REMOTE);
        expect(remote.restartable).toBe(true);
        expect(remote.hostKey).toBe('hosta');
        expect(triggerHtml(remote)).toMatch(/data-row-menu-restartable="1"/);
        expect(triggerHtml(remote)).toMatch(/data-row-menu-host-key="hosta"/);
        expect(triggerHtml(ctxFor(LOCAL))).toMatch(/data-row-menu-host-key="local"/);
        const withUuid = { session_uuid: 'u-1' };
        for (const id of ['fork', 'sleep']) {
            expect(idsFor({ ...LOCAL, ...withUuid }), id).toContain(id);
            expect(idsFor({ ...REMOTE, ...withUuid }), id).not.toContain(id);
        }
        expect(idsFor(REMOTE)).toContain('restart');
        expect(ctxFor({ name: 'cloude_x', status: 'unknown', created_by_cloude: false }).restartable).toBe(false);
    });

    async function restartWith(hostKey: string, withKey = true) {
        const calls = { opened: [] as unknown[], respawned: [] as unknown[], alerts: [] as unknown[] };
        win.SessionRestartPicker = {
            open: async (target: string, _l: string, _s: string, uuid: string | null) => { calls.opened.push({ target, uuid }); return { mode: 'restart', agentType: null, confirmRestartLive: false }; },
            lastError: () => '',
        };
        win.SessionRestartOptions = { recreateTarget: () => 'local-uuid' };
        win.Launchpad = { sessionRecords: [] };
        win.API = { respawnSession: async (target: string) => { calls.respawned.push(target); return { ok: false, detail: 'x' }; } };
        win.alert = (m: unknown) => calls.alerts.push(m);
        if (!win.CSS || typeof win.CSS.escape !== 'function') win.CSS = { ...(win.CSS || {}), escape: (v: string) => String(v) };
        const key = win.SessionKey;
        if (!withKey) delete win.SessionKey;
        try {
            run('session-sidebar-restart-click.js');
            await win.SessionSidebarRestartClick.runRestart({ _fetchAndRender: async () => {} }, 'cloude_api', null, hostKey);
        } finally {
            win.SessionKey = key;
            delete win.Launchpad;
        }
        return calls;
    }

    test('the restart flow previews and restarts the remote KEY with no recreate offer; a local row its bare name', async () => {
        const remote = await restartWith('hosta');
        expect(remote.opened).toEqual([{ target: 'remote:hosta:cloude_api', uuid: null }]);
        expect(remote.respawned).toEqual(['remote:hosta:cloude_api']);
        const local = await restartWith('local');
        expect(local.opened).toEqual([{ target: 'cloude_api', uuid: 'local-uuid' }]);
        expect(local.respawned).toEqual(['cloude_api']);
    });

    test('FAIL CLOSED: a remote row without the key module restarts nothing', async () => {
        const calls = await restartWith('hosta', false);
        expect(calls.opened).toEqual([]);
        expect(calls.respawned).toEqual([]);
        expect(calls.alerts).toHaveLength(1);
    });
});

describe('remove from group (test_session_row_menu_remove_from_group)', () => {
    test('only the copy under its hand-made group\'s own band offers it', () => {
        expect(idsFor(liveRow(), { band: 'g:u-orchard' })).toContain('remove-from-group');
        for (const band of ['pinned', 'p:7', 'rogue', 'other', undefined]) expect(idsFor(liveRow(), { band }), String(band)).not.toContain('remove-from-group');
        win.SessionSidebarGroupStore = groupStore([]);
        expect(idsFor(liveRow(), { band: 'g:u-orchard' }), 'a group the store no longer has').not.toContain('remove-from-group');
        win.SessionSidebarGroupStore = groupStore([{ group_uuid: 'u-orchard', name: 'Orchard' }]);
        delete win.SessionSidebarGroupActions;
        expect(idsFor(liveRow(), { surface: 'launchpad', band: 'g:u-orchard' }), 'NEGATIVE CONTROL: no group model').not.toContain('remove-from-group');
    });

    test('the label is flat, never named, and the group survives the trigger', () => {
        const ctx = ctxFor(liveRow(), { band: 'g:u-orchard' });
        expect(itemsOf(ctx).find((i) => i.id === 'remove-from-group')!.label).toBe('remove from group');
        const back = contextFromTrigger(triggerFrom(triggerHtml(ctx)))!;
        expect(back.groupUuid).toBe('u-orchard');
        expect(back.groupName).toBe('Orchard');
        expect(itemsOf(back).find((i) => i.id === 'remove-from-group')!.label).toBe('remove from group');
    });

    test('it is the one write "other" already uses, never the picker; absent module, nothing', async () => {
        const calls: unknown[] = [];
        win.SessionSidebarGroupActions = {
            commitAssignment: (name: string, uuid: string | null) => { calls.push(['commitAssignment', name, uuid]); return Promise.resolve(true); },
            openPickerFor: () => calls.push(['openPickerFor']),
        };
        loadRunTable();
        const ctx = { name: 'cloude_api', label: 'api', surface: 'sidebar', groupUuid: 'u-orchard', groupName: 'Orchard' };
        await win.SessionRowMenuActions.run('remove-from-group', ctx);
        expect(calls).toEqual([['commitAssignment', 'cloude_api', null]]);
        delete win.SessionSidebarGroupActions;
        await win.SessionRowMenuActions.run('remove-from-group', ctx);
        expect(calls).toHaveLength(1);
    });
});

describe('keep awake and the asleep row (#1839, test_session_sidebar_keep_awake)', () => {
    test('keep awake on an asleep row: off when kept, on for a sleepable family, never remote', () => {
        win.CloudeWeb = { ...win.CloudeWeb, autoSleep: { isKeptAwake: (n: string) => n === 'kept' } };
        const has = (over: Record<string, unknown>) => idsOf(ctxOf({ asleep: true, agentFamily: 'claude', ...over })).includes('keep-awake');
        expect(has({ name: 'kept' })).toBe(true);
        expect(has({ name: 'plain' })).toBe(true);
        expect(has({ name: 'plain', agentFamily: 'shell' })).toBe(false);
        expect(has({ name: 'kept', hostKey: 'peer-1' })).toBe(false);
    });

    test('the asleep row offers fork and send to, no live-process item, and an archived one neither', () => {
        win.CloudeWeb = { ...win.CloudeWeb, autoSleep: { isKeptAwake: () => false } };
        const asleep = ctxOf({ name: 'a', asleep: true, agentFamily: 'claude', sessionUuid: 'u-1', restartable: true, forkable: true });
        const ids = idsOf(asleep);
        for (const id of ['fork', 'send-to', 'keep-awake', 'wake', 'schedule', 'show-path', 'mute', 'close']) expect(ids, id).toContain(id);
        for (const id of ['sleep', 'restart', 'update-restart', 'reconnect-mcp']) expect(ids, id).not.toContain(id);
        const archived = idsOf({ ...asleep, archived: true });
        expect(archived).not.toContain('fork');
        expect(archived).not.toContain('send-to');
    });
});
