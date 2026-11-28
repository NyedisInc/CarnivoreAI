(function (global) {
    'use strict';

    var MAX_ATTEMPTS = 3;

    var RETRY_MS = 1500;

    var runs = new WeakMap();

    function alive(ctl, run) {
        if (runs.get(ctl) !== run || ctl._disposed || !ctl.term) return false;
        if (ctl._connGen !== run.gen || ctl._navToken !== run.nav) return false;
        if (typeof ctl._sessionId === 'function' && ctl._sessionId() !== run.sid) return false;
        if (!ctl._navCurrent || !ctl._navCurrent('history')) return false;
        if (ctl.ws) {
            if (!run.ws) run.ws = ctl.ws;
            else if (run.ws !== ctl.ws) return false;
            return ctl.ws.readyState <= 1;
        }
        return !run.ws;
    }

    async function attempt(ctl, run, n) {
        if (!alive(ctl, run)) return;
        var opts = { stillValid: function () { return alive(ctl, run); } };
        if (n === 1 && run.b64) opts.capturedB64 = run.b64;
        var r;
        try {
            r = await global.TerminalHistory.ensureLoaded(ctl.term, run.sid, ctl, opts);
        } catch (err) {
            console.warn('Terminal: history follow-up failed', err);
            return;
        }
        if (!r || r.loaded !== 'unavailable' || n >= MAX_ATTEMPTS) return;
        if (r.reason !== 'request_failed' && !(n === 1 && run.b64 && r.reason === 'decode_failed')) return;
        run.b64 = null;
        setTimeout(function () { attempt(ctl, run, n + 1); }, RETRY_MS * n);
    }

    function start(ctl, hold, b64) {
        if (!global.TerminalHistory || !ctl || !ctl.term) return;
        var run = { gen: hold.gen, nav: hold.nav, sid: hold.sid, b64: b64 || null, ws: ctl.ws || null };
        var prev = runs.get(ctl);
        runs.set(ctl, run);
        if (!alive(ctl, run)) {
            if (prev) runs.set(ctl, prev); else runs.delete(ctl);
            return;
        }
        attempt(ctl, run, 1);
    }

    global.TerminalHistoryFollowup = { MAX_ATTEMPTS: MAX_ATTEMPTS, start: start };
}(typeof window !== 'undefined' ? window : globalThis));
