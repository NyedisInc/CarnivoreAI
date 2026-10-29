
console.log('[SessionRestartDirect Module] Loading...');

(function () {
    'use strict';

    function decide(answer) {
        var Options = window.SessionRestartOptions;
        var preview = (answer && answer.preview) || {};
        if (!answer || answer.mode !== 'restart') {
            return { choice: null, reason: 'session.restart.now.fallback.gone' };
        }
        var unchanged = preview.unchanged || {};
        var projected = preview.projected || {};
        if (preview.pane_state === 'alive') {
            if (!Options.isActionable(projected.kind || unchanged.kind)) {
                return { choice: null, reason: 'session.restart.now.fallback.outcome' };
            }
            return { choice: choiceFor(true), reason: '' };
        }
        if (preview.pane_state === 'dead') {
            if (unchanged.actionable !== true || !Options.isActionable(unchanged.kind)) {
                return { choice: null, reason: 'session.restart.now.fallback.outcome' };
            }
            return { choice: choiceFor(false), reason: '' };
        }
        return { choice: null, reason: 'session.restart.now.fallback.not_measured' };
    }

    function choiceFor(kill) {
        return {
            agentType: null,
            confirmRestartLive: kill === true,
            mode: 'restart',
            sessionUuid: null,
        };
    }

    var lastErrorText = '';

    function open(tmuxName, displayName, status, sessionUuid, busyWork) {
        lastErrorText = '';
        var Options = window.SessionRestartOptions;
        var picker = window.SessionRestartPicker;
        return Promise.all([
            Options.previewFor(tmuxName, sessionUuid || null),
            Options.accountsFor(sessionUuid || null),
        ]).then(function (both) {
                var answer = both[0];
                var verdict = decide(answer);
                if (verdict.choice) return verdict.choice;
                var pending = picker.present(
                    displayName || tmuxName, answer.preview, status,
                    answer.mode, answer.sessionUuid, false, false,
                    busyWork === true, both[1]);
                noticeFallback(verdict.reason);
                return pending;
            }).catch(function (err) {
                lastErrorText = (err && err.message) || String(err);
                console.error('SessionRestartDirect: preview failed:', err);
                return null;
            });
    }

    function noticeFallback(key) {
        var main = document.querySelector('.restart-picker .restart-picker__main');
        if (!main || !key) return;
        var note = document.createElement('div');
        note.className = 'restart-picker__notice';
        note.setAttribute('data-restart-now-fallback', '1');
        note.textContent = window.SessionRestartOptions.tr(key);
        main.insertBefore(note, main.firstChild);
    }

    window.SessionRestartDirect = {
        decide: decide,
        open: open,
        lastError: function () { return lastErrorText; },
    };
})();

console.log('[SessionRestartDirect Module] Exported as window.SessionRestartDirect');
