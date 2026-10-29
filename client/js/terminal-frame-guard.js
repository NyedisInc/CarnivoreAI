
(function () {
    'use strict';

    const TerminalFrameGuard = {
        accepts(ev) {
            const e = ev || {};
            if (!e.socket || e.socket !== e.liveSocket) {
                return { ok: false, reason: 'superseded-socket' };
            }
            if (
                e.boundSessionId &&
                e.currentSessionId &&
                e.boundSessionId !== e.currentSessionId
            ) {
                return { ok: false, reason: 'session-changed' };
            }
            return { ok: true, reason: 'live' };
        },
    };

    if (typeof window !== 'undefined') {
        window.TerminalFrameGuard = TerminalFrameGuard;
    }
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = TerminalFrameGuard;
    }
})();
