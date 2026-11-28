/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { PluginInspectorSnapshot } from '../plugins/store.svelte';
import type { Translate } from '../sessions/types';
import { toCplugItem, type CplugRow } from './cplugs-adapter';
import {
    DEFAULT_MEMORY_LIMIT_BYTES,
    cpuLabel,
    healthPillStatusKey,
    healthPillTone,
    isPillPaused,
    lastCallSummary,
    rssLabel,
} from './plugin-health-pill';
import PluginHealthPill from './PluginHealthPill.svelte';
import PluginOverview from './PluginOverview.svelte';
import PluginPane from './PluginPane.svelte';

const TEST_STRINGS: Record<string, string> = {
    'plugins.page.health_pill.label': 'runtime health',
    'plugins.page.health_pill.status.active': 'running',
    'plugins.page.health_pill.status.paused': 'paused',
    'plugins.page.health_pill.status.crash_loop': 'crash-loop paused',
    'plugins.page.health_pill.status.held': 'held',
    'plugins.page.health_pill.status.needs_approval': 'needs approval',
    'plugins.page.health_pill.status.inert': 'waiting',
    'plugins.page.health_pill.status.disabled': 'off',
    'plugins.page.health_pill.status.removed': 'removed',
    'plugins.page.health_pill.rss': '{used} / {cap} mb',
    'plugins.page.health_pill.rss_none': '0.0 / 128 mb',
    'plugins.page.health_pill.cpu': 'cpu {value}%',
    'plugins.page.health_pill.restarts': 'restarts {count}',
    'plugins.page.health_pill.last_call': 'last: {summary}',
    'plugins.page.health_pill.logs': 'logs',
    'plugins.page.health_pill.restart': 'restart',
    'plugins.page.health_pill.pause': 'pause',
    'plugins.page.health_pill.resume': 'resume',
    'plugins.page.pane.scope.heading': 'scope',
    'plugins.page.pane.scope.label': 'install scope',
    'plugins.page.pane.scope.global': 'global',
    'plugins.page.pane.scope.project': 'project',
    'plugins.page.pane.scope.project_path': 'project path',
};

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => {
    const template = TEST_STRINGS[key];
    if (!template) return en.t(key, params);
    return template.replace(/\{(\w+)\}/g, (_, k) => String(params?.[k] ?? ''));
};

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) {
        await tick();
        await Promise.resolve();
    }
    flushSync();
}

function sidecarRow(overrides: Partial<CplugRow> = {}): CplugRow {
    return {
        id: 'gh-clock',
        runtime: 'sidecar',
        name: 'GH Clock',
        description: 'Clock sidecar',
        version: '0.2.0',
        kind: 'plugin',
        trust_tier: 'unverified_github',
        trust_badge: 'Unverified GitHub Repo',
        unverified: true,
        scope: 'global',
        enabled: true,
        state: 'active',
        runtime_paused: false,
        watchdog: {
            memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES,
            rss_bytes: 32 * 1024 * 1024,
            cpu_percent: 2.5,
            restart_count: 1,
            strikes: 0,
            crash_loop_paused: false,
        },
        ...overrides,
    };
}

function sampleSnapshot(overrides: Partial<PluginInspectorSnapshot> = {}): PluginInspectorSnapshot {
    return {
        cplug_id: 'gh-clock',
        state: 'running',
        paused: false,
        watchdog: {
            memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES,
            rss_bytes: 64 * 1024 * 1024,
            cpu_percent: 4.2,
            restart_count: 2,
            strikes: 0,
            crash_loop_paused: false,
        },
        rpc_trace: [
            { ts: 1700000001, source: 'cli_sock', method: 'http.fetch', target: 'api.github.com', ok: true },
        ],
        capability_checks: [],
        logs_tail: [{ source: 'stderr', line: 'booted' }],
        ...overrides,
    };
}

