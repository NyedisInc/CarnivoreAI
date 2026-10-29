(function () {
    'use strict';

    var FIELD = 'animations';
    var STORAGE_KEY = 'carnivore.animations';
    var ATTR = 'data-motion';

    function loadLocal() {
        try {
            return localStorage.getItem(STORAGE_KEY) !== '0';
        } catch (_) {
            return true;
        }
    }

    function saveLocal(on) {
        try {
            localStorage.setItem(STORAGE_KEY, on ? '1' : '0');
        } catch (_) {  }
    }

    var TYPES_KEY = 'carnivore.animation-types-off';
    var TYPES_ATTR = 'data-anim-off';

    function paintTypes() {
        var raw = '';
        try {
            raw = localStorage.getItem(TYPES_KEY) || '';
        } catch (_) {  }
        var ids = raw.split(/\s+/).filter(function (id) { return /^[a-z0-9-]+$/.test(id); });
        var root = document.documentElement;
        if (ids.length) root.setAttribute(TYPES_ATTR, ids.join(' '));
        else root.removeAttribute(TYPES_ATTR);
    }

    function typeOff(id) {
        var list = document.documentElement.getAttribute(TYPES_ATTR) || '';
        return (' ' + list + ' ').indexOf(' ' + id + ' ') >= 0;
    }

    function watchTypes(cb) {
        if (typeof MutationObserver !== 'function') return function () {};
        var observer = new MutationObserver(function () { cb(); });
        observer.observe(document.documentElement, { attributes: true, attributeFilter: [TYPES_ATTR] });
        return function () { observer.disconnect(); };
    }

    var blinkTerms = new Set();
    var blinkStop = null;

    function calmNow() {
        return document.documentElement.getAttribute('data-calm') !== null;
    }

    function osReduced() {
        return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    function syncBlink() {
        var blink = !typeOff('cursor-blink') && !calmNow() && !osReduced();
        blinkTerms.forEach(function (ref) {
            var term = ref.deref();
            if (!term) { blinkTerms.delete(ref); return; }
            try {
                term.options.cursorBlink = blink;
            } catch (_) {  }
        });
    }

    function bindCursorBlink(term) {
        blinkTerms.add(new WeakRef(term));
        if (!blinkStop) {
            blinkStop = watchTypes(syncBlink);
            document.addEventListener('carnivore:calm', syncBlink);
            if (typeof matchMedia === 'function') {
                var mq = matchMedia('(prefers-reduced-motion: reduce)');
                if (mq && typeof mq.addEventListener === 'function') mq.addEventListener('change', syncBlink);
            }
        }
        syncBlink();
    }

    function paint(on) {
        var root = document.documentElement;
        if (on) root.removeAttribute(ATTR);
        else root.setAttribute(ATTR, 'off');
    }

    function apply() {
        paintTypes();
        var bridge = globalThis.PreferenceBridge;
        var value = bridge && typeof bridge.read === 'function'
            ? bridge.read(FIELD, function () { return loadLocal(); })
            : loadLocal();
        var on = value !== false;
        saveLocal(on);
        paint(on);
        return on;
    }

    function off() {
        return document.documentElement.getAttribute(ATTR) === 'off';
    }

    function reduced() {
        if (off()) return true;
        return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    var stop = null;

    function start() {
        apply();
        var bridge = globalThis.PreferenceBridge;
        if (!bridge || typeof bridge.follow !== 'function') return;
        if (stop) stop();
        stop = bridge.follow(FIELD, function (value) {
            var on = value !== false;
            saveLocal(on);
            paint(on);
        });
    }

    window.MotionSetting = { apply: apply, start: start };
    window.Motion = { reduced: reduced, off: off, typeOff: typeOff, watchTypes: watchTypes, bindCursorBlink: bindCursorBlink };
    start();
})();
