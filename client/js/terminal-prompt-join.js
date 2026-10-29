(function (global) {
    'use strict';

    var MAX_TEXT = 2000;

    function logicalLines(rows, wraps) {
        var out = [];
        var held = 0;
        for (var i = 0; i < rows.length; i++) {
            var raw = String(rows[i] == null ? '' : rows[i]);
            if (out.length > 0 && wraps && wraps[i] === true) {
                out[out.length - 1] += raw;
            } else {
                out.push(raw);
            }
            held += raw.length;
            if (held >= MAX_TEXT) break;
        }
        return out;
    }

    function firstWordLength(text) {
        var found = /^\s*(\S+)/.exec(String(text == null ? '' : text));
        return found ? found[1].length : 0;
    }

    function dedent(piece, indent) {
        if (indent < 2) return piece;
        var head = piece.slice(0, indent);
        if (head.length < indent || /\S/.test(head)) return piece;
        return piece.slice(indent - 1);
    }

    function joinRows(rows, wraps, cols, brk, indent) {
        var lines = logicalLines(rows, wraps);
        var ends = [];
        var width = cols > 0 ? cols : 0;
        for (var i = 0; i < lines.length; i++) {
            ends.push(lines[i].replace(/\s+$/, '').length);
            if (ends[i] > width) width = ends[i];
        }
        var out = '';
        for (var j = 0; j < lines.length; j++) {
            var piece = lines[j].replace(/\s+$/, '');
            if (j === 0) {
                out = piece;
            } else if (ends[j - 1] + 1 + firstWordLength(lines[j]) > width) {
                out += dedent(piece, indent);
            } else if (piece !== '' || brk !== ' ') {
                out += brk + piece.replace(/^\s+/, '');
            }
            if (out.length >= MAX_TEXT) break;
        }
        return out.replace(/\s+$/, '');
    }

    global.TerminalPromptJoin = {
        joinRows: joinRows,
        logicalLines: logicalLines,
        firstWordLength: firstWordLength,
        dedent: dedent,
        MAX_TEXT: MAX_TEXT
    };
}(typeof window !== 'undefined' ? window : globalThis));
