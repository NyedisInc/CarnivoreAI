import { describe, expect, test } from 'vitest';

import type { PanelEntry } from '../cplug-ui/panel-views.svelte';
import type { PluginInspectorSnapshot } from '../plugins/store.svelte';
import type { Translate } from '../sessions/types';
import type { CplugItem } from './cplugs-adapter';
import {
    CRASH_LOOP_STRIKES_MAX,
    DEFAULT_DISK_QUOTA_BYTES,
    DEFAULT_DISK_QUOTA_FILES,
    capabilityCheckKey,
    categorizeLogs,
    deriveDevLeaseSummary,
    formatBytes,
    formatCpuUsage,
    formatDiskUsage,
    formatDuration,
    formatLatency,
    formatRssUsage,
    formatStrikes,
    formatTimestamp,
    inspectorStatusInfo,
    inspectorTabs,
    isSidecarSubject,
    mergeSurfaces,
    rpcTraceKey,
    secretsSummary,
} from './dev-inspector';
import { DEFAULT_MEMORY_LIMIT_BYTES } from './plugin-health-pill';

const STRINGS: Record<string, string> = {
    'plugins.page.inspector.tab.trace': 'rpc trace',
    'plugins.page.inspector.tab.capabilities': 'capabilities',
    'plugins.page.inspector.tab.watchdog': 'watchdog',
    'plugins.page.inspector.tab.surfaces': 'surfaces',
    'plugins.page.inspector.tab.logs': 'logs',
    'plugins.page.inspector.not_measured': 'not measured',
    'plugins.page.inspector.watchdog.rss_value': '{used} / {cap}',
    'plugins.page.inspector.watchdog.cpu_value': '{pct}%',
    'plugins.page.inspector.watchdog.cpu_seconds': '{pct}% ({seconds}s)',
    'plugins.page.inspector.watchdog.strikes_value': '{count} / {max}',
    'plugins.page.inspector.watchdog.crash_loop': 'crash-loop paused',
    'plugins.page.inspector.dev_lease.alert_dot': 'reload error or permission widening',
    'plugins.page.inspector.dev_lease.reload_ms': '{total} ms (stage {stage}, stop {stop}, start {start})',
    'plugins.page.inspector.dev_lease.reload_total': '{total} ms',
    'plugins.page.inspector.dev_lease.unchanged': 'unchanged',
    'plugins.page.inspector.dev_lease.widened': 'permissions widened: re-consent required before reload resumes',
    'plugins.page.inspector.dev_lease.widened_list': 'new permissions: {names}',
    'plugins.page.inspector.logs.source.reloaded': 'reloaded',
};

const t: Translate = (key, params) => {
    const raw = STRINGS[key] ?? key;
    if (!params) return raw;
    return raw.replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? ''));
};

describe('isSidecarSubject', () => {
    test('distinguishes sidecars from built-ins, agent plugins, and removed rows', () => {
        expect(isSidecarSubject({ thirdParty: true, pluginKind: 'plugin', state: 'active' }, null)).toBe(true);
        expect(isSidecarSubject({ thirdParty: false, pluginKind: 'plugin', state: 'active' }, null)).toBe(false);
        expect(isSidecarSubject({ thirdParty: true, pluginKind: 'agent-plugin', state: 'active' }, null)).toBe(false);
        expect(isSidecarSubject({ thirdParty: true, pluginKind: 'plugin', state: 'removed' }, null)).toBe(false);
        expect(
            isSidecarSubject(null, {
                cplug_id: 'acme',
                kind: 'cplug',
                trust_tier: 'local_dev',
                state: 'running',
                paused: false,
                watchdog: {},
                rpc_trace: [],
                capability_checks: [],
                logs_tail: [],
            }),
        ).toBe(true);
        expect(
            isSidecarSubject(null, {
                cplug_id: 'huddle',
                kind: 'plugin',
                trust_tier: 'builtin',
                state: 'running',
                paused: false,
                watchdog: {},
                rpc_trace: [],
                capability_checks: [],
                logs_tail: [],
            }),
        ).toBe(false);
    });
});

