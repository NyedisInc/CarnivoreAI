
console.log('[SessionRestartReturn Module] Loading...');

(function () {
    'use strict';

    async function reopen(result) {
        var name = (result && result.name) || '';
        var sessionId = (result && result.session_id) || null;
        var layoutPage = window.CloudeWeb && window.CloudeWeb.layoutPage;
        if (layoutPage && typeof layoutPage.holds === 'function'
            && layoutPage.holds(sessionId || '', name)) {
            return { status: 'reopened', detail: '' };
        }
        var nav = window.NavigationGeneration
            ? window.NavigationGeneration.begin('restart:' + (name || sessionId)) : null;
        var stillOurs = function () {
            return !window.NavigationGeneration
                || window.NavigationGeneration.keep(nav, 'restart reopen');
        };

        if (sessionId) {
            var info;
            try {
                info = await window.API.getSession(sessionId, {
                    includeScrollback: true,
                    parallelHistory: true,
                    scrollbackLines: window.CloudeTerminal.SCROLLBACK_ROWS,
                });
            } catch (err) {
                return {
                    status: 'not_reopened',
                    detail: 'the session restarted but could not be reopened: '
                        + ((err && err.message) || String(err)),
                };
            }
            if (!info) {
                return {
                    status: 'not_reopened',
                    detail: 'the session restarted but the server returned '
                        + 'nothing for it, so it was not reopened',
                };
            }
            var gotId = (info.session && info.session.id) || info.id || null;
            if (gotId && sessionId && gotId !== sessionId) {
                return {
                    status: 'wrong_session',
                    detail: 'the session that came back is not the one that '
                        + 'was restarted, so nothing was opened',
                };
            }
            if (!stillOurs()) {
                return {
                    status: 'not_reopened',
                    detail: 'the session restarted but you moved to another '
                        + 'conversation before it came back, so it was not opened',
                };
            }
            window.App.returnToExistingTerminal(info);
            return { status: 'reopened', detail: '' };
        }

        if (!name) {
            return {
                status: 'not_reopened',
                detail: 'the restart reported no session to reopen',
            };
        }

        try {
            var response = await window.API.adoptSession(name, true);
            var session = response.session || response;
            if (!stillOurs()) {
                return {
                    status: 'not_reopened',
                    detail: 'the session restarted but you moved to another '
                        + 'conversation before it came back, so it was not opened',
                };
            }
            window.dispatchEvent(new CustomEvent('session-created', {
                detail: {
                    session: session,
                    nav: nav,
                    initialScrollbackB64: response.initial_scrollback_b64 || '',
                    fifoStartOffset:
                        typeof response.fifo_start_offset === 'number'
                            ? response.fifo_start_offset
                            : null,
                    adopted: true,
                },
            }));
            return { status: 'reopened', detail: '' };
        } catch (err) {
            return {
                status: 'not_reopened',
                detail: 'the session restarted but could not be reopened: '
                    + ((err && err.message) || String(err)),
            };
        }
    }

    window.SessionRestartReturn = { reopen: reopen };
})();

console.log('[SessionRestartReturn Module] Exported as window.SessionRestartReturn');
