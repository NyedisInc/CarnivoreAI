
console.log('[SessionTransport Module] Loading...');

(function () {
    /** @type {string} No socket has been opened, or it was for another
     * session. The honest default and the only value most rows get. */
    const UNKNOWN = 'unknown';

    /** @type {string} The socket for this session is open. */
    const CONNECTED = 'connected';

    /** @type {string} The socket for this session closed unexpectedly. */
    const DISCONNECTED = 'disconnected';

    const held = { name: null, state: UNKNOWN };

    function mark(name, state) {
        if (!name) {
            held.name = null;
            held.state = UNKNOWN;
            return;
        }
        held.name = String(name);
        held.state =
            state === CONNECTED || state === DISCONNECTED ? state : UNKNOWN;
    }

    function clear() {
        mark(null, UNKNOWN);
    }

    function stateFor(name) {
        if (!name || !held.name) return UNKNOWN;
        return String(name) === held.name ? held.state : UNKNOWN;
    }

    const api = {
        UNKNOWN: UNKNOWN,
        CONNECTED: CONNECTED,
        DISCONNECTED: DISCONNECTED,
        mark: mark,
        clear: clear,
        stateFor: stateFor,
    };

    globalThis.SessionTransport = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    console.log('[SessionTransport Module] Loaded');
})();
