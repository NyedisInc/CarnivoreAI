/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

const plugins = vi.hoisted(() => ({ items: [] as Array<{ id: string; label: string; order: number; shortcut: string; locked: boolean }> }));
vi.mock('../plugins/session-card-actions', () => ({
    sessionCardMenuItems: () => plugins.items,
    runSessionCardAction: vi.fn(async () => true),
}));

import { registeredKey } from '../menu-keys/menu-keys';
import { contextFromRow, contextFromTrigger, triggerHtml } from './row-context';
import { runSessionCardAction } from '../plugins/session-card-actions';
import { bench, ctxOf, idsOf, itemsOf, loadRunTable, nodesOf, triggerFrom, win } from './row-test-env';

beforeEach(() => {
    plugins.items = [];
    bench();
});

describe('one letter per verb (test_menu_key_map, test_row_menu_registry_keys)', () => {
    const LIVE = ctxOf({ groupable: true, renameable: true, forkable: true, restartable: true, sessionUuid: 'u-1', groupUuid: 'g-1', conversationId: 'c-1', sessionId: 's-1', agentUpdateReady: true });
    const STATES = {
        live: LIVE,
        muted: { ...LIVE, muted: true },
        asleep: { ...LIVE, asleep: true },
        archived: { ...LIVE, asleep: true, archived: true },
        remote: { ...LIVE, hostKey: 'peer' },
        layout: ctxOf({ name: 'layout:1', kind: 'layout', groupable: true, renameable: true, groupUuid: 'g-1' }),
        browser: ctxOf({ name: 'b1', kind: 'browser' }),
    };

    test('every drawn verb keeps its one fixed letter in every state, and no letter repeats', () => {
        const letterOf = new Map<string, string>();
        const seen = new Set<string>();
        for (const [state, ctx] of Object.entries(STATES)) {
            const items = itemsOf(ctx);
            expect(items.length, `${state}: the menu has items`).toBeGreaterThanOrEqual(3);
            const drawn = items.filter((i) => i.enabled).map((i) => i.shortcut);
            expect(new Set(drawn).size, `${state}: no key repeats (${drawn})`).toBe(drawn.length);
            for (const i of items.filter((x) => x.enabled)) {
                seen.add(i.id);
                expect(registeredKey(i.id), `${state}: ${i.id} is in the fixed map`).not.toBeNull();
                expect(i.shortcut, `${state}: ${i.id} draws its fixed letter`).toBe(registeredKey(i.id));
                expect(letterOf.get(i.id) ?? i.shortcut, `${state}: ${i.id} keeps one letter`).toBe(i.shortcut);
                letterOf.set(i.id, i.shortcut);
            }
        }
        expect(itemsOf(STATES.archived).find((i) => i.id === 'wake')?.shortcut).toBe('w');
        expect(itemsOf(STATES.asleep).find((i) => i.id === 'wake')?.shortcut).toBe('w');
        expect(seen.size, 'enough distinct actions covered').toBeGreaterThanOrEqual(18);
    });

    test('a live row and a Layout row: add to is never d, rename is r, new agent n, color c, load blueprint b', () => {
        plugins.items = [{ id: 'mark-unread', label: 'mark unread', order: 200, shortcut: 'U', locked: false }];
        const live = ctxOf({ groupable: true, renameable: true, forkable: true, restartable: true, sessionUuid: 'u-1', groupUuid: 'g-1', pluginItems: 'mark-unread' });
        const layout = ctxOf({ name: 'layout:1', kind: 'layout', groupable: true, renameable: true });
        for (const [what, ctx] of [['a live session row', live], ['a layout row', layout]] as const) {
            const items = itemsOf(ctx);
            expect(items.length, what).toBeGreaterThanOrEqual(6);
            for (const i of items.filter((x) => x.enabled)) expect(i.shortcut, `${what}: ${i.id} has a key`).toMatch(/^[a-z0-9,+\-[\]?/]$/);
            const addTo = items.find((i) => i.id === 'add-to' || i.id === 'add-members');
            expect(addTo, `${what}: offers add to`).toBeTruthy();
            expect(addTo!.shortcut, `${what}: d means delete in every menu`).not.toBe('d');
            expect(items.find((i) => i.id === 'rename')?.shortcut).toBe('r');
        }
        expect(itemsOf(live).find((i) => i.id === 'new-in-folder')?.shortcut).toBe('n');
        const keys = Object.fromEntries(itemsOf(layout).map((i) => [i.id, i.shortcut]));
        expect(keys.colour).toBe('c');
        expect(keys['load-blueprint']).toBe('b');
    });
});

