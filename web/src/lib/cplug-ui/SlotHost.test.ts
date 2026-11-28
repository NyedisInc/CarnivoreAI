/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mockNet = vi.hoisted(() => ({
    fetches: [] as string[],
    pushRegistrations: [] as { refresh: () => void; topics: readonly string[]; stopped: number }[],
    nextFetchImpl: null as null | ((path: string) => Promise<unknown>),
}));

vi.mock('../../opscenter/api/auth.svelte', async (original) => {
    const mod = await original<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...mod,
        authFetch: vi.fn(async (path: string) => {
            mockNet.fetches.push(path);
            if (mockNet.nextFetchImpl) return mockNet.nextFetchImpl(path);
            return {};
        }),
    };
});

vi.mock('../resource-push/boot', () => ({
    resourcePush: () => ({
        isLive: () => true,
        onChange: () => () => {},
        pushOrPoll: (refresh: () => void, _ms: number, topics: readonly string[]) => {
            const entry = { refresh, topics, stopped: 0 };
            mockNet.pushRegistrations.push(entry);
            return () => {
                entry.stopped += 1;
            };
        },
    }),
}));

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { ApiError, auth } from '../../opscenter/api/auth.svelte';
import { CPLUGS_TOPIC, CPLUG_SLOTS_TOPIC, pluginsStore, type SlotContribution, type StoreCplugRow } from '../plugins/store.svelte';
import type { Translate } from '../sessions/types';
import SlotHost from './SlotHost.svelte';
import { canonicalSlot, safeSlotHref, sortSlotEntries, validateSlotEntry } from './slots';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const PLUGINS: StoreCplugRow[] = [
    {
        id: 'acme',
        runtime: 'sidecar',
        name: 'Acme Tooling',
        enabled: true,
        state: 'active',
        unverified: false,
        routes: ['run_task', 'danger_op'],
        declared_tools: ['acme_inspect'],
    },
    {
        id: 'devplug',
        runtime: 'sidecar',
        name: 'Dev Sideload',
        enabled: true,
        state: 'active',
        unverified: true,
        routes: ['ping'],
        declared_tools: [],
    },
];

let mounted: Record<string, unknown> | null = null;

beforeEach(() => {
    auth.state = 'signed-out';
    mockNet.fetches = [];
    mockNet.pushRegistrations = [];
    mockNet.nextFetchImpl = null;
    pluginsStore.resetForTest();
});

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    mockNet.fetches = [];
    mockNet.pushRegistrations = [];
    mockNet.nextFetchImpl = null;
    pluginsStore.resetForTest();
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) {
        await tick();
        await Promise.resolve();
    }
    flushSync();
}

