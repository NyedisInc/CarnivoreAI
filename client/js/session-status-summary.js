
console.log('[SessionStatusSummary Module] Loading...');

(function () {
    const SUMMARY_PRIORITY = [
        { key: 'permission', inner: 'waiting-permission' },
        { key: 'input', inner: 'waiting-input' },
        { key: 'working', inner: 'working' },
        { key: 'unread', inner: 'done' },
        { key: 'done', inner: 'idle' },
        { key: 'dead', inner: 'dead' },
        { key: 'unknown', inner: 'unknown' },
    ];

    /* waiting on the user */
    const ACTIVE_BUCKETS = ['working', 'permission', 'input'];

    function signalsFor(row) {
        const r = row || {};
        const status =
            (typeof r.activity_status === 'string' && r.activity_status)
                ? r.activity_status
                : ((typeof r.status === 'string' && r.status) ? r.status : undefined);
        return {
            activity_status: status,
            unread: !!r.unread,
            startup_gate: r.startup_gate,
        };
    }

    function bucketFor(led) {
        const l = led || {};
        if (l.inner === 'waiting-permission') return 'permission';
        if (l.inner === 'waiting-input' || l.inner === 'notice') return 'input';
        if (l.inner === 'working') return 'working';
        // without.
        if (l.outer === 'unread') return 'unread';
        if (l.inner === 'idle' || l.inner === 'done') return 'done';
        if (l.inner === 'dead' || l.inner === 'disconnected') return 'dead';
        return 'unknown';
    }

    function outerFor(present, winner) {
        for (let i = 0; i < ACTIVE_BUCKETS.length; i++) {
            if (present[ACTIVE_BUCKETS[i]]) return 'active';
        }
        if (present.unread) return 'unread';
        if (winner === 'unknown') return 'dim';
        if (winner === 'done') return 'steady';
        return 'off';
    }

    function summarizeStates(children) {
        const rows = Array.isArray(children) ? children : [];
        const present = Object.create(null);
        let unreadCount = 0;
        let total = 0;
        let inputIsStopped = false;

        for (let i = 0; i < rows.length; i++) {
            const row = rows[i];
            if (!row || typeof row !== 'object' || row.kind === 'browser') continue;
            total += 1;
            const led = globalThis.StatusLed.ledStateFor(signalsFor(row));
            const bucket = bucketFor(led);
            present[bucket] = true;
            if (bucket === 'input' && led.inner === 'waiting-input') {
                inputIsStopped = true;
            }
            if (row.unread) unreadCount += 1;
        }

        if (total === 0) {
            return {
                inner: 'unknown',
                outer: 'dim',
                bucket: 'unknown',
                unreadCount: 0,
                total: 0,
            };
        }

        for (let i = 0; i < SUMMARY_PRIORITY.length; i++) {
            const entry = SUMMARY_PRIORITY[i];
            if (present[entry.key]) {
                const inner =
                    entry.key === 'input' && !inputIsStopped
                        ? 'notice'
                        : entry.inner;
                return {
                    inner: inner,
                    outer: outerFor(present, entry.key),
                    bucket: entry.key,
                    unreadCount: unreadCount,
                    total: total,
                };
            }
        }

        return {
            inner: 'unknown',
            outer: 'dim',
            bucket: 'unknown',
            unreadCount: unreadCount,
            total: total,
        };
    }

    function accessor() {
        const i18n = globalThis.CloudeI18n;
        if (i18n && typeof i18n.t === 'function') {
            return function (key, params) {
                return i18n.t(key, params);
            };
        }
        console.error(
            '[SessionStatusSummary] no string layer on globalThis.CloudeI18n; '
            + 'rendering catalog keys. Is client/js/i18n/boot.js loaded?',
        );
        return function (key) {
            return key;
        };
    }

    function summaryLabel(s) {
        const labels = globalThis.CloudeLabels;
        const t = accessor();
        if (!labels || typeof labels.sessionSummaryLabel !== 'function') {
            console.error(
                '[SessionStatusSummary] no shared label builder on '
                + 'globalThis.CloudeLabels; is client/js/i18n/boot.js loaded?',
            );
            return t('session.summary.none');
        }
        return labels.sessionSummaryLabel(s, t);
    }

    function summaryHtml(children, opts) {
        const o = opts || {};
        const s = summarizeStates(children);
        return globalThis.StatusLed.ledHtml({
            inner: s.inner,
            outer: s.outer,
            size: o.size,
            title: summaryLabel(s),
        });
    }

    const api = {
        SUMMARY_PRIORITY: SUMMARY_PRIORITY.slice(),
        summarizeStates: summarizeStates,
        summaryHtml: summaryHtml,
        summaryLabel: summaryLabel,
        bucketFor: bucketFor,
        outerFor: outerFor,
        signalsFor: signalsFor,
    };

    globalThis.SessionStatusSummary = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    console.log('[SessionStatusSummary Module] Loaded');
})();
