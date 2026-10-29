import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface PresetField {
    readonly name: string;
    readonly kind: 'text' | 'choice' | 'bool';
    readonly choices: readonly string[];
    readonly default: unknown;
    readonly required: boolean;
}

export interface Preset {
    readonly id: string;
    readonly label: string;
    readonly kind: 'local' | 'cloud' | 'cli';
    readonly capabilities: Readonly<Record<string, readonly string[]>>;
    readonly base_url: string;
    readonly auth: string;
    readonly key_required: boolean;
    readonly auth_choices: readonly string[];
    readonly fields: readonly PresetField[];
    readonly docs_url: string;
    readonly default_models: readonly string[];
    readonly model_source: string;
    readonly custom: boolean;
}

export interface ModelOverride {
    capabilities: string[];
    flags: string[];
    enabled: boolean;
}

export interface Connection {
    readonly id: string;
    readonly preset: string;
    readonly label: string;
    readonly base_url: string;
    readonly options: Readonly<Record<string, unknown>>;
    readonly enabled: boolean;
    readonly key_host: string | null;
    readonly key_hint: string;
    readonly has_key: boolean;
    readonly models: Readonly<Record<string, ModelOverride>>;
}

export interface TargetRef {
    connection: string;
    model: string | null;
    voice: string | null;
}

export interface AiConfig {
    readonly revision: number;
    readonly connections: readonly Connection[];
    readonly defaults: Readonly<Record<string, TargetRef>>;
    readonly features: Readonly<Record<string, TargetRef>>;
}

export interface ModelInfo {
    readonly id: string;
    readonly capabilities: readonly string[];
    readonly flags: readonly string[];
    readonly label: string;
    readonly meta: Readonly<Record<string, unknown>>;
    readonly context_length?: number | null;
    readonly price_in?: number | null;
    readonly price_out?: number | null;
    readonly inputs?: readonly string[];
    readonly outputs?: readonly string[];
}

export interface RecentModel {
    readonly model: string;
    readonly capability: string;
}

export interface ModelList {
    readonly models: ModelInfo[];
    readonly recent: RecentModel[];
}

export interface TestResult {
    readonly ok: boolean;
    readonly capability: string;
    readonly latency_ms: number | null;
    readonly model: string | null;
    readonly detail: string;
    readonly audio: string | null;
    readonly audio_mime: string;
}

export interface MediaItem {
    readonly url: string;
    readonly mime: string;
    readonly width: number | null;
    readonly height: number | null;
    readonly duration_s: number | null;
    readonly data: string | null;
}

export interface Feature {
    readonly id: string;
    readonly capability: string;
    readonly label_key: string;
    readonly description_key: string | null;
    readonly target: TargetRef | null;
    readonly group?: string | null;
    readonly owner?: FeatureOwner | null;
    readonly hidden?: boolean;
}

export interface FeatureOwner {
    readonly id: string;
    readonly label_key: string;
    readonly href: string;
    readonly control: string | null;
    /* could not be read */
    readonly overridden: boolean | null;
}

export interface CallRow {
    readonly id: number;
    readonly ts: number;
    readonly feature: string | null;
    readonly capability: string;
    readonly connection_id: string | null;
    readonly preset: string | null;
    readonly model: string | null;
    readonly ok: number;
    readonly latency_ms: number | null;
    readonly input_tokens: number | null;
    readonly output_tokens: number | null;
    readonly cost_usd: number | null;
    readonly error: string | null;
}

export interface CallFilters {
    range: '24h' | '7d' | '30d';
    feature: string;
    connection: string;
    model: string;
    result: '' | 'ok' | 'error';
}

export interface CallsPage {
    readonly calls: CallRow[];
    readonly total: number;
    readonly start: number;
    readonly latest: number;
    readonly next: number | null;
    readonly prev: number | null;
}

export interface SpendRow {
    readonly key: string;
    readonly calls: number;
    readonly spend: number;
}

export interface CallsSummary {
    readonly range: string;
    readonly calls: number;
    readonly errors: number;
    readonly spend: number;
    readonly tokens_in: number;
    readonly tokens_out: number;
    readonly median_ms: number | null;
    readonly p95_ms: number | null;
    readonly by_feature: SpendRow[];
    readonly by_model: SpendRow[];
    readonly options: { readonly feature: string[]; readonly connection: string[]; readonly model: string[] };
}

export interface LedgerAccount {
    readonly id: string;
    readonly name: string;
    readonly provider: string;
}

export interface CreateBody {
    preset: string;
    label: string;
    base_url: string;
    options: Record<string, unknown>;
    key?: string;
    expected_revision: number;
}

export interface PatchBody {
    label?: string;
    base_url?: string;
    options?: Record<string, unknown>;
    enabled?: boolean;
    models?: Record<string, ModelOverride>;
    key?: string;
    expected_revision: number;
}

