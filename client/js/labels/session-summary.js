
export const SUMMARY_KEYS = {
    none: 'session.summary.none',
    bucketPrefix: 'session.summary.bucket.',
    sessions: 'session.summary.sessions',
    unread: 'session.summary.unread_count',
    line: 'session.summary.line',
    lineWithUnread: 'session.summary.line_with_unread',
};

export function sessionSummaryLabel(summary, t) {
    const s = summary || {};
    const total = typeof s.total === 'number' ? s.total : 0;
    const unread = typeof s.unreadCount === 'number' ? s.unreadCount : 0;

    if (total === 0) return t(SUMMARY_KEYS.none);

    const bucket = t(SUMMARY_KEYS.bucketPrefix + String(s.bucket));
    const sessions = t(SUMMARY_KEYS.sessions, { count: total });
    if (unread > 0) {
        return t(SUMMARY_KEYS.lineWithUnread, {
            bucket,
            sessions,
            unread: t(SUMMARY_KEYS.unread, { count: unread }),
        });
    }
    return t(SUMMARY_KEYS.line, { bucket, sessions });
}
