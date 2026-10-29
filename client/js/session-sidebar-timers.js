
console.log('[SessionSidebarTimers Module] Loading...');

(function () {
    function onClick(el) {
        const web = window.CloudeWeb;
        if (!web || typeof web.openTimerList !== 'function') {
            console.error('SessionSidebarTimers: the compiled list is not loaded');
            return false;
        }
        const label = el.closest && el.closest('.session-sidebar-row');
        const nameEl = label && label.querySelector('.session-sidebar-row-name');
        return web.openTimerList(
            el, el.getAttribute('data-timers-session-id'),
            nameEl ? nameEl.textContent : el.getAttribute('data-timers-session'));
    }

    window.SessionSidebarTimers = { onClick };
    console.log('[SessionSidebarTimers Module] Exported as window.SessionSidebarTimers');
})();
