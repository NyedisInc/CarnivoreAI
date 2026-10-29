(function () {
    'use strict';

    function abandonIfConnecting(ws, WS) {
        if (!ws || !WS || ws.readyState !== WS.CONNECTING) return false;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        try {
            ws.close();
        } catch (err) {
            console.debug('[TerminalSocketAbandon] close failed', err);
        }
        return true;
    }

    window.TerminalSocketAbandon = {
        abandonIfConnecting: abandonIfConnecting,
    };
}());