describe('a closed, asleep or archived row (test_row_menu_closed)', () => {
    const BASE = ctxOf({ groupable: true, renameable: true, forkable: true, restartable: true, sessionUuid: 'u-1', agentFamily: 'claude' });
    const CLOSED = { ...BASE, closed: true, restartable: false };

    test('a closed row offers reopen and archive and nothing that needs a process', () => {
        const closed = idsOf(CLOSED);
        expect(closed).toContain('reopen');
        expect(closed).toContain('archive');
        for (const live of ['restart', 'update-restart', 'sleep', 'wake', 'close', 'fork', 'send-to', 'rename', 'keep-awake']) expect(closed, live).not.toContain(live);
        for (const other of [BASE, { ...BASE, asleep: true }, { ...BASE, archived: true }]) {
            expect(idsOf(other)).not.toContain('reopen');
            expect(idsOf(other)).not.toContain('archive');
        }
        expect(idsOf({ ...BASE, asleep: true })).toContain('wake');
        const arch = idsOf({ ...BASE, archived: true });
        for (const gone of ['wake', 'sleep', 'restart', 'reopen']) expect(arch, gone).not.toContain(gone);
    });

    test('the words come from the catalog, and archive without a uuid is drawn refused', () => {
        const labels = Object.fromEntries(itemsOf(CLOSED).map((i) => [i.id, i.label]));
        expect(labels.reopen).toBe('session.menu.reopen');
        expect(labels.archive).toBe('session.archive.action');
        expect(itemsOf({ ...CLOSED, sessionUuid: '' }).find((i) => i.id === 'archive')?.enabled).toBe(false);
    });

    test('contextFromRow: an archived or closed row is never restartable', () => {
        win.SessionRowActions = { actionsFor: () => ['close', 'restart'], ACTION_RESTART: 'restart' };
        expect(contextFromRow({ name: 'archived:u-1', status: 'archived', archived: true, created_by_cloude: true, session_uuid: 'u-1' }, {}).restartable).toBe(false);
        const closed = contextFromRow({ name: 'cloude_x', status: 'closed', closed: true, created_by_cloude: true, session_uuid: 'u-1' }, { surface: 'sidebar' });
        expect(closed.closed).toBe(true);
        expect(closed.restartable).toBe(false);
        expect(contextFromRow({ name: 'cloude_y', status: 'idle' }, {}).closed).toBe(false);
    });

    test('archive and reopen run through the stored record, by uuid', async () => {
        const calls: unknown[] = [];
        bench({
            API: {
                restartSession: async (uuid: string) => { calls.push(['restartSession', uuid]); return {}; },
                deleteSessionRecord: async (uuid: string) => { calls.push(['deleteSessionRecord', uuid]); return {}; },
            },
        });
        loadRunTable();
        await win.SessionRowMenuActions.run('archive', CLOSED);
        expect(calls.splice(0)).toEqual([['deleteSessionRecord', 'u-1']]);
        await win.SessionRowMenuActions.run('reopen', CLOSED);
        expect(calls.splice(0)).toEqual([['restartSession', 'u-1']]);
    });
});

