/* scrollback: the */
(function (global) {
    'use strict';

    var CARET = '❯';

    var CODEX_CARET = '\u203a';

    var COMPOSER_TAIL_ROWS = 2;

    function caretFor(family) {
        return family === 'codex' ? CODEX_CARET : CARET;
    }

    var RESULT_MARK = '⎿';

    var RULE_CHAR = '─';

    var RULE_RUN = 20;

    var MENU_RADIUS = 30;

    var PREVIEW_CHARS = 80;

    var MAX_TEXT = (global.TerminalPromptJoin || {}).MAX_TEXT;

    var LIVE_BOX_RADIUS = 2;

    function isPromptCell(cell, caret) {
        if (!cell) return false;
        try {
            return cell.getChars() === (caret || CARET);
        } catch (err) {
            return false;
        }
    }

    function isPromptHead(raw, caret) {
        return String(raw || '').indexOf(caret || CARET) === 0
            && /^.[ \u00a0]+\S/.test(String(raw));
    }

    function isRuleRow(raw, isRule) {
        if (typeof isRule === 'function') return !!isRule(raw);
        return String(raw || '').indexOf(new Array(RULE_RUN + 1).join(RULE_CHAR)) !== -1;
    }

    /* Read 2 files (ctrl+o to expand) */
    function continuesPrompt(buf, i, indent, isRule, slash) {
        var text = rowText(buf, i);
        if (isRuleRow(text, isRule)) return false;
        if (rowWrapped(buf, i) === true) return true;
        var body = text.replace(/^\s+/, '');
        if (body === '' || body.charAt(0) === RESULT_MARK) return false;
        var lead = text.length - body.length;
        return !slash && lead >= 1 && lead <= indent;
    }

    function isMenuOption(buf, line, raw, caret) {
        if (raw.indexOf(caret || CARET) !== 0 || !/^.[ \u00a0]+\d+\.\s/.test(raw)) return false;
        var below = rowText(buf, line + 1);
        if (/^ {4,}\S/.test(below) && rowWrapped(buf, line + 1) !== true) return true;
        var sibling = /^ {2}\d+\.\s/;
        var dir = [1, -1];
        for (var d = 0; d < dir.length; d++) {
            for (var k = 1; k <= MENU_RADIUS; k++) {
                var at = line + dir[d] * k;
                if (at < 0 || at >= buf.length) break;
                var row = rowText(buf, at);
                if (sibling.test(row)) return true;
                if (/^\S/.test(row)) break;
            }
        }
        return false;
    }

    function rowText(buf, i) {
        try {
            var line = buf.getLine(i);
            if (!line || typeof line.translateToString !== 'function') return '';
            return line.translateToString(false) || '';
        } catch (err) {
            return '';
        }
    }

    /* padding */
    function caretWidth(raw, caret) {
        var text = String(raw || '');
        var at = text.indexOf(caret || CARET);
        if (at === -1) return 0;
        var rest = text.slice(at + 1);
        return at + 1 + (rest.length - rest.replace(/^\s+/, '').length);
    }

    function stripCaret(raw, caret) {
        var text = String(raw || '');
        return text.slice(caretWidth(text, caret));
    }

    function rowWrapped(buf, i) {
        try {
            var line = buf.getLine(i);
            if (!line || typeof line.isWrapped !== 'boolean') return null;
            return line.isWrapped;
        } catch (err) {
            return null;
        }
    }

    function joinPrompt(rows, wraps, cols, brk, caret) {
        var join = global.TerminalPromptJoin;
        if (!join || typeof join.joinRows !== 'function') return '';
        var indent = caretWidth(rows && rows.length > 0 ? rows[0] : '', caret);
        var out = stripCaret(join.joinRows(rows, wraps, cols, brk, indent), caret);
        return out.length > MAX_TEXT ? out.slice(0, MAX_TEXT) : out;
    }

    function inLiveBox(buf, line, baseY, rows, isRule) {
        if (typeof isRule !== 'function') return false;
        if (line < baseY) return false;
        if (rows > 0 && line >= baseY + rows) return false;
        var from = Math.max(0, line - LIVE_BOX_RADIUS);
        var to = line + LIVE_BOX_RADIUS;
        for (var j = from; j <= to; j++) {
            if (j === line) continue;
            if (isRule(rowText(buf, j))) return true;
        }
        return false;
    }

    function scan(buf, opts) {
        var out = [];
        if (!buf || typeof buf.getLine !== 'function') return out;
        var o = opts || {};
        var cols = typeof o.cols === 'number' && o.cols > 0 ? o.cols : 0;
        var baseY = typeof o.baseY === 'number'
            ? o.baseY
            : (typeof buf.baseY === 'number' ? buf.baseY : 0);
        var rows = typeof o.rows === 'number' && o.rows > 0 ? o.rows : 0;
        var isRule = typeof o.isRule === 'function' ? o.isRule : null;
        var caret = caretFor(o.family);
        var codex = caret === CODEX_CARET;

        var length = typeof buf.length === 'number' ? buf.length : 0;
        if (length <= 0) return out;

        var shared = null;
        try {
            if (typeof buf.getNullCell === 'function') shared = buf.getNullCell();
        } catch (err) {
            shared = null;
        }

        var lastText = null;
        var lastAfter = -1;
        var i = 0;
        while (i < length) {
            var cell = cellAt(buf, i, shared);
            var head = isPromptCell(cell, caret) ? rowText(buf, i) : '';
            if (!isPromptHead(head, caret)) {
                i++;
                continue;
            }

            var start = i;
            var indent = caretWidth(head, caret);
            var rowsOfPrompt = [head];
            var wrapsOfPrompt = [null];
            var j = i + 1;
            var slash = /^.[ \u00a0]+\/[A-Za-z][\w:.-]*(\s|$)/.test(head);
            while (j < length && continuesPrompt(buf, j, indent, isRule, slash)) {
                rowsOfPrompt.push(rowText(buf, j));
                wrapsOfPrompt.push(rowWrapped(buf, j));
                j++;
            }
            i = start + rowsOfPrompt.length;
            var after = start + rowsOfPrompt.length;

            var text = joinPrompt(rowsOfPrompt, wrapsOfPrompt, cols, ' ', caret);
            if (text === '') continue;
            if (text.charAt(0) === '!') continue;
            if (text === lastText) continue;
            if (isMenuOption(buf, start, head, caret)) continue;
            if (isRuleRow(rowText(buf, start - 1), isRule)
                || isRuleRow(rowText(buf, after), isRule)) continue;
            if (inLiveBox(buf, start, baseY, rows, isRule)) continue;

            lastText = text;
            if (codex) lastAfter = after;
            out.push({
                ordinal: out.length + 1,
                line: start,
                text: text,
                full: joinPrompt(rowsOfPrompt, wrapsOfPrompt, cols, '\n', caret),
                preview: text.length > PREVIEW_CHARS
                    ? text.slice(0, PREVIEW_CHARS)
                    : text
            });
        }
        if (codex && out.length > 0 && isComposerTail(buf, lastAfter, length)) out.pop();
        return out;
    }

    function isComposerTail(buf, from, length) {
        var n = 0;
        for (var k = from; k < length; k++) {
            if (rowText(buf, k).replace(/\s+/g, '') !== '') n++;
            if (n > COMPOSER_TAIL_ROWS) return false;
        }
        return true;
    }

    function cellAt(buf, i, shared) {
        try {
            var line = buf.getLine(i);
            if (!line || typeof line.getCell !== 'function') return null;
            return (shared ? line.getCell(0, shared) : line.getCell(0)) || null;
        } catch (err) {
            return null;
        }
    }

    var Ticks = global.TerminalPromptTicks || {};

    global.TerminalPromptScan = {
        scan: scan,
        isPromptCell: isPromptCell,
        isPromptHead: isPromptHead,
        CARET: CARET,
        CODEX_CARET: CODEX_CARET,
        PREVIEW_CHARS: PREVIEW_CHARS,
        MAX_TEXT: MAX_TEXT,
        layoutTicks: Ticks.layoutTicks,
        currentOrdinalFor: Ticks.currentOrdinalFor,
        TICK_MIN_GAP: Ticks.TICK_MIN_GAP
    };
}(typeof window !== 'undefined' ? window : globalThis));