describe('resource formatters', () => {
    test('formats bytes, RSS against 128 MiB cap, CPU, disk quotas, uptime, and strikes', () => {
        expect(formatBytes(512)).toBe('512 B');
        expect(formatBytes(4096)).toBe('4 KiB');
        expect(formatBytes(32 * 1024 * 1024)).toBe('32 MiB');

        const rssOk = formatRssUsage(
            { rss_bytes: 32 * 1024 * 1024, memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES },
            t,
        );
        expect(rssOk.text).toBe('32 MiB / 128 MiB');
        expect(rssOk.tone).toBe('neutral');

        const rssWarn = formatRssUsage({ rss_bytes: 110 * 1024 * 1024 }, t);
        expect(rssWarn.tone).toBe('warn');

        const rssDanger = formatRssUsage({ rss_bytes: 125 * 1024 * 1024 }, t);
        expect(rssDanger.tone).toBe('danger');

        expect(formatRssUsage(null, t).text).toBe('not measured / 128 MiB');

        expect(formatCpuUsage({ cpu_percent: 4.2, cpu_seconds: 12.3 }, t)).toEqual({
            text: '4.2% (12.3s)',
            tone: 'neutral',
        });
        expect(formatCpuUsage({ cpu_percent: 55.0 }, t).tone).toBe('danger');
        expect(formatCpuUsage(undefined, t).text).toBe('not measured');

        const disk = formatDiskUsage(
            {
                disk_bytes: 45 * 1024 * 1024,
                disk_quota_bytes: DEFAULT_DISK_QUOTA_BYTES,
                disk_files: 120,
                disk_quota_files: DEFAULT_DISK_QUOTA_FILES,
            },
            t,
        );
        expect(disk.bytesText).toBe('45 MiB / 50 MiB');
        expect(disk.filesText).toBe('120 / 5000');
        expect(disk.tone).toBe('warn');

        expect(formatDuration(45, t)).toBe('45s');
        expect(formatDuration(185, t)).toBe('3m 5s');
        expect(formatDuration(3660, t)).toBe('1h 1m');
        expect(formatDuration(90000, t)).toBe('1d 1h');
        expect(formatDuration(null, t)).toBe('not measured');

        const strikes = formatStrikes({ strikes: 3, crash_loop_paused: true }, 'crash_loop', t);
        expect(strikes.text).toBe(`3 / ${CRASH_LOOP_STRIKES_MAX}`);
        expect(strikes.crashLoop).toBe(true);
        expect(strikes.tone).toBe('danger');
    });

    test('formats timestamps and latencies without em-dashes', () => {
        expect(formatTimestamp(1700000000.123)).toMatch(/^\d{2}:\d{2}:\d{2}\.\d{3}$/);
        expect(formatTimestamp(null)).toBe('-');
        expect(formatLatency(4.25)).toBe('4.25 ms');
        expect(formatLatency(42.38)).toBe('42.4 ms');
        expect(formatLatency(undefined)).toBe('-');
    });
});

describe('stable keys without seq', () => {
    test('builds unique deterministic keys for rpc_trace and capability_checks when seq is absent', () => {
        const k1 = rpcTraceKey({ ts: 1700000001, source: 'rpc', method: 'http.fetch', ok: true }, 0);
        const k2 = rpcTraceKey({ ts: 1700000001, source: 'rpc', method: 'http.fetch', ok: true }, 1);
        expect(k1).not.toBe(k2);
        expect(k1).not.toContain('undefined');

        const c1 = capabilityCheckKey({ ts: 1700000002, permission: 'net', allowed: false }, 0);
        const c2 = capabilityCheckKey({ ts: 1700000002, permission: 'net', allowed: false }, 1);
        expect(c1).not.toBe(c2);
        expect(c1).not.toContain('undefined');
    });
});

