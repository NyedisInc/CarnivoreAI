
console.log('[SessionSidebarSubagents Module] Loading...');

(function () {
    function t(key, params) {
        const i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    function attr(value) {
        const controls = window.SessionSidebarRowControls;
        if (controls && typeof controls.escAttr === 'function') return controls.escAttr(value);
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function runningOf(r) {
        const n = r ? r.subagents_running : null;
        return (typeof n === 'number' && Number.isFinite(n) && n > 0) ? Math.floor(n) : null;
    }

    function rollupHtml(rows) {
        const seen = new Set();
        let sum = 0;
        (Array.isArray(rows) ? rows : []).forEach((r) => {
            const running = runningOf(r);
            const id = r && (r.session_id || r.name);
            if (running === null || seen.has(id)) return;
            seen.add(id);
            sum += running;
        });
        if (sum === 0) return '';
        return '<span class="subagent-count subagent-count--rollup">'
            + `${attr(t('subagents.badge', { count: sum }))}</span>`;
    }

    function onClick(el) {
        const web = window.CloudeWeb;
        if (!web || typeof web.openSubagentList !== 'function') {
            console.error('SessionSidebarSubagents: the compiled list is not loaded');
            return false;
        }
        const label = el.closest && el.closest('.session-sidebar-row');
        const nameEl = label && label.querySelector('.session-sidebar-row-name');
        return web.openSubagentList(
            el, el.getAttribute('data-subagents-session-id'),
            nameEl ? nameEl.textContent : el.getAttribute('data-subagents-session'));
    }

    window.SessionSidebarSubagents = { rollupHtml, onClick, runningOf };
    console.log('[SessionSidebarSubagents Module] Exported as window.SessionSidebarSubagents');
})();
