(function () {
    'use strict';

    var TERMINAL_CREATED = 'terminal-created';

    function announceCreated(term) {
        try {
            if (typeof window === 'undefined'
                || typeof window.dispatchEvent !== 'function'
                || typeof CustomEvent !== 'function') {
                return false;
            }
            window.dispatchEvent(new CustomEvent(TERMINAL_CREATED, {
                detail: { term: term }
            }));
            return true;
        } catch (e) {
            console.warn('TerminalLifecycle: could not announce the terminal', e);
            return false;
        }
    }

    window.TerminalLifecycle = {
        TERMINAL_CREATED: TERMINAL_CREATED,
        announceCreated: announceCreated
    };
})();
