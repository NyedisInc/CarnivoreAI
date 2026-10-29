(function () {
    'use strict';

    var FALLBACK_CELL_HEIGHT = 17;

    var GESTURE_GAIN = 4;

    function viewportFor(term, root) {
        var el = term && term.element;
        if (el && typeof el.querySelector === 'function') {
            return el.querySelector('.xterm-viewport');
        }
        if (root && typeof root.querySelector === 'function') {
            return root.querySelector('.xterm-viewport');
        }
        if (typeof document === 'undefined'
            || typeof document.querySelector !== 'function') return null;
        return document.querySelector('.xterm-viewport');
    }

    function cellHeight(term, root) {
        try {
            var vp = viewportFor(term, root);
            if (vp && vp.clientHeight > 0 && term && term.rows > 0) {
                return vp.clientHeight / term.rows;
            }
        } catch (err) {
            console.warn('TerminalScrollStep: cell height read failed', err);
        }
        return FALLBACK_CELL_HEIGHT;
    }

    function rowsForPixels(px, term, root) {
        if (!px) return 0;
        return (px / cellHeight(term, root)) * GESTURE_GAIN;
    }

    function rowsForWheel(ev, term, root) {
        if (!ev || !ev.deltaY) return 0;
        var rows;
        if (ev.deltaMode === 1) {
            rows = ev.deltaY * GESTURE_GAIN;
        } else if (ev.deltaMode === 2) {
            rows = ev.deltaY * ((term && term.rows) || 1);
        } else {
            rows = rowsForPixels(ev.deltaY, term, root);
        }
        var dir = ev.deltaY > 0 ? 1 : -1;
        return Math.trunc(rows) || dir;
    }

    window.TerminalScrollStep = {
        cellHeight: cellHeight,
        rowsForPixels: rowsForPixels,
        rowsForWheel: rowsForWheel,
        GESTURE_GAIN: GESTURE_GAIN,
        FALLBACK_CELL_HEIGHT: FALLBACK_CELL_HEIGHT
    };
})();
