/* reconnect to the SAME session */

console.log('[TerminalInputBuffer Module] Loading...');

(function (global) {
    'use strict';

    var MAX_BUFFERED_BYTES = 64 * 1024;

    var READY_TIMEOUT_MS = 4000;

    function createTerminalInputBuffer(deps) {
        var wiring = deps || {};

        function startupNotice() {
            return wiring.startupNotice !== undefined
                ? wiring.startupNotice : global.TerminalStartupNotice;
        }

        var generation = 0;

        var phase = 'idle';

        /** @type {Array<Uint8Array>} Chunks held, oldest first. */
        var held = [];

        /** @type {number} Running total of held bytes, so admission is O(1). */
        var heldBytes = 0;

        /** @type {string|null} What this generation was armed for, for logs. */
        var label = null;

        function arm(what) {
            if (phase === 'buffering') {
                return generation;
            }
            generation += 1;
            phase = 'buffering';
            held = [];
            heldBytes = 0;
            label = what == null ? null : String(what);
            return generation;
        }

        function offer(token, bytes) {
            if (phase === 'idle' || phase === 'ready') return 'send_now';
            if (typeof token !== 'number' || token !== generation) {
                console.debug('[input-buffer] dropped input from a superseded connection',
                    { token: token, current: generation, label: label });
                return 'stale_generation';
            }
            if (phase === 'rejected_overflow') return 'refused_overflowed';

            var size = (bytes && typeof bytes.length === 'number') ? bytes.length : 0;
            if (heldBytes + size > MAX_BUFFERED_BYTES) {
                var lost = heldBytes + size;
                held = [];
                heldBytes = 0;
                phase = 'rejected_overflow';
                console.warn('[input-buffer] rejected', lost,
                    'bytes of pre-ready input: over the', MAX_BUFFERED_BYTES,
                    'byte bound', { label: label, generation: generation });
                return 'rejected_overflow';
            }
            held.push(bytes);
            heldBytes += size;
            return 'buffered';
        }

        function release(token) {
            if (typeof token !== 'number' || token !== generation) {
                console.debug('[input-buffer] ignored a ready for a superseded connection',
                    { token: token, current: generation });
                return { outcome: 'stale_generation', chunks: [], bytes: 0 };
            }
            if (phase === 'rejected_overflow') {
                phase = 'ready';
                return { outcome: 'overflowed', chunks: [], bytes: 0 };
            }
            var chunks = held;
            var bytes = heldBytes;
            held = [];
            heldBytes = 0;
            phase = 'ready';
            if (!chunks.length) return { outcome: 'nothing_held', chunks: [], bytes: 0 };
            console.log('[input-buffer] flushing', bytes, 'bytes typed before the pane was ready');
            return { outcome: 'flushed', chunks: chunks, bytes: bytes };
        }

        function discard(reason) {
            var bytes = heldBytes;
            held = [];
            heldBytes = 0;
            phase = 'idle';
            if (!bytes) return { outcome: 'nothing_held', bytes: 0 };
            console.warn('[input-buffer] discarded', bytes,
                'bytes of pre-ready input:', reason || 'no reason given');
            return { outcome: 'discarded', bytes: bytes };
        }

        function state() {
            return phase;
        }

        function heldByteCount() {
            return heldBytes;
        }

        // ------------------------------------------------------------------
        // ------------------------------------------------------------------

        var RETYPE_MESSAGE = 'input dropped, the session was not ready yet. type it again.';

        var gapReported = false;

        function report(controller, text) {
            if (controller && typeof controller._showStatusPill === 'function') {
                controller._showStatusPill(text, 'error');
                return;
            }
            console.warn('[input-buffer]', text);
        }

        function begin(controller, what) {
            cancelBackstop();
            gapReported = false;
            discard('a new connection to the pane is starting');
            var gen = arm(what);
            if (controller) controller._connGen = gen;
            return gen;
        }

        function send(controller, bytes) {
            var verdict = offer(controller ? controller._connGen : null, bytes);
            if (verdict === 'rejected_overflow') report(controller, RETYPE_MESSAGE);
            if (verdict !== 'send_now') return false;
            var ws = controller && controller.ws;
            if (!ws || ws.readyState !== 1 ) {
                if (!gapReported) {
                    gapReported = true;
                    report(controller, RETYPE_MESSAGE);
                }
                return false;
            }
            gapReported = false;
            ws.send(bytes);
            return true;
        }

        function flushOnReady(controller, message) {
            cancelBackstop();
            var r = release(controller ? controller._connGen : null);
            console.log('[input-buffer] pane ready', {
                startup_command: message && message.startup_command,
                input: r.outcome, bytes: r.bytes
            });
            var notice = startupNotice();
            if (notice) {
                notice.show(
                    controller && typeof controller._sessionId === 'function'
                        ? controller._sessionId() : null,
                    message && message.startup_command
                );
            }
            if (r.outcome !== 'flushed') return r.outcome;
            var ws = controller && controller.ws;
            if (!ws || ws.readyState !== 1 ) {
                report(controller, RETYPE_MESSAGE);
                return 'socket_gone';
            }
            for (var i = 0; i < r.chunks.length; i++) ws.send(r.chunks[i]);
            if (typeof controller._noteUserInputToSession === 'function') {
                controller._noteUserInputToSession();
            }
            return 'flushed';
        }

        function abandon(controller, reason) {
            cancelBackstop();
            var r = discard(reason);
            if (r.outcome === 'discarded') report(controller, RETYPE_MESSAGE);
            return r.outcome;
        }

        /** @type {*} The backstop timer, so a ready can cancel it. */
        var backstop = null;

        function armReadyBackstop(controller, ms) {
            cancelBackstop();
            var wait = typeof ms === 'number' ? ms : READY_TIMEOUT_MS;
            var forGeneration = generation;
            backstop = setTimeout(function () {
                backstop = null;
                if (phase !== 'buffering' || generation !== forGeneration) return;
                console.warn('[input-buffer] no terminal.ready after ' + wait
                    + 'ms, sending anyway and passing input straight through');
                flushOnReady(controller, { startup_command: 'unknown',
                    via: 'ready_backstop' });
            }, wait);
        }

        function cancelBackstop() {
            if (backstop !== null) {
                clearTimeout(backstop);
                backstop = null;
            }
        }

        return {
            MAX_BUFFERED_BYTES: MAX_BUFFERED_BYTES,
            READY_TIMEOUT_MS: READY_TIMEOUT_MS,
            RETYPE_MESSAGE: RETYPE_MESSAGE,
            armReadyBackstop: armReadyBackstop,
            arm: arm,
            offer: offer,
            release: release,
            discard: discard,
            state: state,
            heldByteCount: heldByteCount,
            begin: begin,
            send: send,
            flushOnReady: flushOnReady,
            abandon: abandon
        };
    }

    var defaultInstance = createTerminalInputBuffer();

    global.TerminalInputBuffer = Object.assign(
        { create: createTerminalInputBuffer }, defaultInstance);
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalInputBuffer Module] Exported as window.TerminalInputBuffer');
