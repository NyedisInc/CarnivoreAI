
console.log('[TerminalViewerResync Module] Loading...');

(function (global) {
    'use strict';

    var CAN = 0x18;

    function onResync(controller, message) {
        if (typeof controller._navCurrent === 'function' && !controller._navCurrent('terminal resync')) {
            return false;
        }
        controller.enqueue(new Uint8Array([CAN]));
        controller._resyncCount = (controller._resyncCount || 0) + 1;
        console.info('[terminal] resync #' + controller._resyncCount + ': server dropped '
            + ((message && message.dropped_chunks) | 0) + ' chunks / '
            + ((message && message.dropped_bytes) | 0) + ' bytes and repainted the screen');
        return true;
    }

    global.TerminalViewerResync = { CAN: CAN, onResync: onResync };
}(typeof window !== 'undefined' ? window : globalThis));

console.log('[TerminalViewerResync Module] Exported as window.TerminalViewerResync');
