import { describe, expect, test, vi } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { grantCplug, sheetStamp } from './cplug-grant';
import { createCplugsAdapter, listCplugItems, permissionLabel, setCplugEnabled, toCplugItem, type CplugRow, type CplugSheet } from './cplugs-adapter';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const ASKS = ['sessions.read', 'sessions.message', 'notify', 'agent_writes'];
const OFF: CplugRow = {
    id: 'huddle', name_key: 'cplug.huddle.name', description_key: 'cplug.huddle.description', version: '1.0.0',
    tier: 'builtin', enabled: false, state: 'disabled', permissions: { app: ASKS }, grants: { app: [] }, revision: 3,
};

function server(row: CplugRow) {
    const calls: { path: string; method: string; body: unknown }[] = [];
    let current = row;
    const fetcher = vi.fn(async (path: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET';
        const body = init.body ? JSON.parse(String(init.body)) : null;
        calls.push({ path, method, body });
        if (path === '/cplugs' || path.startsWith('/cplugs?')) return { cplugs: [current] };
        if (method === 'PUT') {
            current = { ...current, enabled: body.enabled, state: body.enabled ? 'active' : 'disabled',
                        grants: body.grants ?? current.grants, revision: (current.revision ?? 0) + 1 };
        }
        return current;
    });
    return { calls, fetcher: fetcher as never };
}

describe('toCplugItem', () => {
    test('names the plugin and every permission it asks in words, never a raw key', () => {
        const item = toCplugItem(OFF, t);
        expect(item.id).toBe('cplug:huddle');
        expect(item.name).toBe('task manager');
        expect(item.marks).toEqual([]);
        expect(item.enabled).toBe(false);
        expect(item.asks).toHaveLength(4);
        for (const word of item.asks) expect(word).not.toContain('plugins.page.permission');
    });

    test('a removed plugin draws no switch', () => {
        expect(toCplugItem({ ...OFF, state: 'removed' }, t).enabled).toBeNull();
        expect(toCplugItem({ ...OFF, state: 'removed' }, t).status).toEqual({ label: 'removed: its data is kept', tone: 'off' });
        expect(toCplugItem({ ...OFF, tier: 'core', enabled: true, state: 'active' }, t).enabled).toBeNull();
    });
});

describe('setCplugEnabled', () => {
    test('on: PUT at the revision just read, granting exactly what it asks, then the enablement re-reads', async () => {
        const { calls, fetcher } = server(OFF);
        const changed = vi.fn(async () => {});
        const item = await setCplugEnabled('cplug:huddle', true, t, fetcher, changed);
        expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(['GET /cplugs/huddle', 'PUT /cplugs/huddle']);
        expect(calls[1]!.body).toEqual({ revision: 3, enabled: true, grants: { app: ASKS } });
        expect(item.enabled).toBe(true);
        expect(changed).toHaveBeenCalledTimes(1);
    });

    test('off: no grants sent, so what was granted is kept', async () => {
        const { calls, fetcher } = server({ ...OFF, enabled: true, state: 'active', grants: { app: ASKS } });
        await setCplugEnabled('cplug:huddle', false, t, fetcher, async () => {});
        expect(calls[1]!.body).toEqual({ revision: 3, enabled: false });
    });
});

describe('createCplugsAdapter', () => {
    test('lists the plugins and sends the switch to the plugin route', async () => {
        const { calls, fetcher } = server(OFF);
        const page = createCplugsAdapter(t, fetcher, async () => {});
        expect((await page.list()).map((i) => i.id)).toEqual(['cplug:huddle']);
        await page.setEnabled!('cplug:huddle', true);
        expect(calls.filter((c) => c.method === 'PUT').map((c) => c.path)).toEqual(['/cplugs/huddle']);
    });
});

