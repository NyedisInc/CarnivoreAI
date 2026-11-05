(function (global) {
    'use strict';

    var URL_REGEX = /https?:[/]{2}[^\s"'!*(){}|\\\^<>`─-╿]*[^\s"':,.!?{}|\\\^~\[\]`()<>─-╿]/;

    /* reads the ambient navigator */
    function isMac() {
        var nav = global.navigator;
        if (!nav) return false;
        var p = (nav.userAgentData && nav.userAgentData.platform) || nav.platform || '';
        return /mac|iphone|ipad|ipod/i.test(p);
    }

    function isTouchOnly() {
        return !!(global.matchMedia && global.matchMedia('(hover: none)').matches);
    }

    function shouldOpen(event) {
        if (isTouchOnly()) return true;
        if (!event) return false;
        return isMac() ? !!event.metaKey : !!event.ctrlKey;
    }

    function activate(event, uri) {
        if (!shouldOpen(event)) return;
        var ct = global.CloudeTerminal;
        if (ct && typeof ct.openTerminalLink === 'function') ct.openTerminalLink(event, uri);
    }

    function attachPaths(term, sessionIdOf) {
        if (typeof sessionIdOf !== 'function' || typeof term.registerLinkProvider !== 'function') return;
        term.registerLinkProvider({
            provideLinks: function (y, callback) {
                var web = global.CloudeWeb;
                var paths = web && web.terminalPaths;
                if (!paths || typeof paths.provideLinks !== 'function') { callback(undefined); return; }
                paths.provideLinks(term, String(sessionIdOf() || ''), y, callback);
            }
        });
    }

    function attach(term, sessionIdOf) {
        if (term) {
            try { attachPaths(term, sessionIdOf); } catch (err) { console.warn('TerminalLinks: path links failed', err); }
        }
        var ns = global.WebLinksAddon;
        if (!term || !ns || typeof ns.WebLinksAddon !== 'function') {
            console.warn('TerminalLinks: web-links add-on not available');
            return null;
        }
        try {
            var addon = new ns.WebLinksAddon(activate, { urlRegex: URL_REGEX });
            term.loadAddon(addon);
            return addon;
        } catch (err) {
            console.warn('TerminalLinks: loadAddon failed', err);
            return null;
        }
    }

    global.TerminalLinks = {
        attach: attach,
        activate: activate,
        shouldOpen: shouldOpen,
        URL_REGEX: URL_REGEX
    };
}(typeof window !== 'undefined' ? window : globalThis));