describe('mark read (test_row_menu_mark_read)', () => {
    const BASE = ctxOf({ groupable: true, renameable: true, forkable: true, restartable: true, sessionUuid: 'u-1', agentFamily: 'claude' });
    const has = (over: Record<string, unknown>): boolean => idsOf({ ...BASE, ...over }).includes('mark-read');

    test('drawn on any row that carries the unread flag (widened, issue 2071), absent without it', () => {
        expect(has({ status: 'finished_unread', unread: true })).toBe(true);
        expect(has({ status: 'idle', unread: true })).toBe(true);
        expect(has({ asleep: true, status: 'asleep', unread: true })).toBe(true);
        expect(has({ status: 'idle', unread: false })).toBe(false);
        expect(has({ asleep: true, status: 'asleep', unread: false })).toBe(false);
        for (const status of ['working', 'working_subagent', 'question', 'notice', 'dead', 'unknown']) expect(has({ status, unread: true }), status).toBe(true);
        expect(has({ kind: 'browser', status: 'idle', unread: true })).toBe(false);
        const item = itemsOf({ ...BASE, status: 'finished_unread', unread: true }).find((i) => i.id === 'mark-read')!;
        expect(item.label).toBe('session.menu.mark_read');
        expect(item.enabled).toBe(true);
    });

    test('it clears unread through the existing route', async () => {
        const calls: unknown[] = [];
        bench({ API: { setSessionUnread: async (name: string, unread: boolean) => { calls.push([name, unread]); return {}; } } });
        loadRunTable();
        await win.SessionRowMenuActions.run('mark-read', { ...BASE, status: 'finished_unread', unread: true });
        expect(calls).toEqual([['cloude_x', false]]);
    });

    test('mark read and the mark unread plugin never sit side by side', () => {
        plugins.items = [{ id: 'mark-unread', order: 200, label: 'clear unread', shortcut: 'U', locked: false }];
        const ids = (over: Record<string, unknown>): string[] => idsOf({ ...BASE, pluginItems: 'mark-unread', ...over });
        expect(ids({ status: 'finished_unread', unread: true })).toContain('mark-read');
        expect(ids({ status: 'finished_unread', unread: true })).not.toContain('mark-unread');
        expect(ids({ status: 'working', unread: false })).not.toContain('mark-unread');
        expect(ids({ status: 'working_subagent', unread: false })).not.toContain('mark-unread');
        expect(ids({ status: 'idle', unread: false })).toContain('mark-unread');
    });

    test('an unread row shows exactly one mark read, working and asleep included (issue 2077)', () => {
        plugins.items = [{ id: 'mark-unread', order: 200, label: 'clear unread', shortcut: 'U', locked: false }];
        const ids = (over: Record<string, unknown>): string[] => idsOf({ ...BASE, pluginItems: 'mark-unread', ...over });
        const readCount = (list: string[]): number => list.filter((id) => id === 'mark-read' || id === 'mark-unread').length;
        for (const over of [{ status: 'working', unread: true }, { status: 'working_subagent', unread: true }, { asleep: true, status: 'asleep', unread: true }]) {
            const list = ids(over);
            expect(list.filter((id) => id === 'mark-read'), JSON.stringify(over)).toHaveLength(1);
            expect(readCount(list), JSON.stringify(over)).toBe(1);
        }
    });
});

