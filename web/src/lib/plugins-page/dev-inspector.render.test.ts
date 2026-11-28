/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { auth } from '../../opscenter/api/auth.svelte';
import { panels } from '../cplug-ui/panel-views.svelte';
import { pluginsStore, type PluginInspectorSnapshot } from '../plugins/store.svelte';
import type { ManagerAdapter } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import DevInspectorDrawer from './DevInspectorDrawer.svelte';
import PluginsScreen from './PluginsScreen.svelte';
import { toCplugItem, type CplugItem, type CplugRow } from './cplugs-adapter';
import { DEFAULT_MEMORY_LIMIT_BYTES } from './plugin-health-pill';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const en = createI18n({ locale: 'en' }) as { t: Translate };
const TEST_STRINGS: Record<string, string> = {
    'plugins.page.inspector.kicker': 'dev inspector',
    'plugins.page.inspector.label': 'plugin dev inspector for {name}',
    'plugins.page.inspector.close': 'close dev inspector',
    'plugins.page.inspector.tabs': 'inspector sections',
    'plugins.page.inspector.tab.trace': 'rpc trace',
    'plugins.page.inspector.tab.capabilities': 'capabilities',
    'plugins.page.inspector.tab.watchdog': 'watchdog',
    'plugins.page.inspector.tab.surfaces': 'surfaces',
    'plugins.page.inspector.tab.logs': 'logs',
    'plugins.page.inspector.not_measured': 'not measured',
    'plugins.page.inspector.none': 'none',
    'plugins.page.inspector.trace.heading': 'rpc and cli socket trace',
    'plugins.page.inspector.trace.source_rpc': 'rpc',
    'plugins.page.inspector.trace.source_cli': 'cli sock',
    'plugins.page.inspector.trace.ok': 'ok',
    'plugins.page.inspector.trace.err': 'err',
    'plugins.page.inspector.capabilities.heading': 'capability checks',
    'plugins.page.inspector.capabilities.allowed': 'allowed',
    'plugins.page.inspector.capabilities.denied': 'denied',
    'plugins.page.inspector.capabilities.caller': 'caller {caller}',
    'plugins.page.inspector.watchdog.heading': 'resource watchdog',
    'plugins.page.inspector.watchdog.controls': 'runtime controls',
    'plugins.page.inspector.watchdog.rss_value': '{used} / {cap}',
    'plugins.page.inspector.watchdog.cpu_value': '{pct}%',
    'plugins.page.inspector.watchdog.cpu_seconds': '{pct}% ({seconds}s)',
    'plugins.page.inspector.watchdog.strikes_value': '{count} / {max}',
    'plugins.page.inspector.watchdog.crash_loop': 'crash-loop paused',
    'plugins.page.inspector.watchdog.crash_loop_note': 'stopped after 3 watchdog strikes. restart to clear strikes and resume.',
    'plugins.page.inspector.watchdog.restart': 'restart',
    'plugins.page.inspector.watchdog.pause': 'pause',
    'plugins.page.inspector.watchdog.resume': 'resume',
    'plugins.page.inspector.surfaces.declarative': 'declarative',
    'plugins.page.inspector.surfaces.iframe': 'iframe',
    'plugins.page.inspector.surfaces.flag.widget': 'widget',
    'plugins.page.inspector.surfaces.flag.panel': 'panel',
    'plugins.page.inspector.surfaces.flag.bar': 'bar',
    'plugins.page.inspector.surfaces.flag.settings': 'settings',
    'plugins.page.inspector.dev_lease.active': 'lease active',
    'plugins.page.inspector.dev_lease.reload_ms': '{total} ms (stage {stage}, stop {stop}, start {start})',
    'plugins.page.inspector.dev_lease.widened': 'permissions widened: re-consent required before reload resumes',
    'plugins.page.inspector.dev_lease.widened_list': 'new permissions: {names}',
};

const t: Translate = (key, params) => {
    const raw = TEST_STRINGS[key];
    if (!raw) return en.t(key, params);
    return raw.replace(/\{(\w+)\}/g, (_, k) => String(params?.[k] ?? ''));
};

