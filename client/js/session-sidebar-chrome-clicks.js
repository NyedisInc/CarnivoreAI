/* the bottom bar */

console.log('[SessionSidebarChromeClicks Module] Loading...');

(function () {
    function onGroupToggleClick(ctrl, btnEl) {
        const key = btnEl.getAttribute('data-group-toggle');
        const arrangement = window.SessionSidebarArrangement;
        if (!key || !arrangement) return;
        const nowPresent = arrangement.toggleCollapsed(key);
        ctrl.repaint();
        const region = document.getElementById('session-sidebar-live');
        if (region) {
            const isLayoutItem = typeof key === 'string' && key.indexOf('layout:') === 0;
            const word = isLayoutItem
                ? (nowPresent ? 'expanded' : 'collapsed')
                : (nowPresent ? 'collapsed' : 'expanded');
            region.textContent = `${key} group ${word}`;
        }
    }

    function shellOwns(target) {
        const shell = window.CloudeWeb && window.CloudeWeb.sidebarShell;
        return !!(shell && typeof shell.owns === 'function' && shell.owns(target));
    }

    function claim(ctrl, e) {
        const at = (sel) => (e.target.closest ? e.target.closest(sel) : null);
        if (shellOwns(e.target)) return true;
        if (at('.session-sidebar-rename-edit')) {
            e.stopPropagation();
            return true;
        }
        const groupToggle = at('[data-group-toggle]');
        if (groupToggle) {
            e.stopPropagation();
            onGroupToggleClick(ctrl, groupToggle);
            return true;
        }
        return false;
    }

    window.SessionSidebarChromeClicks = {
        claim, onGroupToggleClick, shellOwns,
    };
    console.log('[SessionSidebarChromeClicks Module] Exported as window.SessionSidebarChromeClicks');
})();
