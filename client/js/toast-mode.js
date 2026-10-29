
console.log('[ToastMode Module] Loading...');

(function () {
    'use strict';

    var FIELD = 'toast_mode';
    var COMPACT = 'compact';
    var DETAILED = 'detailed';

    function t(key, params) {
        var i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key, params) : key;
    }

    function current() {
        var bridge = globalThis.PreferenceBridge;
        if (!bridge || typeof bridge.read !== 'function') return COMPACT;
        return bridge.read(FIELD, function () { return COMPACT; }) === DETAILED
            ? DETAILED : COMPACT;
    }

    function isDetailed() {
        return current() === DETAILED;
    }

    function instantOf(toast) {
        var ms = toast && toast.created_at ? Date.parse(toast.created_at) : NaN;
        return Number.isFinite(ms) ? ms : -Infinity;
    }

    function pickLatest(toasts) {
        var list = Array.isArray(toasts) ? toasts : [];
        var winner = null;
        var best = -Infinity;
        for (var i = 0; i < list.length; i += 1) {
            var at = instantOf(list[i]);
            if (winner === null || at >= best) {
                winner = list[i];
                best = at;
            }
        }
        return { winner: winner, count: list.length };
    }

    function headline(toast) {
        var detail = toast && toast.detail;
        var reason = detail && detail.reason;
        if (reason === 'permission') {
            if (detail.tool && detail.target) {
                return t('toast.detailed.permission_tool_target',
                    { tool: detail.tool, target: detail.target });
            }
            if (detail.tool) return t('toast.detailed.permission_tool', { tool: detail.tool });
            return t('toast.detailed.permission');
        }
        if (reason === 'question' || reason === 'plan_approval'
            || reason === 'input' || reason === 'turn_ended') {
            return t('toast.detailed.' + reason);
        }
        return (toast && toast.title) || '';
    }

    function snippet(toast) {
        var detail = toast && toast.detail;
        if (detail && typeof detail.snippet === 'string' && detail.snippet) {
            return detail.snippet;
        }
        return (toast && toast.body) || null;
    }

    function waitingCount(groups) {
        var seen = new Set();
        (groups || []).forEach(function (g) {
            var sid = g && g.winner && g.winner.session_id;
            if (sid && !g.winner.local) seen.add(sid);
        });
        return seen.size;
    }

    function renderWaiting(groups, container, anchor) {
        var row = container.querySelector('.toast-waiting');
        var n = isDetailed() ? waitingCount(groups) : 0;
        if (n < 2) {
            if (row) row.remove();
            return null;
        }
        if (!row) {
            row = document.createElement('div');
            row.className = 'toast-waiting';
            row.setAttribute('role', 'status');
        }
        row.dataset.count = String(n);
        row.textContent = t('toast.detailed.waiting', { count: n });
        var before = anchor ? anchor.nextSibling : container.firstChild;
        if (before !== row) container.insertBefore(row, before);
        return row;
    }

    function repaint() {
        var mgr = globalThis.ToastManager;
        if (mgr && typeof mgr._scheduleRender === 'function') mgr._scheduleRender();
    }

    function followSetting() {
        var bridge = globalThis.PreferenceBridge;
        if (!bridge || typeof bridge.follow !== 'function') return;
        bridge.follow(FIELD, repaint);
    }

    var HYDRATION_POLL_MS = 250;
    var HYDRATION_WAIT_MS = 60000;

    /*  hidden  */
    function repaintOnHydration() {
        var waited = 0;
        var timer = setInterval(function () {
            waited += HYDRATION_POLL_MS;
            var prefs = globalThis.Preferences;
            var ready = prefs && typeof prefs.status === 'function' && prefs.status() === prefs.HYDRATED;
            if (ready || waited >= HYDRATION_WAIT_MS) {
                clearInterval(timer);
                if (ready && isDetailed()) repaint();
            }
        }, HYDRATION_POLL_MS);
    }

    var api = {
        FIELD: FIELD,
        COMPACT: COMPACT,
        DETAILED: DETAILED,
        current: current,
        isDetailed: isDetailed,
        pickLatest: pickLatest,
        headline: headline,
        snippet: snippet,
        waitingCount: waitingCount,
        renderWaiting: renderWaiting,
    };
    globalThis.ToastMode = api;
    followSetting();
    repaintOnHydration();
    console.log('[ToastMode Module] Loaded');
})();
