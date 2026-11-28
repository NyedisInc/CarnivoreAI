import type { TabDef } from '../../opscenter/ui/Tabs.svelte';
import type { TagTone } from '../base/classes';
import type { PanelEntry } from '../cplug-ui/panel-views.svelte';
import type {
    InspectorCapabilityCheck,
    InspectorLogEntry,
    InspectorRpcTraceEntry,
    InspectorSurfacesSummary,
    PluginInspectorSnapshot,
} from '../plugins/store.svelte';
import type { Translate } from '../sessions/types';
import type { CplugItem, CplugSecretStatus, CplugWatchdog } from './cplugs-adapter';
import {
    DEFAULT_MEMORY_LIMIT_BYTES,
    healthPillStatusKey,
    healthPillTone,
    isPillPaused,
} from './plugin-health-pill';

export const DEFAULT_DISK_QUOTA_BYTES = 50 * 1024 * 1024;
export const DEFAULT_DISK_QUOTA_FILES = 5000;
export const CRASH_LOOP_STRIKES_MAX = 3;

export type InspectorTabId = 'trace' | 'capabilities' | 'watchdog' | 'surfaces' | 'logs';

export const INSPECTOR_TABS: readonly InspectorTabId[] = [
    'trace',
    'capabilities',
    'watchdog',
    'surfaces',
    'logs',
];

export interface InspectorTabCounts {
    readonly trace?: number;
    readonly capabilities?: number;
    readonly surfaces?: number;
    readonly logs?: number;
    readonly hasReloadAlert?: boolean;
    readonly hasCrashLoop?: boolean;
}

export interface InspectorStatusInfo {
    readonly tone: TagTone;
    readonly key: string;
    readonly paused: boolean;
    readonly crashLoop: boolean;
}

export interface FormattedRssUsage {
    readonly text: string;
    readonly usedText: string;
    readonly capText: string;
    readonly ratio: number | null;
    readonly tone: TagTone;
}

export interface FormattedCpuUsage {
    readonly text: string;
    readonly tone: TagTone;
}

export interface FormattedDiskUsage {
    readonly bytesText: string;
    readonly filesText: string;
    readonly tone: TagTone;
}

export interface FormattedStrikes {
    readonly count: number;
    readonly max: number;
    readonly text: string;
    readonly crashLoop: boolean;
    readonly tone: TagTone;
}

export interface ReloadTimingsSummary {
    readonly totalMs: number | null;
    readonly stageMs: number | null;
    readonly stopMs: number | null;
    readonly startMs: number | null;
    readonly unchanged: boolean;
    readonly needsApproval: boolean;
    readonly digest: string | null;
    readonly changedFiles: readonly string[];
    readonly ts: number | null;
}

export interface WideningAlert {
    readonly widened: readonly string[];
    readonly reason: string | null;
    readonly ts: number | null;
}

export interface FormattedLogEntry {
    readonly key: string;
    readonly source: string;
    readonly sourceLabel: string;
    readonly tone: TagTone;
    readonly tsLabel: string;
    readonly title: string;
    readonly detail: string | null;
}

export interface DevLeaseSummary {
    readonly active: boolean;
    readonly sourceRealpath: string | null;
    readonly baselineSha: string | null;
    readonly ttlSeconds: number | null;
    readonly ttlLabel: string | null;
    readonly lastReload: ReloadTimingsSummary | null;
    readonly widening: WideningAlert | null;
    readonly needsReconsent: boolean;
    readonly uiErrors: readonly FormattedLogEntry[];
    readonly reloadErrors: readonly FormattedLogEntry[];
}

export type SurfaceFlag = 'widget' | 'panel' | 'bar' | 'settings';

export interface MergedSurfaceView {
    readonly key: string;
    readonly kind: string;
    readonly title: string;
    readonly view: string;
    readonly mounted: boolean;
    readonly declarative: boolean;
}

