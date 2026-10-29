(function () {
    'use strict';

    function areMouseEventsActive(term) {
        try {
            return globalThis.TerminalProvider.wrap(term).mouseEventsActive();
        } catch (err) {
            console.warn('TerminalSelectScrolled: mouse-service read failed', err);
            return false;
        }
    }

    function isScrolledUp(term) {
        var ts = window.TerminalScroll;
        var realScrollback = !!(ts && typeof ts.isPinnedToBottom === 'function'
            && !ts.isPinnedToBottom(term));
        if (realScrollback) return true;

        var as = window.AltScreenScroll;
        if (as && typeof as.detectState === 'function') {
            try {
                return as.detectState(term) === 'transcript';
            } catch (err) {
                console.warn('TerminalSelectScrolled: altscreen state read failed', err);
                return false;
            }
        }
        return false;
    }

    var dispatching = false;

    var forcedGesture = false;

    function dispatchForcedMouseDown(term, screenEl, real) {
        var opts = term.options;
        var prevForce = opts.macOptionClickForcesSelection;
        opts.macOptionClickForcesSelection = true;
        dispatching = true;
        try {
            screenEl.dispatchEvent(new MouseEvent('mousedown', {
                bubbles: true,
                cancelable: true,
                view: window,
                button: real.button,
                buttons: real.buttons || 1,
                detail: real.detail || 1,
                clientX: real.clientX,
                clientY: real.clientY,
                shiftKey: true,
                altKey: true,
            }));
        } finally {
            dispatching = false;
            opts.macOptionClickForcesSelection = prevForce;
        }
    }

    function handleMouseDown(term, ev) {
        if (dispatching) return;
        if (!term || !ev || ev.button !== 0) return;
        if (!areMouseEventsActive(term)) return;
        if (!isScrolledUp(term)) return;
        var screenEl = term.element && term.element.querySelector('.xterm-screen');
        if (!screenEl) return;
        ev.preventDefault();
        ev.stopPropagation();
        forcedGesture = true;
        dispatchForcedMouseDown(term, screenEl, ev);
    }

    /* nothing at all */
    function handleMouseUp(ev) {
        if (!forcedGesture) return;
        forcedGesture = false;
        if (!ev) return;
        ev.stopPropagation();
        document.dispatchEvent(new MouseEvent('mouseup', {
            bubbles: false,
            cancelable: true,
            view: window,
            button: ev.button,
            buttons: 0,
            detail: ev.detail || 1,
            clientX: ev.clientX,
            clientY: ev.clientY,
        }));
    }

    /* nothing at all */
    function handleMouseMove(term, ev) {
        if (forcedGesture) return;
        if (!term || !ev) return;
        if (!areMouseEventsActive(term)) return;
        var has = false;
        try {
            has = !!(typeof term.hasSelection === 'function' && term.hasSelection());
        } catch (err) {
            console.warn('TerminalSelectScrolled: selection read failed', err);
            return;
        }
        if (!has) return;
        if (!isScrolledUp(term)) return;
        ev.stopPropagation();
    }

    var wired = false;
    function init(container, termGetter) {
        if (wired || !container || typeof termGetter !== 'function') return;
        wired = true;
        container.addEventListener('mousedown', function (ev) {
            handleMouseDown(termGetter(), ev);
        }, { capture: true });
        container.addEventListener('mouseup', function (ev) {
            handleMouseUp(ev);
        }, { capture: true });
        container.addEventListener('mousemove', function (ev) {
            handleMouseMove(termGetter(), ev);
        }, { capture: true });
    }

    function _reset() {
        wired = false;
        dispatching = false;
        forcedGesture = false;
    }

    function _isDispatching() {
        return dispatching;
    }

    function _isForcedGesture() {
        return forcedGesture;
    }

    window.TerminalSelectScrolled = {
        init: init,
        handleMouseDown: handleMouseDown,
        handleMouseUp: handleMouseUp,
        handleMouseMove: handleMouseMove,
        areMouseEventsActive: areMouseEventsActive,
        isScrolledUp: isScrolledUp,
        _reset: _reset,
        _isDispatching: _isDispatching,
        _isForcedGesture: _isForcedGesture
    };
})();