let mounted: Record<string, unknown> | null = null;
const origAuthState = auth.state;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    panels.list = [];
    auth.state = origAuthState;
    pluginsStore.resetForTest();
    vi.restoreAllMocks();
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) {
        await tick();
        await Promise.resolve();
    }
    flushSync();
}

function sidecarItem(overrides: Partial<CplugRow> = {}): CplugItem {
    return toCplugItem(
        {
            id: 'local-probe',
            name: 'Local Probe',
            description: 'Dev sidecar',
            version: '0.2.0',
            runtime: 'sidecar',
            tier: 'local',
            kind: 'cplug',
            trust_tier: 'local_dev',
            trust_badge: 'Local Dev',
            unverified: true,
            enabled: true,
            state: 'active',
            runtime_paused: false,
            ...overrides,
        },
        t,
    );
}

function builtinItem(): CplugItem {
    return toCplugItem(
        {
            id: 'huddle',
            name_key: 'cplug.huddle.name',
            version: '1.0.0',
            tier: 'builtin',
            enabled: true,
            state: 'active',
            permissions: { app: [] },
        },
        t,
    );
}

function richSnapshot(overrides: Partial<PluginInspectorSnapshot> = {}): PluginInspectorSnapshot {
    return {
        cplug_id: 'local-probe',
        plugin_id: 'local-probe',
        install_key: 'inst-local-1',
        kind: 'cplug',
        trust_tier: 'local_dev',
        trust_badge: 'Local Dev',
        unverified: true,
        state: 'running',
        paused: false,
        watchdog: {
            pid: 4242,
            memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES,
            rss_bytes: 36 * 1024 * 1024,
            cpu_percent: 3.4,
            cpu_seconds: 8.1,
            disk_bytes: 2 * 1024 * 1024,
            disk_quota_bytes: 50 * 1024 * 1024,
            disk_files: 18,
            disk_quota_files: 5000,
            restart_count: 1,
            strikes: 1,
            crash_loop_paused: false,
            uptime_seconds: 125,
        },
        surfaces: {
            widget: true,
            panel: true,
            bar: false,
            settings: true,
            views: ['main'],
            tools: ['probe__scan'],
            routes: ['/health'],
            timers: ['poll'],
            absent_surfaces: ['feed'],
        },
        dev_lease: {
            active: true,
            source_realpath: '/Users/dev/local-probe',
            baseline_sha: 'deadbeef1234',
            ttl_remaining_seconds: 180,
        },
        secrets_status: {
            API_TOKEN: { present: true, needs_reentry: false },
        },
        rpc_trace: [
            {
                ts: 1700000001,
                source: 'rpc',
                method: 'sessions.list',
                target: 'active',
                latency_ms: 4.5,
                ok: true,
            },
            {
                ts: 1700000002,
                source: 'cli_sock',
                method: 'http.fetch',
                target: 'https://api.example.com',
                latency_ms: 19.2,
                ok: false,
                error_code: 'host_denied',
                error_message: 'domain not allowed',
            },
        ],
        capability_checks: [
            { ts: 1700000001, permission: 'sessions.read', allowed: true, caller: 'rpc' },
            {
                ts: 1700000002,
                permission: 'network.http',
                allowed: false,
                reason: 'not_granted',
                caller: 'cli_sock',
            },
        ],
        logs_tail: [
            { source: 'stderr', line: 'listening on sock' },
            {
                seq: 1,
                ts: 1700000003,
                source: 'reloaded',
                payload: {
                    unchanged: false,
                    needs_approval: false,
                    changed: ['plugin.py'],
                    timings: { total_ms: 98, stage_ms: 30, stop_ms: 18, start_ms: 50 },
                },
            },
            {
                seq: 2,
                ts: 1700000004,
                source: 'ui_error',
                payload: { code: 'bad_node', path: 'widget.toml', detail: 'unknown kind' },
            },
        ],
        ...overrides,
    };
}

