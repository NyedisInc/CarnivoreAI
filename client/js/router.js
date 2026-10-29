/**
 * Deep-link router (Item 9).
 *
 * Reads the URL on page load. When the path matches `/session/<project>`,
 * validates the slug against a strict client-side regex, and - once the
 * user has authenticated - hands the project name to the launchpad so
 * it can auto-open that session.
 *
 * Security posture:
 * - The SERVER route `/session/{project}` intentionally serves the SPA
 *   shell for ANY single-path-segment value. The meaningful validation
 *   happens here, in the browser, so we can show a visible error rather
 *   than a 404 when a user pastes a malformed link.
 * - We REJECT invalid names (show a banner + clear the URL), we do NOT
 *   silently strip - silent stripping turns a bad link into a working
 *   one pointing at an unintended project, which is worse than failing
 *   loudly.
 * - The allow-list used to be `[A-Za-z0-9_\- ]` only, which rejected a
 *   name the app itself produces: a fork label is `<parent title>(fork)`
 *   (src/core/session_fork.py `fork_label`), and both project names and
 *   session titles are free-form - unicode, punctuation, digits - per
 *   the two server-side sources of truth: `validate_project_dir_name()`
 *   (src/core/project_directory.py) for a project name and
 *   `name_is_pushable()` (src/core/claude_rename.py) for a session
 *   title. Between them, the only things either one refuses are `/`,
 *   `\`, a null byte, other control characters, and the bare `.` / `..`
 *   segments - so that is exactly what `isLegalDeepLinkName()` below
 *   refuses too. Everything else either side can produce is accepted.
 *
 * Flow:
 * 1. `initRouter()` is called on page load from index.html.
 * 2. If the current path is `/session/<raw>`, we URL-decode + validate.
 * 3. Invalid → show banner, `history.replaceState` back to `/`, done.
 * 4. Valid → stash the target name on `window.DeepLinkTarget`.
 * 5. On the `authenticated` event (fired by auth.js after login), we
 *    hand the stashed name to `window.Launchpad.openProjectByName()`
 *    if the method exists; otherwise we fall back to firing a custom
 *    `deep-link-project` event that launchpad can listen for.
 * 6. We also listen for `popstate` so browser back/forward re-triggers
 *    the same flow.
 */
