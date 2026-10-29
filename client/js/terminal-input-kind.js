(function () {
    'use strict';

    var SGR_MOUSE_REPORT = /^\x1b\[<\d{1,5};\d{1,5};\d{1,5}[Mm]$/;

    var X10_MOUSE_REPORT = /^\x1b\[M[\s\S]{3}$/;

    function isMouseReport(data) {
        if (typeof data !== 'string') return false;
        if (data.length < 6) return false;
        return SGR_MOUSE_REPORT.test(data) || X10_MOUSE_REPORT.test(data);
    }

    var SOFT_KEYBOARD_SHORTCUTS = {
        '\u00a5': '\n',
        '\u20ac': '\t',
        '\uffe1': '\x1b[Z',
        '\u00a3': '\x1b[Z'
    };

    function isCoarsePointer() {
        return !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
    }

    function softKeyboardShortcut(data, coarse) {
        if (typeof data !== 'string' || !Object.prototype.hasOwnProperty.call(SOFT_KEYBOARD_SHORTCUTS, data)) return data;
        var isCoarse = typeof coarse === 'boolean' ? coarse : isCoarsePointer();
        return isCoarse ? SOFT_KEYBOARD_SHORTCUTS[data] : data;
    }

    window.TerminalInputKind = {
        isMouseReport: isMouseReport,
        isCoarsePointer: isCoarsePointer,
        softKeyboardShortcut: softKeyboardShortcut
    };
})();
