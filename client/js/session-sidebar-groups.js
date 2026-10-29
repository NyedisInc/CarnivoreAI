
console.log('[SessionSidebarGroups Module] Loading...');

(function () {
    const KEYS = ['pinned', 'other'];

    const LABELS = { pinned: 'pinned', other: 'other' };

    function chevronHtml() {
        return (
            '<span class="session-sidebar-group__chevron" aria-hidden="true">'
            + '<svg width="10" height="10" viewBox="0 0 12 12" fill="none" '
            + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            + 'stroke-linejoin="round"><path d="M4 2l4 4-4 4"/></svg></span>'
        );
    }

    function labelFor(key) {
        const G = window.SessionSidebarGroupStore;
        if (G) {
            const label = G.labelFor(key);
            if (label && label.trim()) return label;
        }
        return LABELS[key] || key;
    }

    window.SessionSidebarGroups = {
        chevronHtml, labelFor, KEYS, LABELS,
    };
    console.log('[SessionSidebarGroups Module] Exported as window.SessionSidebarGroups');
})();