(function () {
    'use strict';

    var CONTROL_CHAR_RX = /[\x00-\x1F\x7F-\x9F]/;

    function isLegalDeepLinkName(decoded) {
        if (typeof decoded !== 'string' || decoded.length === 0) {
            return false;
        }
        if (decoded === '.' || decoded === '..') {
            return false;
        }
        if (decoded.indexOf('/') !== -1 || decoded.indexOf('\\') !== -1) {
            return false;
        }
        if (CONTROL_CHAR_RX.test(decoded)) {
            return false;
        }
        return true;
    }

    var DEEPLINK_RX = /^\/session\/([^\/]+)\/?$/;


    var SESSIONS_VIEW_URL = '/#sessions';

    function isBareSessionPath(pathname) {
        return pathname === '/session' || pathname === '/session/';
    }

    function redirectBareSession(immediate) {
        try {
            window.history.replaceState({}, '', SESSIONS_VIEW_URL);
        } catch (e) {
        }
        if (!immediate) return;
        if (window.App && typeof window.App.showLaunchpad === 'function') window.App.showLaunchpad();
        var web = window.CloudeWeb;
        if (web && typeof web.openSessionsScreen === 'function') {
            web.openSessionsScreen();
        } else {
            console.error('Router: CloudeWeb.openSessionsScreen is missing, the sessions view did not open');
        }
    }

    var LAYOUT_RX = /^\/layout\/([^\/]+)\/?$/;
    var LAYOUT_UUID_RX = /^[0-9A-Za-z][0-9A-Za-z-]{0,63}$/;

    function parseLayoutPath(pathname) {
        var m = (pathname || '').match(LAYOUT_RX);
        if (!m) return null;
        var decoded;
        try {
            decoded = decodeURIComponent(m[1]);
        } catch (e) {
            return { bad: m[1] };
        }
        return LAYOUT_UUID_RX.test(decoded) ? { uuid: decoded } : { bad: decoded };
    }

    var coldMenuHash = window.location.hash || '';

    function restoreMenuPageHash(work) {
        var saved = coldMenuHash;
        coldMenuHash = '';
        if (!saved) return;
        var restore = function () {
            var web = window.CloudeWeb;
            if (window.location.hash === '' && web && typeof web.namesMenuPage === 'function' && web.namesMenuPage(saved)) {
                window.location.hash = saved;
            }
        };
        Promise.resolve(work).then(restore, restore);
    }

    function deliverLayoutTarget(attempt) {
        var uuid = window.LayoutDeepLinkTarget;
        if (!uuid) return false;
        var web = window.CloudeWeb;
        var page = web && web.layoutPage;
        if (!page || typeof page.openFromUrl !== 'function') {
            var tries = typeof attempt === 'number' ? attempt : 0;
            if (tries < 50) {
                setTimeout(function () { deliverLayoutTarget(tries + 1); }, 100);
            } else {
                console.warn('Router: the Layout page never loaded, cannot open', uuid);
                if (window.App && (!window.App.currentScreen || window.App.currentScreen === 'auth') && typeof window.App.showLaunchpad === 'function') {
                    window.App.showLaunchpad();
                }
            }
            return false;
        }
        window.LayoutDeepLinkTarget = null;
        try {
            restoreMenuPageHash(page.openFromUrl(uuid));
        } catch (err) {
            console.error('Router: layoutPage.openFromUrl threw:', err);
        }
        return true;
    }

    var bootLayout = false;

    function bootScreen(app) {
        if (window.SoloWindow && window.SoloWindow.onBoot(app)) return;
        if (app.currentScreen && app.currentScreen !== 'auth') {
            if (window.AppBootComplete) window.AppBootComplete.announce();
            return;
        }
        if (!bootLayout) {
            app.showLaunchpad();
            return;
        }
        bootLayout = false;
        if (window.AppBootComplete) window.AppBootComplete.announce();
        deliverLayoutTarget(0);
    }

    var DEEPLINK_PREFIX = '/session/';

    var AUTO_DISMISS_MS = 8000;

    var dismissTimerId = null;

    // navigation generation
    // could not be determined
    var bannerGeneration = null;

    function clearDismissTimer() {
        if (dismissTimerId !== null) {
            clearTimeout(dismissTimerId);
            dismissTimerId = null;
        }
    }

    function buildSessionPath(name) {
        return DEEPLINK_PREFIX + encodeURIComponent(String(name));
    }

    function enterSession(name, opts) {
        if (!name) return;
        if (window.SoloWindow && window.SoloWindow.active()) return;
        var path = buildSessionPath(name);
        var layoutPage = window.CloudeWeb && window.CloudeWeb.layoutPage;
        if (layoutPage && typeof layoutPage.pathFor === 'function') {
            var held = layoutPage.pathFor(String(name));
            if (held) path = held;
        }
        if (window.location.pathname === path) return;
        var replace = !!(opts && opts.replace);
        try {
            if (replace) {
                window.history.replaceState({}, '', path);
            } else {
                window.history.pushState({}, '', path);
            }
        } catch (e) {
        }
    }

    function resetToLauncher() {
        if (window.SoloWindow && window.SoloWindow.active()) return;
        if (window.DeepLinkTarget) return;
        if (window.TerminalEmptyEntry && window.TerminalEmptyEntry.isPending()) return;
        if (window.LayoutDeepLinkTarget) return;
        if (LAYOUT_RX.test(window.location.pathname)) {
            var openLayout = window.CloudeWeb && window.CloudeWeb.layoutPage;
            if (!openLayout || typeof openLayout.isActive !== 'function' || !openLayout.isActive()) return;
        }
        if (window.location.pathname === '/') return;
        try {
            window.history.replaceState({}, '', '/');
        } catch (e) {
        }
    }

    /* navigation generation */
    function showError(message) {
        var el = document.getElementById('deep-link-error');
        if (!el) {
            console.warn('Router: #deep-link-error div missing, cannot display', message);
            return;
        }
        var textEl = document.getElementById('deep-link-error-text');
        if (textEl) {
            textEl.textContent = message;
        } else {
            el.textContent = message;
        }
        el.style.display = 'flex';
        bannerGeneration = window.NavigationGeneration
            ? window.NavigationGeneration.current() : null;
        clearDismissTimer();
        dismissTimerId = setTimeout(function () {
            dismissTimerId = null;
            clearError();
        }, AUTO_DISMISS_MS);
    }

    /* could not */
    function rejectTarget(name) {
        showError(`session not found: "${name}" - returned to home.`);
        try {
            window.history.replaceState({}, '', '/');
        } catch (e) {
        }
    }

    function clearError(token) {
        var el = document.getElementById('deep-link-error');
        if (!el) return;
        if (typeof token === 'number' && typeof bannerGeneration === 'number') {
            if (!(bannerGeneration < token)) {
                return;
            }
        }
        el.style.display = 'none';
        var textEl = document.getElementById('deep-link-error-text');
        if (textEl) {
            textEl.textContent = '';
        } else {
            el.textContent = '';
        }
        bannerGeneration = null;
        clearDismissTimer();
    }

    function wireDismissButton() {
        var btn = document.getElementById('deep-link-error-dismiss');
        if (!btn || typeof btn.addEventListener !== 'function') return;
        btn.addEventListener('click', function () {
            clearError();
        });
    }

    function parseCurrentPath() {
        var path = window.location.pathname || '/';
        var m = path.match(DEEPLINK_RX);
        if (!m) {
            return { match: false };
        }
        var raw = m[1];
        var decoded;
        try {
            decoded = decodeURIComponent(raw);
        } catch (e) {
            return { match: true, project: null, bad: raw };
        }
        if (!isLegalDeepLinkName(decoded)) {
            return { match: true, project: null, bad: decoded };
        }
        return { match: true, project: decoded };
    }

    function deliverTargetToLaunchpad() {
        var target = window.DeepLinkTarget;
        if (!target) {
            return;
        }
        if (window.NavigationGeneration) {
            window.NavigationGeneration.begin('deeplink:' + target);
        }
        if (window.Launchpad && typeof window.Launchpad.openProjectByName === 'function') {
            console.log('Router: delivering deep-link target to launchpad:', target);
            try {
                restoreMenuPageHash(window.Launchpad.openProjectByName(target));
            } catch (err) {
                console.error('Router: launchpad.openProjectByName threw:', err);
            }
            window.DeepLinkTarget = null;
            return;
        }
        console.log('Router: launchpad hook missing, firing deep-link-project event for:', target);
        window.dispatchEvent(
            new CustomEvent('deep-link-project', { detail: { project: target } })
        );
        window.DeepLinkTarget = null;
    }

    function applyCurrentPath(immediate) {
        if (isBareSessionPath(window.location.pathname)) {
            clearError();
            redirectBareSession(immediate);
            return;
        }

        var layoutLink = parseLayoutPath(window.location.pathname);
        if (layoutLink && layoutLink.bad !== undefined) {
            showError('Invalid layout link - returned to home.');
            try {
                window.history.replaceState({}, '', '/');
            } catch (e) {
            }
            return;
        }
        if (layoutLink) {
            clearError();
            window.LayoutDeepLinkTarget = layoutLink.uuid;
            if (!immediate) bootLayout = true;
            else if (window.Auth && typeof window.Auth.isAuthenticated === 'function' && window.Auth.isAuthenticated()) {
                deliverLayoutTarget(0);
            }
            return;
        }

        var parsed = parseCurrentPath();

        if (!parsed.match) {
            clearError();
            if (window.location.pathname === '/' &&
                window.App &&
                window.App.currentScreen === 'terminal' &&
                typeof window.App.showLaunchpad === 'function') {
                window.App.showLaunchpad();
            }
            return;
        }

        if (parsed.project === null) {
            showError('Invalid project name in URL - returned to home.');
            try {
                window.history.replaceState({}, '', '/');
            } catch (e) {
            }
            return;
        }

        window.DeepLinkTarget = parsed.project;
        clearError();

        if (window.Auth && typeof window.Auth.isAuthenticated === 'function' && window.Auth.isAuthenticated()) {
            setTimeout(deliverTargetToLaunchpad, 0);
        }
    }

    function initRouter() {
        console.log('Router: initializing deep-link router');

        wireDismissButton();

        applyCurrentPath(false);

        window.addEventListener('popstate', function () {
            if (window.CloudeWeb && typeof window.CloudeWeb.namesMenuPage === 'function' &&
                    window.CloudeWeb.namesMenuPage(window.location.hash)) {
                return;
            }
            applyCurrentPath(true);
        });

        window.addEventListener('authenticated', function () {
            setTimeout(deliverTargetToLaunchpad, 0);
            setTimeout(function () { deliverLayoutTarget(0); }, 0);
        });
    }

    window.Router = {
        init: initRouter,
        enterSession: enterSession,
        resetToLauncher: resetToLauncher,
        buildSessionPath: buildSessionPath,
        rejectTarget: rejectTarget,
        showError: showError,
        clearError: clearError,
        parseLayoutPath: parseLayoutPath,
        bootScreen: bootScreen,
        _parseCurrentPath: parseCurrentPath,
        _isLegalDeepLinkName: isLegalDeepLinkName,
    };
})();
