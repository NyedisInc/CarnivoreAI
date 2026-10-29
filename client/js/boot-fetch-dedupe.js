(function (root) {
    'use strict';

    const BOOT_WINDOW_MS = 8000;
    const BOOT_REUSE_MS = 1500;

    let clock = () => Date.now();
    let windowMs = BOOT_WINDOW_MS;
    let reuseMs = BOOT_REUSE_MS;
    let startedAt = clock();
    const flights = new Map();
    armSweep();

    function armSweep() {
        if (typeof setTimeout !== 'function') return;
        const timer = setTimeout(clear, windowMs + reuseMs + 50);
        if (timer && typeof timer.unref === 'function') timer.unref();
    }

    function isOpen() {
        return clock() - startedAt < windowMs;
    }

    function clear() {
        flights.clear();
    }

    function scopeOf(key) {
        const m = /\/api\/v1\/([^/?#]+)/.exec(key);
        return m ? m[1] : null;
    }

    function clearFor(key) {
        const scope = scopeOf(key);
        if (scope === null) return clear();
        for (const k of [...flights.keys()]) if (scopeOf(k) === scope || scopeOf(k) === null) flights.delete(k);
    }

    function copyOf(value) {
        if (value === null || typeof value !== 'object') return value;
        const tag = Object.prototype.toString.call(value);
        if (tag !== '[object Object]' && tag !== '[object Array]') return value;
        return JSON.parse(JSON.stringify(value));
    }

    function share(key, start) {
        let entry = flights.get(key);
        if (entry && entry.doneAt !== null && clock() - entry.doneAt >= reuseMs) {
            flights.delete(key);
            entry = undefined;
        }
        if (!entry) {
            let flight;
            try {
                flight = Promise.resolve(start());
            } catch (err) {
                flight = Promise.reject(err);
            }
            const mine = { flight, doneAt: null };
            flight.then(() => { mine.doneAt = clock(); }, () => { if (flights.get(key) === mine) flights.delete(key); });
            flights.set(key, mine);
            entry = mine;
        }
        return entry.flight.then(copyOf);
    }

    function run(key, init, start) {
        const options = init || {};
        const method = String(options.method || 'GET').toUpperCase();
        if (method !== 'GET') {
            clearFor(key);
            return start();
        }
        if (!isOpen() || options.body || options.signal || options.headers) return start();
        return share(key, start);
    }

    function configure(opts) {
        const o = opts || {};
        if (typeof o.now === 'function') clock = o.now;
        if (typeof o.windowMs === 'number') windowMs = o.windowMs;
        if (typeof o.reuseMs === 'number') reuseMs = o.reuseMs;
        startedAt = clock();
        clear();
    }

    root.BootFetchDedupe = { run, share, clear, isOpen, configure, BOOT_WINDOW_MS, BOOT_REUSE_MS };
})(typeof window !== 'undefined' ? window : globalThis);
