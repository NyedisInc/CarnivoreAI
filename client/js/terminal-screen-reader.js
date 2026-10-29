(function () {
    'use strict';

    var FIELD = 'terminal_screen_reader';
    var STORAGE_KEY = 'carnivore.terminal-screen-reader';
    var CAPABILITY = 'screenReader';
    var terms = new Set();
    var stop = null;
    var osOn = false;

    function settingOf(value) {
        return value === 'on' || value === 'off' ? value : 'auto';
    }

    function modeFor(setting, osSignal) {
        var s = settingOf(setting);
        if (s === 'on') return true;
        if (s === 'off') return false;
        return osSignal === true;
    }

    /* xterm options */
    function optionsFor(setting, osSignal) {
        return { screenReaderMode: modeFor(setting, osSignal) };
    }

    function loadLocal() {
        try {
            return settingOf(localStorage.getItem(STORAGE_KEY));
        } catch (_) {
            return 'auto';
        }
    }

    function saveLocal(setting) {
        try {
            localStorage.setItem(STORAGE_KEY, setting);
        } catch (_) {  }
    }

    function currentSetting() {
        var bridge = globalThis.PreferenceBridge;
        return settingOf(bridge && typeof bridge.read === 'function' ? bridge.read(FIELD, loadLocal) : loadLocal());
    }

    function paint(on) {
        terms.forEach(function (ref) {
            var term = ref.deref();
            if (!term) { terms.delete(ref); return; }
            try {
                term.options.screenReaderMode = on;
            } catch (_) {  }
        });
    }

    function apply() {
        var setting = currentSetting();
        saveLocal(setting);
        var on = modeFor(setting, osOn);
        paint(on);
        return on;
    }

    function setOsSignal(on) {
        osOn = on === true;
        return apply();
    }

    function follow() {
        var bridge = globalThis.PreferenceBridge;
        if (stop || !bridge || typeof bridge.follow !== 'function') return;
        stop = bridge.follow(FIELD, function (value) {
            var setting = settingOf(value);
            saveLocal(setting);
            paint(modeFor(setting, osOn));
        });
    }

    function bind(term) {
        terms.add(new WeakRef(term));
        follow();
        try {
            term.options.screenReaderMode = modeFor(currentSetting(), osOn);
        } catch (_) {  }
    }

    function watchOs() {
        var desktop = typeof window !== 'undefined' ? window.carnivoreDesktop : null;
        if (!desktop || !desktop.capabilities || typeof desktop.capabilities.indexOf !== 'function') return;
        if (desktop.capabilities.indexOf(CAPABILITY) < 0 || typeof desktop.screenReader !== 'function') return;
        window.addEventListener('message', function (event) {
            if (event.source !== window || event.origin !== window.location.origin) return;
            var data = event.data;
            if (!data || data.type !== 'carnivore.screen-reader' || typeof data.on !== 'boolean') return;
            setOsSignal(data.on);
        });
        Promise.resolve(desktop.screenReader()).then(function (on) {
            if (typeof on === 'boolean') setOsSignal(on);
        }).catch(function (err) {
            // could not
            console.warn('[TerminalScreenReader] OS signal unavailable', err && err.message ? err.message : err);
        });
    }

    window.TerminalScreenReader = { bind: bind, apply: apply, modeFor: modeFor, optionsFor: optionsFor, setOsSignal: setOsSignal };
    watchOs();
})();
