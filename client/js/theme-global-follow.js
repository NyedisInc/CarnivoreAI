(function () {
    'use strict';

    function onGlobalThemeChanged(themeId) {
        var themes = window.Themes;
        if (themes && themes.STORAGE_KEY && typeof themeId === 'string' && themeId) {
            try {
                var migrate = window.BrowserStorageMigrate;
                if (migrate) migrate.writeMigrating(themes.STORAGE_KEY, themeId);
                else localStorage.setItem(themes.STORAGE_KEY, themeId);
            } catch (_) {  }
        }
        var nav = window.ThemeNavigation;
        if (nav && typeof nav.reapply === 'function') nav.reapply();
    }

    var stop = null;

    function start() {
        var bridge = globalThis.PreferenceBridge;
        if (!bridge || typeof bridge.follow !== 'function') return function () {};
        if (stop) stop();
        stop = bridge.follow('theme', onGlobalThemeChanged);
        return stop;
    }

    window.ThemeGlobalFollow = { start: start };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
