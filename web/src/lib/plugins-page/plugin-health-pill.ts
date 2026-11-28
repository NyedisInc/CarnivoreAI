import type { TagTone } from '../base/classes';
import type { PluginInspectorSnapshot } from '../plugins/store.svelte';
import type { Translate } from '../sessions/types';
import type { CplugItem, CplugWatchdog } from './cplugs-adapter';

export const DEFAULT_MEMORY_LIMIT_BYTES = 128 * 1024 * 1024;

export type MetricTone = 'neutral' | 'warn' | 'danger';

export interface FormattedMetric {
    readonly text: string;
    readonly tone: MetricTone;
}

export function rssLabel(watchdog: CplugWatchdog | null | undefined, t: Translate): FormattedMetric | null {
    if (!watchdog || typeof watchdog.rss_bytes !== 'number') return null;
    const limit =
        typeof watchdog.memory_limit_bytes === 'number' && watchdog.memory_limit_bytes > 0
            ? watchdog.memory_limit_bytes
            : DEFAULT_MEMORY_LIMIT_BYTES;
    const ratio = watchdog.rss_bytes / limit;
    const used = (watchdog.rss_bytes / (1024 * 1024)).toFixed(1);
    const cap = Math.round(limit / (1024 * 1024)).toString();
    const tone: MetricTone = ratio >= 0.95 ? 'danger' : ratio >= 0.8 ? 'warn' : 'neutral';
    return {
        text: t('plugins.page.health_pill.rss', { used, cap }),
        tone,
    };
}

export function cpuLabel(watchdog: CplugWatchdog | null | undefined, t: Translate): FormattedMetric | null {
    if (!watchdog || typeof watchdog.cpu_percent !== 'number') return null;
    const pct = watchdog.cpu_percent;
    const tone: MetricTone = pct >= 50 ? 'danger' : pct >= 15 ? 'warn' : 'neutral';
    return {
        text: t('plugins.page.health_pill.cpu', { value: pct.toFixed(1) }),
        tone,
    };
}

function nonEmptyText(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
}

export function lastCallSummary(
    snapshot: PluginInspectorSnapshot | null | undefined,
    watchdog?: CplugWatchdog | null,
    pluginWatchdog?: CplugWatchdog | null,
): string | null {
    const trace = snapshot?.rpc_trace;
    if (Array.isArray(trace) && trace.length > 0) {
        const latest = trace[trace.length - 1]!;
        const target = latest.target ? ` ${latest.target}` : '';
        const errSuffix = latest.ok === false ? (latest.error_code ? ` (${latest.error_code})` : ' (err)') : '';
        return `${latest.method}${target}${errSuffix}`;
    }
    const lastCall =
        nonEmptyText(pluginWatchdog?.last_call) ??
        nonEmptyText(watchdog?.last_call) ??
        nonEmptyText(snapshot?.watchdog?.last_call);
    if (lastCall !== null) return lastCall;
    const lastEvent =
        nonEmptyText(pluginWatchdog?.last_event) ??
        nonEmptyText(watchdog?.last_event) ??
        nonEmptyText(snapshot?.watchdog?.last_event);
    if (lastEvent !== null) return lastEvent;
    const logs = snapshot?.logs_tail;
    if (Array.isArray(logs) && logs.length > 0) {
        for (let i = logs.length - 1; i >= 0; i -= 1) {
            const entry = logs[i];
            const line = nonEmptyText(entry?.line);
            if (line !== null) {
                return entry?.source ? `${entry.source}: ${line}` : line;
            }
        }
    }
    return null;
}

function isCrashLoopPaused(
    plugin: Pick<CplugItem, 'state' | 'runtimePaused' | 'watchdog'>,
    snapshot?: PluginInspectorSnapshot | null,
): boolean {
    if (plugin.watchdog?.crash_loop_paused === true) return true;
    if (plugin.watchdog?.crash_loop_paused === false) return false;
    if (plugin.state === 'active' && !plugin.runtimePaused) return false;
    if (plugin.state === 'disabled' || plugin.state === 'removed') return false;
    return Boolean(snapshot?.watchdog?.crash_loop_paused);
}

export function isPillPaused(
    plugin: Pick<CplugItem, 'state' | 'runtimePaused'>,
    snapshot?: PluginInspectorSnapshot | null,
): boolean {
    if (plugin.runtimePaused === true || plugin.state === 'paused') return true;
    if (plugin.runtimePaused === false) return false;
    if (plugin.state === 'active' || plugin.state === 'disabled' || plugin.state === 'removed') return false;
    return Boolean(snapshot?.paused);
}

export function restartCountOf(
    plugin: Pick<CplugItem, 'watchdog'>,
    snapshot?: PluginInspectorSnapshot | null,
): number {
    const w = snapshot?.watchdog ?? plugin.watchdog;
    return typeof w?.restart_count === 'number' ? w.restart_count : 0;
}

export function healthPillTone(
    plugin: Pick<CplugItem, 'state' | 'runtimePaused' | 'watchdog'>,
    snapshot?: PluginInspectorSnapshot | null,
): TagTone {
    if (isCrashLoopPaused(plugin, snapshot)) return 'danger';
    if (
        isPillPaused(plugin, snapshot) ||
        plugin.state === 'unavailable' ||
        plugin.state === 'needs_approval' ||
        plugin.state === 'inert'
    ) {
        return 'warn';
    }
    if (plugin.state === 'active') return 'ok';
    if (plugin.state === 'disabled' || plugin.state === 'removed') return 'neutral';
    if (snapshot?.state === 'running') return 'ok';
    return 'neutral';
}

export function healthPillStatusKey(
    plugin: Pick<CplugItem, 'state' | 'runtimePaused' | 'watchdog'>,
    snapshot?: PluginInspectorSnapshot | null,
): string {
    if (isCrashLoopPaused(plugin, snapshot)) return 'plugins.page.health_pill.status.crash_loop';
    if (isPillPaused(plugin, snapshot)) return 'plugins.page.health_pill.status.paused';
    if (plugin.state === 'needs_approval') return 'plugins.page.health_pill.status.needs_approval';
    if (plugin.state === 'unavailable') return 'plugins.page.health_pill.status.held';
    if (plugin.state === 'inert') return 'plugins.page.health_pill.status.inert';
    if (plugin.state === 'active') return 'plugins.page.health_pill.status.active';
    if (plugin.state === 'removed') return 'plugins.page.health_pill.status.removed';
    if (plugin.state === 'disabled') return 'plugins.page.health_pill.status.disabled';
    if (snapshot?.state === 'running') return 'plugins.page.health_pill.status.active';
    return 'plugins.page.health_pill.status.disabled';
}