export interface MergedSurfacesSummary {
    readonly activeFlags: readonly SurfaceFlag[];
    readonly livePanels: readonly MergedSurfaceView[];
    readonly manifestViews: readonly string[];
    readonly tools: readonly string[];
    readonly routes: readonly string[];
    readonly timers: readonly string[];
    readonly absentSurfaces: readonly string[];
    readonly totalActiveCount: number;
}

export interface SecretStatusSummary {
    readonly name: string;
    readonly present: boolean;
    readonly needsReentry: boolean;
}

export function isSidecarSubject(
    plugin: Pick<CplugItem, 'thirdParty' | 'pluginKind' | 'state'> | null | undefined,
    snapshot: PluginInspectorSnapshot | null | undefined,
): boolean {
    if (plugin) {
        return plugin.thirdParty && plugin.pluginKind !== 'agent-plugin' && plugin.state !== 'removed';
    }
    if (!snapshot) return false;
    if (
        snapshot.kind === 'sidecar' ||
        (typeof snapshot.kind === 'string' &&
            snapshot.kind !== 'plugin' &&
            snapshot.kind !== 'agent-plugin' &&
            snapshot.trust_tier !== 'builtin')
    ) {
        return true;
    }
    if (snapshot.trust_tier && snapshot.trust_tier !== 'builtin') return snapshot.kind !== 'agent-plugin';
    return false;
}

export function inspectorTabs(t: Translate, counts: InspectorTabCounts = {}): TabDef[] {
    return [
        {
            id: 'trace',
            label: t('plugins.page.inspector.tab.trace'),
            badge: counts.trace && counts.trace > 0 ? counts.trace : null,
        },
        {
            id: 'capabilities',
            label: t('plugins.page.inspector.tab.capabilities'),
            badge: counts.capabilities && counts.capabilities > 0 ? counts.capabilities : null,
        },
        {
            id: 'watchdog',
            label: t('plugins.page.inspector.tab.watchdog'),
            dot: counts.hasCrashLoop === true,
            dotLabel: counts.hasCrashLoop ? t('plugins.page.inspector.watchdog.crash_loop') : undefined,
        },
        {
            id: 'surfaces',
            label: t('plugins.page.inspector.tab.surfaces'),
            badge: counts.surfaces && counts.surfaces > 0 ? counts.surfaces : null,
        },
        {
            id: 'logs',
            label: t('plugins.page.inspector.tab.logs'),
            badge: counts.logs && counts.logs > 0 ? counts.logs : null,
            dot: counts.hasReloadAlert === true,
            dotLabel: counts.hasReloadAlert ? t('plugins.page.inspector.dev_lease.alert_dot') : undefined,
        },
    ];
}

export function inspectorStatusInfo(
    plugin: Pick<CplugItem, 'state' | 'runtimePaused' | 'watchdog'> | null | undefined,
    snapshot: PluginInspectorSnapshot | null | undefined,
): InspectorStatusInfo {
    const subject: Pick<CplugItem, 'state' | 'runtimePaused' | 'watchdog'> = plugin ?? {
        state: snapshot?.state === 'running' ? 'active' : (snapshot?.state ?? 'disabled'),
        runtimePaused: snapshot?.paused,
        watchdog: snapshot?.watchdog,
    };
    const tone = healthPillTone(subject, snapshot);
    const key = healthPillStatusKey(subject, snapshot);
    const paused = isPillPaused(subject, snapshot);
    const crashLoop = Boolean(
        subject.watchdog?.crash_loop_paused ||
            snapshot?.watchdog?.crash_loop_paused ||
            snapshot?.state === 'crash_loop',
    );
    return { tone, key, paused, crashLoop };
}

