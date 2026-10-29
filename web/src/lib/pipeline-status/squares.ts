import { compact, elapsed } from '../../opscenter/lib/format';
import { agoWords } from '../../opscenter/lib/run-chart';
import type { Lag, PipelineState, PipelineStatus, PluginStatus } from './api';
import type { Tone } from './model';

export const FALLBACK_ICON = 'chart';

const MANIFESTS = import.meta.glob<{ id: string; icon?: string }>('../../../../src/cplugs/*/cplug.json', {
    eager: true,
    import: 'default',
});

const CORE_ICONS: Readonly<Record<string, string>> = { deepsearch: 'deep-search' };

const ICONS: ReadonlyMap<string, string> = new Map([
    ...Object.entries(CORE_ICONS),
    ...Object.values(MANIFESTS).flatMap((m) => (m.icon ? [[m.id, m.icon] as const] : [])),
]);

export const pluginIcon = (id: string): string => ICONS.get(id) ?? FALLBACK_ICON;

export type SquareState = 'ok' | 'behind' | 'failing' | 'off';

export const SQUARE_TONE: Readonly<Record<SquareState, Tone>> = { ok: 'ok', behind: 'wait', failing: 'bad', off: 'off' };

export const squareStateKey = (state: SquareState): string => `pipeline.square.state.${state}`;

export interface PluginSquare {
    id: string;
    icon: string;
    state: SquareState;
    rebuilding: boolean;
    lag: Lag;
    failures: number;
    lastError: string | null;
    lastDeliveryAt: number | null;
    runs: number;
}

export interface DetailLine {
    kind: 'backlog' | 'delivery' | 'error' | 'runs';
    key: string;
    params: Record<string, string | number>;
}

export function squareState(engine: PipelineState, plugin: PluginStatus): SquareState {
    if (engine === 'off') return 'off';
    if (plugin.rebuilding) return 'behind';
    if (plugin.failures > 0 || (engine === 'stalled' && plugin.lag.files > 0)) return 'failing';
    return plugin.lag.files > 0 ? 'behind' : 'ok';
}

export function contributedSquares(status: PipelineStatus): PluginSquare[] {
    const seen = new Set(Object.keys(status.plugins));
    const squares: PluginSquare[] = [];
    for (const run of status.recent) {
        if (run.scope !== 'plugin' || seen.has(run.plugin)) continue;
        seen.add(run.plugin);
        const failed = run.outcome === 'failed';
        squares.push({
            id: run.plugin,
            icon: pluginIcon(run.contributor ?? run.plugin),
            state: failed ? 'failing' : 'ok',
            rebuilding: false,
            lag: { files: 0, seconds: 0 },
            failures: failed ? 1 : 0,
            lastError: failed ? run.error : null,
            lastDeliveryAt: run.finished_at,
            runs: run.runs ?? 0,
        });
    }
    return squares;
}

export function pluginSquares(status: PipelineStatus): PluginSquare[] {
    const registry = Object.entries(status.plugins).map(([id, plugin]) => ({
        id,
        icon: pluginIcon(id),
        state: squareState(status.state, plugin),
        rebuilding: plugin.rebuilding,
        lag: plugin.lag,
        failures: plugin.failures,
        lastError: plugin.last_error,
        lastDeliveryAt: plugin.last_delivery_at,
        runs: plugin.runs,
    }));
    return [...registry, ...contributedSquares(status)];
}

export function detailLines(square: PluginSquare, nowS: number): DetailLine[] {
    const backlog: DetailLine = square.lag.files > 0
        ? { kind: 'backlog', key: 'pipeline.square.backlog', params: { files: square.lag.files, lag: elapsed(square.lag.seconds) } }
        : { kind: 'backlog', key: 'pipeline.square.no_backlog', params: {} };
    const delivery: DetailLine = square.lastDeliveryAt === null
        ? { kind: 'delivery', key: 'pipeline.square.no_delivery', params: {} }
        : { kind: 'delivery', key: 'pipeline.status.last', params: { when: agoWords(Math.max(0, nowS - square.lastDeliveryAt)) } };
    let error: DetailLine = { kind: 'error', key: 'pipeline.square.no_errors', params: {} };
    if (square.failures > 0) {
        error = square.lastError
            ? { kind: 'error', key: 'pipeline.square.failing', params: { count: square.failures, error: square.lastError } }
            : { kind: 'error', key: 'pipeline.square.failing_count', params: { count: square.failures } };
    }
    return [backlog, delivery, error, { kind: 'runs', key: 'pipeline.square.runs', params: { count: compact(square.runs) } }];
}
