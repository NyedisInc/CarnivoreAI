
interface ApiShaped {
    status?: unknown;
    body?: { code?: unknown; detail?: { code?: unknown } | string | null } | null;
    message?: unknown;
}

export interface RefusalQuery {
    code?: string;
    status?: number;
    phrase?: string;
}

export function refusalStatus(error: unknown): number | null {
    const status = (error as ApiShaped | null)?.status;
    return typeof status === 'number' ? status : null;
}

export function refusalCode(error: unknown): string | null {
    const body = (error as ApiShaped | null)?.body;
    if (!body) return null;
    if (typeof body.code === 'string') return body.code;
    const detail = body.detail;
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') return detail.code;
    return null;
}

export function refusedWith(error: unknown, query: RefusalQuery): boolean {
    if (query.code !== undefined && refusalCode(error) === query.code) return true;
    const status = refusalStatus(error);
    if (status !== null && query.status !== undefined && status !== query.status) return false;
    if (query.phrase === undefined) return status !== null && status === query.status;
    const message = (error as ApiShaped | null)?.message;
    const text = typeof message === 'string' ? message : String(error ?? '');
    return text.toLowerCase().includes(query.phrase.toLowerCase());
}

export const SERVER_PHRASE = {
    nameInUse: 'already in use',
    invalidSessionName: 'Invalid session name',
} as const;