export function formatBytes(bytes: number | null | undefined): string {
    if (typeof bytes !== 'number' || !Number.isFinite(bytes) || bytes < 0) return '0 B';
    if (bytes >= 1024 * 1024) {
        const mib = bytes / (1024 * 1024);
        return `${mib >= 100 || Number.isInteger(mib) ? mib.toFixed(mib % 1 === 0 ? 0 : 1) : mib.toFixed(1)} MiB`;
    }
    if (bytes >= 1024) {
        const kib = bytes / 1024;
        return `${kib >= 100 || kib % 1 === 0 ? Math.round(kib) : kib.toFixed(1)} KiB`;
    }
    return `${Math.round(bytes)} B`;
}

export function formatRssUsage(watchdog: CplugWatchdog | null | undefined, t: Translate): FormattedRssUsage {
    const limit =
        typeof watchdog?.memory_limit_bytes === 'number' && watchdog.memory_limit_bytes > 0
            ? watchdog.memory_limit_bytes
            : DEFAULT_MEMORY_LIMIT_BYTES;
    const capText = formatBytes(limit);
    if (typeof watchdog?.rss_bytes !== 'number' || !Number.isFinite(watchdog.rss_bytes)) {
        return {
            text: t('plugins.page.inspector.watchdog.rss_value', {
                used: t('plugins.page.inspector.not_measured'),
                cap: capText,
            }),
            usedText: t('plugins.page.inspector.not_measured'),
            capText,
            ratio: null,
            tone: 'neutral',
        };
    }
    const usedText = formatBytes(watchdog.rss_bytes);
    const ratio = watchdog.rss_bytes / limit;
    const tone: TagTone = ratio >= 0.95 ? 'danger' : ratio >= 0.8 ? 'warn' : 'neutral';
    return {
        text: t('plugins.page.inspector.watchdog.rss_value', { used: usedText, cap: capText }),
        usedText,
        capText,
        ratio,
        tone,
    };
}

export function formatCpuUsage(watchdog: CplugWatchdog | null | undefined, t: Translate): FormattedCpuUsage {
    if (typeof watchdog?.cpu_percent !== 'number' || !Number.isFinite(watchdog.cpu_percent)) {
        return { text: t('plugins.page.inspector.not_measured'), tone: 'neutral' };
    }
    const pct = watchdog.cpu_percent;
    const tone: TagTone = pct >= 50 ? 'danger' : pct >= 15 ? 'warn' : 'neutral';
    if (typeof watchdog.cpu_seconds === 'number' && Number.isFinite(watchdog.cpu_seconds)) {
        return {
            text: t('plugins.page.inspector.watchdog.cpu_seconds', {
                pct: pct.toFixed(1),
                seconds: watchdog.cpu_seconds.toFixed(1),
            }),
            tone,
        };
    }
    return {
        text: t('plugins.page.inspector.watchdog.cpu_value', { pct: pct.toFixed(1) }),
        tone,
    };
}

export function formatDiskUsage(watchdog: CplugWatchdog | null | undefined, t: Translate): FormattedDiskUsage {
    const bytesQuota =
        typeof watchdog?.disk_quota_bytes === 'number' && watchdog.disk_quota_bytes > 0
            ? watchdog.disk_quota_bytes
            : DEFAULT_DISK_QUOTA_BYTES;
    const filesQuota =
        typeof watchdog?.disk_quota_files === 'number' && watchdog.disk_quota_files > 0
            ? watchdog.disk_quota_files
            : DEFAULT_DISK_QUOTA_FILES;
    const hasBytes = typeof watchdog?.disk_bytes === 'number' && Number.isFinite(watchdog.disk_bytes);
    const hasFiles = typeof watchdog?.disk_files === 'number' && Number.isFinite(watchdog.disk_files);
    const bytesRatio = hasBytes ? watchdog!.disk_bytes! / bytesQuota : 0;
    const filesRatio = hasFiles ? watchdog!.disk_files! / filesQuota : 0;
    const maxRatio = Math.max(bytesRatio, filesRatio);
    const tone: TagTone = maxRatio >= 0.95 ? 'danger' : maxRatio >= 0.8 ? 'warn' : 'neutral';
    const bytesText = hasBytes
        ? `${formatBytes(watchdog!.disk_bytes)} / ${formatBytes(bytesQuota)}`
        : `${t('plugins.page.inspector.not_measured')} / ${formatBytes(bytesQuota)}`;
    const filesText = hasFiles ? `${watchdog!.disk_files} / ${filesQuota}` : `0 / ${filesQuota}`;
    return { bytesText, filesText, tone };
}