describe('a plugin that is not first-party', () => {
    const THIRD: CplugRow = { ...OFF, consent_required: true, risks: { 'sessions.read': 'low', 'sessions.message': 'high', notify: 'low', agent_writes: 'high' } };
    const SHEET = {
        digest: 'd', body_sha: 'b', grants_sha: 'g',
        permissions: ASKS.map((name) => ({ name, risk: THIRD.risks![name], granted: false })),
    };

    function withSheet(row: CplugRow) {
        const base = server(row);
        const fetcher = vi.fn(async (path: string, init: RequestInit = {}) =>
            path.endsWith('/sheet') ? (base.calls.push({ path, method: 'GET', body: null }), SHEET) : (base.fetcher as never as (p: string, i?: RequestInit) => Promise<unknown>)(path, init));
        return { calls: base.calls, fetcher: fetcher as never };
    }

    test('the switch cannot tick for the owner: a high ask refuses it before any write', async () => {
        const { calls, fetcher } = withSheet(THIRD);
        await expect(setCplugEnabled('cplug:huddle', true, t, fetcher, async () => {})).rejects.toThrow(/tick/);
        expect(calls.some((c) => c.method === 'PUT')).toBe(false);
    });

    test('approving changed code of a plugin that asks for nothing sends the consent body with no grants and no ticks (#2541)', async () => {
        const base = server({ ...THIRD, enabled: true, state: 'needs_approval', permissions: { app: [] }, risks: {} });
        const fetcher = vi.fn(async (path: string, init: RequestInit = {}) =>
            path.endsWith('/sheet') ? { digest: 'd2', body_sha: 'b', grants_sha: 'g', permissions: [] } : (base.fetcher as never as (p: string, i?: RequestInit) => Promise<unknown>)(path, init));
        await grantCplug('huddle', [], t, fetcher as never, async () => {});
        const put = base.calls.find((c) => c.method === 'PUT')!;
        expect(put.body).toEqual({ revision: 3, grants: { app: [] }, consent: { digest: 'd2', body_sha: 'b', grants_sha: 'g', ticks: [] } });
    });

    test('granting an off plugin also asks for it to be turned on, with the same consent body (#2572)', async () => {
        const { calls, fetcher } = withSheet(THIRD);
        await grantCplug('huddle', ['sessions.message', 'agent_writes'], t, fetcher, async () => {}, { enable: true });
        const put = calls.find((c) => c.method === 'PUT')!;
        expect(put.body).toEqual({
            revision: 3, enabled: true, grants: { app: ASKS },
            consent: { digest: 'd', body_sha: 'b', grants_sha: 'g', ticks: ['sessions.message', 'agent_writes'] },
        });
    });

    test('a grant echoes the sheet the owner was shown, not a fresh read, and reads none', async () => {
        const { calls, fetcher } = withSheet(THIRD);
        await grantCplug('huddle', ['sessions.message', 'agent_writes'], t, fetcher, async () => {}, { seen: { ...SHEET, digest: 'seen', permissions: [] } });
        expect(calls.some((c) => c.path.endsWith('/sheet'))).toBe(false);
        expect((calls.find((c) => c.method === 'PUT')!.body as { consent: { digest: string } }).consent.digest).toBe('seen');
    });

    test('a 409 requirements_unmet on the grant reads as the page sentence, not a raw error', async () => {
        const { fetcher } = withSheet(THIRD);
        const refusing = vi.fn(async (path: string, init: RequestInit = {}) => {
            if (init.method === 'PUT') throw new ApiError('conflict', 409, null, { detail: { code: 'requirements_unmet', unmet: { core: ['crosstalk'] } } });
            return (fetcher as never as (p: string, i?: RequestInit) => Promise<unknown>)(path, init);
        });
        await expect(grantCplug('huddle', [], t, refusing as never, async () => {})).rejects.toThrow(/needs/);
    });

    test('grant echoes the sheet hashes with the owner ticks and grants only what the plugin asks', async () => {
        const { calls, fetcher } = withSheet(THIRD);
        await grantCplug('huddle', ['sessions.message', 'agent_writes'], t, fetcher, async () => {});
        const put = calls.find((c) => c.method === 'PUT')!;
        expect(put.body).toEqual({
            revision: 3, grants: { app: ASKS },
            consent: { digest: 'd', body_sha: 'b', grants_sha: 'g', ticks: ['sessions.message', 'agent_writes'] },
        });
    });
});

describe('a plugin held by a requirement (#1611)', () => {
    test('an inert row names, in words, every plugin it waits for', () => {
        const row: CplugRow = { ...OFF, id: 'summarize', enabled: true, state: 'inert', blocked_by: ['huddle', 'save'] };
        const item = toCplugItem(row, t);
        expect(t(`plugins.page.state.${item.state}`)).toBe('on, but doing nothing until a plugin it needs is on');
        expect(item.blockedBy).toEqual(['task manager', 'conversation backups']);
        expect(toCplugItem(OFF, t).blockedBy).toEqual([]);
    });
});