describe('DevInspectorDrawer', () => {
    test('renders inside float Sheet and displays trace, capabilities, watchdog, merged surfaces, and dev-lease logs', async () => {
        const plugin = sidecarItem();
        panels.list = [
            {
                kind: 'local-probe.main',
                key: 'local-probe:inst-local-1:main',
                plugin,
                view: 'main',
                title: 'Probe Widget',
                tail: 'panel-1',
                fits: { sizes: ['medium'], min: { w: 2, h: 2 }, anySize: true },
                declarative: true,
            },
        ];

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(DevInspectorDrawer, {
            target,
            props: {
                open: true,
                cplugId: 'local-probe',
                plugin,
                snapshot: richSnapshot(),
                onClose: vi.fn(),
                t,
            },
        });
        await settle();

        const sheet = target.querySelector<HTMLElement>('[data-dev-inspector="local-probe"]');
        expect(sheet).not.toBeNull();
        expect(sheet!.getAttribute('data-sheet-place')).toBe('float');
        expect(sheet!.style.getPropertyValue('--sheet-w')).toBe('var(--oc-sheet-w-wide)');
        expect(sheet!.querySelector('[data-inspector-lease-badge]')).not.toBeNull();

        const traceRows = sheet!.querySelectorAll('[data-inspector-trace-row]');
        expect(traceRows).toHaveLength(2);
        expect(traceRows[0]!.querySelector('[data-trace-source]')?.textContent?.trim()).toBe('rpc');
        expect(traceRows[1]!.querySelector('[data-trace-source]')?.textContent?.trim()).toBe('cli sock');
        expect(traceRows[1]!.querySelector('[data-trace-error]')?.textContent).toContain('host_denied');

        sheet!.querySelector<HTMLButtonElement>('[data-tab="capabilities"]')!.click();
        await settle();
        const capRows = sheet!.querySelectorAll('[data-inspector-capability-row]');
        expect(capRows).toHaveLength(2);
        expect(capRows[0]!.getAttribute('data-cap-allowed')).toBe('true');
        expect(capRows[1]!.getAttribute('data-cap-allowed')).toBe('false');
        expect(capRows[1]!.querySelector('[data-cap-detail]')?.textContent).toContain('not_granted');

        sheet!.querySelector<HTMLButtonElement>('[data-tab="watchdog"]')!.click();
        await settle();
        expect(sheet!.querySelector('[data-inspector-rss]')?.textContent).toContain('36 MiB / 128 MiB');
        expect(sheet!.querySelector('[data-inspector-cpu]')?.textContent).toContain('3.4%');
        expect(sheet!.querySelector('[data-inspector-disk-bytes]')?.textContent).toContain('2 MiB / 50 MiB');
        expect(sheet!.querySelector('[data-inspector-disk-files]')?.textContent).toContain('18 / 5000');
        expect(sheet!.querySelector('[data-inspector-strikes]')?.textContent).toBe('1 / 3');
        expect(sheet!.querySelector('[data-inspector-pid]')?.textContent?.trim()).toBe('4242');

        sheet!.querySelector<HTMLButtonElement>('[data-tab="surfaces"]')!.click();
        await settle();
        expect(sheet!.querySelector('[data-live-panel="local-probe.main"]')).not.toBeNull();
        expect(sheet!.querySelector('[data-inspector-tools]')?.textContent).toContain('probe__scan');
        expect(sheet!.querySelector('[data-inspector-routes]')?.textContent).toContain('/health');
        expect(sheet!.querySelector('[data-inspector-timers]')?.textContent).toContain('poll');
        expect(sheet!.querySelector('[data-inspector-absent-surfaces]')?.textContent).toContain('feed');
        expect(sheet!.querySelector('[data-inspector-secret="API_TOKEN"]')).not.toBeNull();

        sheet!.querySelector<HTMLButtonElement>('[data-tab="logs"]')!.click();
        await settle();
        expect(sheet!.querySelector('[data-inspector-lease-source]')?.textContent?.trim()).toBe('/Users/dev/local-probe');
        expect(sheet!.querySelector('[data-inspector-lease-sha]')?.textContent?.trim()).toBe('deadbeef1234');
        expect(sheet!.querySelector('[data-inspector-last-reload]')?.textContent).toContain('98 ms');
        expect(sheet!.querySelectorAll('[data-inspector-log-row]')).toHaveLength(3);
    });

    test('shows widening re-consent and crash-loop banners and wires sidecar Pause/Resume/Restart controls', async () => {
        const onRestart = vi.fn(async () => ({ ok: true }));
        const onPauseToggle = vi.fn(async () => ({ ok: true }));
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(DevInspectorDrawer, {
            target,
            props: {
                open: true,
                cplugId: 'local-probe',
                plugin: sidecarItem({ state: 'needs_approval', runtime_paused: true }),
                snapshot: richSnapshot({
                    state: 'crash_loop',
                    paused: true,
                    watchdog: { strikes: 3, crash_loop_paused: true, restart_count: 4 },
                    logs_tail: [
                        {
                            seq: 9,
                            ts: 1700000050,
                            source: 'permission_widened',
                            payload: { reason: 'permissions widened', widened: ['shell.exec'] },
                        },
                    ],
                }),
                onClose: vi.fn(),
                onRestart,
                onPauseToggle,
                t,
            },
        });
        await settle();

        expect(target.querySelector('[data-inspector-widening-banner]')?.textContent).toContain('shell.exec');
        expect(target.querySelector('[data-inspector-crash-loop-banner]')?.textContent).toContain('crash-loop paused');

        const pauseBtn = target.querySelector<HTMLButtonElement>('[data-inspector-pause]')!;
        expect(pauseBtn.textContent?.trim()).toBe('resume');
        pauseBtn.click();
        await settle();
        expect(onPauseToggle).toHaveBeenCalledWith('local-probe', false);

        target.querySelector<HTMLButtonElement>('[data-inspector-restart]')!.click();
        await settle();
        expect(onRestart).toHaveBeenCalledWith('local-probe');
    });

    test('hides Pause/Restart controls for built-in plugins', async () => {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(DevInspectorDrawer, {
            target,
            props: {
                open: true,
                cplugId: 'huddle',
                plugin: builtinItem(),
                snapshot: richSnapshot({ cplug_id: 'huddle', kind: 'plugin', trust_tier: 'builtin' }),
                onClose: vi.fn(),
                t,
            },
        });
        await settle();

        expect(target.querySelector('[data-inspector-controls]')).toBeNull();
    });

    test('acquires and releases pluginsStore.acquireInspector when store-backed', async () => {
        const releaseSpy = vi.fn();
        const acquireSpy = vi.spyOn(pluginsStore, 'acquireInspector').mockReturnValue(releaseSpy);
        pluginsStore.inspectors = {
            'local-probe': richSnapshot(),
        };

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(DevInspectorDrawer, {
            target,
            props: {
                open: true,
                cplugId: 'local-probe',
                plugin: sidecarItem({ install_id: 'inst-local-1' }),
                onClose: vi.fn(),
                t,
            },
        });
        await settle();

        expect(acquireSpy).toHaveBeenCalledWith('local-probe', null);
        expect(target.querySelector('[data-inspector-trace-row]')).not.toBeNull();

        unmount(mounted);
        mounted = null;
        expect(releaseSpy).toHaveBeenCalledTimes(1);
    });

    test('Escape closes only DevInspectorDrawer without closing PluginsScreen', async () => {
        const pausedRow: CplugRow = {
            id: 'paused-probe',
            name: 'Paused Probe',
            description: 'Paused sidecar',
            version: '0.1.0',
            runtime: 'sidecar',
            tier: 'local',
            enabled: false,
            state: 'paused',
            runtime_paused: true,
            unverified: true,
            permissions: { app: [] },
            grants: { app: [] },
            needs: [],
        };
        const adapter: ManagerAdapter = {
            list: async () => [toCplugItem(pausedRow, t)],
            setEnabled: async () => toCplugItem(pausedRow, t),
        };

        const target = document.createElement('div');
        document.body.append(target);
        const screen = mount(PluginsScreen, {
            target,
            props: { embedded: false, scope: 'plugins', adapter, catalog: null, t, loadActivity: async () => [] },
        }) as unknown as { show: () => void; isOpen: () => boolean };
        mounted = screen as unknown as Record<string, unknown>;
        screen.show();
        await settle();

        target.querySelector<HTMLButtonElement>('[data-pill-logs]')!.click();
        await settle();
        expect(target.querySelector('[data-dev-inspector="paused-probe"]')).not.toBeNull();

        const escEvent = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
        window.dispatchEvent(escEvent);
        await settle();

        expect(escEvent.defaultPrevented).toBe(true);
        expect(target.querySelector('[data-dev-inspector="paused-probe"]')).toBeNull();
        expect(screen.isOpen()).toBe(true);
    });
});
