import { ApiError, authFetch } from '../sdk';

const ROUTE = '/cplugs/save';

export type Fetcher = typeof authFetch;

export const BYTES_PER_GB = 1024 ** 3;
export const CAP_MIN_GB = 1;
export const CAP_MAX_GB = 32;

export interface Usage {
    readonly used_bytes: number;
    readonly cap_bytes: number;
    readonly conversations: number;
    readonly points: number;
    readonly current_backups: number;
    readonly pinned: number;
    readonly pinned_bytes: number;
}

export interface SaveSettings {
    readonly cap_gb: number;
    readonly cap_env_locked: boolean;
    readonly cap_env_var: string;
}

function hasNumbers(value: unknown, keys: readonly string[]): boolean {
    return !!value && typeof value === 'object' && keys.every((k) => typeof (value as Record<string, unknown>)[k] === 'number');
}

export async function fetchUsage(fetcher: Fetcher = authFetch): Promise<Usage> {
    const usage = await fetcher<Usage>(`${ROUTE}/summary`);
    if (!hasNumbers(usage, ['used_bytes', 'cap_bytes', 'points', 'conversations', 'pinned'])) {
        throw new Error('restore points did not answer with usage');
    }
    return usage;
}

export async function fetchSaveSettings(fetcher: Fetcher = authFetch): Promise<SaveSettings> {
    const settings = await fetcher<SaveSettings>(`${ROUTE}/settings`);
    if (!hasNumbers(settings, ['cap_gb'])) {
        throw new Error('restore points did not answer with settings');
    }
    return settings;
}

export function saveCap(capGb: number, fetcher: Fetcher = authFetch): Promise<Usage> {
    return fetcher<Usage>(`${ROUTE}/settings`, { method: 'PUT', body: JSON.stringify({ cap_gb: capGb }) });
}

export function gbText(bytes: number): string {
    return `${(bytes / BYTES_PER_GB).toFixed(1)} gb`;
}

export function sliderValue(capGb: number): number {
    return Math.max(CAP_MIN_GB, Math.round(capGb));
}

export function sliderMax(capGb: number): number {
    return Math.max(CAP_MAX_GB, Math.ceil(capGb));
}

export function dropsPoints(capGb: number, usedBytes: number): boolean {
    return capGb * BYTES_PER_GB < usedBytes;
}

export function errorText(error: unknown): string {
    if (error instanceof ApiError) {
        const detail = (error.payload as { detail?: unknown } | null)?.detail;
        if (typeof detail === 'string') return detail;
        if (detail && typeof detail === 'object' && typeof (detail as { detail?: unknown }).detail === 'string') {
            return (detail as { detail: string }).detail;
        }
        return error.message;
    }
    return error instanceof Error ? error.message : String(error);
}

export const CAPTURE_SCOPES = ['human', 'human+subsessions', 'all'] as const;
export type CaptureScope = (typeof CAPTURE_SCOPES)[number];

export interface ScopeView {
    readonly capture_scope: CaptureScope;
    readonly default: CaptureScope;
    readonly choices: readonly CaptureScope[];
}

const SCOPE = `${ROUTE}/capture-scope`;

export async function fetchCaptureScope(fetcher: Fetcher = authFetch): Promise<ScopeView> {
    const view = await fetcher<ScopeView>(SCOPE);
    if (!view || !(CAPTURE_SCOPES as readonly string[]).includes(view.capture_scope)) {
        throw new Error('restore points did not answer with a capture scope');
    }
    return view;
}

export function saveCaptureScope(value: CaptureScope, fetcher: Fetcher = authFetch): Promise<ScopeView> {
    return fetcher<ScopeView>(SCOPE, { method: 'PUT', body: JSON.stringify({ capture_scope: value }) });
}
