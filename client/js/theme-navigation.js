/* nothing at all */
(function () {
    'use strict';

    var lastTarget = { kind: 'global' };

    function globalThemeId() {
        if (window.Themes && typeof window.Themes.getStoredThemeId === 'function') {
            return window.Themes.getStoredThemeId();
        }
        return (window.Themes && window.Themes.DEFAULT_THEME_ID) || 'claude';
    }

    function resolvePinnedTheme(sessionInfo) {
        if (!sessionInfo) return null;
        var inner = sessionInfo.session || null;
        return sessionInfo.pinned_theme
            || (inner && inner.pinned_theme)
            || null;
    }

    function resolveHostKey(sessionInfo) {
        return (sessionInfo && sessionInfo.host_key) || 'local';
    }

    function scopeKeyFor(name, hostKey) {
        if (window.SessionKey && typeof window.SessionKey.forName === 'function') {
            return window.SessionKey.forName(name, hostKey);
        }
        return (!hostKey || hostKey === 'local') ? (name || null) : null;
    }


    function applyForTarget(target) {
        var t = target || {};
        lastTarget = t;
        var isSession = t.kind === 'session';
        var themes = window.Themes;

        if (!isSession && themes && typeof themes.clearSession === 'function') {
            themes.clearSession();
        }

        var scopeName = isSession ? scopeKeyFor(t.sessionName || null, t.hostKey) : null;
        if (themes && typeof themes.setActiveSession === 'function') {
            themes.setActiveSession(scopeName);
        }

        var painted = globalThemeId();
        if (themes && typeof themes.applyTheme === 'function') {
            themes.applyTheme(painted, isSession
                ? { persist: false, forXterm: false }
                : { persist: false });
        }

        if (isSession && themes && typeof themes.applySessionScope === 'function') {
            themes.applySessionScope({ pinnedTheme: t.pinnedTheme || null });
        }

        return painted;
    }

    function applyForSession(sessionInfo, sessionName) {
        return applyForTarget({
            kind: 'session',
            sessionName: sessionName || null,
            pinnedTheme: resolvePinnedTheme(sessionInfo),
            hostKey: resolveHostKey(sessionInfo)
        });
    }

    function applyForGlobal() {
        return applyForTarget({ kind: 'global' });
    }

    function reapply() {
        return applyForTarget(lastTarget);
    }

    window.ThemeNavigation = {
        applyForTarget: applyForTarget,
        reapply: reapply,
        applyForSession: applyForSession,
        applyForGlobal: applyForGlobal,
        resolvePinnedTheme: resolvePinnedTheme
    };
})();
