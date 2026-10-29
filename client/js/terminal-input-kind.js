/* something else */
(function () {
    'use strict';

    var SGR_MOUSE_REPORT = /^\x1b\[<\d{1,5};\d{1,5};\d{1,5}[Mm]$/;

    var X10_MOUSE_REPORT = /^\x1b\[M[\s\S]{3}$/;

    function isMouseReport(data) {
        if (typeof data !== 'string') return false;
        if (data.length < 6) return false;
        return SGR_MOUSE_REPORT.test(data) || X10_MOUSE_REPORT.test(data);
    }

    window.TerminalInputKind = {
        isMouseReport: isMouseReport
    };
})();
