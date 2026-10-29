/* CANNOT DETERMINE did not answer */

export interface ListingVerdict {
    ok: boolean;
    reason?: string | null;
    detail?: string | null;
}

interface ProbeError {
    detail?: unknown;
    message?: unknown;
}

export function esc(value: unknown): string {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
}

export function reasonFromError(err: unknown, status: number | null): string {
    const d = (err as ProbeError | null)?.detail as Record<string, unknown> | undefined;
    if (d && typeof d === 'object' && typeof d.listing_reason === 'string' && d.listing_reason) {
        return d.listing_reason;
    }
    if (status === 401) return 'unauthorized';
    if (typeof status === 'number' && status > 0) return `http_${status}`;
    return 'network_error';
}

/* could not be reached */
export function detailFromError(err: unknown, status: number | null): string {
    const e = err as ProbeError | null;
    const d = e?.detail as Record<string, unknown> | undefined;
    if (d && typeof d === 'object') {
        if (typeof d.listing_detail === 'string' && d.listing_detail) return d.listing_detail;
        if (typeof d.message === 'string' && d.message) return d.message;
    }
    if (status === 401) return 'sign in again to see your sessions';
    if (status === 503) return 'the server could not read the tmux session list';
    if (typeof status === 'number' && status > 0) return `the server answered HTTP ${status}`;
    if (e && typeof e.message === 'string' && e.message) return e.message;
    return 'the server could not be reached';
}

export function fromError(err: unknown, status: number | null): ListingVerdict {
    return { ok: false, reason: reasonFromError(err, status), detail: detailFromError(err, status) };
}

/* CANNOT DETERMINE */
export function attentionHtml(listing: ListingVerdict | null | undefined): string {
    if (!listing || listing.ok) return '';
    const reason = esc(listing.reason || 'probe_error');
    const detail = esc(listing.detail || 'the server could not be reached');
    return (
        `<div class="session-sidebar-attention" role="status" `
        + `data-listing-ok="0" data-listing-reason="${reason}">`
        + '<div class="session-sidebar-attention__head">NEEDS ATTENTION</div>'
        + '<div class="session-sidebar-attention__title">CANNOT DETERMINE which sessions exist</div>'
        + `<div class="session-sidebar-attention__detail">${detail} (${reason})</div>`
        + '</div>'
    );
}
