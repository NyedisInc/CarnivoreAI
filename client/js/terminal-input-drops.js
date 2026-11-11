(function (global) {
    'use strict';

    /** @type {number} Ring size. */
    var RING_MAX = 50;
    /** @type {number} Client-side minimum gap per (slot, reason), ms. */
    var REPORT_GAP_MS = 10000;
    /** @type {string} Route under the API base. */
    var ROUTE = '/terminal/input-drops';

    /** @type {Array<object>} The last RING_MAX drops, oldest first. */
    var drops = [];
    /** @type {Object<string, number>} Last report time per "slot|reason". */
    var lastReport = {};

    function activeSlot() {
        try {
            var el = global.document && global.document.activeElement;
            var host = el && el.closest ? el.closest('[data-abs-slot],[data-tab-pane]') : null;
            if (!host) return null;
            return host.getAttribute('data-abs-slot') || host.getAttribute('data-tab-pane');
        } catch (e) {
            return null;
        }
    }

    function currentOwner() {
        try {
            var f = global.TerminalInputFocus;
            var o = f && typeof f.current === 'function' ? f.current() : null;
            return o == null ? null : String(o);
        } catch (e) {
            return null;
        }
    }

    function clip(v, n) {
        return v == null || v === '' ? null : String(v).slice(0, n);
    }

    function send(entry) {
        try {
            if (!global.API || typeof global.API.rawCall !== 'function') return;
            var p = global.API.rawCall(ROUTE, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(entry)
            });
            if (p && typeof p.catch === 'function') p.catch(function () {  });
        } catch (e) {
        }
    }

    function record(reason, controller, extra) {
        try {
            var now = Date.now();
            var slot = clip(controller && controller._inputOwner, 120);
            var ws = controller && controller.ws;
            var entry = {
                reason: reason,
                slot: slot,
                owner: clip(currentOwner(), 120),
                active_slot: clip(activeSlot(), 120),
                hidden: !!(global.document && global.document.visibilityState === 'hidden'),
                ws_state: ws && typeof ws.readyState === 'number' ? ws.readyState : -1,
                buffer_phase: clip(extra && extra.phase, 40),
                page_ms: Math.max(0, Math.round(
                    (global.performance && global.performance.now) ? global.performance.now() : 0))
            };
            drops.push(entry);
            if (drops.length > RING_MAX) drops.shift();
            var key = (slot || '') + '|' + reason;
            if (lastReport[key] !== undefined && now - lastReport[key] < REPORT_GAP_MS) return;
            lastReport[key] = now;
            send(entry);
        } catch (e) {
        }
    }

    global.TerminalInputDrops = {
        record: record,
        ring: function () { return drops; },
        REPORT_GAP_MS: REPORT_GAP_MS
    };
})(window);
