console.log('[TerminalEmptyEntry Module] Loading...');

(function () {
    var SCREEN_ID = 'terminal-screen';
    var EMPTY_PATH = '/session';

    var pending = false;

    function isEmptyPath(pathname) {
        return pathname === EMPTY_PATH || pathname === EMPTY_PATH + '/';
    }

    function label(key) {
        return globalThis.CloudeTr(key);
    }

    function syncUrl() {
        if (isEmptyPath(window.location.pathname)) return;
        try {
            window.history.pushState({}, '', EMPTY_PATH);
        } catch (e) {
        }
    }

    function show(opts) {
        var app = window.App;
        var web = window.CloudeWeb;
        var screen = document.getElementById(SCREEN_ID);
        if (!app || typeof app.hideAllScreens !== 'function' || !screen
                || !web || typeof web.openTerminalEmpty !== 'function') {
            console.error('TerminalEmptyEntry: the app, #terminal-screen or '
                + 'CloudeWeb.openTerminalEmpty is missing, nothing was shown');
            return false;
        }
        var nav = window.NavigationGeneration;
        var before = nav ? nav.current() : null;
        if (app.currentScreen && nav) nav.begin('terminal-empty');
        if (window.Router && typeof window.Router.clearError === 'function') {
            window.Router.clearError(before);
        }
        var ctl = window.TerminalController;
        if (app.currentScreen === 'terminal' && ctl && typeof ctl.pauseForHome === 'function') {
            ctl.pauseForHome();
        }
        if (window.LaunchpadHost) window.LaunchpadHost.exit();
        app.hideAllScreens();
        if (!web.openTerminalEmpty()) {
            console.error('TerminalEmptyEntry: the panel did not mount');
        }
        screen.classList.add('active');
        ['logoutBtn', 'settingsBtn', 'configEditorBtn'].forEach(function (name) {
            if (app[name]) app[name].classList.remove('hidden');
        });
        app.currentScreen = 'terminal';
        if (window.ScreenChrome) window.ScreenChrome.apply('terminal');
        if (typeof app._placeStatusLight === 'function') app._placeStatusLight('terminal');
        if (window.ThemeNavigation) window.ThemeNavigation.applyForGlobal();
        if (window.SessionSidebar) {
            window.SessionSidebar.setActiveSession(null, null);
            window.SessionSidebar.show();
            // the empty page
            if (!window.SessionSidebar.isOpen) {
                window.SessionSidebar.open({ persist: false });
            }
        }
        if (typeof window.setHeaderIdentity === 'function') {
            window.setHeaderIdentity({ icon: 'cloude', title: label('terminal.empty.header') });
        }
        if (typeof window.setPageTitle === 'function') window.setPageTitle(null);
        if (!(opts && opts.fromRouter)) syncUrl();
        return true;
    }

    function route(immediate) {
        if (immediate) {
            show({ fromRouter: true });
            return;
        }
        pending = true;
        var latch = window.AppBootComplete;
        if (latch && typeof latch.isComplete === 'function' && latch.isComplete()) {
            consume();
            return;
        }
        window.addEventListener(latch && latch.EVENT ? latch.EVENT : 'app-boot-complete', function () {
            setTimeout(consume, 0);
        }, { once: true });
    }

    function consume() {
        if (!pending) return;
        pending = false;
        if (isEmptyPath(window.location.pathname)) show({ fromRouter: true });
    }

    function isPending() {
        return pending;
    }

    window.TerminalEmptyEntry = {
        show: show,
        route: route,
        isEmptyPath: isEmptyPath,
        isPending: isPending,
        EMPTY_PATH: EMPTY_PATH
    };

    console.log('[TerminalEmptyEntry Module] Loaded');
})();
