/* could not */

console.log('[SocketAuthRecovery Module] Loading...');

(function () {
    'use strict';

    /** @type {Object<string,string>} */
    var OUTCOME = {
        REFRESHED: 'refreshed',
        SIGNED_OUT: 'signed-out',
        NETWORK_ERROR: 'network-error',
        NO_REFRESH_PATH: 'no-refresh-path',
    };

    async function resolveAfterUnopenedClose(refresh) {
        if (typeof refresh !== 'function') return OUTCOME.NO_REFRESH_PATH;
        var result;
        try {
            result = await refresh();
        } catch (err) {
            console.warn('SocketAuthRecovery: refresh threw', err);
            return OUTCOME.NETWORK_ERROR;
        }
        if (result === true) return OUTCOME.REFRESHED;
        if (result === 'network-error') return OUTCOME.NETWORK_ERROR;
        return OUTCOME.SIGNED_OUT;
    }

    function defaultRefreshFn() {
        var api = globalThis.API;
        if (api && typeof api._singleFlightRefresh === 'function') {
            return function () { return api._singleFlightRefresh(); };
        }
        var auth = globalThis.Auth;
        if (auth && typeof auth.refresh === 'function') {
            return function () { return auth.refresh(); };
        }
        return null;
    }

    var api = {
        OUTCOME: OUTCOME,
        resolveAfterUnopenedClose: resolveAfterUnopenedClose,
        defaultRefreshFn: defaultRefreshFn,
    };

    globalThis.SocketAuthRecovery = api;
    if (typeof window !== 'undefined') window.SocketAuthRecovery = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
})();

console.log('[SocketAuthRecovery Module] Exported as window.SocketAuthRecovery');