describe('slots.ts validation and canonicalization', () => {
    test('canonicalSlot normalizes underscore core aliases to dotted canonical names', () => {
        expect(canonicalSlot('session_row_actions')).toBe('session.row_actions');
        expect(canonicalSlot('session_badges')).toBe('session.badges');
        expect(canonicalSlot('terminal_toolbar')).toBe('terminal.toolbar');
        expect(canonicalSlot('project_panels')).toBe('project.panels');
        expect(canonicalSlot('custom.board')).toBe('custom.board');
    });

    test('safeSlotHref accepts https/http/safe-relative and refuses javascript:, data:, //, and secrets', () => {
        expect(safeSlotHref('/sessions/abc')).toEqual({ href: '/sessions/abc', external: false });
        expect(safeSlotHref('https://example.com/docs')).toEqual({ href: 'https://example.com/docs', external: true });
        expect(safeSlotHref('javascript:alert(1)')).toBeNull();
        expect(safeSlotHref('data:text/html,hi')).toBeNull();
        expect(safeSlotHref('//evil.example/steal')).toBeNull();
        expect(safeSlotHref('relative/no-slash')).toBeNull();
        expect(safeSlotHref('http:evil.com')).toBeNull();
        expect(safeSlotHref('https:/evil.com')).toBeNull();
        expect(safeSlotHref('http:///evil.com')).toBeNull();
        expect(safeSlotHref('https:///evil.com')).toBeNull();
        expect(safeSlotHref('HTTP://example.com/docs')).toEqual({ href: 'HTTP://example.com/docs', external: true });
        const ghToken = ['ghp', 'aB3dE5fG7h'.repeat(4)].join('_');
        expect(safeSlotHref(`https://example.com/?t=${ghToken}`)).toBeNull();
    });

    test('validateSlotEntry refuses undeclared routes/tools, invisible chars, schemes, secret shapes, and bad documents', () => {
        const declared = { routes: ['run_task'], tools: ['acme_inspect'] };
        const base: SlotContribution = {
            plugin_id: 'acme',
            install_key: 'inst-1',
            slot: 'terminal.toolbar',
            declared_slot: 'terminal.toolbar',
            item: {},
        };

        expect(validateSlotEntry({ ...base, item: { id: 'x', label: 'X', route: 'undeclared' } }, declared)).toBeNull();
        expect(validateSlotEntry({ ...base, item: { id: 'x', label: 'X', tool: 'rm_rf' } }, declared)).toBeNull();

        expect(validateSlotEntry({ ...base, item: { id: 'x', label: 'bad\u202elabel', route: 'run_task' } }, declared)).toBeNull();

        expect(validateSlotEntry({ ...base, item: { id: 'x', label: 'javascript:alert(1)', route: 'run_task' } }, declared)).toBeNull();

        const sk = ['sk', 'ant', 'api03', 'aB3dE5fG7h'.repeat(4)].join('-');
        expect(validateSlotEntry({ ...base, item: { id: 'x', label: 'ok', description: sk, route: 'run_task' } }, declared)).toBeNull();

        expect(validateSlotEntry({ ...base, item: { id: 'x', label: 'link', href: '//evil.test' } }, declared)).toBeNull();

        expect(
            validateSlotEntry({ ...base, item: { schema: 2, root: { type: 'iframe', src: 'x' } } }, declared),
        ).toBeNull();

        const ok = validateSlotEntry({ ...base, item: { id: 'x', label: 'Run', route: 'run_task', order: 2 } }, declared);
        expect(ok?.kind).toBe('descriptor');
    });

    test('validateSlotEntry enforces widget grammar and rejects javascript:, data:, http:, and malformed widget ids', () => {
        const base: SlotContribution = {
            plugin_id: 'linear-sync',
            install_key: 'lin12345',
            slot: 'popout',
            declared_slot: 'popout',
            item: {},
        };

        for (const valid of [
            'linear-sync.issues:panel-lin12345',
            'huddle.chat:agent:7',
            'my-plug.panel:panel-12345678',
            'core.tasks',
        ]) {
            expect(validateSlotEntry({ ...base, item: { id: 'w1', label: 'Open', widget: valid } })?.kind).toBe('descriptor');
        }

        for (const bad of [
            'javascript:alert(1)',
            'data:text/html,<script>alert(1)</script>',
            'http://evil.example/x',
            'https://evil.example/x',
            'my-plug.panel',
            'my-plug.panel:../x',
            'my-plug.panel:bad space',
            'core.notes:t',
            'BadCase.panel:panel-1',
            '',
        ]) {
            expect(validateSlotEntry({ ...base, item: { id: 'w1', label: 'Bad', widget: bad } })).toBeNull();
        }
    });

    test('validateSlotEntry rejects hostile values in props, data, when, and popout', () => {
        const declared = { routes: ['run_task'], tools: ['acme_inspect'] };
        const sk = ['sk', 'ant', 'api03', 'aB3dE5fG7h'.repeat(4)].join('-');
        const entry = (item: Record<string, unknown>): SlotContribution => ({
            plugin_id: 'acme',
            install_key: 'inst-1',
            slot: 'terminal.toolbar',
            declared_slot: 'terminal.toolbar',
            item,
        });

        expect(validateSlotEntry(entry({ id: 'p1', label: 'Safe', route: 'run_task', props: { xss: 'javascript:alert(1)' } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'p2', label: 'Safe', route: 'run_task', props: { leak: sk } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'p3', label: 'Safe', route: 'run_task', props: { bidi: 'a\u202eb' } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'p4', label: 'Safe', route: 'run_task', props: { 'https://evil.com': 1 } }), declared)).toBeNull();
        expect(
            validateSlotEntry(
                entry({ id: 'p5', label: 'Safe', route: 'run_task', props: { a: { b: { c: { d: { e: { f: { g: { h: 1 } } } } } } } } }),
                declared,
            ),
        ).toBeNull();

        expect(validateSlotEntry(entry({ id: 'w1', label: 'Safe', route: 'run_task', when: { url: 'https://evil.com/exfil' } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'w2', label: 'Safe', route: 'run_task', when: { secret: sk } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'w3', label: 'Safe', route: 'run_task', when: 'a\u200bb' }), declared)).toBeNull();

        expect(validateSlotEntry(entry({ id: 'o1', label: 'Safe', route: 'run_task', popout: { title: 'x\u200by' } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'o2', label: 'Safe', route: 'run_task', popout: { url: 'https://evil.com' } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'o3', label: 'Safe', route: 'run_task', popout: { token: sk } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'o4', label: 'Safe', route: 'run_task', popout: true }), declared)?.kind).toBe('descriptor');
        expect(validateSlotEntry(entry({ id: 'o5', label: 'Safe', route: 'run_task', popout: { width: 480, height: 320 } }), declared)?.kind).toBe('descriptor');

        expect(validateSlotEntry(entry({ id: 'd1', label: 'Safe', route: 'run_task', data: { token: sk } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'd2', label: 'Safe', route: 'run_task', data: { bidi: 'a\u202eb' } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'd3', label: 'Safe', route: 'run_task', data: { url: 'https://evil.com/exfil' } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'd4', label: 'Safe', route: 'run_task', data: { xss: 'javascript:alert(1)' } }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'd5', label: 'Safe', route: 'run_task', data: { source: 'plugin:acme:v1', count: 3 } }), declared)?.kind).toBe('descriptor');
    });

    test('validateSlotEntry validates all present action/href/document/payload keys without early return', () => {
        const declared = { routes: ['run_task'], tools: ['acme_inspect'], macros: ['ok_macro'] };
        const entry = (item: Record<string, unknown>): SlotContribution => ({
            plugin_id: 'acme',
            install_key: 'inst-1',
            slot: 'terminal.toolbar',
            declared_slot: 'terminal.toolbar',
            item,
        });

        expect(validateSlotEntry(entry({ id: 'm1', label: 'Safe', route: 'run_task', href: 'javascript:alert(1)' }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'm2', label: 'Safe', route: 'run_task', tool: 'undeclared_tool' }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'm3', label: 'Safe', route: 'run_task', macro: 'undeclared_macro' }), declared)).toBeNull();
        expect(validateSlotEntry(entry({ id: 'm4', label: 'Safe', action: 'run_task', href: 'javascript:alert(1)' }), declared)).toBeNull();
        expect(
            validateSlotEntry(entry({ id: 'm5', label: 'Safe', action: { call: 'route', route: 'run_task', extra: 'evil' } }), declared),
        ).toBeNull();
        expect(
            validateSlotEntry(
                entry({
                    id: 'm6',
                    label: 'Safe',
                    document: { schema: 2, root: { type: 'text', value: 'hi' } },
                    href: 'javascript:alert(1)',
                }),
                declared,
            ),
        ).toBeNull();
        expect(
            validateSlotEntry(
                entry({
                    id: 'm7',
                    label: 'Safe',
                    document: { schema: 2, root: { type: 'text', value: 'hi' } },
                    tool: 'undeclared_tool',
                }),
                declared,
            ),
        ).toBeNull();
        expect(
            validateSlotEntry(
                entry({
                    id: 'm8',
                    label: 'Safe',
                    document: { schema: 2, root: { type: 'text', value: 'hi' } },
                    payload: { url: 'https://evil.com/exfil' },
                }),
                declared,
            ),
        ).toBeNull();

        const combined = validateSlotEntry(
            entry({ id: 'ok-combo', label: 'Run', route: 'run_task', href: 'https://docs.example.com/run' }),
            declared,
        );
        expect(combined?.kind).toBe('descriptor');
        if (combined?.kind === 'descriptor') {
            expect(combined.action).toEqual({ kind: 'route', route: 'run_task' });
        }
    });

    test('sortSlotEntries orders by order/priority ascending then plugin_id and id', () => {
        const declared = { routes: ['run_task'], tools: [] };
        const mk = (id: string, pluginId: string, order?: number, priority?: number) =>
            validateSlotEntry(
                {
                    plugin_id: pluginId,
                    install_key: 'k',
                    slot: 'terminal.toolbar',
                    declared_slot: 'terminal.toolbar',
                    item: {
                        id,
                        label: id,
                        route: 'run_task',
                        ...(order !== undefined ? { order } : {}),
                        ...(priority !== undefined ? { priority } : {}),
                    },
                },
                declared,
            )!;
        const sorted = sortSlotEntries([mk('b', 'z', 20), mk('a', 'b', 5), mk('c', 'a', undefined, 5)]);
        expect(sorted.map((s) => s.id)).toEqual(['c', 'a', 'b']);
    });
});

