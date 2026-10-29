/* and writes nothing the session underneath the whole conversation */
(function () {
    'use strict';

    var PAINT = {
        REPLACE: 'replace',
        KEEP: 'keep',
        KEEP_AND_APPEND_CAPTURE: 'keep_and_append_capture'
    };

    function measureBufferLines(term) {
        if (!term) return 0;
        try {
            var buf = term.buffer && term.buffer.active;
            if (!buf) return 0;

            var baseY = typeof buf.baseY === 'number' ? buf.baseY : 0;
            var cursorY = typeof buf.cursorY === 'number' ? buf.cursorY : 0;
            var length = typeof buf.length === 'number' ? buf.length : 0;

            var visible = 0;
            if (length && typeof buf.getLine === 'function') {
                for (var i = baseY; i < length; i++) {
                    var line = buf.getLine(i);
                    var text = line && typeof line.translateToString === 'function'
                        ? line.translateToString(true)
                        : '';
                    if (text && text.trim() !== '') visible++;
                }
            }
            return Math.max(baseY + visible, baseY + cursorY);
        } catch (err) {
            console.warn('TerminalReconnectBuffer: buffer read failed', err);
            return 0;
        }
    }

    function decideReconnectPaint(input) {
        var opts = input || {};
        var sameSession = opts.sameSession === true;
        var bufferLines = typeof opts.bufferLines === 'number' && opts.bufferLines > 0
            ? opts.bufferLines
            : 0;

        if (sameSession && bufferLines > 0) return PAINT.KEEP;
        return PAINT.REPLACE;
    }

    function isSameSession(previousId, incomingId) {
        if (!previousId || !incomingId) return false;
        return String(previousId) === String(incomingId);
    }

    function planFor(term, previousId, incomingId, captureB64) {
        var bufferLines = measureBufferLines(term);
        var captureBytes = captureB64 ? captureB64.length : 0;
        var verdict = decideReconnectPaint({
            sameSession: isSameSession(previousId, incomingId),
            bufferLines: bufferLines,
            captureBytes: captureBytes
        });
        console.log('[TERM-REJOIN] ' + verdict + ' session=' + incomingId +
            ' was=' + previousId + ' bufferLines=' + bufferLines +
            ' captureB64Bytes=' + captureBytes);
        return verdict;
    }

    window.TerminalReconnectBuffer = {
        PAINT: PAINT,
        decideReconnectPaint: decideReconnectPaint,
        measureBufferLines: measureBufferLines,
        isSameSession: isSameSession,
        planFor: planFor
    };
})();
