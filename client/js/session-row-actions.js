
console.log('[SessionRowActions Module] Loading...');

(function () {
    const ACTION_CLOSE = 'close';
    const ACTION_REMOVE = 'remove';
    const ACTION_RESTART = 'restart';

    /* could not */
    const STOPPED_STATUSES = ['dead'];

    const LIVE_STATUSES = [
        'working',
        'working_subagent',
        'question',
        'notice',
        'finished_unread',
        'idle',
        'running',
    ];

    const ACTION_LABELS = {
        [ACTION_CLOSE]: 'close session',
        [ACTION_REMOVE]: 'remove from the list',
        [ACTION_RESTART]: 'restart the agent',
    };

    const ATTR_ACTION = 'data-session-action';
    const ATTR_NAME = 'data-session-name';
    const BASE_CLASS = 'session-row-action';

    function escapeAttr(value) {
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML.replace(/"/g, '&quot;');
    }

    function actionsFor(status, facts) {
        const key = window.SessionStatusUI
            ? window.SessionStatusUI.normalizeStatus(status)
            : 'unknown';
        if (STOPPED_STATUSES.indexOf(key) !== -1) {
            return [ACTION_RESTART, ACTION_REMOVE];
        }
        if (LIVE_STATUSES.indexOf(key) !== -1) {
            return [ACTION_CLOSE, ACTION_RESTART];
        }
        if (key === 'unknown' && facts && facts.owned === true) {
            return [ACTION_CLOSE, ACTION_RESTART];
        }
        return [ACTION_CLOSE];
    }

    function offersMenu(status) {
        return actionsFor(status).indexOf(ACTION_CLOSE) !== -1;
    }

    function actionFor(status) {
        return actionsFor(status)[0];
    }

    function requiresConfirm(action) {
        return action !== ACTION_RESTART;
    }

    function labelFor(action) {
        return ACTION_LABELS[action] || ACTION_LABELS[ACTION_CLOSE];
    }

    /* width="16" */
    function iconFor(action) {
        if (!window.SessionStatusUI) return '';
        if (action === ACTION_REMOVE) return window.SessionStatusUI.trashIconSvg();
        if (action === ACTION_RESTART) {
            return window.SessionStatusUI.restartIconSvg();
        }
        return window.SessionStatusUI.closeIconSvg();
    }

    /* <button> role="button" */
    function specs(status, tmuxName, surfaceClass) {
        const cls = surfaceClass ? `${BASE_CLASS} ${surfaceClass}` : BASE_CLASS;
        return actionsFor(status).map(function (action) {
            const label = labelFor(action);
            return {
                attrs: {
                    type: 'button',
                    class: cls + (action === ACTION_RESTART ? ` ${BASE_CLASS}-restart` : ''),
                    [ATTR_ACTION]: action,
                    [ATTR_NAME]: tmuxName == null ? '' : String(tmuxName),
                    title: action === ACTION_REMOVE ? label : undefined,
                    'aria-label': label,
                },
                svg: iconFor(action),
            };
        });
    }

    /* <button type="button" class="session-row-action ..." ...> */
    function html(status, tmuxName, surfaceClass) {
        return specs(status, tmuxName, surfaceClass)
            .map(function (spec) {
                const parts = Object.keys(spec.attrs)
                    .filter(function (k) { return spec.attrs[k] !== undefined; })
                    .map(function (k) { return `${k}="${escapeAttr(spec.attrs[k])}"`; });
                return `<button ${parts.join(' ')}>${spec.svg}</button>`;
            })
            .join('');
    }

    /* failed to load */
    function confirm(action, displayName, context) {
        var mod = window.SessionRowActionsConfirm;
        if (!mod) return Promise.resolve(false);
        return mod.confirm(action, displayName, context);
    }

    function attachmentPreamble(context) {
        var mod = window.SessionRowActionsConfirm;
        return mod ? mod.attachmentPreamble(context) : '';
    }

    function perform(tmuxName, sessionId) {
        if (sessionId) return window.API.destroySession(sessionId);
        return window.API.destroyExternalSession(tmuxName);
    }

    window.SessionRowActions = {
        ACTION_CLOSE,
        ACTION_REMOVE,
        ACTION_RESTART,
        LIVE_STATUSES,
        STOPPED_STATUSES,
        ATTR_ACTION,
        ATTR_NAME,
        BASE_CLASS,
        actionFor,
        actionsFor,
        offersMenu,
        requiresConfirm,
        labelFor,
        iconFor,
        specs,
        html,
        confirm,
        attachmentPreamble,
        perform,
    };
    console.log('[SessionRowActions Module] Exported as window.SessionRowActions');
})();
