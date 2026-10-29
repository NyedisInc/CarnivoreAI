/* there is nothing */
(function () {
    'use strict';

    var SETTLE_MS = 500;

    var ANNOUNCED = [
        'window.resize',
        'orientationchange',
        'visualViewport.resize',
        'handshake',
        'ws.onopen',
        'sidebar-pin',
        'right-drawer',
        'agent-drawer-dock',
        'terminal-foot-bar'
    ];

    function isAnnounced(source) {
        return ANNOUNCED.indexOf(String(source)) !== -1;
    }

    function settleMsFor(source, baseMs) {
        var base = typeof baseMs === 'number' && baseMs > 0 ? baseMs : 0;
        if (isAnnounced(source)) return base;
        return Math.max(base, SETTLE_MS);
    }

    function decideResize(input) {
        var o = input || {};
        if (isAnnounced(o.source)) return 'ship';

        var same = typeof o.cols === 'number' && typeof o.rows === 'number'
            && o.cols === o.lastCols && o.rows === o.lastRows;
        return same ? 'skip_transient' : 'ship';
    }

    function describeCulprit(container) {
        try {
            if (!container || !container.children) return '';
            var shown = [];
            for (var i = 0; i < container.children.length; i++) {
                var el = container.children[i];
                if (!el || el.id === 'terminal') continue;
                var visible = !(el.style && el.style.display === 'none');
                if (!visible) continue;
                var label = String(el.tagName || '').toLowerCase();
                if (el.id) label += '#' + el.id;
                if (el.className && typeof el.className === 'string') {
                    label += '.' + el.className.trim().split(/\s+/).join('.');
                }
                shown.push(label);
            }
            return shown.join(' ');
        } catch (err) {
            console.warn('TerminalResizeSettle: culprit read failed', err);
            return '';
        }
    }

    window.TerminalResizeSettle = {
        SETTLE_MS: SETTLE_MS,
        ANNOUNCED: ANNOUNCED,
        isAnnounced: isAnnounced,
        settleMsFor: settleMsFor,
        decideResize: decideResize,
        describeCulprit: describeCulprit
    };
})();
