/* anything at all lands on the row that was asked for */
(function () {
    'use strict';

    var CSI_UP = '\x1b[A';
    var CSI_DOWN = '\x1b[B';

    var CSI_PAGE_UP = '\x1b[5~';
    var CSI_PAGE_DOWN = '\x1b[6~';

    var PAGE_ROWS = 16;

    var MAX_ROWS = 240;

    function keysForRows(rows, maxRows) {
        var cap = (typeof maxRows === 'number' && maxRows > 0) ? maxRows : MAX_ROWS;
        if (typeof rows !== 'number' || !isFinite(rows) || !rows) return '';
        var n = Math.min(Math.abs(Math.trunc(rows)), cap);
        if (!n) return '';
        var down = rows > 0;
        var pages = Math.floor(n / PAGE_ROWS);
        var singles = n - (pages * PAGE_ROWS);
        var pageKey = down ? CSI_PAGE_DOWN : CSI_PAGE_UP;
        var arrowKey = down ? CSI_DOWN : CSI_UP;
        var out = '';
        var i;
        for (i = 0; i < pages; i++) out += pageKey;
        for (i = 0; i < singles; i++) out += arrowKey;
        return out;
    }

    function keystrokesForRows(rows, maxRows) {
        var cap = (typeof maxRows === 'number' && maxRows > 0) ? maxRows : MAX_ROWS;
        if (typeof rows !== 'number' || !isFinite(rows) || !rows) return 0;
        var n = Math.min(Math.abs(Math.trunc(rows)), cap);
        return Math.floor(n / PAGE_ROWS) + (n % PAGE_ROWS);
    }

    window.AltScreenKeys = {
        keysForRows: keysForRows,
        keystrokesForRows: keystrokesForRows,
        PAGE_ROWS: PAGE_ROWS,
        MAX_ROWS: MAX_ROWS,
        _keys: {
            UP: CSI_UP,
            DOWN: CSI_DOWN,
            PAGE_UP: CSI_PAGE_UP,
            PAGE_DOWN: CSI_PAGE_DOWN
        }
    };
})();
