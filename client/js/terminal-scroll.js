(function () {
    'use strict';

    var GESTURE_LATCH_MS = 1200;

    function createTerminalScroll(deps) {
        var wiring = deps || {};

        function dep(name, globalName) {
            return wiring[name] !== undefined ? wiring[name] : window[globalName];
        }

        var lastGestureAt = 0;

        var touchActive = false;

        var wired = false;

        var getTerm = function () { return null; };

        var lastTouchY = 0;

        var tapOrigin = null;

        var TAP_SLOP_PX = 10;

        var pendingRows = 0;

        function isPinnedToBottom(term) {
            if (!term) return true;
            try {
                var buf = term.buffer && term.buffer.active;
                if (!buf) return true;
                return buf.viewportY >= buf.baseY;
            } catch (err) {
                console.warn('TerminalScroll: buffer read failed', err);
                return true;
            }
        }

        function noteUserScroll() {
            lastGestureAt = Date.now();
        }

        function isGestureActive() {
            if (touchActive) return true;
            return (Date.now() - lastGestureAt) < GESTURE_LATCH_MS;
        }

        function shouldFollowOutput(term) {
            if (isGestureActive()) return false;
            return isPinnedToBottom(term);
        }

        function pinToBottom(term) {
            lastGestureAt = 0;
            touchActive = false;
            if (!term) return;
            try {
                term.scrollToBottom();
            } catch (err) {
                console.warn('TerminalScroll: scrollToBottom failed', err);
            }
        }

        function canConsumeScroll(term, rows) {
            if (!term || !rows) return false;
            try {
                var buf = term.buffer && term.buffer.active;
                if (!buf) return false;
                return rows < 0 ? buf.viewportY > 0 : buf.viewportY < buf.baseY;
            } catch (err) {
                console.warn('TerminalScroll: buffer read failed', err);
                return false;
            }
        }

        function scrollByRows(term, rows) {
            if (!term || !rows) return false;
            var alt = dep('altScreen', 'AltScreenScroll');
            if (alt && alt.scrollByRows(rows)) return true;
            if (!canConsumeScroll(term, rows)) return false;
            try {
                term.scrollLines(rows);
            } catch (err) {
                console.warn('TerminalScroll: scrollLines failed', err);
                return false;
            }
            return true;
        }

        function consumeDragScroll(dy) {
            var term = getTerm();
            if (!term || !dy) return false;
            pendingRows += dep('step', 'TerminalScrollStep').rowsForPixels(dy, term);
            var eps = 1e-9;
            var rows = pendingRows > 0
                ? Math.floor(pendingRows + eps)
                : Math.ceil(pendingRows - eps);
            if (!rows) return false;
            pendingRows -= rows;
            if (!scrollByRows(term, rows)) {
                pendingRows = 0;
                return false;
            }
            return true;
        }

        function handleWheel(ev) {
            if (!ev || ev.deltaY === 0) return;
            noteUserScroll();
            var term = getTerm();
            if (!term) return;
            scrollByRows(term, dep('step', 'TerminalScrollStep').rowsForWheel(ev, term));
            if (ev.cancelable) ev.preventDefault();
            if (typeof ev.stopPropagation === 'function') ev.stopPropagation();
        }

        function isSelecting() {
            try {
                var ts = dep('touchSelect', 'TouchSelect');
                return !!(ts && typeof ts.isSelecting === 'function' && ts.isSelecting());
            } catch (err) {
                console.warn('TerminalScroll: select-state read failed', err);
                return false;
            }
        }

        function handleDragScroll(ev) {
            noteUserScroll();
            if (!ev || !ev.touches || ev.touches.length !== 1) return;
            if (tapOrigin) {
                var tdx = ev.touches[0].pageX - tapOrigin.x;
                var tdy = ev.touches[0].pageY - tapOrigin.y;
                if (tdx * tdx + tdy * tdy <= TAP_SLOP_PX * TAP_SLOP_PX) {
                    if (typeof ev.stopPropagation === 'function') ev.stopPropagation();
                    return;
                }
                tapOrigin = null;
            }
            var y = ev.touches[0].pageY;
            var dy = lastTouchY - y;
            lastTouchY = y;
            if (isSelecting()) return;
            consumeDragScroll(dy);
            if (!ev.cancelable) return;
            ev.preventDefault();
            if (typeof ev.stopPropagation === 'function') ev.stopPropagation();
        }

        function blockOverscrollEscape(ev) {
            if (ev.defaultPrevented) return;
            if (!ev.cancelable) return;
            if (ev.touches && ev.touches.length !== 1) return;
            ev.preventDefault();
        }

        function init(container, termGetter) {
            if (typeof termGetter === 'function') getTerm = termGetter;
            if (wired || !container) return;
            wired = true;

            container.addEventListener('touchstart', function (ev) {
                touchActive = true;
                pendingRows = 0;
                tapOrigin = null;
                if (ev && ev.touches && ev.touches.length) {
                    lastTouchY = ev.touches[0].pageY;
                    if (ev.touches.length === 1) {
                        tapOrigin = { x: ev.touches[0].pageX, y: ev.touches[0].pageY };
                    }
                }
                noteUserScroll();
            }, { capture: true, passive: true });

            container.addEventListener('touchmove', handleDragScroll, {
                capture: true, passive: false
            });

            var endGesture = function () {
                touchActive = false;
                tapOrigin = null;
                noteUserScroll();
            };
            container.addEventListener('touchend', endGesture, { capture: true, passive: true });
            container.addEventListener('touchcancel', endGesture, { capture: true, passive: true });

            container.addEventListener('wheel', handleWheel, {
                capture: true, passive: false
            });

            container.addEventListener('touchmove', blockOverscrollEscape, { passive: false });
        }

        function _reset() {
            lastGestureAt = 0;
            touchActive = false;
            wired = false;
            lastTouchY = 0;
            tapOrigin = null;
            pendingRows = 0;
            getTerm = function () { return null; };
        }

        return {
            init: init,
            blockOverscrollEscape: blockOverscrollEscape,
            canConsumeScroll: canConsumeScroll,
            consumeDragScroll: consumeDragScroll,
            scrollByRows: scrollByRows,
            handleWheel: handleWheel,
            isPinnedToBottom: isPinnedToBottom,
            shouldFollowOutput: shouldFollowOutput,
            noteUserScroll: noteUserScroll,
            isGestureActive: isGestureActive,
            pinToBottom: pinToBottom,
            _reset: _reset
        };
    }

    var defaultInstance = createTerminalScroll();

    window.TerminalScroll = {
        create: createTerminalScroll,
        init: defaultInstance.init,
        blockOverscrollEscape: defaultInstance.blockOverscrollEscape,
        canConsumeScroll: defaultInstance.canConsumeScroll,
        consumeDragScroll: defaultInstance.consumeDragScroll,
        scrollByRows: defaultInstance.scrollByRows,
        handleWheel: defaultInstance.handleWheel,
        isPinnedToBottom: defaultInstance.isPinnedToBottom,
        shouldFollowOutput: defaultInstance.shouldFollowOutput,
        noteUserScroll: defaultInstance.noteUserScroll,
        isGestureActive: defaultInstance.isGestureActive,
        pinToBottom: defaultInstance.pinToBottom,
        _reset: defaultInstance._reset
    };
})();
