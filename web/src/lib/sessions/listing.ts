/* did not answer */
import type { ListingState } from './types';

export const DEFAULT_REASON = 'probe_error';

export function emptyListing(): ListingState {
    return { ok: true, reason: null, detail: null, sources: [] };
}

export function noteListingUnknown(
    state: ListingState,
    source: string,
    reason: string | null,
    detail: string | null,
): void {
    state.ok = false;
    if (!state.reason) state.reason = reason || DEFAULT_REASON;
    if (!state.detail) state.detail = detail || null;
    if (state.sources.indexOf(source) === -1) state.sources.push(source);
}

/* could not be determined */
export function statusFromError(err: unknown): number | null {
    const e = err as { status?: unknown; message?: unknown } | null | undefined;
    if (e && typeof e.status === 'number') {
        return e.status;
    }
    if (e && typeof e.message === 'string') {
        const m = e.message.match(/HTTP\s+(\d{3})/);
        if (m) return parseInt(m[1]!, 10);
        if (/Authentication required/i.test(e.message)) return 401;
    }
    return null;
}

export function listingReasonFromError(err: unknown, status: number | null): string {
    const d = (err as { detail?: unknown } | null | undefined)?.detail;
    if (d && typeof d === 'object') {
        const reason = (d as { listing_reason?: unknown }).listing_reason;
        if (typeof reason === 'string' && reason) return reason;
    }
    if (status === 401) return 'unauthorized';
    if (typeof status === 'number' && status > 0) return `http_${status}`;
    return 'network_error';
}
