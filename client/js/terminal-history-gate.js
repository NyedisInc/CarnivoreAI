
console.log('[TerminalHistoryGate Module] Loading...');

(function (global) {
    'use strict';

    var HELD_MAX_BYTES = 64 * 1024;

    var HISTORY_HOLD_MS = 2000;

    function active(controller) {
        var hold = controller && controller._historyGate;
        return hold && hold.on ? hold : null;
    }

    function holding(controller) {
        return !!active(controller);
    }

    function offer(controller, bytes) {
        var hold = active(controller);
        if (!hold) return false;
        var policy = global.TerminalWriteQueue;
        if (policy) {
            var over = policy.overflowBytes(hold.bytes, bytes.length, HELD_MAX_BYTES);
            if (over > 0) {
                var dropped = policy.shedFront(hold.frames, over);
                hold.bytes -= dropped;
                if (hold.bytes < 0) hold.bytes = 0;
                hold.dropped += dropped;
                console.warn('[terminal] shed', dropped, 'bytes of held output');
            }
        }
        hold.frames.push(bytes);
        hold.bytes += bytes.length;
        return true;
    }

    function release(controller, reason) {
        var hold = active(controller);
        if (!hold) return;
        hold.on = false;
        clearTimeout(hold.timer);
        var frames = hold.frames;
        hold.frames = [];
        hold.bytes = 0;
        console.log('Terminal: history hold released (' + reason + '), '
            + frames.length + ' live frames follow');
        if (hold.dropped && global.TerminalWriteQueue && typeof TextEncoder !== 'undefined') {
            frames.unshift(new TextEncoder().encode(global.TerminalWriteQueue.dropMarker(hold.dropped)));
        }
        for (var i = 0; i < frames.length; i++) controller.enqueue(frames[i]);
    }

    function discard(controller, reason) {
        var hold = active(controller);
        if (!hold) return;
        hold.on = false;
        clearTimeout(hold.timer);
        console.log('Terminal: history hold discarded (' + reason + '), '
            + hold.frames.length + ' held frames dropped');
        hold.frames = [];
        hold.bytes = 0;
    }

    function valid(controller, hold) {
        if (controller._historyGate !== hold || !hold.on) return false;
        if (controller._connGen !== hold.gen) return false;
        return typeof controller._navCurrent !== 'function' || controller._navCurrent('history');
    }

    async function onHistory(controller, hold, b64) {
        var outcome = 'nothing';
        try {
            if (valid(controller, hold) && b64 && global.TerminalScrollbackPaint) {
                outcome = await global.TerminalScrollbackPaint.paint(controller, b64, 'rejoin', {
                    stillValid: function () { return valid(controller, hold); }
                });
            }
        } catch (err) {
            console.warn('Terminal: history paint failed, continuing without it:', err);
        }
        if (!hold.on || controller._historyGate !== hold) return;
        if (valid(controller, hold)) release(controller, 'history ' + outcome);
        else discard(controller, 'stale connection or navigation');
    }

    function begin(controller, pending, opts) {
        discard(controller, 'a new hold begins');
        var hold = {
            on: true, gen: controller._connGen, frames: [], bytes: 0, dropped: 0, timer: null
        };
        controller._historyGate = hold;
        var ms = opts && opts.holdMs > 0 ? opts.holdMs : HISTORY_HOLD_MS;
        hold.timer = setTimeout(function () {
            if (controller._historyGate === hold) release(controller, 'bound ' + ms + ' ms');
        }, ms);
        Promise.resolve(pending).then(function (b64) {
            return onHistory(controller, hold, b64);
        }, function () {
            return onHistory(controller, hold, null);
        });
    }

    global.TerminalHistoryGate = {
        HELD_MAX_BYTES: HELD_MAX_BYTES,
        HISTORY_HOLD_MS: HISTORY_HOLD_MS,
        begin: begin,
        holding: holding,
        offer: offer,
        release: release,
        discard: discard
    };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalHistoryGate Module] Exported as window.TerminalHistoryGate');
