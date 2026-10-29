/* aria-label="Theme" */
(function () {
    'use strict';

    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    function buildOptions(selectEl, themes, activeId) {
        while (selectEl.firstChild) selectEl.removeChild(selectEl.firstChild);
        themes.forEach(function (m) {
            var opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.name || m.id;
            if (m.id === activeId) opt.selected = true;
            selectEl.appendChild(opt);
        });
    }

    /* already exists */
    function mount(parentEl) {
        if (!parentEl) {
            console.warn('ThemeSelector.mount: no parent element - skipping');
            return null;
        }
        if (!window.Themes) {
            console.warn('ThemeSelector.mount: window.Themes not available - skipping');
            return null;
        }

        var existing = parentEl.querySelector('#theme-selector');
        var selectEl = existing;
        if (!selectEl) {
            selectEl = document.createElement('select');
            selectEl.id = 'theme-selector';
            selectEl.className = 'theme-selector';
            selectEl.setAttribute('aria-label', tr('header.menu.theme'));
            parentEl.appendChild(selectEl);
            selectEl.addEventListener('change', function (e) {
                var id = e.target.value;
                window.Themes.applyGlobal(id);
            });
        }

        var themes = window.Themes.listAll();
        var active = (window.Themes.getActiveGlobal() || {}).id || window.Themes.DEFAULT_THEME_ID;
        buildOptions(selectEl, themes, active);
        return selectEl;
    }

    function refresh() {
        var existing = document.getElementById('theme-selector');
        if (!existing || !window.Themes) return;
        var themes = window.Themes.listAll();
        var active = (window.Themes.getActiveGlobal() || {}).id || window.Themes.DEFAULT_THEME_ID;
        buildOptions(existing, themes, active);
    }

    window.ThemeSelector = {
        mount: mount,
        refresh: refresh
    };
})();
