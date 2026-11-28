import { authFetch } from '../sdk';
import { savePluginSettings, type Fetcher } from './plugin-settings-api';

export const OFFLOAD_TOPIC = 'cplug.save.offload';
export const OFFLOAD_SETTING = 'offloadEnabled';
export const PAGE_SIZE = 50;

const ROUTE = '/cplugs/save/offload';

export type OffloadState = 'failed' | 'conflict' | 'restoring' | 'offloading' | 'offloaded';

export interface OffloadRow {
    readonly kind: 'session' | 'conversation';
    readonly session_uuid: string | null;
    readonly conversation_id: string | null;
    readonly title: string | null;
    readonly project_id: number | null;
    readonly project: string | null;
    readonly conversations: number;
    readonly bytes: number;
    readonly offloaded_at: number;
    readonly state: OffloadState;
    readonly error: string;
    readonly error_code?: string;
    readonly error_path?: string;
}

export type BatchState = 'running' | 'done' | 'stopped' | 'failed';

export interface OffloadBatch {
    readonly id: string;
    readonly state: BatchState;
    readonly planned: number;
    readonly offloaded: number;
    readonly skipped: number;
    readonly failed: number;
    readonly bytes: number;
}

export type RestoreBatchState = 'running' | 'done' | 'stopped';

export interface OffloadRestoreItem {
    readonly kind: 'session' | 'conversation';
    readonly id: string;
    readonly status: 'restored' | 'failed';
    readonly code: string;
    readonly detail: string;
}

export interface OffloadRestoreBatch {
    readonly id: string;
    readonly state: RestoreBatchState;
    readonly planned: number;
    readonly restored: number;
    readonly failed: number;
    readonly bytes: number;
    readonly items: readonly OffloadRestoreItem[];
}

export interface OffloadPage {
    readonly enabled: boolean;
    readonly batch: OffloadBatch | null;
    readonly restore_batch: OffloadRestoreBatch | null;
    readonly totals: { readonly rows: number; readonly conversations: number; readonly bytes: number };
    readonly rows: readonly OffloadRow[];
    readonly next_cursor: string | null;
}

export async function fetchOffloaded(cursor: string | null, fetcher: Fetcher = authFetch): Promise<OffloadPage> {
    const query = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (cursor) query.set('cursor', cursor);
    const body = await fetcher<Partial<OffloadPage>>(`${ROUTE}?${query}`);
    return {
        enabled: body?.enabled === true,
        batch: body?.batch ?? null,
        restore_batch: body?.restore_batch ? { ...body.restore_batch, items: body.restore_batch.items ?? [] } : null,
        totals: body?.totals ?? { rows: 0, conversations: 0, bytes: 0 },
        rows: Array.isArray(body?.rows) ? body.rows : [],
        next_cursor: body?.next_cursor ?? null,
    };
}

export async function restoreOffloaded(row: OffloadRow, fetcher: Fetcher = authFetch): Promise<readonly { conversation_id: string; status: string }[]> {
    const path = row.kind === 'session' ? `sessions/${encodeURIComponent(row.session_uuid ?? '')}` : `conversations/${encodeURIComponent(row.conversation_id ?? '')}`;
    const body = await fetcher<{ conversations?: readonly { conversation_id: string; status: string }[] }>(`${ROUTE}/${path}/restore`, { method: 'POST', body: JSON.stringify({}) });
    return body?.conversations ?? [];
}

export async function stopBatch(batchId: string, fetcher: Fetcher = authFetch): Promise<void> {
    await fetcher(`${ROUTE}/batch/${encodeURIComponent(batchId)}/stop`, { method: 'POST', body: JSON.stringify({}) });
}

export async function startRestoreBatch(rows: readonly OffloadRow[], fetcher: Fetcher = authFetch): Promise<OffloadRestoreBatch> {
    const session_uuids = rows.filter((r) => r.kind === 'session' && r.session_uuid).map((r) => r.session_uuid as string);
    const conversation_ids = rows.filter((r) => r.kind === 'conversation' && r.conversation_id).map((r) => r.conversation_id as string);
    return fetcher<OffloadRestoreBatch>(`${ROUTE}/restore-batch`, { method: 'POST', body: JSON.stringify({ session_uuids, conversation_ids }) });
}

export async function stopRestoreBatch(batchId: string, fetcher: Fetcher = authFetch): Promise<void> {
    await fetcher(`${ROUTE}/restore-batch/${encodeURIComponent(batchId)}/stop`, { method: 'POST', body: JSON.stringify({}) });
}

export function keepPicked(picked: readonly string[], rows: readonly OffloadRow[]): readonly string[] {
    const listed = new Set(rows.map(rowKey));
    return picked.filter((key) => listed.has(key));
}

export async function saveOffloadSwitch(on: boolean, fetcher: Fetcher = authFetch): Promise<void> {
    await savePluginSettings(() => ({ [OFFLOAD_SETTING]: on }), fetcher);
}

const PLUGIN_ROUTE = '/cplugs/save';

export async function readOffloadSwitch(fetcher: Fetcher = authFetch): Promise<boolean> {
    const current = await fetcher<{ settings?: Record<string, unknown> }>(PLUGIN_ROUTE);
    return current?.settings?.[OFFLOAD_SETTING] === true;
}

export function rowKey(row: OffloadRow): string {
    return `${row.kind}:${row.session_uuid ?? row.conversation_id ?? ''}`;
}

export function appendNew(shown: readonly OffloadRow[], page: readonly OffloadRow[]): readonly OffloadRow[] {
    const seen = new Set(shown.map(rowKey));
    return [...shown, ...page.filter((r) => !seen.has(rowKey(r)))];
}

const ON_DISK: readonly string[] = ['written', 'already_present', 'disk_newer'];

export function backCount(outcomes: readonly { status: string }[]): number {
    return outcomes.filter((o) => ON_DISK.includes(o.status)).length;
}
