/* nothing at all something else */
(function () {
    'use strict';

    var CTRL_O = '\x0f';

    var CSI_UP = '\x1b[A';
    var CSI_DOWN = '\x1b[B';

    var RULE_CHAR = '─';

    var RULE_RUN = 20;

    var CARET = '❯';

    var TRANSCRIPT_MARK = 'ctrl+o to toggle';

    var TYPING_QUIET_MS = 1200;

    var OPEN_SETTLE_MS = 1500;

    var OPEN_POLL_MS = 40;

    var MAX_ROWS_PER_GESTURE = 240;

    function createAltScreenScroll(deps) {
        var wiring = deps || {};

        function dep(name, globalName) {
            return wiring[name] !== undefined ? wiring[name] : window[globalName];
        }

        var lastInputAt = 0;

        var openSentAt = 0;

        var getTerm = function () { return null; };

        var sendKeys = function () { };

        var settleTimer = null;

        function visibleRows(term) {
            var out = [];
            try {
                var buf = term && term.buffer && term.buffer.active;
                if (!buf) return out;
                var top = buf.viewportY;
                var n = term.rows || 0;
                for (var i = 0; i < n; i++) {
                    var line = buf.getLine(top + i);
                    out.push(line ? line.translateToString(true) : '');
                }
            } catch (err) {
                console.warn('AltScreenScroll: buffer read failed', err);
                return [];
            }
            return out;
        }

        function isRule(row) {
            if (!row) return false;
            var run = 0;
            for (var i = 0; i < row.length; i++) {
                if (row.charAt(i) === RULE_CHAR) {
                    run++;
                    if (run >= RULE_RUN) return true;
                } else {
                    run = 0;
                }
            }
            return false;
        }

        function isPromptLine(row) {
            if (!row) return false;
            return row.replace(/^\s+/, '').indexOf(CARET) === 0;
        }

        function detectState(term) {
            var type = null;
            var baseY = null;
            try {
                var buf = term && term.buffer && term.buffer.active;
                if (buf) {
                    type = buf.type;
                    baseY = buf.baseY;
                }
            } catch (err) {
                console.warn('AltScreenScroll: buffer read failed', err);
                return 'unknown';
            }
            // could not
            if (typeof type !== 'string' || typeof baseY !== 'number') return 'unknown';
            if (baseY > 0) return 'main';

            var rows = visibleRows(term);
            if (!rows.length) return 'unknown';

            for (var i = 0; i < rows.length; i++) {
                if (rows[i].toLowerCase().indexOf(TRANSCRIPT_MARK) !== -1) {
                    return 'transcript';
                }
            }
            for (var j = 0; j + 2 < rows.length; j++) {
                if (isRule(rows[j]) && isPromptLine(rows[j + 1]) && isRule(rows[j + 2])) {
                    return 'live';
                }
            }
            return 'unknown';
        }

        function noteUserInput() {
            lastInputAt = Date.now();
        }

        function isTyping() {
            if (!lastInputAt) return false;
            return (Date.now() - lastInputAt) < TYPING_QUIET_MS;
        }

        function openPending() {
            if (!openSentAt) return false;
            return (Date.now() - openSentAt) < OPEN_SETTLE_MS;
        }

        function arrowRun(rows) {
            var keys = dep('keys', 'AltScreenKeys');
            if (!keys || typeof keys.keysForRows !== 'function') {
                console.warn('AltScreenScroll: AltScreenKeys missing, sending nothing');
                return '';
            }
            return keys.keysForRows(rows, MAX_ROWS_PER_GESTURE);
        }

        /* nothing at all */
        function sendAfterOpen(rows, deadline) {
            settleTimer = null;
            var term = getTerm();
            var state = detectState(term);
            if (state === 'transcript') {
                openSentAt = 0;
                if (!isTyping()) sendKeys(arrowRun(rows));
                return;
            }
            if (Date.now() >= deadline || state === 'main') {
                openSentAt = 0;
                return;
            }
            settleTimer = setTimeout(function () {
                sendAfterOpen(rows, deadline);
            }, OPEN_POLL_MS);
        }

        function scrollByRows(rows) {
            var term = getTerm();
            if (!term) return false;
            var state = detectState(term);
            if (state === 'main') return false;
            if (!rows) return true;
            if (state === 'unknown') return true;
            if (openPending() && state !== 'transcript') return true;
            if (isTyping()) return true;

            if (state === 'live') {
                openSentAt = Date.now();
                sendKeys(CTRL_O);
                if (settleTimer) clearTimeout(settleTimer);
                settleTimer = setTimeout(function () {
                    sendAfterOpen(rows, Date.now() + OPEN_SETTLE_MS);
                }, OPEN_POLL_MS);
                return true;
            }

            openSentAt = 0;
            sendKeys(arrowRun(rows));
            return true;
        }

        function exitTranscript() {
            var term = getTerm();
            if (detectState(term) !== 'transcript') return false;
            if (settleTimer) {
                clearTimeout(settleTimer);
                settleTimer = null;
            }
            openSentAt = 0;
            sendKeys(CTRL_O);
            return true;
        }

        function init(termGetter, writer) {
            if (typeof termGetter === 'function') getTerm = termGetter;
            if (typeof writer === 'function') sendKeys = writer;
        }

        function _reset() {
            lastInputAt = 0;
            openSentAt = 0;
            if (settleTimer) clearTimeout(settleTimer);
            settleTimer = null;
            getTerm = function () { return null; };
            sendKeys = function () { };
        }

        return {
            init: init,
            detectState: detectState,
            isRule: isRule,
            scrollByRows: scrollByRows,
            exitTranscript: exitTranscript,
            noteUserInput: noteUserInput,
            isTyping: isTyping,
            _reset: _reset,
            _keys: { CTRL_O: CTRL_O, UP: CSI_UP, DOWN: CSI_DOWN },
            _timing: {
                TYPING_QUIET_MS: TYPING_QUIET_MS,
                OPEN_SETTLE_MS: OPEN_SETTLE_MS,
                OPEN_POLL_MS: OPEN_POLL_MS,
                MAX_ROWS_PER_GESTURE: MAX_ROWS_PER_GESTURE
            }
        };
    }

    var defaultInstance = createAltScreenScroll();

    window.AltScreenScroll = Object.assign(
        { create: createAltScreenScroll }, defaultInstance);
})();
