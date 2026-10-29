
(function attachSessionEntryToasts(global) {
    'use strict';

    function dismissFor(sessionId, tmuxName) {
        const id = sessionId || null;
        const name = tmuxName || null;
        if (!id && !name) return false;
        const manager = global.ToastManager;
        if (!manager || typeof manager.dismissForSessionEntry !== 'function') {
            return false;
        }
        manager.dismissForSessionEntry(id, name);
        return true;
    }

    global.SessionEntryToasts = { dismissFor: dismissFor };
})(window);
