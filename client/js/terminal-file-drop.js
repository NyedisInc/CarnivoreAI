/* one trailing space */
(function () {
    'use strict';

    var CAPABILITY = 'droppedPaths';

    function bridgeReady() {
        var bridge = window.carnivoreDesktop;
        return !!(bridge && typeof bridge.droppedPaths === 'function'
            && Array.isArray(bridge.capabilities) && bridge.capabilities.indexOf(CAPABILITY) !== -1);
    }

    function carriesFiles(dt) {
        if (!dt || !dt.types) return false;
        return Array.prototype.indexOf.call(dt.types, 'Files') !== -1;
    }

    function buildDropText(paths, quote) {
        var usable = [];
        for (var i = 0; i < paths.length; i++) {
            var p = paths[i];
            // eslint-disable-next-line no-control-regex
            if (typeof p !== 'string' || p.charAt(0) !== '/' || /[\u0000-\u001f\u007f]/.test(p)) continue;
            usable.push(quote(p));
        }
        return usable.length ? usable.join(' ') + ' ' : '';
    }

    function attach(term) {
        if (!bridgeReady() || !term || typeof term._containerEl !== 'function') return false;
        var container = term._containerEl();
        if (!container) return false;
        container.addEventListener('dragover', function (e) {
            if (!carriesFiles(e.dataTransfer)) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        }, true);
        container.addEventListener('drop', function (e) {
            if (!carriesFiles(e.dataTransfer)) return;
            var ticket = window.TerminalInputOwnership ? window.TerminalInputOwnership.claim('paste') : null;
            e.preventDefault();
            e.stopPropagation();
            var quote = window.ClipboardTools && window.ClipboardTools.quotePathForPrompt;
            if (typeof quote !== 'function') return;
            var paths;
            try {
                paths = window.carnivoreDesktop.droppedPaths(e.dataTransfer.files);
            } catch (err) {
                console.warn('[TerminalFileDrop] could not read the dropped paths:', err && err.message);
                return;
            }
            var text = buildDropText(Array.isArray(paths) ? paths : [], quote);
            if (text) term.insertText(text, ticket);
        }, true);
        return true;
    }

    window.TerminalFileDrop = { attach: attach, buildDropText: buildDropText };
})();
