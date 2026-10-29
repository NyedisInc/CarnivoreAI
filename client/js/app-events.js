
console.log('[AppEvents Module] Loading...');

(function () {
    /** @type {string} WebSocket path. Auth rides the subprotocol header. */
    var EVENTS_PATH = '/ws/events';

    var OVERFLOW_CLOSE_CODE = 4429;

    /** @type {number} Close code for a rejected or expired token. */
    var AUTH_CLOSE_CODE = 4401;

    /** @type {number} First reconnect delay, milliseconds. */
    var BASE_DELAY_MS = 1000;

    /** @type {number} Ceiling on the backoff, milliseconds. */
    var MAX_DELAY_MS = 30000;

    var PROBE_TIMEOUT_MS = 5000;

    /** @type {number} The close code a failed wake probe drops the socket with. */
    var PROBE_CLOSE_CODE = 4000;

    var state = {
        ws: null,
        hello: null,
        timer: null,
        attempts: 0,
        stopped: true,
        openedThisAttempt: false,
        retriedAuthThisEpisode: false,
        refusedToken: null,
        parked: false,
        probeTimer: null,
        abandon: null,
    };

    /** @type {string} The storage key the access token lives under (client/js/api.js). */
    var TOKEN_KEY = 'claude_tunnel_token';

    function currentToken() {
        var host = globalThis.API;
        if (!host || typeof host.getToken !== 'function') return null;
        try { return host.getToken() || null; } catch (err) { return null; }
    }

    function park(token) {
        state.refusedToken = token;
        state.parked = true;
        if (state.timer) {
            clearTimeout(state.timer);
            state.timer = null;
        }
        console.warn('[AppEvents] token refused after re-auth, waiting for a new one');
    }

    function unparkIfNewToken() {
        if (!state.parked || state.stopped) return;
        var token = currentToken();
        if (!token || token === state.refusedToken) return;
        state.parked = false;
        state.attempts = 0;
        state.retriedAuthThisEpisode = false;
        connect();
    }

    if (typeof globalThis.addEventListener === 'function') {
        globalThis.addEventListener('storage', function (event) {
            if (!event || event.key === TOKEN_KEY || event.key === null) unparkIfNewToken();
        });
        globalThis.addEventListener('authenticated', unparkIfNewToken);
        globalThis.addEventListener('focus', unparkIfNewToken);
    }
    if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState !== 'visible') return;
            unparkIfNewToken();
            reconnectNow();
        });
    }
    if (typeof globalThis.addEventListener === 'function') {
        globalThis.addEventListener('online', function () { reconnectNow(); });
        globalThis.addEventListener('pageshow', function (event) {
            if (event && event.persisted) reconnectNow();
        });
    }

    function clearProbe() {
        if (state.probeTimer) {
            clearTimeout(state.probeTimer);
            state.probeTimer = null;
        }
    }

    function reconnectNow(manual) {
        if (state.stopped && !manual) return;
        if (state.ws) {
            probe();
            return;
        }
        if (state.parked) return;
        if (state.timer) {
            clearTimeout(state.timer);
            state.timer = null;
        }
        state.attempts = 0;
        if (state.stopped) {
            start();
            return;
        }
        connect();
    }

    function probe() {
        var ws = state.ws;
        if (!ws || ws.readyState !== 1 || state.probeTimer) return;
        try {
            ws.send(JSON.stringify({ type: 'ping' }));
        } catch (err) {
            return;
        }
        state.probeTimer = setTimeout(function () {
            state.probeTimer = null;
            if (state.ws === ws && typeof state.abandon === 'function') {
                console.warn('[AppEvents] wake probe unanswered, reconnecting');
                state.abandon(PROBE_CLOSE_CODE);
            }
        }, PROBE_TIMEOUT_MS);
    }

    var subscribers = [];

    function subscribe(handler) {
        if (typeof handler !== 'function') return function () {};
        subscribers.push(handler);
        return function () {
            var at = subscribers.indexOf(handler);
            if (at >= 0) subscribers.splice(at, 1);
        };
    }

    function notify(frame) {
        for (var i = 0; i < subscribers.length; i += 1) {
            try {
                subscribers[i](frame);
            } catch (err) {
                console.warn('[AppEvents] a subscriber threw and was skipped', err);
            }
        }
    }

    function isConnected() {
        return !!state.ws && state.ws.readyState === 1;
    }

    function lastHello() {
        return isConnected() ? state.hello || null : null;
    }

    function refreshAll() {
        if (globalThis.PreferencesTransport) {
            try { globalThis.PreferencesTransport.refreshOnReconnect(); } catch (err) {
                console.warn('[AppEvents] preferences refresh failed', err);
            }
        }
        refreshSessionSurfaces();
    }

    function refreshSessionSurfaces() {
        var sidebar = globalThis.SessionSidebar;
        if (sidebar && typeof sidebar.refreshNow === 'function') {
            try { sidebar.refreshNow(); } catch (err) {
                console.warn('[AppEvents] sidebar refresh failed', err);
            }
        }
        var header = globalThis.SessionHeaderLed;
        if (header && typeof header.tick === 'function') header.tick();
        var launchpad = globalThis.Launchpad;
        if (launchpad && typeof launchpad.loadRunningSessions === 'function') {
            try { launchpad.loadRunningSessions(); } catch (err) {
                console.warn('[AppEvents] launchpad refresh failed', err);
            }
        }
    }

    function handleFrame(frame) {
        if (!frame || typeof frame !== 'object') return false;
        var type = frame.type;

        notify(frame);

        if (type === 'events.hello') {
            state.hello = frame;
            refreshAll();
            return true;
        }
        if (type === 'session.status' || type === 'sessions.changed') {
            var push = globalThis.ListingPush;
            if (!(push && typeof push.isLive === 'function' && push.isLive())) {
                refreshSessionSurfaces();
            }
            return true;
        }
        if (type === 'toast.new') {
            if (globalThis.ToastManager && frame.toast) {
                globalThis.ToastManager.add(frame.toast);
            }
            return true;
        }
        if (type === 'toast.ack') {
            if (globalThis.ToastManager && frame.toast_id) {
                globalThis.ToastManager.dismiss(frame.toast_id, { syncToServer: false });
            }
            return true;
        }
        if (globalThis.PreferencesTransport
            && type === globalThis.PreferencesTransport.CHANGED) {
            globalThis.PreferencesTransport.handleFrame(frame);
            return true;
        }
        if (type === 'pong') return true;
        return false;
    }

    /* the socket closed */
    function backoffFor(closeCode) {
        if (closeCode === OVERFLOW_CLOSE_CODE) return 0;
        var delay = BASE_DELAY_MS * Math.pow(2, Math.max(0, state.attempts - 1));
        delay = Math.min(delay, MAX_DELAY_MS);
        var jitter = delay * 0.2 * (Math.random() * 2 - 1);
        return Math.max(0, Math.min(MAX_DELAY_MS, Math.round(delay + jitter)));
    }

    function scheduleReconnect(closeCode) {
        if (state.stopped) return;
        if (state.timer) return;
        var delay = backoffFor(closeCode);
        state.timer = setTimeout(function () {
            state.timer = null;
            connect();
        }, delay);
    }

    function refreshThenReconnect(refusedToken) {
        var recovery = globalThis.SocketAuthRecovery;
        var refresh = recovery ? recovery.defaultRefreshFn() : null;
        if (!recovery || !refresh) {
            park(refusedToken);
            return;
        }
        recovery.resolveAfterUnopenedClose(refresh).then(function (outcome) {
            var O = recovery.OUTCOME;
            if (outcome === O.REFRESHED) {
                console.log('[AppEvents] token refreshed after auth-refused close, reconnecting');
                state.attempts = 0;
                connect();
                return;
            }
            if (outcome === O.NETWORK_ERROR || outcome === O.NO_REFRESH_PATH) {
                console.warn('[AppEvents] refresh unresolved, retrying with backoff');
                state.retriedAuthThisEpisode = false;
                state.attempts += 1;
                scheduleReconnect();
                return;
            }
            console.warn('[AppEvents] refresh failed, standing down and signalling signed-out');
            state.stopped = true;
            var api = globalThis.API;
            if (api && typeof api.handleUnauthorized === 'function') {
                api.handleUnauthorized();
            } else {
                globalThis.dispatchEvent(new CustomEvent('auth-required'));
            }
        });
    }

    function connect() {
        if (state.stopped) return;
        if (state.ws) return;
        if (state.parked) return;
        if (!globalThis.API || typeof globalThis.API.openWebSocket !== 'function') return;
        if (typeof globalThis.API.getToken === 'function' && !globalThis.API.getToken()) {
            return;
        }

        if (state.refusedToken !== null && currentToken() === state.refusedToken) {
            state.parked = true;
            return;
        }
        state.openedThisAttempt = false;
        var presented = currentToken();
        var ws;
        try {
            ws = globalThis.API.openWebSocket(null, EVENTS_PATH);
        } catch (err) {
            console.warn('[AppEvents] could not open events socket', err);
            state.attempts += 1;
            scheduleReconnect();
            return;
        }
        state.ws = ws;

        ws.onopen = function () {
            state.attempts = 0;
            state.openedThisAttempt = true;
            state.retriedAuthThisEpisode = false;
            state.refusedToken = null;
            console.log('[AppEvents] events channel open');
            notify({ type: 'events.open' });
        };
        ws.onmessage = function (event) {
            clearProbe();
            var frame;
            try {
                frame = JSON.parse(event.data);
            } catch (err) {
                console.warn('[AppEvents] undecodable frame ignored');
                return;
            }
            handleFrame(frame);
        };
        ws.onerror = function () {
        };
        var finished = false;
        ws.onclose = function (event) {
            closed(event && event.code);
        };
        state.abandon = function (code) {
            ws.onopen = null;
            ws.onmessage = null;
            ws.onclose = null;
            ws.onerror = null;
            try { ws.close(code, 'probe timeout'); } catch (err) {  }
            closed(code);
        };

        function closed(code) {
            if (finished) return;
            finished = true;
            if (state.ws === ws) {
                state.ws = null;
                state.abandon = null;
                clearProbe();
            }
            state.hello = null;
            notify({ type: 'events.closed', code: code });
            var authRefused = code === AUTH_CLOSE_CODE || !state.openedThisAttempt;
            if (authRefused && !state.retriedAuthThisEpisode) {
                state.retriedAuthThisEpisode = true;
                refreshThenReconnect(presented);
                return;
            }
            if (authRefused && presented !== null && currentToken() === presented) {
                park(presented);
                return;
            }
            if (code !== OVERFLOW_CLOSE_CODE) state.attempts += 1;
            scheduleReconnect(code);
        }
    }

    function start() {
        state.stopped = false;
        state.parked = false;
        connect();
    }

    function stop() {
        state.stopped = true;
        if (state.timer) {
            clearTimeout(state.timer);
            state.timer = null;
        }
        clearProbe();
        if (state.ws) {
            try { state.ws.close(1000, 'client stopping'); } catch (err) {  }
            state.ws = null;
            state.abandon = null;
        }
        state.attempts = 0;
    }

    var api = {
        EVENTS_PATH: EVENTS_PATH,
        OVERFLOW_CLOSE_CODE: OVERFLOW_CLOSE_CODE,
        start: start,
        stop: stop,
        handleFrame: handleFrame,
        subscribe: subscribe,
        isConnected: isConnected,
        lastHello: lastHello,
        reconnectNow: reconnectNow,
        PROBE_TIMEOUT_MS: PROBE_TIMEOUT_MS,
        refreshAll: refreshAll,
        refreshSessionSurfaces: refreshSessionSurfaces,
        backoffFor: backoffFor,
        _state: state,
    };

    globalThis.AppEvents = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }

    console.log('[AppEvents Module] Loaded');
})();
