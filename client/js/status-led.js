/* box-shadow */

console.log('[StatusLed Module] Loading...');

(function () {
    const INNER_STATES = [
        'working',
        'waiting-permission',
        'waiting-input',
        'notice',
        'idle',
        'done',
        'dead',
        'disconnected',
        'asleep',
        'asleep-unread',
        'limit',
        'unknown',
    ];

    const OUTER_STATES = ['active', 'steady', 'unread', 'off', 'dim'];

    /** @type {string} Fallback inner state for any unrecognised input. */
    const INNER_FALLBACK = 'unknown';

    /** @type {string} Fallback outer state for any unrecognised input. */
    const OUTER_FALLBACK = 'dim';

    const INNER_LABELS = {
        working: 'working',
        'waiting-permission': 'stopped - waiting on your permission',
        'waiting-input': 'stopped - waiting on you',
        notice: 'still working - wants your attention',
        idle: 'idle - already read',
        done: 'done',
        dead: 'dead - the process exited',
        disconnected: 'disconnected - no live connection to this session',
        asleep: 'asleep - stopped to free memory, wake it from the session menu',
        'asleep-unread': 'asleep, flagged unread - wake it to follow up',
        limit: 'over limit',
        unknown: 'status not measured',
    };

    const OUTER_LABELS = {
        active: '',
        steady: '',
        unread: 'unread',
        off: '',
        dim: '',
    };

    function escapeAttr(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function normalizeInner(inner) {
        return INNER_STATES.indexOf(inner) >= 0 ? inner : INNER_FALLBACK;
    }

    function normalizeOuter(outer) {
        return OUTER_STATES.indexOf(outer) >= 0 ? outer : OUTER_FALLBACK;
    }

    function ledLabel(inner, outer) {
        const head = INNER_LABELS[inner];
        const tail = OUTER_LABELS[outer];
        return tail ? head + ', ' + tail : head;
    }

    /* aria-label="working" box-shadow title="working" */
    function ledHtml(opts) {
        const o = opts || {};
        const inner = normalizeInner(o.inner);
        const outer = normalizeOuter(o.outer);
        const label = o.title == null ? ledLabel(inner, outer) : String(o.title);
        const size =
            typeof o.size === 'string' && /^[0-9]+(\.[0-9]+)?(px|rem|em)$/.test(o.size)
                ? o.size
                : '';
        const styleAttr = size ? ` style="--led-size: ${escapeAttr(size)}"` : '';
        const extra =
            typeof o.extraClass === 'string' && /^[A-Za-z0-9 _-]+$/.test(o.extraClass)
                ? o.extraClass.trim() + ' '
                : '';
        return (
            `<span class="${escapeAttr(extra)}status-led" data-inner="${escapeAttr(inner)}" ` +
            `data-outer="${escapeAttr(outer)}" role="img" ` +
            `title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}"` +
            `${styleAttr}></span>`
        );
    }

    /* label: ' */
    function hostOffline(r) {
        if (!r || !r.host_key || r.host_key === 'local') return null;
        const state = r.host_state || 'up';
        return state === 'up' ? null : (r.host_label || r.host_key);
    }

    const LIMIT_MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

    function usageLimitLabel(r) {
        const u = r && r.usage_limit;
        if (!u || typeof u !== 'object') return null;
        const at = typeof u.resets_at === 'string' ? new Date(u.resets_at) : null;
        if (!at || isNaN(at.getTime())) return 'over limit';
        const h = at.getHours();
        const m = at.getMinutes();
        const clock = (h % 12 || 12) + (m ? ':' + (m < 10 ? '0' : '') + m : '') + (h < 12 ? 'am' : 'pm');
        return 'over limit, resets ' + LIMIT_MONTHS[at.getMonth()] + ' ' + at.getDate() + ' ' + clock;
    }

    function ledStateFor(signals) {
        const s = signals || {};
        const status = s.activity_status;
        const unread = !!s.unread;
        const gate = s.startup_gate;

        if (status === 'asleep') {
            return { inner: unread ? 'asleep-unread' : 'asleep', outer: 'off' };
        }

        if (s.transport === 'disconnected' || s.host_offline) {
            return { inner: 'disconnected', outer: 'off' };
        }

        if (status === 'dead' || status === 'stopped') {
            return { inner: 'dead', outer: 'off' };
        }

        if (s.usage_limit) {
            return { inner: 'limit', outer: 'off' };
        }

        if (gate === 'awaiting_startup_prompt') {
            return { inner: 'waiting-input', outer: 'active' };
        }

        if (status === 'question') {
            return { inner: 'waiting-permission', outer: 'active' };
        }

        if (status === 'notice') {
            return { inner: 'notice', outer: 'active' };
        }

        if (
            status === 'working' ||
            status === 'working_subagent' ||
            status === 'running'
        ) {
            return { inner: 'working', outer: 'active' };
        }

        if (status === 'finished_unread') {
            return { inner: 'done', outer: 'unread' };
        }

        if (status === 'idle') {
            return unread
                ? { inner: 'done', outer: 'unread' }
                : { inner: 'idle', outer: 'steady' };
        }

        return { inner: 'unknown', outer: 'dim' };
    }

    const api = {
        INNER_STATES: INNER_STATES.slice(),
        OUTER_STATES: OUTER_STATES.slice(),
        INNER_LABELS: INNER_LABELS,
        ledHtml: ledHtml,
        ledStateFor: ledStateFor,
        hostOffline: hostOffline,
        usageLimitLabel: usageLimitLabel,
        ledLabel: ledLabel,
        normalizeInner: normalizeInner,
        normalizeOuter: normalizeOuter,
    };

    globalThis.StatusLed = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    console.log('[StatusLed Module] Loaded');
})();
