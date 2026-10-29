/* --color- */
(function () {
    'use strict';

    var cache = new Map();

    function parseHex(hex) {
        if (typeof hex !== 'string') return null;
        var h = hex.trim();
        if (h.charAt(0) !== '#') return null;
        h = h.slice(1);
        if (h.length === 3) {
            h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
        }
        if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
        var n = parseInt(h, 16);
        return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
    }

    function manifestFor(themeId) {
        if (!window.Themes || typeof window.Themes.listAll !== 'function') return null;
        var all;
        try {
            all = window.Themes.listAll();
        } catch (_) {
            return null;
        }
        if (!Array.isArray(all)) return null;
        for (var i = 0; i < all.length; i++) {
            if (all[i] && all[i].id === themeId) return all[i];
        }
        return null;
    }

    function colorsFor(themeId) {
        if (!themeId) return null;
        if (cache.has(themeId)) return cache.get(themeId);
        var manifest = manifestFor(themeId);
        if (!manifest || !manifest.cssVars) return null;
        var rgb = parseHex(manifest.cssVars['--color-accent']);
        if (!rgb) return null;
        var value = {
            accent: 'rgb(' + rgb.r + ', ' + rgb.g + ', ' + rgb.b + ')',
            label: (typeof manifest.name === 'string' && manifest.name.trim())
                ? manifest.name.trim()
                : String(themeId),
        };
        cache.set(themeId, value);
        return value;
    }

    /**
     * Scrub a theme id down to what is safe to write into markup.
     *
     * @param {?string} themeId - the session's pinned theme id.
     * @returns {string} the id reduced to [A-Za-z0-9_-], or '' when
     *   nothing survives - which yields an untinted row rather than a
     *   partially-escaped one.
     */
    function safeThemeId(themeId) {
        return String(themeId).replace(/[^a-zA-Z0-9_-]/g, '');
    }

    function escAttr(text) {
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function attrs(themeId) {
        var colors = colorsFor(themeId);
        if (!colors) return '';
        var safeId = safeThemeId(themeId);
        if (!safeId) return '';
        return (
            ' data-session-theme="' + safeId + '"' +
            ' style="--session-theme-accent: ' + colors.accent + ';"'
        );
    }

    function swatchHtml(themeId) {
        var colors = colorsFor(themeId);
        if (!colors) return '';
        if (!safeThemeId(themeId)) return '';
        var label = 'session theme: ' + colors.label;
        return (
            '<span class="session-theme-swatch" role="img"' +
            ' aria-label="' + escAttr(label) + '"' +
            ' title="' + escAttr(label) + '"></span>'
        );
    }

    window.SessionThemeTint = {
        attrs: attrs,
        swatchHtml: swatchHtml,
        colorsFor: colorsFor,
    };
})();