describe('an installed third-party plugin (A6, #2122)', () => {
    test('shows the author literal name and description, never a catalog key, and carries the third-party mark', () => {
        const seen: string[] = [];
        const spy: Translate = (key, params) => { seen.push(key); return t(key, params); };
        const row: CplugRow = {
            id: 'clock', runtime: 'sidecar', name: 'Clock <b>', description: 'Tells the time.', publisher: 'acme', tier: 'catalog',
            enabled: true, state: 'active', tools: ['clock_now'], permissions: { app: [] }, grants: { app: [] }, revision: 1,
        };
        const item = toCplugItem(row, spy);
        expect(item.name).toBe('Clock <b>');
        expect(item.brief).toBe('Tells the time.');
        expect(item.thirdParty).toBe(true);
        expect(item.tags).toContain('third-party');
        expect(item.byline).toBe('by acme');
        expect(item.tools).toEqual(['clock_now']);
        expect(seen.some((key) => key.startsWith('cplug.clock'))).toBe(false);
        expect(toCplugItem(OFF, t).thirdParty).toBe(false);
    });
});

describe('unified agent-plugin rows (M3.2)', () => {
    test('listCplugItems fetches /cplugs?include_agent_plugins=true and maps agent-plugin metadata', async () => {
        const agentRow: CplugRow = {
            id: 'agent:demo-plugin',
            item_id: 'demo-plugin',
            install_id: 'inst-agent-1',
            kind: 'agent-plugin',
            tier: 'catalog',
            name: 'Demo Agent Plugin',
            description: 'Installed from GitHub.',
            publisher: 'octocat',
            enabled: null,
            state: 'active',
            trust_tier: 'unverified_github',
            trust_badge: 'Unverified',
            scope: 'project',
            project_path: '/tmp/proj',
            git_source: { url: 'https://github.com/octocat/demo-plugin', repo: 'octocat/demo-plugin', ref: 'main', commit: 'deadbeef' },
            permissions: { app: [] },
            grants: { app: [] },
            revision: 1,
            watchdog: { pid: 4321, restart_count: 0, rss_bytes: 18 * 1024 * 1024, last_call: 'ping', last_event: 'ready' },
            declarative_widget: { id: 'demo-w', title: 'Demo Widget' },
        };
        const { fetcher, calls } = server(agentRow);
        const items = await listCplugItems(t, fetcher as never);
        expect(calls[0]?.path).toBe('/cplugs?include_agent_plugins=true');
        expect(items).toHaveLength(1);
        const item = items[0]!;
        expect(item.id).toBe('cplug:agent:demo-plugin');
        expect(item.name).toBe('Demo Agent Plugin');
        expect(item.pluginKind).toBe('agent-plugin');
        expect(item.enabled).toBeNull();
        expect(item.trustTier).toBe('unverified_github');
        expect(item.trustBadge).toBe('Unverified');
        expect(item.scope).toBe('project');
        expect(item.projectPath).toBe('/tmp/proj');
        expect(item.installId).toBe('inst-agent-1');
        expect(item.gitSource?.repo).toBe('octocat/demo-plugin');
        expect(item.watchdog?.pid).toBe(4321);
        expect(item.declarativeWidget).toEqual({ id: 'demo-w', title: 'Demo Widget' });
    });

    test('toCplugItem forwards runtime_active onto runtimeActive when present', () => {
        expect(toCplugItem({ ...OFF, runtime_active: false }, t).runtimeActive).toBe(false);
        expect(toCplugItem({ ...OFF, runtime_active: true }, t).runtimeActive).toBe(true);
        expect(toCplugItem(OFF, t).runtimeActive).toBeUndefined();
    });
});

