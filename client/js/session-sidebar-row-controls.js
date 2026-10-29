
console.log('[SessionSidebarRowControls Module] Loading...');

(function () {
    'use strict';

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function pinButtonHtml(name, pinned) {
        var label = pinned ? 'Unpin ' + name : 'Pin ' + name + ' to the top';
        return (
            '<button type="button" class="session-sidebar-row-pin" data-pin-session="'
            + esc(name) + '" '
            + 'aria-pressed="' + (pinned ? 'true' : 'false') + '" tabindex="-1" '
            + 'aria-label="' + esc(label) + '" '
            + 'title="' + esc(pinned ? 'unpin' : 'pin to top') + '">'
            + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + '<line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14l-2-4V4H7v9l-2 4z"/>'
            + '</svg></button>'
        );
    }

    function escHtml(value) {
        var div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML.replace(/"/g, '&quot;');
    }

    window.SessionSidebarRowControls = {
        pinButtonHtml: pinButtonHtml,
        escAttr: esc,
        escHtml: escHtml,
    };
})();

console.log('[SessionSidebarRowControls Module] Exported as window.SessionSidebarRowControls');