describe('plugin-health-pill pure formatters', () => {
    test('rssLabel computes MB against 128 MiB cap with warn >= 80% and danger >= 95%', () => {
        expect(rssLabel({ rss_bytes: 64 * 1024 * 1024, memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES }, t)).toEqual({
            text: '64.0 / 128 mb',
            tone: 'neutral',
        });
        expect(rssLabel({ rss_bytes: Math.round(DEFAULT_MEMORY_LIMIT_BYTES * 0.85), memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES }, t)?.tone).toBe('warn');
        expect(rssLabel({ rss_bytes: Math.round(DEFAULT_MEMORY_LIMIT_BYTES * 0.96), memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES }, t)?.tone).toBe('danger');
        expect(rssLabel(null, t)).toBeNull();
    });

    test('cpuLabel formats percentage and flags high CPU', () => {
        expect(cpuLabel({ cpu_percent: 3.14 }, t)).toEqual({ text: 'cpu 3.1%', tone: 'neutral' });
        expect(cpuLabel({ cpu_percent: 18.0 }, t)?.tone).toBe('warn');
        expect(cpuLabel({ cpu_percent: 55.0 }, t)?.tone).toBe('danger');
    });

    test('lastCallSummary prefers rpc_trace, then watchdog.last_call / last_event, then logs_tail with non-empty .line', () => {
        expect(lastCallSummary(sampleSnapshot())).toBe('http.fetch api.github.com');
        expect(lastCallSummary(sampleSnapshot({ rpc_trace: [] }))).toBe('stderr: booted');
        expect(lastCallSummary(null, { last_call: 'timer.fire' } as never)).toBe('timer.fire');
        expect(lastCallSummary(null, { last_call: null, last_event: 'sessions.read (allowed)' })).toBe(
            'sessions.read (allowed)',
        );
        expect(
            lastCallSummary(
                sampleSnapshot({
                    rpc_trace: [],
                    logs_tail: [{ seq: 1, ts: 1700000001, source: 'reloaded', payload: { ms: 12 } }],
                }),
                { last_call: 'http.fetch api.github.com', last_event: 'reloaded' },
            ),
        ).toBe('http.fetch api.github.com');
        expect(
            lastCallSummary(
                sampleSnapshot({
                    rpc_trace: [],
                    logs_tail: [{ seq: 1, ts: 1700000001, source: 'reloaded', payload: { ms: 12 } }],
                }),
                { last_call: null, last_event: 'sessions.read (allowed)' },
            ),
        ).toBe('sessions.read (allowed)');
        expect(
            lastCallSummary(
                sampleSnapshot({
                    rpc_trace: [],
                    logs_tail: [{ seq: 1, ts: 1700000001, source: 'reloaded', payload: { ms: 12 } }],
                }),
                null,
            ),
        ).toBeNull();
        expect(lastCallSummary(null, null)).toBeNull();
    });

    test('healthPillTone and healthPillStatusKey prefer fresh active plugin row over stale paused/crash_loop snapshot', () => {
        expect(healthPillTone({ state: 'active', runtimePaused: false, watchdog: { crash_loop_paused: true } })).toBe('danger');
        expect(healthPillTone({ state: 'active', runtimePaused: true, watchdog: {} })).toBe('warn');
        expect(healthPillTone({ state: 'active', runtimePaused: false, watchdog: {} })).toBe('ok');
        expect(healthPillTone({ state: 'disabled', runtimePaused: false, watchdog: {} })).toBe('neutral');

        const staleSnapshot = sampleSnapshot({
            state: 'crash_loop',
            paused: true,
            watchdog: { crash_loop_paused: true, restart_count: 3 },
        });
        const freshPlugin = {
            state: 'active',
            runtimePaused: false,
            watchdog: { crash_loop_paused: false, restart_count: 3 },
        };
        expect(isPillPaused(freshPlugin, staleSnapshot)).toBe(false);
        expect(healthPillTone(freshPlugin, staleSnapshot)).toBe('ok');
        expect(healthPillStatusKey(freshPlugin, staleSnapshot)).toBe('plugins.page.health_pill.status.active');

        const heldPlugin = { state: 'unavailable', runtimePaused: false };
        expect(healthPillTone(heldPlugin, staleSnapshot)).toBe('danger');
        expect(healthPillStatusKey(heldPlugin, staleSnapshot)).toBe('plugins.page.health_pill.status.crash_loop');
    });
});

