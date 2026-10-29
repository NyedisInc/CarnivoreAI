(function () {
    'use strict';

    var TEXT_TARGET = 4.5;

    var ACCENT_TARGET = 3.0;

    var TARGET_MARGIN = 1.02;

    var BLACK = { r: 0, g: 0, b: 0 };
    var WHITE = { r: 255, g: 255, b: 255 };

    var ANSI_KEYS = [
        'black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white',
        'brightBlack', 'brightRed', 'brightGreen', 'brightYellow',
        'brightBlue', 'brightMagenta', 'brightCyan', 'brightWhite'
    ];

    var floorCache = {};


    function linearize(channel) {
        var c = channel / 255;
        return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }

    function relativeLuminance(rgb) {
        return 0.2126 * linearize(rgb.r)
            + 0.7152 * linearize(rgb.g)
            + 0.0722 * linearize(rgb.b);
    }

    function contrastRatio(a, b) {
        var la = relativeLuminance(a);
        var lb = relativeLuminance(b);
        var hi = Math.max(la, lb);
        var lo = Math.min(la, lb);
        return (hi + 0.05) / (lo + 0.05);
    }

    function composite(bg, img, dim) {
        return {
            r: dim * bg.r + (1 - dim) * img.r,
            g: dim * bg.g + (1 - dim) * img.g,
            b: dim * bg.b + (1 - dim) * img.b
        };
    }

    function worstRatio(bg, text, dim) {
        var lo = relativeLuminance(composite(bg, BLACK, dim));
        var hi = relativeLuminance(composite(bg, WHITE, dim));
        var lt = relativeLuminance(text);
        if (lt >= lo && lt <= hi) return 1;
        var a = (Math.max(lt, lo) + 0.05) / (Math.min(lt, lo) + 0.05);
        var b = (Math.max(lt, hi) + 0.05) / (Math.min(lt, hi) + 0.05);
        return Math.min(a, b);
    }

    function minimumDimFor(bg, text, target) {
        if (worstRatio(bg, text, 1) < target) return 1;
        if (worstRatio(bg, text, 0) >= target) return 0;
        var lo = 0;
        var hi = 1;
        for (var i = 0; i < 18; i++) {
            var mid = (lo + hi) / 2;
            if (worstRatio(bg, text, mid) >= target) {
                hi = mid;
            } else {
                lo = mid;
            }
        }
        return hi;
    }

    function minimumDim(xtermTheme) {
        if (!xtermTheme || typeof xtermTheme !== 'object') return null;
        var parse = (window.TerminalBackgroundOpacity
            && window.TerminalBackgroundOpacity.parseCssColorChannels) || null;
        if (!parse) return null;

        var key = JSON.stringify([xtermTheme.background, xtermTheme.foreground]
            .concat(ANSI_KEYS.map(function (k) { return xtermTheme[k]; })));
        if (Object.prototype.hasOwnProperty.call(floorCache, key)) {
            return floorCache[key];
        }

        var bg = parse(xtermTheme.background);
        var fg = parse(xtermTheme.foreground);
        if (!bg || !fg) {
            floorCache[key] = null;
            return null;
        }

        var floor = minimumDimFor(bg, fg, TEXT_TARGET * TARGET_MARGIN);
        for (var i = 0; i < ANSI_KEYS.length; i++) {
            var colour = parse(xtermTheme[ANSI_KEYS[i]]);
            if (!colour) continue;
            if (contrastRatio(colour, bg) < TEXT_TARGET) continue;
            var need = minimumDimFor(bg, colour, ACCENT_TARGET * TARGET_MARGIN);
            if (need > floor) floor = need;
        }
        floorCache[key] = floor;
        return floor;
    }

    window.TerminalBackgroundContrast = {
        TEXT_TARGET: TEXT_TARGET,
        ACCENT_TARGET: ACCENT_TARGET,
        contrastRatio: contrastRatio,
        composite: composite,
        worstRatio: worstRatio,
        minimumDim: minimumDim
    };
})();