describe('a dropped MCP server (test_row_menu_mcp_drop)', () => {
    const t = (key: string, p?: Record<string, unknown>): string => (p && p.servers ? `${key}:${String(p.servers)}` : p ? `${key}(${Object.values(p).join('|')})` : key);
    const ROW = { name: 'cloude_x', label: 'x', session_id: 'ses_1', status: 'idle', agent_family: 'claude' };
    const ctxFor = (extra: Record<string, unknown>) => contextFromRow({ ...ROW, ...extra }, {});
    const DROP = { dropped: [{ name: 'carnivore', state: 'dropped', exact: true }, { name: 'docs', state: 'failed' }] };
    beforeEach(() => bench({}, t));

    test('only a measured drop is a drop, and the kebab says which servers', () => {
        expect(ctxFor({ mcp_health: null }).mcpDropped).toBe(false);
        expect(ctxFor({ mcp_health: { dropped: [] } }).mcpDropped).toBe(false);
        expect(ctxFor({}).mcpDropped).toBe(false);
        const dropped = ctxFor({ mcp_health: DROP });
        expect(dropped.mcpDropped).toBe(true);
        expect(dropped.mcpServers).toBe('carnivore, docs');
        const html = triggerHtml(dropped);
        expect(html).toContain('session-row-menu-trigger--mcp');
        expect(html).toContain('data-tooltip="mcp.dropped_tooltip:carnivore, docs"');
        expect(html).toContain('data-row-menu-mcp-dropped="1"');
        expect(triggerHtml(ctxFor({ mcp_health: null }))).not.toContain('--mcp');
        expect(triggerHtml({ ...dropped, agentUpdateReady: true, agentUpdateRunning: '1', agentUpdateInstalled: '2' })).not.toContain('session-row-menu-trigger--mcp');
        expect(contextFromTrigger(triggerFrom('<button data-row-menu="x" data-row-menu-mcp-dropped="1" data-row-menu-mcp-servers="a"></button>'))!.mcpServers).toBe('a');
    });

    test('reconnect leads the menu on a local claude row, refused while busy', () => {
        const dropped = { ...ctxFor({ mcp_health: DROP }), agentFamily: 'claude' };
        const item = (over: Record<string, unknown>) => itemsOf({ ...dropped, ...over }).find((i) => i.id === 'reconnect-mcp');
        expect(item({})?.label).toBe('mcp.reconnect_named:carnivore, docs');
        expect(item({ mcpServers: '' })?.label).toBe('mcp.reconnect');
        expect(idsOf(dropped)[0]).toBe('reconnect-mcp');
        expect(idsOf({ ...dropped, agentUpdateReady: true, restartable: true })[0]).toBe('reconnect-mcp');
        expect(idsOf({ ...dropped, mcpDropped: false })[0]).not.toBe('reconnect-mcp');
        expect(item({ agentFamily: 'codex' })).toBeUndefined();
        expect(item({ mcpDropped: false })).toBeUndefined();
        expect(item({ hostKey: 'peer-1' })).toBeUndefined();
        expect(item({ status: 'idle' })?.enabled).toBe(true);
        expect(item({ status: 'working' })?.enabled).toBe(false);
    });

    test('the item posts the reconnect route', async () => {
        const apiCalls: unknown[] = [];
        bench({ API: { call: async (url: string, opts: unknown) => { apiCalls.push([url, opts]); return {}; } } }, t);
        loadRunTable();
        await win.SessionRowMenuActions.run('reconnect-mcp', { ...ctxFor({ mcp_health: DROP }), sessionId: 'ses_1', agentFamily: 'claude' });
        expect(apiCalls).toEqual([['/sessions/ses_1/mcp/reconnect', { method: 'POST', body: {} }]]);
    });

    test('a measured servers list names only the down ones, each with its reason', () => {
        const SERVERS = { servers: [
            { name: 'docs', transport: 'http', state: 'down', reason: 'gave_up', source: 'client_log', detail: 'ECONNREFUSED' },
            { name: 'files', transport: 'stdio', state: 'down', reason: 'process_gone', source: 'process' },
            { name: 'search', transport: 'http', state: 'unknown', reason: 'auth_required', source: 'probe', detail: '401' },
            { name: 'memory', transport: 'stdio', state: 'connected', reason: 'connected', source: 'client_log' },
        ], dropped: [] };
        const measured = ctxFor({ mcp_health: SERVERS, agent_family: 'codex' });
        expect(measured.mcpDropped).toBe(true);
        expect(measured.mcpServers).toBe('docs, files');
        const html = triggerHtml(measured);
        expect(html).toContain('data-tooltip="mcp.down_tooltip:mcp.server_reason(docs|mcp.reason_detail(mcp.reason.gave_up|ECONNREFUSED)); mcp.server_reason(files|mcp.reason.process_gone)"');
        expect(html).toContain('session-row-menu-trigger--mcp');
        expect(itemsOf({ ...measured, agentFamily: 'codex' }).find((i) => i.id === 'reconnect-mcp')).toBeUndefined();
        expect(ctxFor({ mcp_health: { servers: [SERVERS.servers[2], SERVERS.servers[3]], dropped: [] } }).mcpDropped).toBe(false);
    });
});

describe('schedule this (test_row_menu_schedule_this)', () => {
    const LIVE = ctxOf({ groupable: true, renameable: true, forkable: true, restartable: true, sessionUuid: 'u-1' });

    test('offered on a local row with a uuid, live or asleep, never on a browser, a Layout or a remote row', () => {
        expect(idsOf(LIVE)).toContain('schedule');
        expect(idsOf({ ...LIVE, asleep: true })).toContain('schedule');
        expect(idsOf({ ...LIVE, sessionUuid: '' })).not.toContain('schedule');
        expect(idsOf({ ...LIVE, kind: 'browser' })).not.toContain('schedule');
        expect(idsOf({ ...LIVE, kind: 'layout' })).not.toContain('schedule');
        expect(idsOf({ ...LIVE, hostKey: 'peer-1' })).not.toContain('schedule');
        expect(itemsOf(LIVE).find((i) => i.id === 'schedule')?.label).toBe('automations.schedule_this');
    });

    test('it hands the uuid, never the tmux name, and a missing bridge is quiet', async () => {
        const calls: unknown[] = [];
        bench({ CloudeWeb: { scheduleThis: (arg: unknown) => calls.push(arg) } });
        loadRunTable();
        await win.SessionRowMenuActions.run('schedule', LIVE);
        expect(calls).toEqual([{ kind: 'session', id: 'u-1' }]);
        bench();
        await win.SessionRowMenuActions.run('schedule', LIVE);
    });
});

