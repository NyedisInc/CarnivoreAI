(function () {
    'use strict';

    function revealAuthedChrome(app) {
        app.logoutBtn.classList.remove('hidden');
        if (app.settingsBtn) app.settingsBtn.classList.remove('hidden');
        if (app.configEditorBtn) app.configEditorBtn.classList.remove('hidden');
        if (app.sessionNotesBtn) app.sessionNotesBtn.classList.remove('hidden');
    }

    function tmuxNameOf(session, inner) {
        return (session && (session.tmux_session || session.name))
            || (inner && (inner.tmux_session || inner.name))
            || null;
    }

    function paintSessionChrome(app, session, inner, cameFromTerminal) {
        var sessionName = tmuxNameOf(session, inner);
        window.ThemeNavigation.applyForSession(session, sessionName);
        app._syncSessionUrl(sessionName, cameFromTerminal);
        if (window.SessionSidebar) {
            var activeSid = (inner && inner.id) || (session && session.id) || null;
            window.SessionSidebar.show();
            window.SessionSidebar.setActiveSession(activeSid, sessionName);
        }
        var label = (session && session.label) || (inner && inner.label) || null;
        setHeaderIdentity({
            icon: 'cloude',
            title: sessionDisplayName({ label: label, name: sessionName }) || 'session'
        });
        setPageTitle({ label: label, name: sessionName });
        return sessionName;
    }

    async function enterTerminal(app, session, inner, what, connect) {
        var nav = window.NavigationGeneration
            ? window.NavigationGeneration.current() : null;
        if (window.Router && typeof window.Router.clearError === 'function') {
            window.Router.clearError(nav);
        }
        var cameFromTerminal = app.currentScreen === 'terminal';
        app.hideAllScreens();
        document.getElementById('terminal-screen').classList.add('active');
        revealAuthedChrome(app);
        app.currentScreen = 'terminal';
        window.ScreenChrome.apply('terminal');
        app._placeStatusLight('terminal');
        paintSessionChrome(app, session, inner, cameFromTerminal);

        if (!window.TerminalController.term) {
            await window.TerminalController.init();
        }
        if (window.SlashCommandsBoot) {
            window.SlashCommandsBoot.start(session && session.working_dir);
        }
        if (window.NavigationGeneration
            && !window.NavigationGeneration.keep(nav, what)) return;
        connect(nav);
        app.focusTerminal();
    }

    window.AppScreenEntry = {
        revealAuthedChrome: revealAuthedChrome,
        enterTerminal: enterTerminal,
    };
})();
