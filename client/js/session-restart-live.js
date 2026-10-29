
console.log('[SessionRestartLive Module] Loading...');

(function () {
    'use strict';

    function armHtml(opts) {
        var i18n = globalThis.CloudeI18n;
        var tr = function (key) {
            return (i18n && typeof i18n.t === 'function') ? i18n.t(key) : key;
        };
        // at the gesture
        var armedByGesture = !!(opts && opts.armedByGesture === true);
        return '<label class="restart-picker__arm oc-focus-host" for="restart-picker-live">'
            + '<input type="checkbox" id="restart-picker-live" '
            + (armedByGesture ? 'checked ' : '')
            + 'aria-describedby="restart-picker-arm-hint">'
            + '<span>' + tr('session.restart.picker.arm') + '</span>'
            + '<span class="restart-picker__sr" id="restart-picker-arm-hint">'
            + tr('session.restart.picker.arm.hint') + '</span>'
            + '</label>';
    }

    window.SessionRestartLive = {
        armHtml: armHtml,
    };
})();

console.log('[SessionRestartLive Module] Exported as window.SessionRestartLive');