export function formatDuration(seconds: number | null | undefined, t?: Translate): string {
    if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) {
        return t ? t('plugins.page.inspector.not_measured') : '-';
    }
    const whole = Math.floor(seconds);
    if (whole < 60) return `${whole}s`;
    const mins = Math.floor(whole / 60);
    const remSec = whole % 60;
    if (mins < 60) return remSec > 0 ? `${mins}m ${remSec}s` : `${mins}m`;
    const hours = Math.floor(mins / 60);
    const remMin = mins % 60;
    if (hours < 24) return remMin > 0 ? `${hours}h ${remMin}m` : `${hours}h`;
    const days = Math.floor(hours / 24);
    const remHours = hours % 24;
    return remHours > 0 ? `${days}d ${remHours}h` : `${days}d`;
}

export function formatStrikes(
    watchdog: CplugWatchdog | null | undefined,
    state: string | null | undefined,
    t: Translate,
): FormattedStrikes {
    const count = typeof watchdog?.strikes === 'number' && Number.isFinite(watchdog.strikes) ? watchdog.strikes : 0;
    const crashLoop = Boolean(watchdog?.crash_loop_paused) || state === 'crash_loop';
    const tone: TagTone = crashLoop || count >= CRASH_LOOP_STRIKES_MAX ? 'danger' : count > 0 ? 'warn' : 'neutral';
    return {
        count,
        max: CRASH_LOOP_STRIKES_MAX,
        text: t('plugins.page.inspector.watchdog.strikes_value', { count, max: CRASH_LOOP_STRIKES_MAX }),
        crashLoop,
        tone,
    };
}

export function formatTimestamp(ts: number | null | undefined): string {
    if (typeof ts !== 'number' || !Number.isFinite(ts) || ts <= 0) return '-';
    return new Date(ts * 1000).toISOString().slice(11, 23);
}

export function formatLatency(ms: number | null | undefined): string {
    if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return '-';
    return `${ms < 10 ? ms.toFixed(2) : ms.toFixed(1)} ms`;
}

export function rpcTraceKey(entry: InspectorRpcTraceEntry, index: number): string {
    return `${index}:${entry.ts}:${entry.source}:${entry.method}:${entry.target ?? ''}`;
}

export function capabilityCheckKey(entry: InspectorCapabilityCheck, index: number): string {
    return `${index}:${entry.ts}:${entry.permission}:${entry.allowed ? '1' : '0'}:${entry.caller ?? ''}`;
}

function asString(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
}

function asNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asStringArray(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return value.map((item) => (typeof item === 'string' ? item.trim() : '')).filter(Boolean);
}

const KNOWN_LOG_SOURCE_KEYS: Readonly<Record<string, string>> = {
    stderr: 'plugins.page.inspector.logs.source.stderr',
    reloaded: 'plugins.page.inspector.logs.source.reloaded',
    reload_error: 'plugins.page.inspector.logs.source.reload_error',
    ui_error: 'plugins.page.inspector.logs.source.ui_error',
    permission_widened: 'plugins.page.inspector.logs.source.permission_widened',
};

