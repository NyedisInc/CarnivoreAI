/* there is nothing */

console.log('[TerminalStartupNotice Module] Loading...');

(function (global) {

    function createTerminalStartupNotice(deps) {
        var wiring = deps || {};

        function host() {
            return wiring.web !== undefined ? wiring.web : global.CloudeWeb;
        }

        var currentSessionId = null;

        function show(sessionId, startupCommand) {
            currentSessionId = sessionId || null;
            var web = host();
            if (!web || typeof web.showTerminalStartupNotice !== 'function') return;
            web.showTerminalStartupNotice(startupCommand === 'failed');
        }

        function clear() {
            currentSessionId = null;
            var web = host();
            if (!web || typeof web.clearTerminalStartupNotice !== 'function') return;
            web.clearTerminalStartupNotice();
        }

        function sessionId() {
            return currentSessionId;
        }

        return {
            show: show,
            clear: clear,
            sessionId: sessionId
        };
    }

    var defaultInstance = createTerminalStartupNotice();

    global.TerminalStartupNotice = Object.assign(
        { create: createTerminalStartupNotice }, defaultInstance);
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalStartupNotice Module] Exported as window.TerminalStartupNotice');
