(function (global) {
    'use strict';

    var URL_REGEX = /https?:[/]{2}[^\s"'!*(){}|\\\^<>`─-╿]*[^\s"':,.!?{}|\\\^~\[\]`()<>─-╿]/;
    var URL_RAW_RE = /https?:[/]{2}[^\s"'!*(){}|\\\^<>`─-╿]+/g;
    var URL_CONT_RE = /^[^\s"'!*(){}|\\\^<>`─-╿]+/;
    var TRIM_END_RE = /["':,.!?{}|\\\^~\[\]`()<>─-╿]+$/;
    var LEADING_MARGIN_RE = /^(?:[ \t]*[│┃║][ \t]*|[ \t]*)/;
    var TRAILING_BORDER_RE = /[ \t]*[│┃║]?[ \t]*$/;
    var HARD_JOINER_RE = /[-?&=%_+~:#]$/;
    var URL_PUNCT_RE = /[\/?&=%#_~+\-]/;
    var NEW_BLOCK_RE = /^(?:https?:\/\/|[-*+•]\s|\d+[.)]\s|#+\s|>\s|[─━═\-=_]{3,})/i;
    var MAX_WRAP_LINES = 16;

    function isTouchOnly() {
        return !!(global.matchMedia && global.matchMedia('(hover: none)').matches);
    }

    function shouldOpen(event) {
        if (isTouchOnly()) return true;
        if (!event) return false;
        return event.button === undefined || event.button === 0;
    }

    function activate(event, uri) {
        if (!shouldOpen(event)) return;
        var ct = global.CloudeTerminal;
        if (ct && typeof ct.openTerminalLink === 'function') ct.openTerminalLink(event, uri);
    }

    function readRow(buf, idx) {
        if (idx < 0 || idx >= buf.length) return null;
        var line = buf.getLine(idx);
        if (!line) return null;
        var text = '';
        var cols = [];
        for (var x = 0; x < line.length; x++) {
            var cell = line.getCell(x);
            if (!cell || cell.getWidth() === 0) continue;
            var ch = cell.getChars() || ' ';
            text += ch;
            for (var i = 0; i < ch.length; i++) cols.push(x);
        }
        var trimmed = text.replace(TRAILING_BORDER_RE, '');
        return {
            text: text,
            cols: cols,
            isWrapped: !!line.isWrapped,
            contentEnd: trimmed.length
        };
    }

    function continuationOf(row) {
        if (!row || row.contentEnd === 0) return null;
        var body = row.text.slice(0, row.contentEnd);
        var start = 0;
        if (!row.isWrapped) {
            var m = LEADING_MARGIN_RE.exec(body);
            start = m ? m[0].length : 0;
        }
        var rest = body.slice(start);
        if (!rest) return null;
        if (!row.isWrapped && NEW_BLOCK_RE.test(rest)) return null;
        var tokMatch = URL_CONT_RE.exec(rest);
        if (!tokMatch || !tokMatch[0]) return null;
        var tok = tokMatch[0];
        var after = rest.slice(tok.length).trim();
        return { start: start, token: tok, hasMoreWords: after.length > 0 };
    }

    function shouldContinue(prevRaw, prevRow, nextRow, termCols) {
        if (!nextRow) return null;
        var cont = continuationOf(nextRow);
        if (!cont) return null;
        if (nextRow.isWrapped) return cont;
        var tok = cont.token;
        var prevLen = prevRow.contentEnd;
        var wrapFloor = Math.min(Math.max((termCols || 80) - 18, 44), 66);
        var nearWrap = prevLen >= wrapFloor;
        var hasPunct = URL_PUNCT_RE.test(tok) || /\.[a-z0-9]{2,6}(?:[\/?#]|$)/i.test(tok);
        if (HARD_JOINER_RE.test(prevRaw)) return cont;
        if (prevRaw.charAt(prevRaw.length - 1) === '/') {
            if (hasPunct || !cont.hasMoreWords || nearWrap) return cont;
            return null;
        }
        if (nearWrap && (hasPunct || (!cont.hasMoreWords && /^[a-z0-9]/i.test(tok)))) return cont;
        return null;
    }

    function stitchUrl(getRow, startIdx, matchStart, rawFirst, termCols) {
        var firstRow = getRow(startIdx);
        var segments = [{ rowIdx: startIdx, start: matchStart, raw: rawFirst }];
        var curIdx = startIdx;
        var curRow = firstRow;
        var curEnd = matchStart + rawFirst.length;
        var curRaw = rawFirst;

        while (curEnd === curRow.contentEnd && segments.length < MAX_WRAP_LINES) {
            var nextRow = getRow(curIdx + 1);
            var cont = shouldContinue(curRaw, curRow, nextRow, termCols);
            if (!cont) break;
            curIdx += 1;
            curRow = nextRow;
            curRaw = cont.token;
            curEnd = cont.start + cont.token.length;
            segments.push({ rowIdx: curIdx, start: cont.start, raw: cont.token });
        }

        var full = '';
        for (var i = 0; i < segments.length; i++) full += segments[i].raw;
        var trimMatch = TRIM_END_RE.exec(full);
        var trimLen = trimMatch ? trimMatch[0].length : 0;
        var cleaned = trimLen ? full.slice(0, full.length - trimLen) : full;
        if (!cleaned || !URL_REGEX.test(cleaned)) return null;

        var rem = trimLen;
        var lastSegIdx = segments.length - 1;
        var lastLen = segments[lastSegIdx].raw.length;
        while (rem > 0 && lastSegIdx >= 0) {
            if (rem < lastLen) {
                lastLen -= rem;
                rem = 0;
            } else {
                rem -= lastLen;
                lastSegIdx -= 1;
                lastLen = lastSegIdx >= 0 ? segments[lastSegIdx].raw.length : 0;
            }
        }
        if (lastSegIdx < 0 || lastLen <= 0) return null;

        var endSeg = segments[lastSegIdx];
        var endRow = getRow(endSeg.rowIdx);
        var startCol = (firstRow.cols[matchStart] !== undefined ? firstRow.cols[matchStart] : 0) + 1;
        var endChar = endSeg.start + lastLen - 1;
        var endCol = (endRow.cols[endChar] !== undefined ? endRow.cols[endChar] : endChar) + 1;
        return {
            text: cleaned,
            startRow: startIdx,
            endRow: endSeg.rowIdx,
            endCharIdx: endSeg.start + lastLen,
            range: {
                start: { x: startCol, y: startIdx + 1 },
                end: { x: endCol, y: endSeg.rowIdx + 1 }
            }
        };
    }

    function findLinksForRow(term, y) {
        var buf = term && term.buffer && term.buffer.active;
        if (!buf) return [];
        var targetIdx = y - 1;
        if (targetIdx < 0 || targetIdx >= buf.length) return [];

        var cache = {};
        function getRow(idx) {
            if (!(idx in cache)) cache[idx] = readRow(buf, idx);
            return cache[idx];
        }

        var startIdx = targetIdx;
        while (startIdx > 0 && (targetIdx - startIdx) < MAX_WRAP_LINES - 1) {
            var cur = getRow(startIdx);
            if (!cur || cur.contentEnd === 0) break;
            if (!cur.isWrapped) {
                var body = cur.text.slice(0, cur.contentEnd);
                var m = LEADING_MARGIN_RE.exec(body);
                var rest = body.slice(m ? m[0].length : 0);
                if (NEW_BLOCK_RE.test(rest)) break;
            }
            var prev = getRow(startIdx - 1);
            if (!prev || prev.contentEnd === 0) break;
            startIdx -= 1;
        }

        var termCols = term.cols || 80;
        var links = [];
        var rowIdx = startIdx;
        var minChar = 0;

        while (rowIdx <= targetIdx) {
            var row = getRow(rowIdx);
            if (!row || row.contentEnd === 0) {
                rowIdx += 1;
                minChar = 0;
                continue;
            }
            var sliceText = row.text.slice(0, row.contentEnd);
            URL_RAW_RE.lastIndex = minChar;
            var match = URL_RAW_RE.exec(sliceText);
            if (!match) {
                rowIdx += 1;
                minChar = 0;
                continue;
            }
            var stitched = stitchUrl(getRow, rowIdx, match.index, match[0], termCols);
            if (!stitched) {
                minChar = match.index + match[0].length;
                continue;
            }
            if (stitched.startRow <= targetIdx && targetIdx <= stitched.endRow) {
                links.push({
                    range: stitched.range,
                    text: stitched.text,
                    activate: activate
                });
            }
            if (stitched.endRow > rowIdx) {
                rowIdx = stitched.endRow;
                minChar = stitched.endCharIdx;
            } else {
                minChar = stitched.endCharIdx;
            }
        }
        return links;
    }

    function attachPaths(term, sessionIdOf) {
        if (typeof sessionIdOf !== 'function' || typeof term.registerLinkProvider !== 'function') return;
        term.registerLinkProvider({
            provideLinks: function (y, callback) {
                var web = global.CloudeWeb;
                var paths = web && web.terminalPaths;
                if (!paths || typeof paths.provideLinks !== 'function') { callback(undefined); return; }
                paths.provideLinks(term, String(sessionIdOf() || ''), y, callback);
            }
        });
    }

    function attach(term, sessionIdOf) {
        if (!term || typeof term.registerLinkProvider !== 'function') {
            console.warn('TerminalLinks: terminal link provider not available');
            return null;
        }
        try { attachPaths(term, sessionIdOf); } catch (err) { console.warn('TerminalLinks: path links failed', err); }
        try {
            return term.registerLinkProvider({
                provideLinks: function (y, callback) {
                    var found = findLinksForRow(term, y);
                    callback(found.length ? found : undefined);
                }
            });
        } catch (err) {
            console.warn('TerminalLinks: registerLinkProvider failed', err);
            return null;
        }
    }

    global.TerminalLinks = {
        attach: attach,
        activate: activate,
        shouldOpen: shouldOpen,
        findLinksForRow: findLinksForRow,
        URL_REGEX: URL_REGEX
    };
}(typeof window !== 'undefined' ? window : globalThis));