const json = (value: unknown): string => JSON.stringify(value);
const id = encodeURIComponent;

export const isStale = (error: unknown): boolean => error instanceof ApiError && error.status === 409;

export async function fetchPresets(fetcher: Fetcher = authFetch): Promise<Preset[]> {
    const body = await fetcher<{ presets?: Preset[] } | null>('/ai/presets');
    return Array.isArray(body?.presets) ? body.presets : [];
}

export async function fetchConfig(fetcher: Fetcher = authFetch): Promise<AiConfig> {
    const body = await fetcher<Partial<AiConfig> | null>('/ai/connections');
    return { revision: body?.revision ?? 0, connections: body?.connections ?? [], defaults: body?.defaults ?? {}, features: body?.features ?? {} };
}

export const createConnection = (body: CreateBody, fetcher: Fetcher = authFetch) =>
    fetcher<{ revision: number; connection: Connection }>('/ai/connections', { method: 'POST', body: json(body) });

export const patchConnection = (connection: string, body: PatchBody, fetcher: Fetcher = authFetch) =>
    fetcher<{ revision: number; connection: Connection }>(`/ai/connections/${id(connection)}`, { method: 'PATCH', body: json(body) });

export const deleteConnection = (connection: string, revision: number, fetcher: Fetcher = authFetch) =>
    fetcher<{ revision: number }>(`/ai/connections/${id(connection)}?expected_revision=${revision}`, { method: 'DELETE' });

export const clearKey = (connection: string, revision: number, fetcher: Fetcher = authFetch) =>
    fetcher<{ revision: number; connection: Connection }>(`/ai/connections/${id(connection)}/key?expected_revision=${revision}`, { method: 'DELETE' });

export const testConnection = (connection: string, capability: string, model: string | null, fetcher: Fetcher = authFetch) =>
    fetcher<TestResult>(`/ai/connections/${id(connection)}/test`, { method: 'POST', body: json({ capability, model }) });

export const fetchModels = async (connection: string, refresh = false, fetcher: Fetcher = authFetch): Promise<ModelList> => {
    const body = await fetcher<{ models?: ModelInfo[]; recent?: RecentModel[] }>(`/ai/connections/${id(connection)}/models?refresh=${refresh}`);
    return { models: body?.models ?? [], recent: body?.recent ?? [] };
};

export const fetchFeatures = async (fetcher: Fetcher = authFetch): Promise<Feature[]> =>
    (await fetcher<{ features?: Feature[] }>('/ai/features'))?.features ?? [];

export const putDefault = (capability: string, target: TargetRef | null, revision: number, fetcher: Fetcher = authFetch) =>
    fetcher<{ revision: number }>(`/ai/routing/defaults/${id(capability)}`, { method: 'PUT', body: json({ target, expected_revision: revision }) });

export const putFeature = (feature: string, target: TargetRef | null, revision: number, fetcher: Fetcher = authFetch) =>
    fetcher<{ revision: number }>(`/ai/routing/features/${id(feature)}`, { method: 'PUT', body: json({ target, expected_revision: revision }) });

export const fetchCallsPage = async (
    filters: CallFilters, limit: number, cursor: { before?: number; after?: number } = {}, fetcher: Fetcher = authFetch,
): Promise<CallsPage> => {
    const q = new URLSearchParams({ limit: String(limit), range: filters.range });
    for (const key of ['feature', 'connection', 'model', 'result'] as const) if (filters[key]) q.set(key, filters[key]);
    if (cursor.before !== undefined) q.set('before', String(cursor.before));
    if (cursor.after !== undefined) q.set('after', String(cursor.after));
    const body = await fetcher<Partial<CallsPage>>(`/ai/calls?${q}`);
    return { calls: body?.calls ?? [], total: body?.total ?? 0, start: body?.start ?? 0, latest: body?.latest ?? 0, next: body?.next ?? null, prev: body?.prev ?? null };
};

export const fetchCallsSummary = async (range: CallFilters['range'], fetcher: Fetcher = authFetch): Promise<CallsSummary | null> =>
    (await fetcher<CallsSummary>(`/ai/calls/summary?range=${range}`)) ?? null;

export const generateMedia = (connection: string, model: string | null, capability: string, prompt: string, fetcher: Fetcher = authFetch) =>
    fetcher<{ items: MediaItem[] }>('/ai/generate', { method: 'POST', body: json({ connection, model, capability, prompt }) });

export async function fetchLedgerAccounts(fetcher: Fetcher = authFetch): Promise<LedgerAccount[]> {
    const rows = await fetcher<LedgerAccount[] | null>('/provider-ledger/accounts');
    return Array.isArray(rows) ? rows : [];
}