export function categorizeLogs(
    logsTail: readonly InspectorLogEntry[] | null | undefined,
    t: Translate,
): FormattedLogEntry[] {
    if (!Array.isArray(logsTail) || logsTail.length === 0) return [];
    return logsTail.map((entry, index) => {
        const source = entry.source || 'stderr';
        const sourceKey = Object.hasOwn(KNOWN_LOG_SOURCE_KEYS, source) ? KNOWN_LOG_SOURCE_KEYS[source] : undefined;
        const sourceLabel = sourceKey ? t(sourceKey) : source;
        const payload = entry.payload ?? {};
        const tsLabel = formatTimestamp(entry.ts);
        const key = `${index}:${source}:${entry.ts ?? 'nots'}:${entry.line ?? ''}`;

        if (source === 'stderr') {
            const text = asString(entry.line) ?? asString(payload.text) ?? '';
            return {
                key,
                source,
                sourceLabel,
                tone: 'neutral',
                tsLabel,
                title: text,
                detail: null,
            };
        }

        if (source === 'reloaded') {
            const timings = (payload.timings && typeof payload.timings === 'object'
                ? payload.timings
                : {}) as Readonly<Record<string, unknown>>;
            const total = asNumber(timings.total_ms);
            const stage = asNumber(timings.stage_ms);
            const stop = asNumber(timings.stop_ms);
            const start = asNumber(timings.start_ms);
            const changed = asStringArray(payload.changed);
            const unchanged = payload.unchanged === true;
            const title =
                total !== null
                    ? stage !== null && stop !== null && start !== null
                        ? t('plugins.page.inspector.dev_lease.reload_ms', {
                              total: Math.round(total),
                              stage: Math.round(stage),
                              stop: Math.round(stop),
                              start: Math.round(start),
                          })
                        : t('plugins.page.inspector.dev_lease.reload_total', { total: Math.round(total) })
                    : t('plugins.page.inspector.logs.source.reloaded');
            const detailParts: string[] = [];
            if (unchanged) detailParts.push(t('plugins.page.inspector.dev_lease.unchanged'));
            if (changed.length > 0) detailParts.push(changed.join(', '));
            const uiErr = asString(payload.ui_error);
            if (uiErr) detailParts.push(uiErr);
            return {
                key,
                source,
                sourceLabel,
                tone: payload.needs_approval === true ? 'warn' : 'ok',
                tsLabel,
                title,
                detail: detailParts.length > 0 ? detailParts.join(' | ') : null,
            };
        }

        if (source === 'permission_widened') {
            const widened = asStringArray(payload.widened);
            const reason = asString(payload.reason);
            return {
                key,
                source,
                sourceLabel,
                tone: 'warn',
                tsLabel,
                title: reason ?? t('plugins.page.inspector.dev_lease.widened'),
                detail:
                    widened.length > 0
                        ? t('plugins.page.inspector.dev_lease.widened_list', { names: widened.join(', ') })
                        : null,
            };
        }

        if (source === 'ui_error' || source === 'reload_error') {
            const code = asString(payload.code) ?? source;
            const path = asString(payload.path);
            const detail = asString(payload.detail);
            const parts = [path, detail].filter((v): v is string => v !== null);
            return {
                key,
                source,
                sourceLabel,
                tone: 'danger',
                tsLabel,
                title: code,
                detail: parts.length > 0 ? parts.join(': ') : null,
            };
        }

        return {
            key,
            source,
            sourceLabel,
            tone: 'neutral',
            tsLabel,
            title: asString(entry.line) ?? source,
            detail: Object.keys(payload).length > 0 ? JSON.stringify(payload) : null,
        };
    });
}

