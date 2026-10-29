
console.log('[TerminalAddons Module] Loading...');

(function (global) {
    'use strict';

    var WEBGL_CONTEXT_CAP = 16;

    var REARM_MIN_INTERVAL_MS = 5000;

    var MAX_REARMS = 2;

    var records = [];
    var passTimer = null;
    var focusTimer = null;
    var listening = false;

    function liveCount() {
        var n = 0;
        for (var i = 0; i < records.length; i += 1) if (records[i].live) n += 1;
        return n;
    }

    function attach(rec) {
        var addon = new WebglAddon.WebglAddon();
        rec.term.loadAddon(addon);
        rec.addon = addon;
        rec.live = true;
        if (rec.holder) rec.holder._webglAddon = addon;
        var released = false;
        function release() {
            if (released) return false;
            released = true;
            if (rec.addon === addon) {
                rec.addon = null;
                rec.live = false;
                if (rec.holder && rec.holder._webglAddon === addon) rec.holder._webglAddon = null;
            }
            return true;
        }
        var dispose = addon.dispose;
        addon.dispose = function () {
            var result = dispose.apply(addon, arguments);
            if (release()) { rec.retired = true; schedulePass(); }
            return result;
        };
        addon.onContextLoss(function () {
            console.warn('Terminal: WebGL context lost - disposing addon, '
                + 'falling back to DOM renderer');
            release();
            rec.lastAt = Date.now();
            try { addon.dispose(); } catch (err) {  }
        });
        return addon;
    }

    function loadWebgl(term, holder) {
        var rec = { term: term, holder: holder || null, addon: null, live: false,
            rearms: 0, retired: false, lastAt: -Infinity };
        var addon = null;
        try {
            addon = attach(rec);
        } catch (err) {
            console.warn('Terminal: WebGL addon unavailable - using DOM renderer', err);
            return null;
        }
        prune();
        records.push(rec);
        listenOnce();
        redrawWhenPaintedAgain(term, rec);
        return addon;
    }

    var UNPAINTED_POLL_MS = 100;

    /*  hidden  display: none */
    function isPainted(el, doc) {
        if (!el || !el.isConnected) return false;
        if (doc && doc.visibilityState === 'hidden') return false;
        if (typeof el.checkVisibility === 'function') {
            return el.checkVisibility({ visibilityProperty: true, contentVisibilityAuto: true });
        }
        var view = el.ownerDocument && el.ownerDocument.defaultView;
        if (!view || typeof view.getComputedStyle !== 'function') return true;
        var style = view.getComputedStyle(el);
        return style.visibility !== 'hidden' && style.display !== 'none';
    }

    /*  hidden  visibility: hidden */
    function redrawWhenPaintedAgain(term, rec) {
        if (!term || typeof term.onRender !== 'function') return;
        var doc = global.document;
        var dirty = false;
        var pollTimer = null;
        var redrawTimer = null;

        function redraw() {
            redrawTimer = null;
            if (!term.element || !term.element.isConnected) return;
            if (rec && !rec.live) { schedulePass(); return; }
            term.refresh(0, term.rows - 1);
        }

        function scheduleRedraw() {
            dirty = false;
            if (redrawTimer === null) redrawTimer = setTimeout(redraw, UNPAINTED_POLL_MS);
        }

        function poll() {
            pollTimer = null;
            if (!term.element || !term.element.isConnected) return;
            if (isPainted(term.element, doc)) {
                scheduleRedraw();
                return;
            }
            pollTimer = setTimeout(poll, UNPAINTED_POLL_MS);
        }

        term.onRender(function () {
            if (!isPainted(term.element, doc)) {
                dirty = true;
                if (pollTimer === null) pollTimer = setTimeout(poll, UNPAINTED_POLL_MS);
            } else if (dirty) {
                scheduleRedraw();
            }
        });
    }

    function prune() {
        records = records.filter(function (rec) {
            return rec.live || (!rec.retired && rec.term.element && rec.term.element.isConnected);
        });
    }

    function rearm(rec) {
        if (rec.live || rec.retired || rec.rearms >= MAX_REARMS) return false;
        if (!isPainted(rec.term.element, global.document)) return false;
        if (liveCount() >= WEBGL_CONTEXT_CAP) return false;
        if (Date.now() - rec.lastAt < REARM_MIN_INTERVAL_MS) return false;
        rec.rearms += 1;
        rec.lastAt = Date.now();
        try {
            attach(rec);
        } catch (err) {
            console.warn('Terminal: WebGL re-arm failed - staying on the DOM renderer', err);
            return false;
        }
        rec.term.refresh(0, rec.term.rows - 1);
        return true;
    }

    function runPass() {
        passTimer = null;
        prune();
        for (var i = 0; i < records.length; i += 1) rearm(records[i]);
    }

    function schedulePass() {
        if (passTimer === null) passTimer = setTimeout(runPass, UNPAINTED_POLL_MS);
    }

    /*  hidden
 */
    function refreshLive() {
        focusTimer = null;
        for (var i = 0; i < records.length; i += 1) {
            var rec = records[i];
            if (rec.live && isPainted(rec.term.element, global.document)) {
                rec.term.refresh(0, rec.term.rows - 1);
            }
        }
    }

    function listenOnce() {
        if (listening) return;
        listening = true;
        if (typeof global.addEventListener === 'function') {
            global.addEventListener('focus', function () {
                if (focusTimer === null) focusTimer = setTimeout(refreshLive, UNPAINTED_POLL_MS);
                schedulePass();
            });
        }
        var doc = global.document;
        if (doc && typeof doc.addEventListener === 'function') {
            doc.addEventListener('visibilitychange', schedulePass);
        }
    }

    function loadUnicode11(term) {
        try {
            term.loadAddon(new Unicode11Addon.Unicode11Addon());
            term.unicode.activeVersion = '11';
        } catch (err) {
            console.warn('Unicode11 addon not available', err);
        }
    }

    global.TerminalAddons = {
        loadWebgl: loadWebgl,
        loadUnicode11: loadUnicode11,
        isPainted: isPainted,
        UNPAINTED_POLL_MS: UNPAINTED_POLL_MS,
        WEBGL_CONTEXT_CAP: WEBGL_CONTEXT_CAP,
        REARM_MIN_INTERVAL_MS: REARM_MIN_INTERVAL_MS,
        MAX_REARMS: MAX_REARMS,
    };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalAddons Module] Exported as window.TerminalAddons');
