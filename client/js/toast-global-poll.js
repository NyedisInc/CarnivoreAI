(function () {
    'use strict';

    var POLL_MS = 10000;

    var DISMISS_EVENT = 'cloude:toast-dismissed';

    var state = {
        timer: null,
        inFlight: false,
        ring: null,
        wired: false,
    };

    function ring() {
        if (!state.ring && window.ToastDismissedRing) {
            state.ring = new window.ToastDismissedRing();
        }
        return state.ring;
    }

    function canPoll() {
        if (state.inFlight) return false;
        if (document.hidden) return false;
        if (document.documentElement.hasAttribute('data-solo')) return false;
        if (!window.API || typeof window.API.getAllToasts !== 'function') return false;
        if (typeof window.API.getToken === 'function' && !window.API.getToken()) {
            return false;
        }
        return !!window.ToastManager;
    }

    function tick() {
        if (!canPoll()) return Promise.resolve();
        state.inFlight = true;
        var startedAt = Date.now();
        return window.API.getAllToasts({ unackedOnly: true })
            .then(function (payload) {
                var list = (payload && payload.toasts) || [];
                var r = ring();
                var fresh = r ? r.filter(list) : list;
                if (fresh.length) window.ToastManager.backfill(fresh);
                // the launchpad, the archive, a terminal attached
                // look smaller than the server said
                if (typeof window.ToastManager.reconcileOpen === 'function') {
                    window.ToastManager.reconcileOpen(list, { since: startedAt });
                }
            })
            .catch(function (err) {
                console.warn('[ToastGlobalPoll] tick failed', err && err.message);
            })
            .then(function () {
                state.inFlight = false;
            });
    }

    function onDismissed(evt) {
        var id = evt && evt.detail && evt.detail.id;
        var r = ring();
        if (id && r) r.note(id);
    }

    function start() {
        if (!state.wired) {
            document.addEventListener(DISMISS_EVENT, onDismissed);
            document.addEventListener('visibilitychange', function () {
                if (!document.hidden) tick();
            });
            state.wired = true;
        }
        if (state.timer) return;
        var push = window.ResourcePush;
        if (push && typeof push.pushOrPoll === 'function') {
            state.timer = { stop: push.pushOrPoll(tick, POLL_MS, ['toasts']) };
        } else {
            state.timer = { interval: setInterval(tick, POLL_MS) };
        }
        tick();
    }

    function stop() {
        if (state.timer) {
            if (state.timer.stop) state.timer.stop();
            else clearInterval(state.timer.interval);
            state.timer = null;
        }
    }

    window.ToastGlobalPoll = {
        start: start,
        stop: stop,
        tick: tick,
        POLL_MS: POLL_MS,
        DISMISS_EVENT: DISMISS_EVENT,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
}());
