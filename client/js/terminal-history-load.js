(function (global) {
    'use strict';

    var memos = new WeakMap();

    var MAX_SCROLLBACK = 50000;

    function countLines(bytes) {
        if (!bytes || !bytes.length) return 0;
        var n = 0;
        for (var i = 0; i < bytes.length; i++) if (bytes[i] === 0x0a) n++;
        return bytes[bytes.length - 1] === 0x0a ? n : n + 1;
    }

    function decide(input) {
        var o = input || {};
        if (o.altScreen === true) return 'alternate_screen';
        var have = typeof o.bufferLines === 'number' ? o.bufferLines : 0;
        var got = typeof o.captureLines === 'number' ? o.captureLines : 0;
        if (got <= have) return 'not_deeper';
        return 'paint';
    }

    function forget() {
        memos = new WeakMap();
    }

    function result(loaded, lines, reason) {
        var r = { loaded: loaded, lines: lines || 0 };
        if (reason) r.reason = reason;
        return r;
    }

    function controller() {
        return global.TerminalController || null;
    }

    function alreadyLoaded(term, sessionId, navToken) {
        var memo = memos.get(term);
        if (!memo || memo.sessionId !== sessionId) return false;
        if (memo.navToken !== navToken) return false;
        var buf = term && term.buffer && term.buffer.active;
        if (!buf || typeof buf.baseY !== 'number') return false;
        return buf.baseY >= memo.baseYAfterPaint;
    }

    async function ensureLoaded(term, sessionId, explicitController, opts) {
        var ctl = explicitController || controller();
        var buf = term && term.buffer && term.buffer.active;
        if (!term || !buf) return result('unavailable', 0, 'no_terminal');

        if (buf.type === 'alternate') {
            return result('unavailable', 0, 'alternate_screen');
        }

        var navToken = ctl ? ctl._navToken : null;
        var depth = opts && opts.scrollbackLines > 0 ? opts.scrollbackLines : 0;
        if (!depth && alreadyLoaded(term, sessionId, navToken)) {
            return result('already', measure(term));
        }

        var scroll = ctl && typeof ctl._m === 'function'
            ? ctl._m('TerminalScroll') : global.TerminalScroll;
        var pinned = scroll && typeof scroll.isPinnedToBottom === 'function'
            ? scroll.isPinnedToBottom(term)
            : true;
        var distance = Math.max(0, (buf.baseY || 0) - (buf.viewportY || 0));
        var bufferLines = measure(term);

        var info;
        try {
            var api = global.API;
            if (!api || typeof api.getSession !== 'function') {
                return result('unavailable', 0, 'no_api');
            }
            info = await api.getSession(sessionId, {
                includeScrollback: true,
                cols: term.cols,
                rows: term.rows,
                scrollbackLines: depth || null
            });
        } catch (err) {
            console.warn('TerminalHistory: the capture request failed', err);
            return result('unavailable', 0, 'request_failed');
        }

        var ctlNow = explicitController || controller();
        if (ctlNow && (ctlNow._navToken !== navToken
            || (explicitController && ctlNow.term !== term))) {
            return result('unavailable', 0, 'navigated_away');
        }

        var b64 = info && (info.initial_scrollback_b64
            || (info.session && info.session.initial_scrollback_b64));
        if (!b64) return result('unavailable', 0, 'no_capture');

        var painter = global.TerminalScrollbackPaint;
        if (!painter || typeof painter.paint !== 'function') {
            return result('unavailable', 0, 'no_paint_module');
        }

        var captureLines;
        try {
            captureLines = countLines(painter.decodeCapture(b64));
        } catch (err) {
            console.warn('TerminalHistory: the capture would not decode', err);
            return result('unavailable', 0, 'decode_failed');
        }

        var verdict = decide({
            bufferLines: bufferLines,
            captureLines: captureLines,
            altScreen: buf.type === 'alternate'
        });
        if (verdict !== 'paint') {
            return verdict === 'alternate_screen'
                ? result('unavailable', 0, 'alternate_screen')
                : result('already', bufferLines, 'not_deeper');
        }

        raiseScrollback(term, captureLines);
        var shim = shimFor(term, ctlNow, pinned, distance, sessionId, navToken);
        var painted = await painter.paint(shim, b64, 'history',
            { clearScrollback: true });
        if (painted !== 'painted') {
            return result('unavailable', 0, painted);
        }
        rememberFrom(term, sessionId, navToken);
        return result('painted', captureLines);
    }

    function raiseScrollback(term, captureLines) {
        var want = Math.min(MAX_SCROLLBACK, captureLines + (term.rows || 0));
        if (term.options && want > (term.options.scrollback || 0)) {
            term.options.scrollback = want;
        }
    }

    function measure(term) {
        var m = global.TerminalReconnectBuffer;
        return m && typeof m.measureBufferLines === 'function'
            ? m.measureBufferLines(term)
            : 0;
    }

    function shimFor(term, ctl, pinned, distance, sessionId, navToken) {
        return {
            term: term,
            fitAddon: ctl ? ctl.fitAddon : null,
            _forceScrollToBottom: function () {
                rememberFrom(term, sessionId, navToken);
                if (pinned) {
                    if (ctl && typeof ctl._forceScrollToBottom === 'function') {
                        ctl._forceScrollToBottom();
                    }
                    return;
                }
                try {
                    var b = term.buffer.active;
                    term.scrollToLine(Math.max(0, (b.baseY || 0) - distance));
                } catch (err) {
                    console.warn('TerminalHistory: could not restore the '
                        + 'scroll position after the history paint', err);
                }
            }
        };
    }

    function rememberFrom(term, sessionId, navToken) {
        var buf = term && term.buffer && term.buffer.active;
        memos.set(term, {
            sessionId: sessionId,
            navToken: navToken,
            baseYAfterPaint: buf && typeof buf.baseY === 'number' ? buf.baseY : 0
        });
    }

    global.TerminalHistory = {
        ensureLoaded: ensureLoaded,
        decide: decide,
        countLines: countLines,
        forget: forget
    };
}(typeof window !== 'undefined' ? window : globalThis));