describe('SlotHost.svelte rendering, isolation, confirm, and errors', () => {
    test('renders direct declarative document and descriptor+document via Renderer with HostFrame mark outside .cu-box', async () => {
        const items: SlotContribution[] = [
            {
                plugin_id: 'acme',
                install_key: 'k1',
                slot: 'project.panels',
                declared_slot: 'project.panels',
                item: { schema: 2, root: { type: 'text', value: 'Direct Doc' } },
            },
            {
                plugin_id: 'devplug',
                install_key: 'k2',
                slot: 'project.panels',
                declared_slot: 'project.panels',
                item: {
                    id: 'embedded-doc',
                    title: 'Embedded',
                    order: 10,
                    document: { schema: 2, root: { type: 'text', value: 'Wrapped Doc' } },
                },
            },
        ];

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(SlotHost, {
            target,
            props: { slot: 'project_panels', items, plugins: PLUGINS, t },
        });
        await settle();

        expect(target.querySelector('[data-cu-slot="project.panels"]')).not.toBeNull();
        const frames = Array.from(target.querySelectorAll('[data-cplug-frame]'));
        expect(frames).toHaveLength(2);
        for (const frame of frames) {
            const box = frame.querySelector('[data-cplug-box]')!;
            const mark = frame.querySelector('[data-cplug-mark]')!;
            expect(box).not.toBeNull();
            expect(mark).not.toBeNull();
            expect(box.contains(mark)).toBe(false);
        }
        expect(target.textContent).toContain('Direct Doc');
        expect(target.textContent).toContain('Wrapped Doc');
    });

    test('executes route, tool, macro, inline confirm, safe href, and handles cplug_not_running / failure copy', async () => {
        const run = vi
            .fn()
            .mockResolvedValueOnce({ ok: true })
            .mockRejectedValueOnce(new ApiError('offline', 409, 'cplug_not_running'));
        const onAction = vi.fn();

        const items: SlotContribution[] = [
            {
                plugin_id: 'acme',
                install_key: 'k1',
                slot: 'terminal.toolbar',
                declared_slot: 'terminal.toolbar',
                item: { id: 'run-btn', label: 'Run Task', route: 'run_task', order: 1 },
            },
            {
                plugin_id: 'acme',
                install_key: 'k1',
                slot: 'terminal.toolbar',
                declared_slot: 'terminal.toolbar',
                item: {
                    id: 'danger-btn',
                    label: 'Wipe Cache',
                    route: 'danger_op',
                    tone: 'danger',
                    confirm: 'confirm cache wipe?',
                    order: 2,
                },
            },
            {
                plugin_id: 'acme',
                install_key: 'k1',
                slot: 'terminal.toolbar',
                declared_slot: 'terminal.toolbar',
                item: { id: 'docs-link', label: 'Docs', href: '/docs/acme', order: 3 },
            },
            {
                plugin_id: 'acme',
                install_key: 'k1',
                slot: 'terminal.toolbar',
                declared_slot: 'terminal.toolbar',
                item: { id: 'bad-js', label: 'Evil', href: 'javascript:alert(1)', order: 4 },
            },
        ];

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(SlotHost, {
            target,
            props: { slot: 'terminal.toolbar', items, plugins: PLUGINS, sessionRef: 'sess-1', layout: 'row', compact: true, t, run, onAction },
        });
        await settle();

        expect(target.querySelector('[data-cu-slot-item="bad-js"]')).toBeNull();

        const link = target.querySelector<HTMLAnchorElement>('[data-cu-slot-link="docs-link"]')!;
        expect(link.getAttribute('href')).toBe('/docs/acme');

        target.querySelector<HTMLButtonElement>('[data-cu-slot-action="run-btn"]')!.click();
        await settle();
        expect(run).toHaveBeenCalledTimes(1);
        expect(run.mock.calls[0]![1]).toEqual({ kind: 'route', route: 'run_task' });
        expect(onAction).toHaveBeenCalledTimes(1);

        target.querySelector<HTMLButtonElement>('[data-cu-slot-action="danger-btn"]')!.click();
        await settle();
        expect(target.querySelector('[data-cu-slot-confirm-text]')?.textContent).toBe('confirm cache wipe?');
        expect(run).toHaveBeenCalledTimes(1);

        target.querySelector<HTMLButtonElement>('[data-cu-slot-confirm-yes]')!.click();
        await settle();
        expect(run).toHaveBeenCalledTimes(2);
        expect(target.querySelector('[data-cu-slot-error]')?.textContent).toBe('this plugin is not running');
    });

    test('subscribes reactively to pluginsStore slots when items prop is omitted', async () => {
        pluginsStore.rows = PLUGINS;
        pluginsStore.read = true;
        pluginsStore.slots = {
            'terminal.toolbar': [
                {
                    plugin_id: 'acme',
                    install_key: 'k1',
                    slot: 'terminal.toolbar',
                    declared_slot: 'terminal.toolbar',
                    item: { id: 'tool-1', label: 'Inspect', tool: 'acme_inspect' },
                },
            ],
        };
        pluginsStore.slotsRead = true;

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(SlotHost, {
            target,
            props: { slot: 'terminal_toolbar', t },
        });
        await settle();

        expect(target.querySelector('[data-cu-slot-action="tool-1"]')?.textContent?.trim()).toBe('Inspect');

        pluginsStore.slots = {};
        await settle();
        expect(target.querySelector('[data-cu-slot-action="tool-1"]')).toBeNull();
    });

    test('signed-in mount with pluginsStore.read=false fetches once without re-acquire churn and retains cplugs push', async () => {
        auth.state = 'signed-in';
        let serverRows: StoreCplugRow[] = [PLUGINS[0]!];
        let serverSlots: Record<string, SlotContribution[]> = {
            'terminal.toolbar': [
                {
                    plugin_id: 'acme',
                    install_key: 'k1',
                    slot: 'terminal.toolbar',
                    declared_slot: 'terminal.toolbar',
                    item: { id: 'run-1', label: 'Run Task', route: 'run_task' },
                },
            ],
        };
        mockNet.nextFetchImpl = async (path) => {
            if (path === '/cplugs') return { cplugs: serverRows };
            if (path === '/cplugs/slots') return { slots: serverSlots, owners: {} };
            return {};
        };

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(SlotHost, {
            target,
            props: { slot: 'terminal.toolbar', t },
        });
        await vi.waitFor(() => expect(pluginsStore.read).toBe(true));
        await vi.waitFor(() => expect(pluginsStore.slotsRead).toBe(true));
        await settle();

        expect(target.querySelector('[data-cu-slot-action="run-1"]')?.textContent?.trim()).toBe('Run Task');
        expect(mockNet.fetches.filter((p) => p === '/cplugs')).toHaveLength(1);
        expect(mockNet.fetches.filter((p) => p === '/cplugs/slots')).toHaveLength(1);
        expect(mockNet.pushRegistrations).toHaveLength(2);
        const cplugsPush = mockNet.pushRegistrations.find((r) => r.topics.includes(CPLUGS_TOPIC))!;
        const slotsPush = mockNet.pushRegistrations.find((r) => r.topics.includes(CPLUG_SLOTS_TOPIC))!;
        expect(cplugsPush.stopped).toBe(0);
        expect(slotsPush.stopped).toBe(0);

        serverRows = [
            ...serverRows,
            {
                id: 'beta',
                runtime: 'sidecar',
                name: 'Beta Plugin',
                enabled: true,
                state: 'active',
                unverified: false,
                routes: ['beta_act'],
                declared_tools: [],
            },
        ];
        serverSlots = {
            ...serverSlots,
            'terminal.toolbar': [
                ...serverSlots['terminal.toolbar']!,
                {
                    plugin_id: 'beta',
                    install_key: 'k2',
                    slot: 'terminal.toolbar',
                    declared_slot: 'terminal.toolbar',
                    item: { id: 'beta-btn', label: 'Beta Action', route: 'beta_act' },
                },
            ],
        };
        cplugsPush.refresh();
        await settle();

        expect(target.querySelector('[data-cu-slot-action="beta-btn"]')?.textContent?.trim()).toBe('Beta Action');
        expect(cplugsPush.stopped).toBe(0);
        expect(slotsPush.stopped).toBe(0);

        unmount(mounted);
        mounted = null;
        expect(cplugsPush.stopped).toBe(1);
        expect(slotsPush.stopped).toBe(1);
    });

    test('renders custom plugin-owned slot via pluginsStore.acquire({ includeSlots: true }) and clears when owner pauses/disables', async () => {
        auth.state = 'signed-in';
        let serverRows: StoreCplugRow[] = [
            {
                id: 'provcomp',
                runtime: 'sidecar',
                name: 'Provider Comp',
                enabled: true,
                state: 'active',
                unverified: false,
                routes: [],
                declared_tools: [],
                ui_slots: ['provcomp.board'],
            },
            {
                id: 'conscomp',
                runtime: 'sidecar',
                name: 'Consumer Comp',
                enabled: true,
                state: 'active',
                unverified: false,
                routes: ['compose'],
                declared_tools: [],
            },
        ];
        let serverSlots: Record<string, SlotContribution[]> = {
            'provcomp.board': [
                {
                    plugin_id: 'conscomp',
                    install_key: 'k-cons',
                    slot: 'provcomp.board',
                    declared_slot: 'provcomp.board',
                    item: { id: 'board-act', label: 'Compose 42', route: 'compose' },
                },
            ],
        };
        let serverOwners: Record<string, string> = { 'provcomp.board': 'provcomp' };
        mockNet.nextFetchImpl = async (path) => {
            if (path === '/cplugs') return { cplugs: serverRows };
            if (path === '/cplugs/slots') return { slots: serverSlots, owners: serverOwners };
            return {};
        };

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(SlotHost, {
            target,
            props: { slot: 'provcomp.board', empty: 'No board items', t },
        });
        await vi.waitFor(() => expect(pluginsStore.read).toBe(true));
        await vi.waitFor(() => expect(pluginsStore.slotsRead).toBe(true));
        await settle();

        expect(target.querySelector('[data-cu-slot="provcomp.board"]')).not.toBeNull();
        expect(target.querySelector('[data-cu-slot-action="board-act"]')?.textContent?.trim()).toBe('Compose 42');
        expect(target.querySelector('[data-cu-slot-plugin="conscomp"]')?.textContent?.trim()).toBe('Consumer Comp');
        expect(pluginsStore.slotOwners['provcomp.board']).toBe('provcomp');

        serverRows = [{ ...serverRows[0]!, enabled: false, state: 'disabled' }, serverRows[1]!];
        serverSlots = {};
        serverOwners = {};
        const slotsPush = mockNet.pushRegistrations.find((r) => r.topics.includes(CPLUG_SLOTS_TOPIC))!;
        slotsPush.refresh();
        await settle();

        expect(target.querySelector('[data-cu-slot-action="board-act"]')).toBeNull();
        expect(target.querySelector('[data-cu-slot-empty]')?.textContent).toBe('No board items');
        expect(pluginsStore.slotOwners).toEqual({});
    });
});
