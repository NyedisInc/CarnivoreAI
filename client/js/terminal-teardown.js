
console.log('[TerminalTeardown Module] Loading...');

(function (global) {
    'use strict';

    function step(what, fn) {
        try {
            fn();
        } catch (err) {
            console.warn('TerminalTeardown: ' + what + ' failed', err);
        }
    }

    function dispose(ctl) {
        if (!ctl || ctl._disposed) return false;
        ctl._disposed = true;
        if (global.TerminalPaintGate) global.TerminalPaintGate.unregister(ctl);

        step('reconnect stop', function () { ctl.stopReconnecting(); });
        step('socket close', function () { ctl.pauseForHome(); });
        ctl.sessionActive = false;
        ctl._currentSession = null;

        ctl.queue = [];
        ctl._queuedBytes = 0;
        ctl.flushing = false;

        var layout = typeof ctl._m === 'function' ? ctl._m('TerminalLayout') : null;
        if (layout && typeof layout.uninstall === 'function') {
            step('layout uninstall', function () { layout.uninstall(); });
        }

        if (typeof ctl._uninstallKeyboardReveal === 'function') {
            step('keyboard reveal uninstall', function () { ctl._uninstallKeyboardReveal(); });
            ctl._uninstallKeyboardReveal = null;
        }

        if (typeof ctl._unsubscribeXtermTheme === 'function') {
            step('theme unsubscribe', function () { ctl._unsubscribeXtermTheme(); });
            ctl._unsubscribeXtermTheme = null;
        }

        if (global.TerminalBackground
            && typeof global.TerminalBackground.unregisterSurface === 'function') {
            step('background surface unregister', function () {
                global.TerminalBackground.unregisterSurface(ctl);
            });
        }

        if (ctl._xtermOpacity && typeof ctl._xtermOpacity.dispose === 'function') {
            step('background opacity dispose', function () { ctl._xtermOpacity.dispose(); });
        }
        ctl._xtermOpacity = null;

        if (global.TerminalProvider) global.TerminalProvider.wrap(ctl.term).quiesceViewport();

        if (ctl._webglAddon) {
            step('webgl dispose', function () { ctl._webglAddon.dispose(); });
            ctl._webglAddon = null;
        }

        if (ctl.term) {
            var term = ctl.term;
            step('xterm dispose', function () { term.dispose(); });
            ctl.term = null;
        }
        ctl.fitAddon = null;
        return true;
    }

    global.TerminalTeardown = { dispose: dispose };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalTeardown Module] Exported as window.TerminalTeardown');