describe('deriveDevLeaseSummary and categorizeLogs', () => {
    test('extracts active lease, reload timings, permission widening, and categorized errors', () => {
        const snapshot: PluginInspectorSnapshot = {
            cplug_id: 'local-probe',
            state: 'needs_approval',
            paused: false,
            watchdog: { strikes: 1, restart_count: 2 },
            dev_lease: {
                active: true,
                source_realpath: '/Users/dev/local-probe',
                baseline_sha: 'abc123def',
                ttl_remaining_seconds: 270,
            },
            rpc_trace: [],
            capability_checks: [],
            logs_tail: [
                { source: 'stderr', line: 'booting plugin' },
                {
                    seq: 1,
                    ts: 1700000010,
                    source: 'reloaded',
                    payload: {
                        unchanged: false,
                        needs_approval: false,
                        changed: ['main.py'],
                        timings: { total_ms: 142.4, stage_ms: 40, stop_ms: 20, start_ms: 82.4 },
                    },
                },
                {
                    seq: 2,
                    ts: 1700000020,
                    source: 'ui_error',
                    payload: { code: 'invalid_schema', path: 'ui/widget.json', detail: 'bad grid' },
                },
                {
                    seq: 3,
                    ts: 1700000030,
                    source: 'reload_error',
                    payload: { code: 'syntax_error', detail: 'unexpected EOF' },
                },
                {
                    seq: 4,
                    ts: 1700000040,
                    source: 'permission_widened',
                    payload: { reason: 'manifest asked for network', widened: ['http.fetch'] },
                },
            ],
        };

        const logs = categorizeLogs(snapshot.logs_tail, t);
        expect(logs).toHaveLength(5);
        expect(logs[0]!.title).toBe('booting plugin');
        expect(logs[1]!.title).toBe('142 ms (stage 40, stop 20, start 82)');
        expect(logs[1]!.detail).toContain('main.py');
        expect(logs[2]!.tone).toBe('danger');
        expect(logs[2]!.detail).toBe('ui/widget.json: bad grid');
        expect(logs[3]!.tone).toBe('danger');
        expect(logs[4]!.tone).toBe('warn');

        const summary = deriveDevLeaseSummary(snapshot, { state: 'needs_approval', changedFiles: [] }, t);
        expect(summary.active).toBe(true);
        expect(summary.sourceRealpath).toBe('/Users/dev/local-probe');
        expect(summary.baselineSha).toBe('abc123def');
        expect(summary.ttlLabel).toBe('4m 30s');
        expect(summary.lastReload?.totalMs).toBe(142.4);
        expect(summary.widening?.widened).toEqual(['http.fetch']);
        expect(summary.needsReconsent).toBe(true);
        expect(summary.uiErrors).toHaveLength(1);
        expect(summary.reloadErrors).toHaveLength(1);
    });

    test('clears widening and needsReconsent after a clean reloaded entry (needs_approval: false)', () => {
        const snapshot: PluginInspectorSnapshot = {
            cplug_id: 'local-probe',
            state: 'running',
            paused: false,
            watchdog: {},
            dev_lease: { active: true, ttl_remaining_seconds: 120 },
            rpc_trace: [],
            capability_checks: [],
            logs_tail: [
                {
                    seq: 1,
                    ts: 100,
                    source: 'permission_widened',
                    payload: { widened: ['net.fetch'], reason: 'widened' },
                },
                {
                    seq: 2,
                    ts: 200,
                    source: 'reloaded',
                    payload: {
                        timings: { total_ms: 120, stage_ms: 20, stop_ms: 30, start_ms: 70 },
                        needs_approval: false,
                    },
                },
            ],
        };

        const summary = deriveDevLeaseSummary(snapshot, { state: 'active', changedFiles: [] }, t);
        expect(summary.widening).toBeNull();
        expect(summary.needsReconsent).toBe(false);
        expect(summary.lastReload?.needsApproval).toBe(false);
    });

    test('categorizeLogs uses allow-listed source keys and falls back to raw source for unknown sources', () => {
        const logs = categorizeLogs(
            [
                { ts: 100, source: 'reloaded', payload: { timings: { total_ms: 50 } } },
                { ts: 200, source: 'future_source', line: 'custom line' },
            ],
            t,
        );
        expect(logs).toHaveLength(2);
        expect(logs[0]!.sourceLabel).toBe('reloaded');
        expect(logs[1]!.source).toBe('future_source');
        expect(logs[1]!.sourceLabel).toBe('future_source');
        expect(logs[1]!.title).toBe('custom line');
    });
});

