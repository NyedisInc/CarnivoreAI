(function (global) {
    'use strict';

    var MIN_SIZE = 9;
    var MAX_SIZE = 28;
    var DEFAULT_SIZE = 14;
    var DEBOUNCE_MS = 100;
    var MAX_FAMILY_LENGTH = 200;
    var SIZE_KEY = 'carnivore.terminal-font-size';
    var FAMILY_KEY = 'carnivore.terminal-font-family';
    var SYMBOLS_FAMILY = 'SymbolsNerdFontMono';
    var FALLBACK_BASE = 'monospace';

    var bound = new Set();
    var listeners = new Set();
    var timer = null;
    var symbolsAsked = false;

    function clampSize(value) {
        var n = Math.round(Number(value));
        if (!isFinite(n) || value === null || value === '') return DEFAULT_SIZE;
        return Math.min(MAX_SIZE, Math.max(MIN_SIZE, n));
    }

    function sanitizeFamily(value) {
        var s = typeof value === 'string' ? value.trim() : '';
        if (!s || s.length > MAX_FAMILY_LENGTH) return '';
        if (/["';,{}<>\\\u0000-\u001f\u007f]/.test(s)) return '';
        return s;
    }

    function platformStack(base) {
        var ct = global.CloudeTerminal;
        var stack = base || (ct && ct.XTERM_OPTIONS && ct.XTERM_OPTIONS.fontFamily) || FALLBACK_BASE;
        return String(stack).replace(/,?\s*monospace\s*$/, '');
    }

    function familyStack(picked, base) {
        var name = sanitizeFamily(picked);
        var head = name ? '"' + name + '", ' : '';
        return head + platformStack(base) + ', "' + SYMBOLS_FAMILY + '", monospace';
    }

    function load(key) {
        try { return global.localStorage ? global.localStorage.getItem(key) : null; } catch (_) { return null; }
    }

    function store(key, value) {
        try {
            if (!global.localStorage) return;
            if (value === null) global.localStorage.removeItem(key);
            else global.localStorage.setItem(key, value);
        } catch (_) {  }
    }

    function size() { return clampSize(load(SIZE_KEY)); }

    function family() { return sanitizeFamily(load(FAMILY_KEY)); }

    function optionsFor(base) {
        return { fontSize: size(), fontFamily: familyStack(family(), base) };
    }

    function notify() {
        var state = { size: size(), family: family() };
        listeners.forEach(function (fn) {
            try { fn(state); } catch (err) { console.warn('TerminalFont: listener failed', err); }
        });
    }

    function applyNow() {
        timer = null;
        var changed = 0;
        bound.forEach(function (rec) {
            var term = rec.ref.deref();
            if (!term) { bound.delete(rec); return; }
            var want = optionsFor(rec.base);
            try {
                var moved = false;
                if (term.options.fontSize !== want.fontSize) { term.options.fontSize = want.fontSize; moved = true; }
                if (term.options.fontFamily !== want.fontFamily) { term.options.fontFamily = want.fontFamily; moved = true; }
                if (!moved) return;
                changed++;
                if (rec.refit) rec.refit('terminal-font');
            } catch (err) {
                console.warn('TerminalFont: apply failed on one terminal', err);
            }
        });
        return changed;
    }

    function schedule() {
        notify();
        if (timer) clearTimeout(timer);
        timer = setTimeout(applyNow, DEBOUNCE_MS);
    }

    function setSize(value) {
        var n = clampSize(value);
        store(SIZE_KEY, n === DEFAULT_SIZE ? null : String(n));
        schedule();
        return n;
    }

    function step(delta) { return setSize(size() + (delta < 0 ? -1 : 1)); }

    function reset() { return setSize(DEFAULT_SIZE); }

    function loadFace(name) {
        var fonts = global.document && global.document.fonts;
        if (!fonts || typeof fonts.load !== 'function') return Promise.resolve();
        var px = size() + 'px ';
        return Promise.all([fonts.load(px + '"' + name + '"'), fonts.load('bold ' + px + '"' + name + '"')])
            .then(function () {}, function (err) { console.warn('TerminalFont: font load failed', name, err); });
    }

    function setFamily(value) {
        var raw = typeof value === 'string' ? value.trim() : '';
        var name = sanitizeFamily(raw);
        if (raw && !name) return Promise.resolve(false);
        return (name ? loadFace(name) : Promise.resolve()).then(function () {
            store(FAMILY_KEY, name || null);
            schedule();
            return true;
        });
    }

    function askSymbolsOnce() {
        if (symbolsAsked) return;
        symbolsAsked = true;
        var fonts = global.document && global.document.fonts;
        if (!fonts || typeof fonts.load !== 'function') return;
        fonts.load('14px "' + SYMBOLS_FAMILY + '"', '').then(function () {
            bound.forEach(function (rec) {
                var term = rec.ref.deref();
                if (term && typeof term.clearTextureAtlas === 'function') term.clearTextureAtlas();
            });
        }, function (err) { console.warn('TerminalFont: icon font did not load', err); });
    }

    function bind(term, refit, base) {
        if (!term) return;
        bound.add({ ref: new WeakRef(term), refit: typeof refit === 'function' ? refit : null, base: base || '' });
        askSymbolsOnce();
    }

    function onChange(fn) {
        listeners.add(fn);
        return function () { listeners.delete(fn); };
    }

    if (typeof global.addEventListener === 'function') {
        global.addEventListener('storage', function (event) {
            if (event && (event.key === SIZE_KEY || event.key === FAMILY_KEY)) schedule();
        });
    }

    global.TerminalFont = {
        MIN_SIZE: MIN_SIZE,
        MAX_SIZE: MAX_SIZE,
        DEFAULT_SIZE: DEFAULT_SIZE,
        DEBOUNCE_MS: DEBOUNCE_MS,
        SYMBOLS_FAMILY: SYMBOLS_FAMILY,
        clampSize: clampSize,
        sanitizeFamily: sanitizeFamily,
        familyStack: familyStack,
        optionsFor: optionsFor,
        size: size,
        family: family,
        setSize: setSize,
        step: step,
        reset: reset,
        setFamily: setFamily,
        bind: bind,
        onChange: onChange
    };
}(typeof window !== 'undefined' ? window : globalThis));
