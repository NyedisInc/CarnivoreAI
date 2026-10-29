
console.log('[TerminalSessionBind Module] Loading...');

(function (global) {
    'use strict';

    var EVENT = 'cloude:primary-session-bound';

    function announce(controller, sessionId) {
        if (!controller || controller !== global.TerminalController) return false;
        var id = (sessionId || '').trim();
        if (!id) return false;
        var tmuxName = typeof controller._currentTmuxName === 'function'
            ? String(controller._currentTmuxName() || '').trim()
            : '';
        var inner = typeof controller._unwrapSession === 'function'
            ? controller._unwrapSession(controller._currentSession)
            : null;
        var raw = inner ? inner.tmux_created_epoch : null;
        var tmuxEpoch = (typeof raw === 'number' && Number.isFinite(raw)) ? raw : null;
        try {
            global.dispatchEvent(new CustomEvent(EVENT, {
                detail: { sessionId: id, tmuxName: tmuxName, tmuxEpoch: tmuxEpoch },
            }));
        } catch (err) {
            console.warn('TerminalSessionBind: announcement failed', err);
            return false;
        }
        return true;
    }

    global.TerminalSessionBind = { announce: announce, EVENT: EVENT };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalSessionBind Module] Exported as window.TerminalSessionBind');
