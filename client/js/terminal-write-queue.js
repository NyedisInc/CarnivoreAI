/* not a guarantee */

console.log('[TerminalWriteQueue Module] Loading...');

(function () {
    'use strict';

    var MAX_QUEUED_BYTES = 4 * 1024 * 1024;

    var MARKER_RESERVE = 128;

    function dropMarker(bytes) {
        return '\r\n\x1b[33m[cloude: dropped ' + bytes
            + ' bytes of output that could not be written in time]\x1b[0m\r\n';
    }

    function overflowBytes(queuedBytes, incomingBytes, budget) {
        var cap = (typeof budget === 'number' && budget > 0) ? budget : MAX_QUEUED_BYTES;
        var over = (queuedBytes + incomingBytes) - cap;
        return over > 0 ? over + MARKER_RESERVE : 0;
    }

    function shedFront(queue, needed) {
        var dropped = 0;
        while (queue.length && dropped < needed) {
            dropped += queue.shift().length;
        }
        return dropped;
    }

    window.TerminalWriteQueue = {
        MAX_QUEUED_BYTES: MAX_QUEUED_BYTES,
        MARKER_RESERVE: MARKER_RESERVE,
        dropMarker: dropMarker,
        overflowBytes: overflowBytes,
        shedFront: shedFront
    };
})();

console.log('[TerminalWriteQueue Module] Exported as window.TerminalWriteQueue');