describe('the kebab round trip (test_session_row_menu_agent_family, test_session_row_menu_copy_session_id)', () => {
    const CONVERSATION = 'c562a11e-9a01-4bac-8cae-bad879006dbd';
    const ROW_KEY = '11111111-2222-4333-8444-555555555555';
    const row = (over: Record<string, unknown> = {}) => ({ name: 'cloude_api', label: 'api', status: 'idle', session_id: 'ses_1', session_uuid: ROW_KEY, ...over });
    const opened = (r: Record<string, unknown>) => contextFromTrigger(triggerFrom(triggerHtml(contextFromRow(r, { surface: 'sidebar', renameable: true }))))!;

    test('the agent family and the conversation id survive the trigger', () => {
        expect(opened(row({ agent_family: 'claude' })).agentFamily).toBe('claude');
        expect(opened(row({ agent_family: 'codex' })).agentFamily).toBe('codex');
        expect(opened(row({ claude_session_uuid: CONVERSATION })).conversationId).toBe(CONVERSATION);
    });

    test('copy session id: offered only with a conversation id; the row lists none of the retired items', () => {
        const copy = (r: Record<string, unknown>) => itemsOf(contextFromRow(r, { surface: 'sidebar', renameable: true })).find((i) => i.id === 'copy-session-id');
        for (const over of [{}, { claude_session_uuid: null }, { claude_session_uuid: '' }]) expect(copy(row(over))).toBeUndefined();
        expect(copy(row({ claude_session_uuid: CONVERSATION }))?.enabled).toBe(true);
        const ids = idsOf(contextFromRow(row({ claude_session_uuid: CONVERSATION, agent_family: 'claude' }), { surface: 'sidebar', renameable: true }));
        for (const gone of ['crosstalk', 'bookmark', 'huddle-session-nudge', 'messaging', 'change-agent-type']) expect(ids).not.toContain(gone);
        expect(ids).toContain('mute');
        expect(ids).toContain('copy-session-id');
    });

    test('copy copies the conversation id, not the row key; a refused clipboard is said out loud', async () => {
        const copied: string[] = [];
        const errors: string[] = [];
        let ok = true;
        bench({
            CopyCompat: { copyText: (text: string) => { copied.push(text); return Promise.resolve({ ok, method: 'async' }); } },
            Launchpad: { showError: (text: string) => errors.push(text) },
        });
        loadRunTable();
        const ctx = contextFromRow(row({ claude_session_uuid: CONVERSATION }), { surface: 'sidebar' });
        expect(await win.SessionRowMenuActions.run('copy-session-id', ctx)).toBe(true);
        expect(copied).toEqual([CONVERSATION]);
        expect(errors).toEqual([]);
        ok = false;
        expect(await win.SessionRowMenuActions.runCopySessionId(ctx)).toBe(false);
        expect(errors).toHaveLength(1);
    });
});

describe('a locked plugin item (test_row_menu_locked)', () => {
    test('is drawn locked, never blocked, and activating it still runs the plugin; an unlocked one is untouched', async () => {
        plugins.items = [
            { id: 'share-read-only', label: 'share read only', order: 260, shortcut: 'S', locked: true, feature: 'share' } as (typeof plugins.items)[number],
            { id: 'mark-unread', label: 'mark unread', order: 200, shortcut: 'U', locked: false },
        ];
        const ctx = ctxOf({ name: 'cloude_x', pluginItems: 'share-read-only,mark-unread' });
        const nodes = nodesOf(ctx);
        const locked = nodes.find((n) => n.id === 'share-read-only')!;
        const plain = nodes.find((n) => n.id === 'mark-unread')!;
        expect(locked.locked).toBe('share');
        expect(locked.blocked, 'a locked item is not disabled').toBeUndefined();
        expect(plain.locked).toBeUndefined();
        await locked.run!();
        expect(vi.mocked(runSessionCardAction).mock.calls.at(-1)?.[0]).toBe('share-read-only');
    });
});

describe('pin is always offered on a session row (#2528)', () => {
    const LIVE = ctxOf({ sessionUuid: 'u-1', sessionId: 's-1' });
    test('offers pin while the inline pin icon is visible, and unpin when pinned', () => {
        const store = { isPinned: (n: string) => n === 'pinned_one' };
        (win as unknown as Record<string, unknown>).SessionSidebarStore = store;
        const labels = (name: string): string[] => itemsOf(ctxOf({ ...LIVE, name })).map((i) => i.label);
        expect(labels('plain_one')).toContain('pin');
        expect(labels('pinned_one')).toContain('unpin');
    });
});
