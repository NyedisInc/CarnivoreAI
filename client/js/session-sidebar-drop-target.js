
console.log('[SessionSidebarDropTarget Module] Loading...');

(function () {
    function listEl() {
        const sidebar = window.SessionSidebar;
        return (sidebar && sidebar.listEl) || null;
    }

    function bandKeyAt(clientY) {
        const list = listEl();
        if (!list) return null;
        const groups = Array.prototype.slice.call(
            list.querySelectorAll('.session-sidebar-group[data-group]'),
        );
        if (!groups.length) return null;
        let last = null;
        for (const g of groups) {
            const box = g.getBoundingClientRect();
            last = g;
            if (clientY < box.bottom) return g.getAttribute('data-group');
        }
        return last ? last.getAttribute('data-group') : null;
    }

    function bandAt(clientY) {
        const key = bandKeyAt(clientY);
        return key === null ? null : key === 'pinned';
    }

    window.SessionSidebarDropTarget = { bandKeyAt, bandAt };
    console.log('[SessionSidebarDropTarget Module] Exported as window.SessionSidebarDropTarget');
})();
