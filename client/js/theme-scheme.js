
(function () {
    'use strict';

    var SCHEME_VAR = '--color-scheme';
    var LINE_VAR = '--oc-light-line-l';
    var GROUND_VARS = ['--color-bg-page', '--color-bg'];
    var CACHE_LIMIT = 64;
    var NOT_A_GROUND = /^\s*(transparent|currentcolor|inherit|initial|unset|revert|revert-layer)\s*$/i;

    var cache = new Map();

    function oklabLightness(r, g, b) {
        function linear(channel) {
            var c = channel / 255;
            return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        }
        var lr = linear(r), lg = linear(g), lb = linear(b);
        var l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
        var m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
        var s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
        return 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s;
    }

    function schemeOfPixel(rgba, line) {
        if (!rgba || rgba.length < 4 || rgba[3] !== 255 || typeof line !== 'number' || !isFinite(line)) return null;
        return oklabLightness(rgba[0], rgba[1], rgba[2]) >= line ? 'light' : 'dark';
    }

    /* there is nothing */
    function lightLine() {
        var doc = globalThis.document;
        if (!doc || !doc.documentElement || typeof globalThis.getComputedStyle !== 'function') return null;
        var raw = globalThis.getComputedStyle(doc.documentElement).getPropertyValue(LINE_VAR).trim();
        var line = raw ? Number(raw) : NaN;
        return isFinite(line) ? line : null;
    }

    var makeCanvas = null;

    function useCanvas(make) {
        makeCanvas = typeof make === 'function' ? make : null;
    }

    function context2d() {
        var Canvas = globalThis.OffscreenCanvas;
        if (typeof Canvas === 'function') return new Canvas(1, 1).getContext('2d') || null;
        var canvas = makeCanvas ? makeCanvas() : null;
        if (!canvas) return null;
        canvas.width = 1;
        canvas.height = 1;
        return canvas.getContext('2d') || null;
    }

    function paintedPixel(color) {
        var ctx = context2d();
        if (!ctx) return null;
        ctx.fillStyle = '#010203';
        ctx.fillStyle = color;
        var first = ctx.fillStyle;
        ctx.fillStyle = '#040506';
        ctx.fillStyle = color;
        if (first === '#010203' && ctx.fillStyle === '#040506') return null;
        ctx.clearRect(0, 0, 1, 1);
        ctx.fillRect(0, 0, 1, 1);
        return ctx.getImageData(0, 0, 1, 1).data;
    }

    function schemeOfColor(color) {
        var key = String(color);
        if (cache.has(key)) return cache.get(key);
        var line = lightLine();
        if (line === null) return null;
        if (typeof globalThis.OffscreenCanvas !== 'function' && !makeCanvas) return null;
        var scheme = NOT_A_GROUND.test(key) ? null : schemeOfPixel(paintedPixel(key), line);
        if (cache.size >= CACHE_LIMIT) cache.delete(cache.keys().next().value);
        cache.set(key, scheme);
        return scheme;
    }

    function withColorScheme(vars) {
        if (!vars || Object.prototype.hasOwnProperty.call(vars, SCHEME_VAR)) return vars;
        var ground;
        for (var i = 0; i < GROUND_VARS.length && ground === undefined; i++) ground = vars[GROUND_VARS[i]];
        if (ground === undefined) return vars;
        var scheme = schemeOfColor(ground);
        if (scheme === null) return vars;
        var out = {};
        for (var key in vars) {
            if (Object.prototype.hasOwnProperty.call(vars, key)) out[key] = vars[key];
        }
        out[SCHEME_VAR] = scheme;
        return out;
    }

    globalThis.ThemeScheme = {
        SCHEME_VAR: SCHEME_VAR,
        LINE_VAR: LINE_VAR,
        oklabLightness: oklabLightness,
        schemeOfPixel: schemeOfPixel,
        schemeOfColor: schemeOfColor,
        withColorScheme: withColorScheme,
        useCanvas: useCanvas
    };
})();