describe('mergeSurfaces and secretsSummary', () => {
    test('merges snapshot.surfaces with matching live panels.list entries only', () => {
        const fakePlugin = (cplugId: string): CplugItem =>
            ({
                id: `cplug:${cplugId}`,
                cplugId,
                name: cplugId,
                kind: 'cplug',
                thirdParty: true,
                state: 'active',
                enabled: true,
            }) as unknown as CplugItem;

        const livePanels: PanelEntry[] = [
            {
                kind: 'acme.clock',
                key: 'acme:inst:clock',
                plugin: fakePlugin('acme'),
                view: 'clock',
                title: 'Acme Clock',
                tail: 'panel-1',
                fits: { sizes: ['medium'], min: { w: 2, h: 2 }, anySize: true },
                declarative: true,
            },
            {
                kind: 'other.view',
                key: 'other:inst:view',
                plugin: fakePlugin('other'),
                view: 'view',
                title: 'Other View',
                tail: 'panel-2',
                fits: { sizes: ['medium'], min: { w: 2, h: 2 }, anySize: true },
                declarative: false,
            },
        ];

        const merged = mergeSurfaces(
            'acme',
            {
                widget: true,
                panel: false,
                bar: true,
                settings: true,
                views: ['clock'],
                tools: ['acme__ping'],
                routes: ['/status'],
                timers: ['heartbeat'],
                absent_surfaces: ['feed'],
            },
            livePanels,
        );

        expect(merged.activeFlags).toEqual(['widget', 'bar', 'settings']);
        expect(merged.livePanels).toHaveLength(1);
        expect(merged.livePanels[0]!.kind).toBe('acme.clock');
        expect(merged.livePanels[0]!.declarative).toBe(true);
        expect(merged.tools).toEqual(['acme__ping']);
        expect(merged.routes).toEqual(['/status']);
        expect(merged.timers).toEqual(['heartbeat']);
        expect(merged.absentSurfaces).toEqual(['feed']);
        expect(merged.totalActiveCount).toBe(7);
    });

    test('normalizes secrets_status keys sorted alphabetically', () => {
        expect(
            secretsSummary({
                Z_TOKEN: { present: false, needs_reentry: true },
                A_KEY: { secret_present: true },
            }),
        ).toEqual([
            { name: 'A_KEY', present: true, needsReentry: false },
            { name: 'Z_TOKEN', present: false, needsReentry: true },
        ]);
    });

    test('inspectorTabs and inspectorStatusInfo expose crash-loop and reload alert dots', () => {
        const tabs = inspectorTabs(t, {
            trace: 4,
            capabilities: 2,
            surfaces: 3,
            logs: 5,
            hasCrashLoop: true,
            hasReloadAlert: true,
        });
        expect(tabs.find((tab) => tab.id === 'trace')?.badge).toBe(4);
        expect(tabs.find((tab) => tab.id === 'watchdog')?.dot).toBe(true);
        expect(tabs.find((tab) => tab.id === 'logs')?.dot).toBe(true);

        const status = inspectorStatusInfo(null, {
            cplug_id: 'acme',
            state: 'crash_loop',
            paused: true,
            watchdog: { crash_loop_paused: true, strikes: 3 },
            rpc_trace: [],
            capability_checks: [],
            logs_tail: [],
        });
        expect(status.tone).toBe('danger');
        expect(status.crashLoop).toBe(true);
        expect(status.paused).toBe(true);
    });
});
