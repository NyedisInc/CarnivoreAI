/* display: none */

console.log('[TerminalGridHost Module] Loading...');

(function () {
    var SCREEN_ID = 'terminal-screen';

    var GRID_ID = 'terminal-grid';

    var WIDE = '(min-width: 1024px)';

    var PHONE_ID = 'terminal-phone-tabs';

    var mounted = false;

    var phoneMounted = false;

    function bundle() {
        var found = globalThis.CloudeWeb;
        return found && typeof found.mountTerminalGrid === 'function' ? found : null;
    }

    function wide() {
        if (typeof window.matchMedia !== 'function') return true;
        return window.matchMedia(WIDE).matches;
    }

    function apply() {
        if (globalThis.DashboardPolls) globalThis.DashboardPolls.sync();
        var solo = !!(window.SoloWindow && window.SoloWindow.active());
        var want = onTerminal() && wide() && !solo;
        var wantPhone = onTerminal() && !wide() && !solo;
        var app = bundle();
        if (!app) return;
        if (want !== mounted) {
            try {
                if (want) mounted = app.mountTerminalGrid(GRID_ID);
                else {
                    app.unmountTerminalGrid(GRID_ID);
                    mounted = false;
                }
            } catch (err) {
                console.warn('[TerminalGridHost] the dashboard refused a mount change', err);
                mounted = false;
            }
        }
        if (wantPhone === phoneMounted || typeof app.mountTerminalPhoneTabs !== 'function') return;
        try {
            if (wantPhone) phoneMounted = app.mountTerminalPhoneTabs(PHONE_ID);
            else {
                app.unmountTerminalPhoneTabs(PHONE_ID);
                phoneMounted = false;
            }
        } catch (err) {
            console.warn('[TerminalGridHost] the phone tab strip refused a mount change', err);
            phoneMounted = false;
        }
    }

    function onTerminal() {
        var screen = document.getElementById(SCREEN_ID);
        return !!screen && screen.classList.contains('active')
            && !screen.classList.contains('terminal-screen--empty');
    }

    function observe() {
        var screen = document.getElementById(SCREEN_ID);
        if (screen && typeof MutationObserver === 'function') {
            new MutationObserver(function () {
                Promise.resolve().then(apply);
            }).observe(screen, { attributes: true, attributeFilter: ['class'] });
        }
        if (typeof window.matchMedia === 'function') {
            window.matchMedia(WIDE).addEventListener('change', function () {
                apply();
            });
        }
        apply();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', observe, { once: true });
    } else {
        observe();
    }

    globalThis.TerminalGridHost = {
        apply: apply,
        onTerminal: onTerminal,
        wide: wide,
        isMounted: function () {
            return mounted;
        },
        isPhoneMounted: function () {
            return phoneMounted;
        },
        GRID_ID: GRID_ID,
    };

    console.log('[TerminalGridHost Module] Loaded');
})();
