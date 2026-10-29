(function (global) {
    'use strict';

    var SETTLE_MS = 50;
    var HELD_POLL_MS = 1000;

    var controllers = new Set();
    var observer = null;
    var timer = null;
    var pollTimer = null;

    function insideXterm(rec) {
        var t = rec.target;
        return !!(t && t.closest && t.closest('.xterm'));
    }

    function schedule() {
        if (timer === null) timer = setTimeout(check, SETTLE_MS);
    }

    function painted(ctl) {
        if (global.CarnivoreWindowHidden === true) return false;
        var el = ctl.term && ctl.term.element;
        var addons = global.TerminalAddons;
        if (!el || !addons || typeof addons.isPainted !== 'function') return true;
        return addons.isPainted(el, global.document);
    }

    function report(ctl, held) {
        var ws = ctl.ws;
        if (!ws || ws.readyState !== 1) return;
        try { ws.send(JSON.stringify({ type: held ? 'pause' : 'resume' })); } catch (err) {  }
    }

    function release(ctl) {
        ctl._paintHeld = false;
        report(ctl, false);
        var held = ctl.queue && ctl.queue.length > 0;
        if (held && !ctl.flushing && ctl.term) {
            ctl.flushing = true;
            ctl.flush();
        }
        if (held && ctl.term && typeof ctl.term.write === 'function') {
            ctl.term.write('', function () {
                if (ctl.term && !ctl._paintHeld) ctl.term.refresh(0, ctl.term.rows - 1);
            });
        }
    }

    function check() {
        timer = null;
        var anyHeld = false;
        controllers.forEach(function (ctl) {
            if (ctl._disposed) { controllers.delete(ctl); return; }
            var shown = painted(ctl);
            if (shown && ctl._paintHeld) release(ctl);
            else if (!shown) { if (!ctl._paintHeld) report(ctl, true); ctl._paintHeld = true; anyHeld = true; }
        });
        if (pollTimer !== null) { clearTimeout(pollTimer); pollTimer = null; }
        if (anyHeld) pollTimer = setTimeout(schedule, HELD_POLL_MS);
        if (!controllers.size) uninstall();
    }

    function install() {
        if (observer || typeof global.MutationObserver !== 'function') return;
        observer = new global.MutationObserver(function (records) {
            for (var i = 0; i < records.length; i++) {
                if (!insideXterm(records[i])) { schedule(); return; }
            }
        });
        observer.observe(global.document.documentElement, {
            attributes: true, subtree: true,
            attributeFilter: ['class', 'style', 'hidden', 'inert'],
        });
        global.document.addEventListener('visibilitychange', schedule);
    }

    function uninstall() {
        if (observer) observer.disconnect();
        observer = null;
        global.document.removeEventListener('visibilitychange', schedule);
        if (timer !== null) clearTimeout(timer);
        if (pollTimer !== null) clearTimeout(pollTimer);
        timer = pollTimer = null;
    }

    function register(ctl) {
        if (!ctl || controllers.has(ctl)) return;
        ctl._paintHeld = false;
        controllers.add(ctl);
        install();
        schedule();
    }

    function unregister(ctl) {
        controllers.delete(ctl);
        if (!controllers.size) uninstall();
    }

    global.TerminalPaintGate = {
        register: register,
        unregister: unregister,
        check: check,
        reassert: function (ctl) { if (ctl && ctl._paintHeld) report(ctl, true); },
    };
})(window);
