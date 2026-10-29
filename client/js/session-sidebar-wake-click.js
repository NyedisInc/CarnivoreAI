
console.log('[SessionSidebarWakeClick Module] Loading...');

(function () {
    /* a double click wakes once */
    var inflight = new Set();

    function rowFor(ctrl, name) {
        var rows = (ctrl && Array.isArray(ctrl._rows)) ? ctrl._rows : [];
        for (var i = 0; i < rows.length; i += 1) {
            if (rows[i] && rows[i].name === name) return rows[i];
        }
        return null;
    }

    function liveRowElement(ctrl, sessionUuid) {
        var rows = (ctrl && Array.isArray(ctrl._rows)) ? ctrl._rows : [];
        var row = null;
        for (var i = 0; i < rows.length; i += 1) {
            var r = rows[i];
            if (r && !r.asleep && r.session_uuid === sessionUuid) { row = r; break; }
        }
        if (!row || typeof document === 'undefined') return null;
        var els = document.querySelectorAll('.session-sidebar-row');
        for (var j = 0; j < els.length; j += 1) {
            if (els[j].dataset.name === row.name && els[j].dataset.asleep !== '1') return els[j];
        }
        return null;
    }

    async function onAsleepClick(ctrl, rowEl, open) {
        var name = rowEl && rowEl.dataset.name;
        var row = rowFor(ctrl, name);
        var sleeper = window.SessionRowMenuSleep;
        if (!row || !sleeper || typeof sleeper.runWake !== 'function') return false;
        var sessionUuid = row.session_uuid || '';
        if (sessionUuid && inflight.has(sessionUuid)) return true;
        var nav = window.NavigationGeneration
            ? window.NavigationGeneration.begin('wake:' + name) : null;
        if (sessionUuid) inflight.add(sessionUuid);
        var started = false;
        try {
            started = await sleeper.runWake({
                name: name,
                label: (row.label != null && String(row.label)) || '',
                sessionUuid: sessionUuid,
                surface: 'sidebar',
            });
        } finally {
            if (sessionUuid) inflight.delete(sessionUuid);
        }
        if (!started) return true;
        if (window.NavigationGeneration
            && !window.NavigationGeneration.keep(nav, 'open after wake of ' + name)) return true;
        var el = liveRowElement(ctrl, sessionUuid);
        if (el && typeof open === 'function') await open(ctrl, el);
        return true;
    }

    var api = { onAsleepClick: onAsleepClick };
    if (typeof window !== 'undefined') window.SessionSidebarWakeClick = api;
    if (typeof globalThis !== 'undefined') globalThis.SessionSidebarWakeClick = api;
})();

console.log('[SessionSidebarWakeClick Module] Exported as window.SessionSidebarWakeClick');
