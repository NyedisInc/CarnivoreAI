/* permission prompt */
(function () {
    'use strict';

    function findSession(sessions, sessionId) {
        if (!Array.isArray(sessions) || !sessionId) return null;
        for (var i = 0; i < sessions.length; i++) {
            var info = sessions[i];
            if (!info) continue;
            var inner = info.session || info;
            if ((inner && inner.id === sessionId) || info.id === sessionId) {
                return info;
            }
        }
        return null;
    }

    function tmuxNameOf(info) {
        if (!info) return null;
        var inner = info.session || info;
        return (info.tmux_session || info.name)
            || (inner && (inner.tmux_session || inner.name))
            || null;
    }

    function alreadyAttachedTo(name) {
        if (!name) return false;
        var sidebar = window.SessionSidebar;
        if (!sidebar || typeof sidebar.activeTmuxName !== 'function') return false;
        var active = sidebar.activeTmuxName();
        return !!active && active === name;
    }

    /* could not */
    function go(toast) {
        var sessionId = toast && toast.session_id;
        if (!sessionId || !window.API || !window.App) return Promise.resolve(false);

        if (alreadyAttachedTo(toast && toast.session_name)) {
            return Promise.resolve(true);
        }

        var nav = window.NavigationGeneration
            ? window.NavigationGeneration.begin('toast:' + sessionId) : null;
        return window.API.listSessions()
            .then(function (sessions) {
                // could not the session is gone
                if (!Array.isArray(sessions)) {
                    console.warn('[ToastNavigate] session listing was malformed, cannot confirm status');
                    return false;
                }
                var info = findSession(sessions, sessionId);
                if (!info) {
                    announceMissing(toast);
                    return false;
                }
                if (alreadyAttachedTo(tmuxNameOf(info))) {
                    console.debug('[ToastNavigate] already attached, not re-entering');
                    return true;
                }
                if (window.SoloWindow && window.SoloWindow.active()) {
                    return window.SoloWindow.forwardToMain(info);
                }
                if (window.CloudeWeb && typeof window.CloudeWeb.closeSettingsScreen === 'function') {
                    try {
                        window.CloudeWeb.closeSettingsScreen();
                    } catch (err) {
                        console.debug('[ToastNavigate] settings close skipped', err);
                    }
                }
                if (window.NavigationGeneration
                    && !window.NavigationGeneration.keep(nav, 'toast jump')) {
                    // could not
                    return true;
                }
                window.App.returnToExistingTerminal(info);
                return true;
            })
            .catch(function (err) {
                console.warn('[ToastNavigate] jump failed', err && err.message);
                return false;
            });
    }

    function announceMissing(toast) {
        var name = null;
        if (window.SessionLabel && typeof window.SessionLabel.resolveToast === 'function') {
            name = window.SessionLabel.resolveToast(toast);
        }
        name = name || (toast && (toast.session_label || toast.session_name)) || 'that session';
        var message = name + ' is no longer running';
        if (window.Router && typeof window.Router.showError === 'function') {
            window.Router.showError(message);
            return;
        }
        console.warn('[ToastNavigate]', message);
    }

    var ASK_KIND = 'PermissionRequest';

    function isAskToast(toast) {
        return !!(toast && toast.kind === ASK_KIND && toast.session_id);
    }

    /* could not be read */
    function open(toast) {
        var web = window.CloudeWeb;
        if (!isAskToast(toast) || !web || typeof web.openApprovalFor !== 'function') return go(toast);
        return Promise.resolve(web.openApprovalFor(toast.session_id)).then(function (outcome) {
            return outcome === 'unknown' ? go(toast) : true;
        }, function (err) {
            console.warn('[ToastNavigate] approvals open failed', err && err.message);
            return go(toast);
        });
    }

    window.ToastNavigate = {
        go: go,
        open: open,
        isAskToast: isAskToast,
        findSession: findSession,
        tmuxNameOf: tmuxNameOf,
        alreadyAttachedTo: alreadyAttachedTo,
    };
}());
