(function () {
    'use strict';

    var IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif'];
    var SAFE_NAME_RE = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}$/;


    function isSafeImageName(name) {
        if (typeof name !== 'string' || !name) return false;
        if (name.length > 96) return false;
        if (name.indexOf('/') !== -1 || name.indexOf('\\') !== -1) return false;
        if (name.indexOf('..') !== -1) return false;
        if (name.indexOf(':') !== -1) return false;
        if (name.indexOf('%') !== -1) return false;
        if (!SAFE_NAME_RE.test(name)) return false;
        var lower = name.toLowerCase();
        for (var i = 0; i < IMAGE_EXTENSIONS.length; i++) {
            if (lower.slice(-IMAGE_EXTENSIONS[i].length) === IMAGE_EXTENSIONS[i]) {
                return true;
            }
        }
        return false;
    }

    function imageUrlFor(manifest) {
        if (!manifest || !manifest.background) return null;
        var file = manifest.background.image;
        if (!isSafeImageName(file)) {
            if (file) {
                console.warn('TerminalBackground: refusing image name for '
                    + manifest.id + ':', file);
            }
            return null;
        }
        var base = (manifest.source === 'user')
            ? '/themes/'
            : '/static/css/themes/';
        return base + encodeURIComponent(manifest.id) + '/' + encodeURIComponent(file);
    }

    // ---- the ladder ---------------------------------------------------

    function manifestForSession(pinnedThemeId) {
        var themes = window.Themes;
        if (!themes) return null;
        if (pinnedThemeId && typeof themes.listAll === 'function') {
            var all = themes.listAll() || [];
            for (var i = 0; i < all.length; i++) {
                if (all[i] && all[i].id === pinnedThemeId) return all[i];
            }
        }
        return typeof themes.getActiveTerminalManifest === 'function'
            ? themes.getActiveTerminalManifest()
            : null;
    }

    window.TerminalBackgroundManifest = {
        isSafeImageName: isSafeImageName,
        imageUrlFor: imageUrlFor,
        manifestForSession: manifestForSession
    };
})();
