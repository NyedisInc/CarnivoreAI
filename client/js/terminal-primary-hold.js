(function () {
    'use strict';

    var heldIds = [];

    var refused = {};

    var started = {};

    function hold(ids) {
        heldIds = (ids || []).filter(function (id) { return typeof id === 'string' && id !== ''; });
    }

    function held(sessionId) {
        return sessionId != null && heldIds.indexOf(sessionId) !== -1;
    }

    function begun(sessionId) {
        if (held(sessionId)) started[sessionId] = true;
    }

    function defer(sessionId, retry) {
        if (!held(sessionId)) return false;
        delete started[sessionId];
        refused[sessionId] = retry;
        return true;
    }

    function release() {
        var pending = refused;
        var inFlight = started;
        heldIds = [];
        refused = {};
        started = {};
        Object.keys(pending).forEach(function (id) { if (!inFlight[id]) pending[id](); });
    }

    function navigatedTo(ids) {
        if (ids.some(held)) return;
        release();
    }

    window.TerminalPrimaryHold = { hold: hold, release: release, held: held, defer: defer, begun: begun, navigatedTo: navigatedTo };
})();
