(function () {
    'use strict';

    var TERMINAL_BG_OPACITY = 0.90;

    function parseCssColorChannels(color) {
        if (typeof color !== 'string') return null;
        var hex3 = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(color);
        if (hex3) {
            return {
                r: parseInt(hex3[1] + hex3[1], 16),
                g: parseInt(hex3[2] + hex3[2], 16),
                b: parseInt(hex3[3] + hex3[3], 16)
            };
        }
        var hex6 = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color);
        if (hex6) {
            return {
                r: parseInt(hex6[1], 16),
                g: parseInt(hex6[2], 16),
                b: parseInt(hex6[3], 16)
            };
        }
        var rgb = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i.exec(color);
        if (rgb) {
            return { r: Number(rgb[1]), g: Number(rgb[2]), b: Number(rgb[3]) };
        }
        return null;
    }

    function relativeLuminance(channels) {
        function linearize(channel8bit) {
            var c = channel8bit / 255;
            return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        }
        return 0.2126 * linearize(channels.r)
            + 0.7152 * linearize(channels.g)
            + 0.0722 * linearize(channels.b);
    }

    function minimumContrastRatioForXtermTheme(xtermTheme) {
        return isLightXtermTheme(xtermTheme) ? 4.5 : 1;
    }

    function isLightXtermTheme(xtermTheme) {
        if (!xtermTheme || typeof xtermTheme !== 'object') return false;
        var channels = parseCssColorChannels(xtermTheme.background);
        return !!channels && relativeLuminance(channels) > 0.5;
    }

    function isThemeEffectVisible() {
        try {
            var status = document.documentElement.dataset.themeEffects;
            return status === 'running' || status === 'paused' || status === 'static';
        } catch (_) {
            return false;
        }
    }

    function normaliseImageAlpha(raw) {
        if (raw === null || raw === undefined) return null;
        var n = parseFloat(raw);
        if (!isFinite(n) || n < 0 || n > 1) return null;
        return n;
    }

    function withTerminalBackgroundOpacity(rawTheme, imageAlpha) {
        if (!rawTheme || typeof rawTheme !== 'object') return rawTheme;
        var alpha;
        if (normaliseImageAlpha(imageAlpha) !== null) {
            alpha = 0;
        } else {
            if (!isThemeEffectVisible()) return rawTheme;
            alpha = TERMINAL_BG_OPACITY;
        }
        var channels = parseCssColorChannels(rawTheme.background);
        if (!channels) return rawTheme;
        if (alpha >= 1) return rawTheme;
        return Object.assign({}, rawTheme, {
            background: 'rgba(' + channels.r + ', ' + channels.g + ', ' + channels.b + ', ' + alpha + ')'
        });
    }

    function attach(term) {
        var lastRaw = null;
        var imageAlpha = null;
        function apply(rawTheme) {
            lastRaw = rawTheme;
            if (!term) return;
            try {
                var remap = window.TerminalPromptRemap;
                var shown = remap ? remap.withLightPromptRemap(rawTheme) : rawTheme;
                term.options.theme = withTerminalBackgroundOpacity(shown, imageAlpha);
                term.options.minimumContrastRatio = minimumContrastRatioForXtermTheme(rawTheme);
            } catch (e) {
                if (window.console && console.warn) {
                    console.warn('TerminalBackgroundOpacity: failed to apply theme', e);
                }
            }
        }
        function setImageAlpha(next) {
            var value = normaliseImageAlpha(next);
            if (value === imageAlpha) return false;
            imageAlpha = value;
            if (lastRaw) apply(lastRaw);
            return true;
        }
        var observer = null;
        try {
            observer = new MutationObserver(function () { apply(lastRaw); });
            observer.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-theme-effects']
            });
        } catch (e) {
            if (window.console && console.warn) {
                console.warn('TerminalBackgroundOpacity: effect-status observer unavailable', e);
            }
        }
        return {
            apply: apply,
            setImageAlpha: setImageAlpha,
            imageAlpha: function () { return imageAlpha; },
            dispose: function () { if (observer) observer.disconnect(); }
        };
    }

    window.TerminalBackgroundOpacity = {
        TERMINAL_BG_OPACITY: TERMINAL_BG_OPACITY,
        parseCssColorChannels: parseCssColorChannels,
        isThemeEffectVisible: isThemeEffectVisible,
        normaliseImageAlpha: normaliseImageAlpha,
        withTerminalBackgroundOpacity: withTerminalBackgroundOpacity,
        minimumContrastRatioForXtermTheme: minimumContrastRatioForXtermTheme,
        isLightXtermTheme: isLightXtermTheme,
        relativeLuminance: relativeLuminance,
        attach: attach
    };
})();
