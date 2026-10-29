
console.log('[TerminalScrollbackPaint Module] Loading...');

(function (global) {
    'use strict';

    function decodeCapture(b64) {
        var bin = atob(b64);
        var bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) {
            bytes[i] = bin.charCodeAt(i) & 0xff;
        }
        return bytes;
    }

    async function paint(controller, b64, what, opts) {
        if (controller) global.TerminalReadiness?.recordPrepaint?.(controller, null);
        if (!controller || !controller.term || !b64) return 'nothing';
        var connection = controller._connGen;
        var clearScrollback = !!(opts && opts.clearScrollback);

        var frames = await (global.TerminalLayoutWait
            ? global.TerminalLayoutWait.settleFrames(2)
            : Promise.resolve());

        if (opts && typeof opts.stillValid === 'function' && !opts.stillValid()) return 'stale';

        var measured = fitBeforePaint(controller, what);
        if (what === 'adopt' || what === 'rejoin') {
            global.TerminalReadiness?.recordPrepaint?.(controller, measured, frames, connection);
        }

        try {
            var bytes = decodeCapture(b64);
            controller.term.write((clearScrollback ? '\x1b[3J' : '')
                + '\x1b[?1049l\x1b[2J\x1b[H');
            controller.term.write(bytes, function () {
                if (typeof controller._forceScrollToBottom === 'function') {
                    controller._forceScrollToBottom();
                }
            });
            console.log('Terminal: painted ' + bytes.length + ' bytes of '
                + (what || 'session') + ' scrollback');
            return 'painted';
        } catch (err) {
            console.warn('Terminal: ' + (what || 'session')
                + ' scrollback paint failed, continuing without it:', err);
            return 'decode_failed';
        }
    }

    function fitBeforePaint(controller, what) {
        var metrics = global.TerminalMetrics;
        if (metrics && typeof metrics.guardedFit === 'function') {
            var r = metrics.guardedFit(controller);
            if (!r.fitted) {
                console.warn('Terminal: pre-paint fit skipped, reason=' + r.reason
                    + ' path=' + (what || 'session'));
            }
            return r;
        }
        try {
            if (controller.fitAddon && typeof controller.fitAddon.fit === 'function') {
                controller.fitAddon.fit();
                return { fitted: true, reason: 'unguarded' };
            }
        } catch (err) {
            console.warn('pre-paint fit failed (continuing):', err);
        }
        return { fitted: false, reason: 'fit-failed' };
    }

    global.TerminalScrollbackPaint = {
        paint: paint,
        decodeCapture: decodeCapture
    };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalScrollbackPaint Module] Exported as window.TerminalScrollbackPaint');
