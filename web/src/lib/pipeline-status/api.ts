import { authFetch } from '../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export type PipelineState = 'caught_up' | 'behind' | 'stalled' | 'rebuilding' | 'off';

export interface Lag {
    files: number;
    seconds: number;
}

export interface PluginStatus {
    lag: Lag;
    failures: number;
    last_error: string | null;
    rebuilding: boolean;
    last_delivery_at: number | null;
    runs: number;
}

export type RunScope = 'session' | 'project' | 'machine' | 'plugin';

export type RunOutcome = 'ok' | 'failed' | 'parked';

export interface RecentRun {
    plugin: string;
    contributor?: string | null;
    kind: 'delivery' | 'rebuild';
    scope: RunScope;
    session_uuid: string | null;
    session: string | null;
    project_id: number | null;
    project: string | null;
    conversation_id: string | null;
    family: string | null;
    trigger: string | null;
    finished_at: number;
    duration_ms: number | null;
    runs: number | null;
    events: number;
    outcome: RunOutcome;
    error: string | null;
    seeded?: boolean;
    detail?: { conversations: number; size_bytes: number } | null;
}

export interface KeyArea {
    scope: RunScope;
    session_uuid: string | null;
    session: string | null;
    project_id: number | null;
    project: string | null;
    conversation: string | null;
}

export interface RunningKey extends KeyArea {
    plugin: string;
    kind: 'delivery' | 'rebuild';
    family: string | null;
    trigger: string | null;
    started_at: number;
    running_s: number;
}

export interface QueuedKey extends KeyArea {
    plugins: string[];
    family: string;
    trigger: string;
    backoff: boolean;
    marked_at: number;
    waited_s: number;
    due_at: number | null;
}

export interface KeyQueue {
    items: QueuedKey[];
    total: number;
}

export interface PipelineStatus {
    state: PipelineState;
    lag: Lag;
    last_delivery_at: number | null;
    stalled_since: number | null;
    rebuilding: string[];
    plugins: Record<string, PluginStatus>;
    recent: RecentRun[];
    running: RunningKey[];
    queue: KeyQueue;
}

export async function fetchPipelineStatus(fetcher: Fetcher = authFetch): Promise<PipelineStatus> {
    const body = await fetcher<Partial<PipelineStatus> | null>('/pipeline/status');
    return {
        state: body?.state ?? 'off',
        lag: body?.lag ?? { files: 0, seconds: 0 },
        last_delivery_at: body?.last_delivery_at ?? null,
        stalled_since: body?.stalled_since ?? null,
        rebuilding: body?.rebuilding ?? [],
        plugins: body?.plugins ?? {},
        recent: Array.isArray(body?.recent) ? body.recent : [],
        running: Array.isArray(body?.running) ? body.running : [],
        queue: body?.queue && Array.isArray(body.queue.items)
            ? { items: body.queue.items, total: Math.max(body.queue.total ?? 0, body.queue.items.length) }
            : { items: [], total: 0 },
    };
}

export const rebuildPlugin = (plugin: string, fetcher: Fetcher = authFetch) =>
    fetcher<unknown>(`/pipeline/plugins/${encodeURIComponent(plugin)}/rebuild`, { method: 'POST' });
