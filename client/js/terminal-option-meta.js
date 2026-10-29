(function () {
    'use strict';

    var FIELD = 'mac_option_is_meta';
    var STORAGE_KEY = 'carnivore.mac-option-is-meta';
    var terms = new Set();
    var stop = null;

    function loadLocal() {
        try {
            return localStorage.getItem(STORAGE_KEY) === '1';
        } catch (_) {
            return false;
        }
    }

    function saveLocal(on) {
        try {
            localStorage.setItem(STORAGE_KEY, on ? '1' : '0');
        } catch (_) {  }
    }

    function current() {
        var bridge = globalThis.PreferenceBridge;
        var value = bridge && typeof bridge.read === 'function' ? bridge.read(FIELD, loadLocal) : loadLocal();
        return value === true;
    }

    function paint(on) {
        terms.forEach(function (ref) {
            var term = ref.deref();
            if (!term) { terms.delete(ref); return; }
            try {
                term.options.macOptionIsMeta = on;
            } catch (_) {  }
        });
    }

    function apply() {
        var on = current();
        saveLocal(on);
        paint(on);
        return on;
    }

    function follow() {
        var bridge = globalThis.PreferenceBridge;
        if (stop || !bridge || typeof bridge.follow !== 'function') return;
        stop = bridge.follow(FIELD, function (value) {
            var on = value === true;
            saveLocal(on);
            paint(on);
        });
    }

    function bind(term) {
        terms.add(new WeakRef(term));
        follow();
        var on = current();
        saveLocal(on);
        try {
            term.options.macOptionIsMeta = on;
        } catch (_) {  }
    }

    window.TerminalOptionMeta = { bind: bind, apply: apply };
})();
