(function (global) {
    'use strict';

    var STEP_LINES = 2500;
    var MAX_LINES = 50000;
    var RETRY_MS = 5000;

    var states = new WeakMap();
    var attached = new WeakSet();

    function heldRows(term) {
        var buf = term && term.buffer && term.buffer.active;
        return buf && typeof buf.baseY === 'number' ? buf.baseY : 0;
    }

    function nextDepth(held) {
        return Math.min(MAX_LINES, held + STEP_LINES);
    }

    function stateFor(term, sessionId, navToken) {
        var st = states.get(term);
        var base = heldRows(term);
        if (!st || st.sessionId !== sessionId || st.navToken !== navToken
            || base < st.baseY) {
            st = { sessionId: sessionId, navToken: navToken, inflight: false,
                   exhausted: false, baseY: base, retryAt: 0 };
            states.set(term, st);
        }
        return st;
    }

    async function fetchOlder(ctl, now) {
        var term = ctl && ctl.term;
        var buf = term && term.buffer && term.buffer.active;
        var history = global.TerminalHistory;
        if (!buf || !history || buf.type === 'alternate' || buf.viewportY > 0) {
            return 'skipped';
        }
        var sessionId = typeof ctl._sessionId === 'function' ? ctl._sessionId() : null;
        if (!sessionId) return 'skipped';
        var st = stateFor(term, sessionId, ctl._navToken);
        if (st.inflight) return 'busy';
        if (st.exhausted) return 'skipped';
        var held = heldRows(term);
        if (held >= MAX_LINES) {
            st.exhausted = true;
            return 'skipped';
        }
        if ((now === undefined ? Date.now() : now) < st.retryAt) return 'skipped';

        st.inflight = true;
        var outcome;
        try {
            outcome = await history.ensureLoaded(term, sessionId, ctl,
                { scrollbackLines: nextDepth(held) });
        } finally {
            st.inflight = false;
        }
        if (outcome.loaded === 'painted') {
            st.baseY = heldRows(term);
            return 'painted';
        }
        if (outcome.reason === 'not_deeper') {
            st.exhausted = true;
            return 'top';
        }
        if (outcome.reason === 'navigated_away') return 'stale';
        if (outcome.reason === 'alternate_screen') return 'skipped';
        st.retryAt = (now === undefined ? Date.now() : now) + RETRY_MS;
        return 'failed';
    }

    function attach(ctl) {
        var term = ctl && ctl.term;
        if (!term || typeof term.onScroll !== 'function' || attached.has(term)) return;
        attached.add(term);
        term.onScroll(function () {
            var buf = term.buffer && term.buffer.active;
            if (buf && buf.viewportY === 0 && buf.baseY > 0) {
                fetchOlder(ctl).catch(function (err) {
                    console.warn('TerminalHistoryScroll: fetch failed', err);
                });
            }
        });
    }

    global.TerminalHistoryScroll = {
        STEP_LINES: STEP_LINES,
        MAX_LINES: MAX_LINES,
        RETRY_MS: RETRY_MS,
        nextDepth: nextDepth,
        fetchOlder: fetchOlder,
        attach: attach
    };
}(typeof window !== 'undefined' ? window : globalThis));
