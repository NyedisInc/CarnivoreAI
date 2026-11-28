
(function (global) {
    function decideFocus(state) {
        var out = {};
        var onScreen = [];
        state.clients.forEach(function (c) {
            out[c.key] = false;
            if (!c.withdrawn) onScreen.push(c.key);
        });
        if (!state.windowFocused || !state.visible) return out;
        if (state.lastFocusedKey !== null && onScreen.indexOf(state.lastFocusedKey) !== -1) {
            out[state.lastFocusedKey] = true;
        } else if (onScreen.length === 1) {
            out[onScreen[0]] = true;
        }
        return out;
    }

    var registry = [];
    var lastFocused = null;
    var listening = false;

    function isOpen(ctl) {
        return !!ctl && !ctl._disposed && !!ctl.ws && ctl.ws.readyState === 1;
    }

    function isWithdrawn(ctl) {
        var vote = global.TerminalSizeVote;
        return !!(vote && vote.isWithdrawn(ctl, global.document));
    }

    function recompute() {
        registry = registry.filter(isOpen);
        var doc = global.document;
        var decided = decideFocus({
            windowFocused: !!doc && typeof doc.hasFocus === 'function' && doc.hasFocus(),
            visible: !!doc && doc.visibilityState !== 'hidden',
            clients: registry.map(function (c, i) { return { key: String(i), withdrawn: isWithdrawn(c) }; }),
            lastFocusedKey: lastFocused === null ? null : String(registry.indexOf(lastFocused)),
        });
        registry.forEach(function (ctl, i) {
            var focused = decided[String(i)] === true;
            if (ctl._viewerFocusSent === focused) return;
            ctl._viewerFocusSent = focused;
            ctl.ws.send(JSON.stringify({ type: 'viewer_focus', focused: focused }));
        });
    }

    function listen() {
        if (listening || !global.addEventListener) return;
        listening = true;
        global.addEventListener('focus', recompute);
        global.addEventListener('blur', recompute);
        global.document.addEventListener('visibilitychange', recompute);
    }

    function attach(ctl) {
        if (!ctl) return;
        listen();
        ctl._viewerFocusSent = undefined;
        if (registry.indexOf(ctl) === -1) registry.push(ctl);
        var el = ctl.term && ctl.term.element;
        if (el && !ctl._viewerFocusBound) {
            ctl._viewerFocusBound = true;
            el.addEventListener('focusin', function () { lastFocused = ctl; recompute(); });
            if (el.contains(global.document.activeElement)) lastFocused = ctl;
        }
        recompute();
    }

    function detach(ctl) {
        registry = registry.filter(function (c) { return c !== ctl; });
        if (lastFocused === ctl) lastFocused = null;
        recompute();
    }

    global.TerminalViewerFocus = { decideFocus: decideFocus, attach: attach, detach: detach, recompute: recompute };
})(typeof window !== 'undefined' ? window : globalThis);
