
(function () {
    'use strict';

    var opening = 0;

    function freeze(controller, host) {
        var current = controller && controller._currentSession;
        var session = current && (current.session || current);
        var pinnedTheme = (window.ThemeNavigation
            && typeof window.ThemeNavigation.resolvePinnedTheme === 'function')
            ? window.ThemeNavigation.resolvePinnedTheme(current)
            : null;
        var frozenHost = host || (controller && controller === window.TerminalController
            ? document.getElementById('terminal-container') : null);
        var target = {
            sessionActive: !!(controller && controller.sessionActive),
            _currentSession: session
                ? {
                    working_dir: session.working_dir, pinned_theme: pinnedTheme,
                    session_id: session.id || session.session_id || null,
                    session_row_id: typeof current.session_row_id === 'number' ? current.session_row_id : null,
                    tmux_session: current.tmux_session || session.tmux_session || null
                }
                : null,
            host: frozenHost
        };
        return target;
    }

    function openWhenReady(triggerBtn, controller = window.TerminalController, directory = null, host = null) {
        var request = ++opening;
        var target = freeze(controller, host);
        if (!window.ModuleLoader || typeof window.ModuleLoader.loadFamily !== 'function') {
            _fail('App: ModuleLoader is not loaded - the config editor ' +
                'family cannot be fetched.',
                'the file editor could not be loaded. reload the page and try again.');
            return;
        }

        var urls = (window.ModuleFamilies && window.ModuleFamilies.CONFIG_EDITOR) || [];
        return window.ModuleLoader.loadFamily('config-editor', urls).then(function () {
            if (request !== opening) return;
            if (window.ConfigEditorPanel && typeof window.ConfigEditorPanel.open === 'function') {
                return window.ConfigEditorPanel.open(triggerBtn, target, directory);
            } else {
                _fail('App: ConfigEditorPanel is not loaded even after the ' +
                    'config editor family loaded - check module-families.js.',
                    'the file editor could not be opened. reload the page and try again.');
            }
        }).catch(function (err) {
            if (request !== opening) return;
            _fail('App: the config editor script family failed to load: ' +
                (err && err.message ? err.message : err),
                'the file editor could not be loaded: ' +
                (err && err.message ? err.message : 'network error') +
                '. reload the page and try again.');
        });
    }

    function _fail(logMessage, bannerMessage) {
        console.error(logMessage);
        if (window.Router && typeof window.Router.showError === 'function') {
            window.Router.showError(bannerMessage);
        }
    }

    function panel() {
        return window.ConfigEditorPanel || null;
    }

    function toggleWhenReady(triggerBtn, controller = window.TerminalController, directory = null, host = null) {
        var open = panel();
        var scope = ['skills', 'plugins'].includes(directory) ? directory : null;
        if (open && open.isOpen && open.directory === scope) {
            opening++;
            return open.close();
        }
        return openWhenReady(triggerBtn, controller, directory, host);
    }

    function closeDrawer() {
        var open = panel();
        opening++;
        if (open && open.isOpen) return open.close();
    }

    function retarget(controller, host) {
        var open = panel();
        if (!open || !open.isOpen || typeof open.retarget !== 'function') return;
        open.retarget(freeze(controller, host || null));
    }

    window.ConfigEditorLoader = {
        openWhenReady: openWhenReady,
        toggleWhenReady: toggleWhenReady,
        closeDrawer: closeDrawer,
        retarget: retarget
    };
})();
