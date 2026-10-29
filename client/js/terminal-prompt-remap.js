(function () {
    'use strict';

    var CLAUDE_DARK_PROMPT_SLOTS = Object.freeze({ background: 237, foreground: 231 });

    /**
     * How far the prompt band moves from the terminal ground toward the
     * ink: 0.11 lands Carnivore Light (#f1f2f3 ground, #1d2226 ink) at
     * #dadbdc, the depth of its own card surface (--color-bg-card
     * #dadee1). Still sticks out, not a slab; ink on it measures about
     * 12:1.
     * @type {number}
     */
    var PROMPT_BAND_MIX = 0.11;

    function toHex(c) {
        return '#' + [c.r, c.g, c.b].map(function (v) {
            return ('0' + Math.round(v).toString(16)).slice(-2);
        }).join('');
    }

    function withLightPromptRemap(xtermTheme) {
        var shared = window.TerminalBackgroundOpacity;
        if (!shared || !shared.isLightXtermTheme(xtermTheme)) return xtermTheme;
        var ground = shared.parseCssColorChannels(xtermTheme.background);
        var ink = shared.parseCssColorChannels(xtermTheme.foreground);
        if (!ground || !ink) return xtermTheme;
        var band = {
            r: ground.r + (ink.r - ground.r) * PROMPT_BAND_MIX,
            g: ground.g + (ink.g - ground.g) * PROMPT_BAND_MIX,
            b: ground.b + (ink.b - ground.b) * PROMPT_BAND_MIX
        };
        var extended = Array.isArray(xtermTheme.extendedAnsi)
            ? xtermTheme.extendedAnsi.slice() : [];
        extended[CLAUDE_DARK_PROMPT_SLOTS.background - 16] = toHex(band);
        extended[CLAUDE_DARK_PROMPT_SLOTS.foreground - 16] = toHex(ink);
        return Object.assign({}, xtermTheme, { extendedAnsi: extended });
    }

    window.TerminalPromptRemap = {
        CLAUDE_DARK_PROMPT_SLOTS: CLAUDE_DARK_PROMPT_SLOTS,
        PROMPT_BAND_MIX: PROMPT_BAND_MIX,
        withLightPromptRemap: withLightPromptRemap
    };
})();