describe('M4.1b bus/slot metadata, permissionLabel, and ui_slots consent forwarding', () => {
    test('permissionLabel resolves services: and events: prefixes cleanly via i18n catalog', () => {
        const svc = permissionLabel('services:kv.v1', t);
        const evt = permissionLabel('events:session.started', t);
        expect(svc).toBe('call the kv.v1 plugin service');
        expect(evt).toBe('emit or subscribe to the session.started plugin event');
        expect(svc).not.toContain('plugins.page.permission.');
        expect(evt).not.toContain('plugins.page.permission.');
    });

    test('toCplugItem maps all M4.1b slot, bus, channel, harness, and popout fields', () => {
        const row: CplugRow = {
            ...OFF,
            id: 'bus-plugin',
            runtime: 'sidecar',
            name: 'Bus Plugin',
            tier: 'catalog',
            grants: { app: [], ui_slots: ['terminal.toolbar'] },
            granted_ui_slots: ['terminal.toolbar'],
            services: { provides: [{ name: 'kv.v1', methods: ['get', 'set'] }], consumes: ['auth.v1'] },
            events: { on: ['session.started'], emit: ['bus:updated'], allowed: ['session.started'] },
            ui_slots: ['bus.board'],
            ui_contribute: { 'terminal.toolbar': [{ id: 'btn', label: 'Run', route: 'run' }] },
            commands: [{ id: 'bus.open', title: 'Open Bus', shortcut: 'Cmd+Shift+B' }],
            chords: [{ command: 'bus.open', shortcut: 'Cmd+Shift+B' }],
            session_row_actions: [{ id: 'act', label: 'Inspect', route: 'inspect' }],
            session_badges: [{ text: 'ok', tone: 'accent' }],
            terminal_toolbar: [{ id: 'btn', label: 'Run', route: 'run' }],
            project_panels: [{ id: 'panel', title: 'Bus', route: 'panel' }],
            channels: [{ id: 'ops', kind_id: 'plugin:bus-plugin:ops', label: 'Ops Feed' }],
            harnesses: ['harnesses/agent.toml'],
            popout: true,
        };
        const item = toCplugItem(row, t);
        expect(item.grantedUiSlots).toEqual(['terminal.toolbar']);
        expect(item.uiSlotGrants).toEqual(['terminal.toolbar']);
        expect(item.services).toEqual(row.services);
        expect(item.events).toEqual(row.events);
        expect(item.uiSlots).toEqual(['bus.board']);
        expect(item.uiContribute).toEqual(row.ui_contribute);
        expect(item.commands).toEqual(row.commands);
        expect(item.chords).toEqual(row.chords);
        expect(item.sessionRowActions).toEqual(row.session_row_actions);
        expect(item.sessionBadges).toEqual(row.session_badges);
        expect(item.terminalToolbar).toEqual(row.terminal_toolbar);
        expect(item.projectPanels).toEqual(row.project_panels);
        expect(item.channels).toEqual(row.channels);
        expect(item.harnesses).toEqual(['harnesses/agent.toml']);
        expect(item.popout).toBe(true);
    });

    test('setCplugEnabled blocks un-ticked ui_slots and grantCplug forwards ui_slots, ui_slots_sha, and slot_ticks', async () => {
        const slotRow: CplugRow = {
            ...OFF,
            id: 'slot-plugin',
            consent_required: true,
            permissions: { app: ['sessions.read'] },
            risks: { 'sessions.read': 'low' },
            ui_contribute: { 'terminal.toolbar': [{ id: 't1', label: 'Go', route: 'go' }] },
        };
        const sheet: CplugSheet = {
            digest: 'd1',
            body_sha: 'b1',
            grants_sha: 'g1',
            permissions: [{ name: 'sessions.read', risk: 'low', granted: false }],
            ui_slots: [{ slot: 'terminal.toolbar', count: 1, risk: 'medium', reason: 'add toolbar action', granted: false, needs_tick: true }],
            ui_slots_sha: 'slots-sha-1',
        };
        expect(sheetStamp(sheet)).toBe('d1|b1|g1|slots-sha-1');

        const base = server(slotRow);
        const fetcher = vi.fn(async (path: string, init: RequestInit = {}) =>
            path.endsWith('/sheet')
                ? (base.calls.push({ path, method: 'GET', body: null }), sheet)
                : (base.fetcher as never as (p: string, i?: RequestInit) => Promise<unknown>)(path, init),
        );

        await expect(setCplugEnabled('cplug:slot-plugin', true, t, fetcher as never, async () => {})).rejects.toThrow(/tick/);

        await grantCplug('slot-plugin', [], t, fetcher as never, async () => {}, {
            enable: true,
            seen: sheet,
            slotTicks: ['terminal.toolbar'],
            uiSlots: ['terminal.toolbar'],
        });
        const put = base.calls.find((c) => c.method === 'PUT')!;
        expect(put.body).toEqual({
            revision: 3,
            enabled: true,
            grants: { app: ['sessions.read'], ui_slots: ['terminal.toolbar'] },
            consent: {
                digest: 'd1',
                body_sha: 'b1',
                grants_sha: 'g1',
                ticks: [],
                ui_slots_sha: 'slots-sha-1',
                slot_ticks: ['terminal.toolbar'],
            },
        });
    });
});
