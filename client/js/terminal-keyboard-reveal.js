
console.log('[TerminalKeyboardReveal Module] Loading...');

(function (global) {
    'use strict';

    var SETTLE_MS = 150;

    var KEYBOARD_MIN_PX = 120;

    function keyboardOpen(win) {
        var vv = win.visualViewport;
        if (!vv) return false;
        if (typeof win.matchMedia === 'function'
            && !win.matchMedia('(pointer: coarse)').matches) return false;
        return (win.innerHeight - vv.height) >= KEYBOARD_MIN_PX;
    }

    function reveal(term, scroll) {
        if (scroll && typeof scroll.pinToBottom === 'function') {
            scroll.pinToBottom(term);
        } else if (typeof term.scrollToBottom === 'function') {
            term.scrollToBottom();
        }
        if (global.TerminalProvider) global.TerminalProvider.wrap(term).syncInputTextarea();
        var ta = term.textarea;
        if (ta && typeof ta.scrollIntoView === 'function') {
            ta.scrollIntoView({ block: 'center', inline: 'nearest' });
        }
    }

    function install(term, scroll) {
        var win = global;
        var ta = term && term.textarea;
        if (!ta || typeof ta.addEventListener !== 'function') return function () {};
        var timer = null;

        function settle() {
            timer = null;
            if (win.document.activeElement !== ta) return;
            if (!keyboardOpen(win)) return;
            reveal(term, scroll);
        }
        function schedule() {
            if (win.document.activeElement !== ta) return;
            if (timer !== null) clearTimeout(timer);
            timer = setTimeout(settle, SETTLE_MS);
        }

        ta.addEventListener('focus', schedule);
        var vv = win.visualViewport;
        if (vv) vv.addEventListener('resize', schedule);
        return function uninstall() {
            if (timer !== null) { clearTimeout(timer); timer = null; }
            ta.removeEventListener('focus', schedule);
            if (vv) vv.removeEventListener('resize', schedule);
        };
    }

    global.TerminalKeyboardReveal = {
        install: install,
        keyboardOpen: keyboardOpen,
        SETTLE_MS: SETTLE_MS,
        KEYBOARD_MIN_PX: KEYBOARD_MIN_PX
    };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalKeyboardReveal Module] Exported as window.TerminalKeyboardReveal');