describe('PluginHealthPill.svelte', () => {
    test('renders live snapshot metrics and invokes Logs, Restart, and Pause/Resume callbacks', async () => {
        const plugin = toCplugItem(sidecarRow(), t);
        const onLogs = vi.fn();
        const onRestart = vi.fn(async () => ({}));
        const onPauseToggle = vi.fn(async () => ({}));

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginHealthPill, {
            target,
            props: {
                plugin,
                snapshot: sampleSnapshot(),
                onLogs,
                onRestart,
                onPauseToggle,
                t,
            },
        });
        await settle();

        const pill = target.querySelector('[data-health-pill="gh-clock"]')!;
        expect(pill.querySelector('[data-pill-status]')?.textContent).toBe('running');
        expect(pill.querySelector('[data-pill-rss]')?.textContent?.trim()).toBe('64.0 / 128 mb');
        expect(pill.querySelector('[data-pill-cpu]')?.textContent?.trim()).toBe('cpu 4.2%');
        expect(pill.querySelector('[data-pill-restarts]')?.textContent?.trim()).toBe('restarts 2');
        expect(pill.querySelector('[data-pill-last-call]')?.textContent?.trim()).toBe('last: http.fetch api.github.com');

        pill.querySelector<HTMLButtonElement>('[data-pill-logs]')!.click();
        expect(onLogs).toHaveBeenCalledWith('gh-clock');

        pill.querySelector<HTMLButtonElement>('[data-pill-restart]')!.click();
        await settle();
        expect(onRestart).toHaveBeenCalledWith('gh-clock');

        const pauseBtn = pill.querySelector<HTMLButtonElement>('[data-pill-pause]')!;
        expect(pauseBtn.textContent?.trim()).toBe('pause');
        pauseBtn.click();
        await settle();
        expect(onPauseToggle).toHaveBeenCalledWith('gh-clock', true);
    });

    test('renders crash-loop paused badge and Resume label when paused', async () => {
        const plugin = toCplugItem(
            sidecarRow({
                state: 'paused',
                runtime_paused: true,
                watchdog: { rss_bytes: 125 * 1024 * 1024, memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES, crash_loop_paused: true, restart_count: 5 },
            }),
            t,
        );
        const onPauseToggle = vi.fn(async () => ({}));

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginHealthPill, {
            target,
            props: {
                plugin,
                onRestart: vi.fn(async () => ({})),
                onPauseToggle,
                t,
            },
        });
        await settle();

        expect(target.querySelector('[data-pill-status]')?.textContent).toBe('crash-loop paused');
        expect(target.querySelector('[data-pill-rss]')?.getAttribute('data-tone')).toBe('danger');
        const resumeBtn = target.querySelector<HTMLButtonElement>('[data-pill-pause]')!;
        expect(resumeBtn.textContent?.trim()).toBe('resume');
        resumeBtn.click();
        await settle();
        expect(onPauseToggle).toHaveBeenCalledWith('gh-clock', false);
    });

    test('renders fresh active plugin row over stale crash-loop snapshot and shows plugin.watchdog.last_event (BUG-6a/6b/6c)', async () => {
        const plugin = toCplugItem(
            sidecarRow({
                state: 'active',
                runtime_paused: false,
                watchdog: {
                    memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES,
                    rss_bytes: 20 * 1024 * 1024,
                    cpu_percent: 1.0,
                    restart_count: 1,
                    strikes: 0,
                    crash_loop_paused: false,
                    last_call: null,
                    last_event: 'sessions.read (allowed)',
                },
            }),
            t,
        );
        const staleSnapshot = sampleSnapshot({
            state: 'crash_loop',
            paused: true,
            watchdog: {
                memory_limit_bytes: DEFAULT_MEMORY_LIMIT_BYTES,
                rss_bytes: 20 * 1024 * 1024,
                cpu_percent: 1.0,
                restart_count: 1,
                strikes: 3,
                crash_loop_paused: true,
            },
            rpc_trace: [],
            logs_tail: [{ seq: 1, ts: 1700000001, source: 'reloaded', payload: { ms: 12 } }],
        });

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginHealthPill, {
            target,
            props: {
                plugin,
                snapshot: staleSnapshot,
                onRestart: vi.fn(async () => ({})),
                onPauseToggle: vi.fn(async () => ({})),
                t,
            },
        });
        await settle();

        expect(target.querySelector('[data-pill-status]')?.textContent).toBe('running');
        expect(target.querySelector('[data-pill-pause]')?.textContent?.trim()).toBe('pause');
        expect(target.querySelector('[data-pill-last-call]')?.textContent?.trim()).toBe('last: sessions.read (allowed)');
    });
});

describe('PluginOverview & PluginPane integration', () => {
    test('PluginPane threads inspector and onInspectLogs to PluginOverview for sidecars and hides agent-plugin scope block', async () => {
        const plugin = toCplugItem(sidecarRow(), t);
        const onInspectLogs = vi.fn();
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginPane, {
            target,
            props: {
                plugin,
                tab: 'overview',
                onTab: vi.fn(),
                onConfirmOff: vi.fn(),
                onCancelOff: vi.fn(),
                onGrant: vi.fn(),
                loadActivity: async () => [],
                inspector: sampleSnapshot(),
                onInspectLogs,
                t,
            },
        });
        await settle();

        expect(target.querySelector('[data-health-pill="gh-clock"]')).not.toBeNull();
        expect(target.querySelector('[data-agent-plugin-scope]')).toBeNull();
        target.querySelector<HTMLButtonElement>('[data-pill-logs]')!.click();
        expect(onInspectLogs).toHaveBeenCalledWith('gh-clock');
    });

    test('PluginOverview renders agent-plugin scope & project detail ONLY when pluginKind === "agent-plugin"', async () => {
        const agentPlugin = toCplugItem(
            {
                id: 'gh-agent-mod',
                kind: 'agent-plugin',
                name: 'Agent Mod',
                runtime: 'sidecar',
                scope: 'project',
                project_path: '/Users/dev/my-app',
                enabled: true,
                state: 'active',
            },
            t,
        );
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginOverview, {
            target,
            props: { plugin: agentPlugin, t },
        });
        await settle();

        expect(target.querySelector('[data-health-pill]')).toBeNull();
        const scopeBlock = target.querySelector('[data-agent-plugin-scope]');
        expect(scopeBlock).not.toBeNull();
        expect(scopeBlock?.querySelector('[data-agent-scope-value]')?.textContent?.trim()).toBe('project');
        expect(scopeBlock?.querySelector('[data-agent-scope-project]')?.textContent?.trim()).toBe('/Users/dev/my-app');
    });
});