export function deriveDevLeaseSummary(
    snapshot: PluginInspectorSnapshot | null | undefined,
    plugin: Pick<CplugItem, 'state' | 'changedFiles'> | null | undefined,
    t: Translate,
): DevLeaseSummary {
    const lease = snapshot?.dev_lease ?? null;
    const logs = Array.isArray(snapshot?.logs_tail) ? snapshot!.logs_tail : [];
    const formattedLogs = categorizeLogs(logs, t);

    let lastReload: ReloadTimingsSummary | null = null;
    let widening: WideningAlert | null = null;
    const uiErrors: FormattedLogEntry[] = [];
    const reloadErrors: FormattedLogEntry[] = [];

    for (let i = 0; i < logs.length; i += 1) {
        const entry = logs[i]!;
        const payload = entry.payload ?? {};
        if (entry.source === 'reloaded') {
            const timings = (payload.timings && typeof payload.timings === 'object'
                ? payload.timings
                : {}) as Readonly<Record<string, unknown>>;
            const needsApproval = payload.needs_approval === true;
            lastReload = {
                totalMs: asNumber(timings.total_ms),
                stageMs: asNumber(timings.stage_ms),
                stopMs: asNumber(timings.stop_ms),
                startMs: asNumber(timings.start_ms),
                unchanged: payload.unchanged === true,
                needsApproval,
                digest: asString(payload.digest),
                changedFiles: asStringArray(payload.changed),
                ts: asNumber(entry.ts),
            };
            if (!needsApproval) {
                widening = null;
            }
        } else if (entry.source === 'permission_widened') {
            widening = {
                widened: asStringArray(payload.widened),
                reason: asString(payload.reason),
                ts: asNumber(entry.ts),
            };
        } else if (entry.source === 'ui_error') {
            const formatted = formattedLogs[i];
            if (formatted) uiErrors.push(formatted);
        } else if (entry.source === 'reload_error') {
            const formatted = formattedLogs[i];
            if (formatted) reloadErrors.push(formatted);
        }
    }

    const ttlSeconds = asNumber(lease?.ttl_remaining_seconds);
    const needsReconsent =
        plugin?.state === 'needs_approval' ||
        snapshot?.state === 'needs_approval' ||
        widening !== null ||
        lastReload?.needsApproval === true;

    return {
        active: lease?.active === true,
        sourceRealpath: asString(lease?.source_realpath),
        baselineSha: asString(lease?.baseline_sha),
        ttlSeconds,
        ttlLabel: ttlSeconds !== null ? formatDuration(ttlSeconds, t) : null,
        lastReload,
        widening,
        needsReconsent,
        uiErrors,
        reloadErrors,
    };
}

export function mergeSurfaces(
    cplugId: string,
    surfaces: InspectorSurfacesSummary | null | undefined,
    livePanels: readonly PanelEntry[],
): MergedSurfacesSummary {
    const matchingPanels = livePanels.filter((entry) => entry.plugin.cplugId === cplugId);
    const liveViews: MergedSurfaceView[] = matchingPanels.map((entry) => ({
        key: entry.key || `${entry.kind}:${entry.view}`,
        kind: entry.kind,
        title: entry.title,
        view: entry.view,
        mounted: true,
        declarative: entry.declarative === true,
    }));

    const activeFlags: SurfaceFlag[] = [];
    if (surfaces?.widget || liveViews.some((v) => v.declarative)) activeFlags.push('widget');
    if (surfaces?.panel || liveViews.some((v) => !v.declarative)) activeFlags.push('panel');
    if (surfaces?.bar) activeFlags.push('bar');
    if (surfaces?.settings) activeFlags.push('settings');

    const manifestViews = surfaces?.views ?? [];
    const tools = surfaces?.tools ?? [];
    const routes = surfaces?.routes ?? [];
    const timers = surfaces?.timers ?? [];
    const absentSurfaces = surfaces?.absent_surfaces ?? [];

    const totalActiveCount =
        activeFlags.length + liveViews.length + tools.length + routes.length + timers.length;

    return {
        activeFlags,
        livePanels: liveViews,
        manifestViews,
        tools,
        routes,
        timers,
        absentSurfaces,
        totalActiveCount,
    };
}

export function secretsSummary(
    secretsStatus: Readonly<Record<string, CplugSecretStatus>> | null | undefined,
): SecretStatusSummary[] {
    if (!secretsStatus) return [];
    return Object.keys(secretsStatus)
        .sort((a, b) => a.localeCompare(b))
        .map((name) => {
            const st = secretsStatus[name] ?? {};
            return {
                name,
                present: Boolean(st.present ?? st.secret_present),
                needsReentry: Boolean(st.needs_reentry),
            };
        });
}
