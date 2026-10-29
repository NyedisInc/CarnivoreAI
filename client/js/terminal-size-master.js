
console.log('[TerminalSizeMaster Module] Loading...');

(function (global) {
    var EVENT = 'cloude:size-master';

    var STORAGE_KEY = 'carnivore.terminal.client_id';

    var ID_PATTERN = /^[A-Za-z0-9_-]{8,64}$/;

    var memo = null;

    function mint() {
        var c = global.crypto;
        try {
            if (c && typeof c.randomUUID === 'function') return c.randomUUID();
            if (c && typeof c.getRandomValues === 'function') {
                var bytes = c.getRandomValues(new Uint8Array(16));
                return Array.prototype.map.call(bytes, function (b) {
                    return (b < 16 ? '0' : '') + b.toString(16);
                }).join('');
            }
        } catch (err) {
            console.warn('[TerminalSizeMaster] crypto unavailable, using Math.random', err);
        }
        return 'tab-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    }

    function clientId() {
        if (memo) return memo;
        var store = null;
        try { store = global.sessionStorage || null; } catch (err) { store = null; }
        var stored = null;
        try { stored = store ? store.getItem(STORAGE_KEY) : null; } catch (err) { stored = null; }
        memo = (stored && ID_PATTERN.test(stored)) ? stored : mint();
        try { if (store && stored !== memo) store.setItem(STORAGE_KEY, memo); } catch (err) {
        }
        return memo;
    }

    function isFollower(ctl) {
        var master = ctl && ctl._sizeMaster;
        return !!master && master !== clientId();
    }

    function note(ctl, message) {
        if (!ctl || !message) return false;
        var before = ctl._sizeMaster;
        var next = typeof message.master === 'string' ? message.master : null;
        ctl._sizeMaster = next;
        publish(message.session_id, next);
        return before !== undefined && before !== next;
    }

    function publish(sessionId, master) {
        if (!sessionId || typeof global.dispatchEvent !== 'function'
            || typeof global.CustomEvent !== 'function') return;
        try {
            global.dispatchEvent(new global.CustomEvent(EVENT, {
                detail: { sessionId: sessionId, master: master }
            }));
        } catch (err) {
            console.warn('[TerminalSizeMaster] crown not told', err);
        }
    }

    function scaleFor(fit, shown, following) {
        if (!following || !fit || !shown || !(shown.cols > 0) || !(shown.rows > 0)) return 1;
        return Math.min(1, fit.cols / shown.cols, fit.rows / shown.rows);
    }

    function applyScale(ctl, scale) {
        var el = ctl && ctl.term && ctl.term.element;
        if (!el || !el.style) return;
        if (scale < 1) {
            el.style.transformOrigin = '0 0';
            el.style.transform = 'scale(' + scale.toFixed(4) + ')';
            el.setAttribute('data-size-follower-scale', scale.toFixed(4));
            installPointerMap(ctl);
        } else if (el.hasAttribute('data-size-follower-scale')) {
            el.style.transform = '';
            el.style.transformOrigin = '';
            el.removeAttribute('data-size-follower-scale');
        }
    }

    function mapPointer(x, y, rect, scale) {
        if (!(scale > 0) || scale >= 1) return { x: x, y: y };
        return { x: rect.left + (x - rect.left) / scale, y: rect.top + (y - rect.top) / scale };
    }

    function currentScale(el) {
        var raw = el && el.getAttribute ? parseFloat(el.getAttribute('data-size-follower-scale')) : NaN;
        return raw > 0 && raw < 1 ? raw : 1;
    }

    function wrapMouseMethod(service, name, outer) {
        var orig = service[name];
        if (typeof orig !== 'function' || orig.__followerScaled) return;
        var wrapped = function (event, element) {
            var scale = currentScale(outer);
            if (scale >= 1 || !element || typeof element.getBoundingClientRect !== 'function') {
                return orig.apply(this, arguments);
            }
            var at = mapPointer(event.clientX, event.clientY, element.getBoundingClientRect(), scale);
            var args = Array.prototype.slice.call(arguments);
            args[0] = { clientX: at.x, clientY: at.y };
            return orig.apply(this, args);
        };
        wrapped.__followerScaled = true;
        service[name] = wrapped;
    }

    function installPointerMap(ctl) {
        var term = ctl && ctl.term;
        var service = global.TerminalProvider && global.TerminalProvider.wrap(term).mouseService();
        if (!service || !term.element) return;
        wrapMouseMethod(service, 'getCoords', term.element);
        wrapMouseMethod(service, 'getMouseReportCoords', term.element);
    }

    global.TerminalSizeMaster = {
        EVENT: EVENT,
        clientId: clientId,
        isFollower: isFollower,
        note: note,
        scaleFor: scaleFor,
        applyScale: applyScale,
        mapPointer: mapPointer
    };
}(typeof window !== 'undefined' ? window : globalThis));
