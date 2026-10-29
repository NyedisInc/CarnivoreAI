/* permission prompt */

console.log('[ToastSessionGroup Module] Loading...');

(function () {
    const KIND_BUCKET = {
        PermissionRequest: 'permission',
        Notification: 'input',
        Stop: 'unread',
    };

    const DEFAULT_BUCKET = 'input';

    const KEY_SUFFIX = '|session';

    let warned = false;

    function priorityKeys() {
        const summary = globalThis.SessionStatusSummary;
        const fold = summary && summary.SUMMARY_PRIORITY;
        if (!Array.isArray(fold) || fold.length === 0) {
            if (!warned) {
                warned = true;
                console.error(
                    '[ToastSessionGroup] session-status-summary.js has not '
                    + 'loaded, so the attention order is unavailable. Toasts '
                    + 'fall back to per-kind coalescing.');
            }
            return null;
        }
        return fold.map(function (entry) { return entry && entry.key; });
    }

    function bucketForKind(kind) {
        const bucket = KIND_BUCKET[kind];
        return bucket || DEFAULT_BUCKET;
    }

    function groupKey(toast) {
        if (!toast || !toast.session_id) return null;
        if (!priorityKeys()) return null;
        return String(toast.session_id) + KEY_SUFFIX;
    }

    function pick(toasts, severityOf) {
        if (!Array.isArray(toasts) || toasts.length === 0) return null;
        const order = priorityKeys();
        const rankOf = function (toast) {
            if (!order) return 0;
            const idx = order.indexOf(bucketForKind(toast && toast.kind));
            return idx === -1 ? order.length : idx;
        };
        const sevOf = typeof severityOf === 'function'
            ? function (toast) { return severityOf(toast && toast.kind); }
            : function () { return 0; };

        let winner = null;
        let winnerRank = Infinity;
        let winnerSev = -Infinity;
        for (let i = 0; i < toasts.length; i++) {
            const toast = toasts[i];
            if (!toast) continue;
            const rank = rankOf(toast);
            if (rank > winnerRank) continue;
            const sev = sevOf(toast);
            if (rank === winnerRank && sev < winnerSev) continue;
            winner = toast;
            winnerRank = rank;
            winnerSev = sev;
        }
        if (!winner) return null;

        let count = 0;
        for (let i = 0; i < toasts.length; i++) {
            if (toasts[i] && toasts[i].kind === winner.kind) count += 1;
        }
        return { winner: winner, count: count };
    }

    const api = {
        KIND_BUCKET: Object.assign({}, KIND_BUCKET),
        DEFAULT_BUCKET: DEFAULT_BUCKET,
        bucketForKind: bucketForKind,
        groupKey: groupKey,
        pick: pick,
    };

    globalThis.ToastSessionGroup = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    console.log('[ToastSessionGroup Module] Loaded');
})();
