(function (global) {
    'use strict';

    function rejectsLeadingSpace(makeContext) {
        try {
            const ctx = makeContext();
            const good = ['12px', 'monospace'].join(' ');
            ctx.font = ['20px', 'serif'].join(' ');
            ctx.font = ' ' + good;
            return ctx.font !== good;
        } catch (err) {
            return false;
        }
    }

    function wrapFont(proto) {
        const desc = Object.getOwnPropertyDescriptor(proto, 'font');
        if (!desc || !desc.set || desc.set.__fontTrim) return false;
        const origSet = desc.set;
        const set = function (value) {
            origSet.call(this, typeof value === 'string' ? value.trim() : value);
        };
        set.__fontTrim = true;
        Object.defineProperty(proto, 'font', {
            configurable: true,
            enumerable: desc.enumerable,
            get: desc.get,
            set,
        });
        return true;
    }

    function install(g) {
        const installed = [];
        if (!g.OffscreenCanvas || !rejectsLeadingSpace(() => new g.OffscreenCanvas(1, 1).getContext('2d'))) return installed;
        for (const name of ['CanvasRenderingContext2D', 'OffscreenCanvasRenderingContext2D']) {
            const Ctor = g[name];
            if (Ctor && Ctor.prototype && wrapFont(Ctor.prototype)) installed.push(name);
        }
        return installed;
    }

    global.CanvasFontTrim = { install, wrapFont, rejectsLeadingSpace };
    install(global);
})(typeof window !== 'undefined' ? window : globalThis);
