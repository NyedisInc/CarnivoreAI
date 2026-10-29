
console.log('[SessionSidebarKeepAwake Module] Loading...');

(function () {
    'use strict';

    function store() {
        var web = window.CloudeWeb;
        return web && web.autoSleep ? web.autoSleep : null;
    }

    async function onClick(ctrl, el) {
        var s = store();
        var name = el.getAttribute('data-keep-awake-session');
        if (!s || !name) return;
        var on = s.isKeptAwake(name);
        if (on === null) return;
        await s.setKeepAwake(name, !on);
        repaint(ctrl);
    }

    function repaint(ctrl) {
        var target = ctrl || window.SessionSidebar;
        if (!target || typeof target.repaint !== 'function') return;
        target.repaint();
    }

    window.addEventListener('cloude:auto-sleep-changed', function () { repaint(null); });

    window.SessionSidebarKeepAwake = { onClick: onClick };
    console.log('[SessionSidebarKeepAwake Module] Exported as window.SessionSidebarKeepAwake');
})();
