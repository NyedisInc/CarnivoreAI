
console.log('[SessionHeaderLed Module] Loading...');

(function () {
    const LED_ID = 'header-session-led';

    const TITLE_ID = 'header-title-text';

    function rowFor(rows, tmuxName) {
        if (!tmuxName || !Array.isArray(rows)) return null;
        for (const row of rows) {
            if (row && row.name === tmuxName) return row;
        }
        return null;
    }

    /* there is nothing */
    function ledHtmlFor(row) {
        if (!row || !window.SessionStatusUI || row.agent_family === 'shell') return '';
        return window.SessionStatusUI.dotHtml(row.status, {
            unread: !!row.unread,
            startup_gate: row.startup_gate,
            status_source: row.status_source,
            activity_hint: row.activity_hint,
            parked_summary: row.parked_summary,
            usage_limit: window.StatusLed ? window.StatusLed.usageLimitLabel(row) : null,
            size: '10px',
        });
    }

    let requestGeneration = 0;

    function beginRequest() { return ++requestGeneration; }

    function update(rows, tmuxName, request) {
        if (request !== undefined && request !== requestGeneration) return;
        const titleEl = document.getElementById(TITLE_ID);
        if (!titleEl || !titleEl.parentNode) return;
        const existing = document.getElementById(LED_ID);
        const html = ledHtmlFor(rowFor(rows, tmuxName));

        if (!html) {
            if (existing && existing.parentNode) {
                existing.parentNode.removeChild(existing);
            }
            return;
        }

        if (existing) {
            if (existing.innerHTML !== html) existing.innerHTML = html;
            return;
        }
        const holder = document.createElement('span');
        holder.id = LED_ID;
        holder.className = 'header-session-led';
        holder.innerHTML = html;
        titleEl.parentNode.insertBefore(holder, titleEl);
    }

    function clear() {
        ++requestGeneration;
        const existing = document.getElementById(LED_ID);
        if (existing && existing.parentNode) {
            existing.parentNode.removeChild(existing);
        }
    }

    function pollMs() {
        const sidebar = window.SessionSidebar;
        const C = sidebar && sidebar.constructor;
        return (C && typeof C.POLL_MS === 'number') ? C.POLL_MS : 5000;
    }

    function rowFromInfo(info) {
        const i = info || {};
        return {
            name: i.tmux_session || null,
            status: i.activity_status || 'unknown',
            unread: !!i.unread,
            startup_gate: i.startup_gate,
            status_source: i.status_source,
            activity_hint: i.activity_hint,
            parked_summary: i.parked_summary,
            usage_limit: i.usage_limit,
            agent_family: i.agent_family,
        };
    }

    let timer = null;

    let wired = false;

    function onVisibilityChange() {
        if (!document.hidden) tick();
    }

    async function tick() {
        if (document.hidden) return;
        const sidebar = window.SessionSidebar;
        if (!sidebar || typeof sidebar.activeTmuxName !== 'function') return;
        const name = sidebar.activeTmuxName();
        if (!name) {
            clear();
            return;
        }
        if (sidebar.isOpen) return;
        if (!window.API || typeof window.API.listSessions !== 'function') return;
        const request = beginRequest();
        try {
            const live = await window.API.listSessions();
            if (sidebar.activeTmuxName() !== name) return;
            const rows = (Array.isArray(live) ? live : []).map(rowFromInfo);
            update(rows, name, request);
        } catch (err) {
            console.warn('SessionHeaderLed: poll tick failed:', err && err.message);
        }
    }

    function start() {
        if (!wired && typeof document.addEventListener === 'function') {
            document.addEventListener('visibilitychange', onVisibilityChange);
            wired = true;
        }
        if (timer) return;
        const push = globalThis.ListingPush;
        if (push && typeof push.pushOrPoll === 'function') {
            timer = { stop: push.pushOrPoll(() => { tick(); }, pollMs(), ['list']) };
            return;
        }
        timer = setInterval(() => { tick(); }, pollMs());
    }

    function stop() {
        if (timer) {
            if (typeof timer.stop === 'function') timer.stop();
            else clearInterval(timer);
            timer = null;
        }
    }

    window.SessionHeaderLed = {
        rowFor, rowFromInfo, ledHtmlFor, update, clear, start, stop, tick, beginRequest, LED_ID,
    };
    if (typeof setInterval === 'function' && typeof document !== 'undefined') {
        start();
    }
    console.log('[SessionHeaderLed Module] Exported as window.SessionHeaderLed');
})();
