/* did not answer */

export const LISTING_KEYS = {
    /* CANNOT DETERMINE */
    detailUnauthorized: 'session.listing.detail.unauthorized',
    detailTmuxUnreadable: 'session.listing.detail.tmux_unreadable',
    detailHttpStatus: 'session.listing.detail.http_status',
    sessionsMalformed: 'session.listing.detail.malformed_sessions',
    recordsMalformed: 'session.listing.detail.malformed_records',
    projectsLoadFailed: 'project.list.load_failed',
    unreachable: 'error.server_unreachable',
};

export function serverDetail(err) {
    const d = err && err.detail;
    if (d && typeof d === 'object') {
        if (typeof d.listing_detail === 'string' && d.listing_detail) return d.listing_detail;
        if (typeof d.message === 'string' && d.message) return d.message;
    }
    return null;
}

/* CANNOT DETERMINE */
export function listingDetail(err, status, t) {
    const fromServer = serverDetail(err);
    if (fromServer) return fromServer;
    if (status === 401) return t(LISTING_KEYS.detailUnauthorized);
    if (status === 503) return t(LISTING_KEYS.detailTmuxUnreadable);
    if (typeof status === 'number' && status > 0) {
        return t(LISTING_KEYS.detailHttpStatus, { status });
    }
    if (err && typeof err.message === 'string' && err.message) return err.message;
    return t(LISTING_KEYS.unreachable);
}

export function sessionsMalformedDetail(t) {
    return t(LISTING_KEYS.sessionsMalformed);
}

export function recordsMalformedDetail(t) {
    return t(LISTING_KEYS.recordsMalformed);
}

export function attributionFailedDetail(error, t) {
    if (error && typeof error.message === 'string' && error.message) return error.message;
    return t(LISTING_KEYS.unreachable);
}

export function projectsLoadFailed(error, t) {
    const reason = (error && typeof error.message === 'string' && error.message)
        ? error.message
        : t(LISTING_KEYS.unreachable);
    return t(LISTING_KEYS.projectsLoadFailed, { reason });
}
